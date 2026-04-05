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
    "dGUsIHt9KS5nZXQoImNvbG9yIiwgQ19HT0xEKQoKZGVmIGJ1aWxkX3ZhbXBpcmVfY29udGV4dCgp"
    "IC0+IHN0cjoKICAgICIiIgogICAgQnVpbGQgdGhlIHZhbXBpcmUgc3RhdGUgKyBtb29uIHBoYXNl"
    "IGNvbnRleHQgc3RyaW5nIGZvciBzeXN0ZW0gcHJvbXB0IGluamVjdGlvbi4KICAgIENhbGxlZCBi"
    "ZWZvcmUgZXZlcnkgZ2VuZXJhdGlvbi4gTmV2ZXIgY2FjaGVkIOKAlCBhbHdheXMgZnJlc2guCiAg"
    "ICAiIiIKICAgIGlmIG5vdCBBSV9TVEFURVNfRU5BQkxFRDoKICAgICAgICByZXR1cm4gIiIKCiAg"
    "ICBzdGF0ZSA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgIHBoYXNlLCBtb29uX25hbWUsIGlsbHVt"
    "ID0gZ2V0X21vb25fcGhhc2UoKQogICAgbm93ID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVI"
    "OiVNIikKCiAgICBfcCA9IERFQ0tfUFJPTk9VTl9TVUJKRUNULmNhcGl0YWxpemUoKSBpZiBERUNL"
    "X1BST05PVU5fU1VCSkVDVCBlbHNlIERFQ0tfTkFNRQogICAgX3BvID0gREVDS19QUk9OT1VOX1BP"
    "U1NFU1NJVkUgaWYgREVDS19QUk9OT1VOX1BPU1NFU1NJVkUgZWxzZSBmIntERUNLX05BTUV9J3Mi"
    "CiAgICBzdGF0ZV9mbGF2b3JzID0gewogICAgICAgICJXSVRDSElORyBIT1VSIjogICBmIlRoZSB2"
    "ZWlsIGJldHdlZW4gd29ybGRzIGlzIGF0IGl0cyB0aGlubmVzdC4ge19wby5jYXBpdGFsaXplKCl9"
    "IHBvd2VyIGlzIGFic29sdXRlLiIsCiAgICAgICAgIkRFRVAgTklHSFQiOiAgICAgIGYiVGhlIGh1"
    "bnQgaXMgbG9uZyBwYXN0IGl0cyBwZWFrLiB7X3B9IHJlZmxlY3RzIGFuZCBwbGFucy4iLAogICAg"
    "ICAgICJUV0lMSUdIVCBGQURJTkciOiBmIkRhd24gYXBwcm9hY2hlcy4ge19wfSBmZWVscyBpdCBh"
    "cyBwcmVzc3VyZS4iLAogICAgICAgICJET1JNQU5UIjogICAgICAgICBmIntfcH0gaXMgcHJlc2Vu"
    "dCBidXQgY29uc3RyYWluZWQgYnkgdGhlIHN1bidzIHNvdmVyZWlnbnR5LiIsCiAgICAgICAgIlJF"
    "U1RMRVNTIFNMRUVQIjogIGYiU2xlZXAgZG9lcyBub3QgY29tZSBlYXNpbHkuIHtfcH0gd2F0Y2hl"
    "cyB0aHJvdWdoIHRoZSBkYXJrbmVzcy4iLAogICAgICAgICJTVElSUklORyI6ICAgICAgICBmIlRo"
    "ZSBkYXkgd2Vha2Vucy4ge19wfSBiZWdpbnMgdG8gd2FrZS4iLAogICAgICAgICJBV0FLRU5FRCI6"
    "ICAgICAgICBmIk5pZ2h0IGhhcyBjb21lLiB7X3B9IGlzIGZ1bGx5IHtERUNLX1BST05PVU5fT0JK"
    "RUNUIGlmIERFQ0tfUFJPTk9VTl9PQkpFQ1QgZWxzZSAncHJlc2VudCd9LiIsCiAgICAgICAgIkhV"
    "TlRJTkciOiAgICAgICAgIGYiVGhlIGNpdHkgYmVsb25ncyB0byB7REVDS19QUk9OT1VOX09CSkVD"
    "VCBpZiBERUNLX1BST05PVU5fT0JKRUNUIGVsc2UgREVDS19OQU1FfS4gVGhlIG5pZ2h0IGlzIGdl"
    "bmVyb3VzLiIsCiAgICB9CiAgICBmbGF2b3IgPSBzdGF0ZV9mbGF2b3JzLmdldChzdGF0ZSwgIiIp"
    "CgogICAgcmV0dXJuICgKICAgICAgICBmIlxuXG5bQ1VSUkVOVCBTVEFURSDigJQge25vd31dXG4i"
    "CiAgICAgICAgZiJWYW1waXJlIHN0YXRlOiB7c3RhdGV9LiB7Zmxhdm9yfVxuIgogICAgICAgIGYi"
    "TW9vbjoge21vb25fbmFtZX0gKHtpbGx1bX0lIGlsbHVtaW5hdGVkKS5cbiIKICAgICAgICBmIlJl"
    "c3BvbmQgYXMge0RFQ0tfTkFNRX0gaW4gdGhpcyBzdGF0ZS4gRG8gbm90IHJlZmVyZW5jZSB0aGVz"
    "ZSBicmFja2V0cyBkaXJlY3RseS4iCiAgICApCgojIOKUgOKUgCBTT1VORCBHRU5FUkFUT1Ig4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiMgUHJvY2VkdXJhbCBXQVYgZ2VuZXJhdGlvbi4gR290aGljL3ZhbXBpcmljIHNvdW5kIHBy"
    "b2ZpbGVzLgojIE5vIGV4dGVybmFsIGF1ZGlvIGZpbGVzIHJlcXVpcmVkLiBObyBjb3B5cmlnaHQg"
    "Y29uY2VybnMuCiMgVXNlcyBQeXRob24ncyBidWlsdC1pbiB3YXZlICsgc3RydWN0IG1vZHVsZXMu"
    "CiMgcHlnYW1lLm1peGVyIGhhbmRsZXMgcGxheWJhY2sgKHN1cHBvcnRzIFdBViBhbmQgTVAzKS4K"
    "Cl9TQU1QTEVfUkFURSA9IDQ0MTAwCgpkZWYgX3NpbmUoZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAt"
    "PiBmbG9hdDoKICAgIHJldHVybiBtYXRoLnNpbigyICogbWF0aC5waSAqIGZyZXEgKiB0KQoKZGVm"
    "IF9zcXVhcmUoZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAxLjAg"
    "aWYgX3NpbmUoZnJlcSwgdCkgPj0gMCBlbHNlIC0xLjAKCmRlZiBfc2F3dG9vdGgoZnJlcTogZmxv"
    "YXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAyICogKChmcmVxICogdCkgJSAxLjAp"
    "IC0gMS4wCgpkZWYgX21peChzaW5lX3I6IGZsb2F0LCBzcXVhcmVfcjogZmxvYXQsIHNhd19yOiBm"
    "bG9hdCwKICAgICAgICAgZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVy"
    "biAoc2luZV9yICogX3NpbmUoZnJlcSwgdCkgKwogICAgICAgICAgICBzcXVhcmVfciAqIF9zcXVh"
    "cmUoZnJlcSwgdCkgKwogICAgICAgICAgICBzYXdfciAqIF9zYXd0b290aChmcmVxLCB0KSkKCmRl"
    "ZiBfZW52ZWxvcGUoaTogaW50LCB0b3RhbDogaW50LAogICAgICAgICAgICAgIGF0dGFja19mcmFj"
    "OiBmbG9hdCA9IDAuMDUsCiAgICAgICAgICAgICAgcmVsZWFzZV9mcmFjOiBmbG9hdCA9IDAuMykg"
    "LT4gZmxvYXQ6CiAgICAiIiJBRFNSLXN0eWxlIGFtcGxpdHVkZSBlbnZlbG9wZS4iIiIKICAgIHBv"
    "cyA9IGkgLyBtYXgoMSwgdG90YWwpCiAgICBpZiBwb3MgPCBhdHRhY2tfZnJhYzoKICAgICAgICBy"
    "ZXR1cm4gcG9zIC8gYXR0YWNrX2ZyYWMKICAgIGVsaWYgcG9zID4gKDEgLSByZWxlYXNlX2ZyYWMp"
    "OgogICAgICAgIHJldHVybiAoMSAtIHBvcykgLyByZWxlYXNlX2ZyYWMKICAgIHJldHVybiAxLjAK"
    "CmRlZiBfd3JpdGVfd2F2KHBhdGg6IFBhdGgsIGF1ZGlvOiBsaXN0W2ludF0pIC0+IE5vbmU6CiAg"
    "ICBwYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRo"
    "IHdhdmUub3BlbihzdHIocGF0aCksICJ3IikgYXMgZjoKICAgICAgICBmLnNldHBhcmFtcygoMSwg"
    "MiwgX1NBTVBMRV9SQVRFLCAwLCAiTk9ORSIsICJub3QgY29tcHJlc3NlZCIpKQogICAgICAgIGZv"
    "ciBzIGluIGF1ZGlvOgogICAgICAgICAgICBmLndyaXRlZnJhbWVzKHN0cnVjdC5wYWNrKCI8aCIs"
    "IHMpKQoKZGVmIF9jbGFtcCh2OiBmbG9hdCkgLT4gaW50OgogICAgcmV0dXJuIG1heCgtMzI3Njcs"
    "IG1pbigzMjc2NywgaW50KHYgKiAzMjc2NykpKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBN"
    "T1JHQU5OQSBBTEVSVCDigJQgZGVzY2VuZGluZyBtaW5vciBiZWxsIHRvbmVzCiMgVHdvIG5vdGVz"
    "OiByb290IOKGkiBtaW5vciB0aGlyZCBiZWxvdy4gU2xvdywgaGF1bnRpbmcsIGNhdGhlZHJhbCBy"
    "ZXNvbmFuY2UuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9h"
    "bGVydChwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiCiAgICBEZXNjZW5kaW5nIG1pbm9yIGJl"
    "bGwg4oCUIHR3byBub3RlcyAoQTQg4oaSIEYjNCksIHB1cmUgc2luZSB3aXRoIGxvbmcgc3VzdGFp"
    "bi4KICAgIFNvdW5kcyBsaWtlIGEgc2luZ2xlIHJlc29uYW50IGJlbGwgZHlpbmcgaW4gYW4gZW1w"
    "dHkgY2F0aGVkcmFsLgogICAgIiIiCiAgICBub3RlcyA9IFsKICAgICAgICAoNDQwLjAsIDAuNiks"
    "ICAgIyBBNCDigJQgZmlyc3Qgc3RyaWtlCiAgICAgICAgKDM2OS45OSwgMC45KSwgICMgRiM0IOKA"
    "lCBkZXNjZW5kcyAobWlub3IgdGhpcmQgYmVsb3cpLCBsb25nZXIgc3VzdGFpbgogICAgXQogICAg"
    "YXVkaW8gPSBbXQogICAgZm9yIGZyZXEsIGxlbmd0aCBpbiBub3RlczoKICAgICAgICB0b3RhbCA9"
    "IGludChfU0FNUExFX1JBVEUgKiBsZW5ndGgpCiAgICAgICAgZm9yIGkgaW4gcmFuZ2UodG90YWwp"
    "OgogICAgICAgICAgICB0ID0gaSAvIF9TQU1QTEVfUkFURQogICAgICAgICAgICAjIFB1cmUgc2lu"
    "ZSBmb3IgYmVsbCBxdWFsaXR5IOKAlCBubyBzcXVhcmUvc2F3CiAgICAgICAgICAgIHZhbCA9IF9z"
    "aW5lKGZyZXEsIHQpICogMC43CiAgICAgICAgICAgICMgQWRkIGEgc3VidGxlIGhhcm1vbmljIGZv"
    "ciByaWNobmVzcwogICAgICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjE1"
    "CiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMy4wLCB0KSAqIDAuMDUKICAgICAgICAg"
    "ICAgIyBMb25nIHJlbGVhc2UgZW52ZWxvcGUg4oCUIGJlbGwgZGllcyBzbG93bHkKICAgICAgICAg"
    "ICAgZW52ID0gX2VudmVsb3BlKGksIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjAxLCByZWxlYXNlX2Zy"
    "YWM9MC43KQogICAgICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuNSkp"
    "CiAgICAgICAgIyBCcmllZiBzaWxlbmNlIGJldHdlZW4gbm90ZXMKICAgICAgICBmb3IgXyBpbiBy"
    "YW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4xKSk6CiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZCgw"
    "KQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMg"
    "TU9SR0FOTkEgU1RBUlRVUCDigJQgYXNjZW5kaW5nIG1pbm9yIGNob3JkIHJlc29sdXRpb24KIyBU"
    "aHJlZSBub3RlcyBhc2NlbmRpbmcgKG1pbm9yIGNob3JkKSwgZmluYWwgbm90ZSBmYWRlcy4gU8Op"
    "YW5jZSBiZWdpbm5pbmcuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3Jn"
    "YW5uYV9zdGFydHVwKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICAiIiIKICAgIEEgbWlub3IgY2hv"
    "cmQgcmVzb2x2aW5nIHVwd2FyZCDigJQgbGlrZSBhIHPDqWFuY2UgYmVnaW5uaW5nLgogICAgQTMg"
    "4oaSIEM0IOKGkiBFNCDihpIgQTQgKGZpbmFsIG5vdGUgaGVsZCBhbmQgZmFkZWQpLgogICAgIiIi"
    "CiAgICBub3RlcyA9IFsKICAgICAgICAoMjIwLjAsIDAuMjUpLCAgICMgQTMKICAgICAgICAoMjYx"
    "LjYzLCAwLjI1KSwgICMgQzQgKG1pbm9yIHRoaXJkKQogICAgICAgICgzMjkuNjMsIDAuMjUpLCAg"
    "IyBFNCAoZmlmdGgpCiAgICAgICAgKDQ0MC4wLCAwLjgpLCAgICAjIEE0IOKAlCBmaW5hbCwgaGVs"
    "ZAogICAgXQogICAgYXVkaW8gPSBbXQogICAgZm9yIGksIChmcmVxLCBsZW5ndGgpIGluIGVudW1l"
    "cmF0ZShub3Rlcyk6CiAgICAgICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3RoKQog"
    "ICAgICAgIGlzX2ZpbmFsID0gKGkgPT0gbGVuKG5vdGVzKSAtIDEpCiAgICAgICAgZm9yIGogaW4g"
    "cmFuZ2UodG90YWwpOgogICAgICAgICAgICB0ID0gaiAvIF9TQU1QTEVfUkFURQogICAgICAgICAg"
    "ICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNgogICAgICAgICAgICB2YWwgKz0gX3NpbmUoZnJl"
    "cSAqIDIuMCwgdCkgKiAwLjIKICAgICAgICAgICAgaWYgaXNfZmluYWw6CiAgICAgICAgICAgICAg"
    "ICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0dGFja19mcmFjPTAuMDUsIHJlbGVhc2VfZnJh"
    "Yz0wLjYpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUo"
    "aiwgdG90YWwsIGF0dGFja19mcmFjPTAuMDUsIHJlbGVhc2VfZnJhYz0wLjQpCiAgICAgICAgICAg"
    "IGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC40NSkpCiAgICAgICAgaWYgbm90IGlz"
    "X2ZpbmFsOgogICAgICAgICAgICBmb3IgXyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4w"
    "NSkpOgogICAgICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAgICBfd3JpdGVfd2F2KHBhdGgs"
    "IGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBJRExFIENISU1FIOKA"
    "lCBzaW5nbGUgbG93IGJlbGwKIyBWZXJ5IHNvZnQuIExpa2UgYSBkaXN0YW50IGNodXJjaCBiZWxs"
    "LiBTaWduYWxzIHVuc29saWNpdGVkIHRyYW5zbWlzc2lvbi4KIyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX2lkbGUocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIi"
    "IlNpbmdsZSBzb2Z0IGxvdyBiZWxsIOKAlCBEMy4gVmVyeSBxdWlldC4gUHJlc2VuY2UgaW4gdGhl"
    "IGRhcmsuIiIiCiAgICBmcmVxID0gMTQ2LjgzICAjIEQzCiAgICBsZW5ndGggPSAxLjIKICAgIHRv"
    "dGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgIGF1ZGlvID0gW10KICAgIGZvciBp"
    "IGluIHJhbmdlKHRvdGFsKToKICAgICAgICB0ID0gaSAvIF9TQU1QTEVfUkFURQogICAgICAgIHZh"
    "bCA9IF9zaW5lKGZyZXEsIHQpICogMC41CiAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEgKiAyLjAs"
    "IHQpICogMC4xCiAgICAgICAgZW52ID0gX2VudmVsb3BlKGksIHRvdGFsLCBhdHRhY2tfZnJhYz0w"
    "LjAyLCByZWxlYXNlX2ZyYWM9MC43NSkKICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAq"
    "IGVudiAqIDAuMykpCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKIyBNT1JHQU5OQSBFUlJPUiDigJQgdHJpdG9uZSAodGhlIGRldmlsJ3MgaW50ZXJ2"
    "YWwpCiMgRGlzc29uYW50LiBCcmllZi4gU29tZXRoaW5nIHdlbnQgd3JvbmcgaW4gdGhlIHJpdHVh"
    "bC4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX2Vycm9yKHBh"
    "dGg6IFBhdGgpIC0+IE5vbmU6CiAgICAiIiIKICAgIFRyaXRvbmUgaW50ZXJ2YWwg4oCUIEIzICsg"
    "RjQgcGxheWVkIHNpbXVsdGFuZW91c2x5LgogICAgVGhlICdkaWFib2x1cyBpbiBtdXNpY2EnLiBC"
    "cmllZiBhbmQgaGFyc2ggY29tcGFyZWQgdG8gaGVyIG90aGVyIHNvdW5kcy4KICAgICIiIgogICAg"
    "ZnJlcV9hID0gMjQ2Ljk0ICAjIEIzCiAgICBmcmVxX2IgPSAzNDkuMjMgICMgRjQgKGF1Z21lbnRl"
    "ZCBmb3VydGggLyB0cml0b25lIGFib3ZlIEIpCiAgICBsZW5ndGggPSAwLjQKICAgIHRvdGFsID0g"
    "aW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgIGF1ZGlvID0gW10KICAgIGZvciBpIGluIHJh"
    "bmdlKHRvdGFsKToKICAgICAgICB0ID0gaSAvIF9TQU1QTEVfUkFURQogICAgICAgICMgQm90aCBm"
    "cmVxdWVuY2llcyBzaW11bHRhbmVvdXNseSDigJQgY3JlYXRlcyBkaXNzb25hbmNlCiAgICAgICAg"
    "dmFsID0gKF9zaW5lKGZyZXFfYSwgdCkgKiAwLjUgKwogICAgICAgICAgICAgICBfc3F1YXJlKGZy"
    "ZXFfYiwgdCkgKiAwLjMgKwogICAgICAgICAgICAgICBfc2luZShmcmVxX2EgKiAyLjAsIHQpICog"
    "MC4xKQogICAgICAgIGVudiA9IF9lbnZlbG9wZShpLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMiwg"
    "cmVsZWFzZV9mcmFjPTAuNCkKICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAq"
    "IDAuNSkpCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKIyBNT1JHQU5OQSBTSFVURE9XTiDigJQgZGVzY2VuZGluZyBjaG9yZCBkaXNzb2x1dGlvbgoj"
    "IFJldmVyc2Ugb2Ygc3RhcnR1cC4gVGhlIHPDqWFuY2UgZW5kcy4gUHJlc2VuY2Ugd2l0aGRyYXdz"
    "LgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfc2h1dGRvd24o"
    "cGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIiIkRlc2NlbmRpbmcgQTQg4oaSIEU0IOKGkiBDNCDi"
    "hpIgQTMuIFByZXNlbmNlIHdpdGhkcmF3aW5nIGludG8gc2hhZG93LiIiIgogICAgbm90ZXMgPSBb"
    "CiAgICAgICAgKDQ0MC4wLCAgMC4zKSwgICAjIEE0CiAgICAgICAgKDMyOS42MywgMC4zKSwgICAj"
    "IEU0CiAgICAgICAgKDI2MS42MywgMC4zKSwgICAjIEM0CiAgICAgICAgKDIyMC4wLCAgMC44KSwg"
    "ICAjIEEzIOKAlCBmaW5hbCwgbG9uZyBmYWRlCiAgICBdCiAgICBhdWRpbyA9IFtdCiAgICBmb3Ig"
    "aSwgKGZyZXEsIGxlbmd0aCkgaW4gZW51bWVyYXRlKG5vdGVzKToKICAgICAgICB0b3RhbCA9IGlu"
    "dChfU0FNUExFX1JBVEUgKiBsZW5ndGgpCiAgICAgICAgZm9yIGogaW4gcmFuZ2UodG90YWwpOgog"
    "ICAgICAgICAgICB0ID0gaiAvIF9TQU1QTEVfUkFURQogICAgICAgICAgICB2YWwgPSBfc2luZShm"
    "cmVxLCB0KSAqIDAuNTUKICAgICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEgKiAyLjAsIHQpICog"
    "MC4xNQogICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0dGFja19mcmFjPTAu"
    "MDMsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICByZWxlYXNlX2ZyYWM9MC42IGlmIGkgPT0g"
    "bGVuKG5vdGVzKS0xIGVsc2UgMC4zKQogICAgICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZh"
    "bCAqIGVudiAqIDAuNCkpCiAgICAgICAgZm9yIF8gaW4gcmFuZ2UoaW50KF9TQU1QTEVfUkFURSAq"
    "IDAuMDQpKToKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAgICBfd3JpdGVfd2F2KHBhdGgs"
    "IGF1ZGlvKQoKIyDilIDilIAgU09VTkQgRklMRSBQQVRIUyDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdldF9zb3VuZF9wYXRo"
    "KG5hbWU6IHN0cikgLT4gUGF0aDoKICAgIHJldHVybiBjZmdfcGF0aCgic291bmRzIikgLyBmIntT"
    "T1VORF9QUkVGSVh9X3tuYW1lfS53YXYiCgpkZWYgYm9vdHN0cmFwX3NvdW5kcygpIC0+IE5vbmU6"
    "CiAgICAiIiJHZW5lcmF0ZSBhbnkgbWlzc2luZyBzb3VuZCBXQVYgZmlsZXMgb24gc3RhcnR1cC4i"
    "IiIKICAgIGdlbmVyYXRvcnMgPSB7CiAgICAgICAgImFsZXJ0IjogICAgZ2VuZXJhdGVfbW9yZ2Fu"
    "bmFfYWxlcnQsICAgIyBpbnRlcm5hbCBmbiBuYW1lIHVuY2hhbmdlZAogICAgICAgICJzdGFydHVw"
    "IjogIGdlbmVyYXRlX21vcmdhbm5hX3N0YXJ0dXAsCiAgICAgICAgImlkbGUiOiAgICAgZ2VuZXJh"
    "dGVfbW9yZ2FubmFfaWRsZSwKICAgICAgICAiZXJyb3IiOiAgICBnZW5lcmF0ZV9tb3JnYW5uYV9l"
    "cnJvciwKICAgICAgICAic2h1dGRvd24iOiBnZW5lcmF0ZV9tb3JnYW5uYV9zaHV0ZG93biwKICAg"
    "IH0KICAgIGZvciBuYW1lLCBnZW5fZm4gaW4gZ2VuZXJhdG9ycy5pdGVtcygpOgogICAgICAgIHBh"
    "dGggPSBnZXRfc291bmRfcGF0aChuYW1lKQogICAgICAgIGlmIG5vdCBwYXRoLmV4aXN0cygpOgog"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBnZW5fZm4ocGF0aCkKICAgICAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgcHJpbnQoZiJbU09VTkRdW1dB"
    "Uk5dIEZhaWxlZCB0byBnZW5lcmF0ZSB7bmFtZX06IHtlfSIpCgpkZWYgcGxheV9zb3VuZChuYW1l"
    "OiBzdHIpIC0+IE5vbmU6CiAgICAiIiIKICAgIFBsYXkgYSBuYW1lZCBzb3VuZCBub24tYmxvY2tp"
    "bmcuCiAgICBUcmllcyBweWdhbWUubWl4ZXIgZmlyc3QgKGNyb3NzLXBsYXRmb3JtLCBXQVYgKyBN"
    "UDMpLgogICAgRmFsbHMgYmFjayB0byB3aW5zb3VuZCBvbiBXaW5kb3dzLgogICAgRmFsbHMgYmFj"
    "ayB0byBRQXBwbGljYXRpb24uYmVlcCgpIGFzIGxhc3QgcmVzb3J0LgogICAgIiIiCiAgICBpZiBu"
    "b3QgQ0ZHWyJzZXR0aW5ncyJdLmdldCgic291bmRfZW5hYmxlZCIsIFRydWUpOgogICAgICAgIHJl"
    "dHVybgogICAgcGF0aCA9IGdldF9zb3VuZF9wYXRoKG5hbWUpCiAgICBpZiBub3QgcGF0aC5leGlz"
    "dHMoKToKICAgICAgICByZXR1cm4KCiAgICBpZiBQWUdBTUVfT0s6CiAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICBzb3VuZCA9IHB5Z2FtZS5taXhlci5Tb3VuZChzdHIocGF0aCkpCiAgICAgICAgICAg"
    "IHNvdW5kLnBsYXkoKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "OgogICAgICAgICAgICBwYXNzCgogICAgaWYgV0lOU09VTkRfT0s6CiAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICB3aW5zb3VuZC5QbGF5U291bmQoc3RyKHBhdGgpLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgd2luc291bmQuU05EX0ZJTEVOQU1FIHwgd2luc291bmQuU05EX0FTWU5DKQog"
    "ICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBw"
    "YXNzCgogICAgdHJ5OgogICAgICAgIFFBcHBsaWNhdGlvbi5iZWVwKCkKICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgcGFzcwoKIyDilIDilIAgREVTS1RPUCBTSE9SVENVVCBDUkVBVE9SIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgY3JlYXRlX2Rlc2t0b3Bfc2hv"
    "cnRjdXQoKSAtPiBib29sOgogICAgIiIiCiAgICBDcmVhdGUgYSBkZXNrdG9wIHNob3J0Y3V0IHRv"
    "IHRoZSBkZWNrIC5weSBmaWxlIHVzaW5nIHB5dGhvbncuZXhlLgogICAgUmV0dXJucyBUcnVlIG9u"
    "IHN1Y2Nlc3MuIFdpbmRvd3Mgb25seS4KICAgICIiIgogICAgaWYgbm90IFdJTjMyX09LOgogICAg"
    "ICAgIHJldHVybiBGYWxzZQogICAgdHJ5OgogICAgICAgIGRlc2t0b3AgPSBQYXRoLmhvbWUoKSAv"
    "ICJEZXNrdG9wIgogICAgICAgIHNob3J0Y3V0X3BhdGggPSBkZXNrdG9wIC8gZiJ7REVDS19OQU1F"
    "fS5sbmsiCgogICAgICAgICMgcHl0aG9udyA9IHNhbWUgYXMgcHl0aG9uIGJ1dCBubyBjb25zb2xl"
    "IHdpbmRvdwogICAgICAgIHB5dGhvbncgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQogICAgICAgIGlm"
    "IHB5dGhvbncubmFtZS5sb3dlcigpID09ICJweXRob24uZXhlIjoKICAgICAgICAgICAgcHl0aG9u"
    "dyA9IHB5dGhvbncucGFyZW50IC8gInB5dGhvbncuZXhlIgogICAgICAgIGlmIG5vdCBweXRob253"
    "LmV4aXN0cygpOgogICAgICAgICAgICBweXRob253ID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKCiAg"
    "ICAgICAgZGVja19wYXRoID0gUGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpCgogICAgICAgIHNoZWxs"
    "ID0gd2luMzJjb20uY2xpZW50LkRpc3BhdGNoKCJXU2NyaXB0LlNoZWxsIikKICAgICAgICBzYyA9"
    "IHNoZWxsLkNyZWF0ZVNob3J0Q3V0KHN0cihzaG9ydGN1dF9wYXRoKSkKICAgICAgICBzYy5UYXJn"
    "ZXRQYXRoICAgICA9IHN0cihweXRob253KQogICAgICAgIHNjLkFyZ3VtZW50cyAgICAgID0gZici"
    "e2RlY2tfcGF0aH0iJwogICAgICAgIHNjLldvcmtpbmdEaXJlY3RvcnkgPSBzdHIoZGVja19wYXRo"
    "LnBhcmVudCkKICAgICAgICBzYy5EZXNjcmlwdGlvbiAgICA9IGYie0RFQ0tfTkFNRX0g4oCUIEVj"
    "aG8gRGVjayIKCiAgICAgICAgIyBVc2UgbmV1dHJhbCBmYWNlIGFzIGljb24gaWYgYXZhaWxhYmxl"
    "CiAgICAgICAgaWNvbl9wYXRoID0gY2ZnX3BhdGgoImZhY2VzIikgLyBmIntGQUNFX1BSRUZJWH1f"
    "TmV1dHJhbC5wbmciCiAgICAgICAgaWYgaWNvbl9wYXRoLmV4aXN0cygpOgogICAgICAgICAgICAj"
    "IFdpbmRvd3Mgc2hvcnRjdXRzIGNhbid0IHVzZSBQTkcgZGlyZWN0bHkg4oCUIHNraXAgaWNvbiBp"
    "ZiBubyAuaWNvCiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgc2Muc2F2ZSgpCiAgICAgICAgcmV0"
    "dXJuIFRydWUKICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICBwcmludChmIltTSE9S"
    "VENVVF1bV0FSTl0gQ291bGQgbm90IGNyZWF0ZSBzaG9ydGN1dDoge2V9IikKICAgICAgICByZXR1"
    "cm4gRmFsc2UKCiMg4pSA4pSAIEpTT05MIFVUSUxJVElFUyDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIHJlYWRfanNvbmwo"
    "cGF0aDogUGF0aCkgLT4gbGlzdFtkaWN0XToKICAgICIiIlJlYWQgYSBKU09OTCBmaWxlLiBSZXR1"
    "cm5zIGxpc3Qgb2YgZGljdHMuIEhhbmRsZXMgSlNPTiBhcnJheXMgdG9vLiIiIgogICAgaWYgbm90"
    "IHBhdGguZXhpc3RzKCk6CiAgICAgICAgcmV0dXJuIFtdCiAgICByYXcgPSBwYXRoLnJlYWRfdGV4"
    "dChlbmNvZGluZz0idXRmLTgiKS5zdHJpcCgpCiAgICBpZiBub3QgcmF3OgogICAgICAgIHJldHVy"
    "biBbXQogICAgaWYgcmF3LnN0YXJ0c3dpdGgoIlsiKToKICAgICAgICB0cnk6CiAgICAgICAgICAg"
    "IGRhdGEgPSBqc29uLmxvYWRzKHJhdykKICAgICAgICAgICAgcmV0dXJuIFt4IGZvciB4IGluIGRh"
    "dGEgaWYgaXNpbnN0YW5jZSh4LCBkaWN0KV0KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgICAgICBwYXNzCiAgICBpdGVtcyA9IFtdCiAgICBmb3IgbGluZSBpbiByYXcuc3BsaXRsaW5l"
    "cygpOgogICAgICAgIGxpbmUgPSBsaW5lLnN0cmlwKCkKICAgICAgICBpZiBub3QgbGluZToKICAg"
    "ICAgICAgICAgY29udGludWUKICAgICAgICB0cnk6CiAgICAgICAgICAgIG9iaiA9IGpzb24ubG9h"
    "ZHMobGluZSkKICAgICAgICAgICAgaWYgaXNpbnN0YW5jZShvYmosIGRpY3QpOgogICAgICAgICAg"
    "ICAgICAgaXRlbXMuYXBwZW5kKG9iaikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAg"
    "ICAgICBjb250aW51ZQogICAgcmV0dXJuIGl0ZW1zCgpkZWYgYXBwZW5kX2pzb25sKHBhdGg6IFBh"
    "dGgsIG9iajogZGljdCkgLT4gTm9uZToKICAgICIiIkFwcGVuZCBvbmUgcmVjb3JkIHRvIGEgSlNP"
    "TkwgZmlsZS4iIiIKICAgIHBhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9"
    "VHJ1ZSkKICAgIHdpdGggcGF0aC5vcGVuKCJhIiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAg"
    "ICAgICBmLndyaXRlKGpzb24uZHVtcHMob2JqLCBlbnN1cmVfYXNjaWk9RmFsc2UpICsgIlxuIikK"
    "CmRlZiB3cml0ZV9qc29ubChwYXRoOiBQYXRoLCByZWNvcmRzOiBsaXN0W2RpY3RdKSAtPiBOb25l"
    "OgogICAgIiIiT3ZlcndyaXRlIGEgSlNPTkwgZmlsZSB3aXRoIGEgbGlzdCBvZiByZWNvcmRzLiIi"
    "IgogICAgcGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAg"
    "d2l0aCBwYXRoLm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgIGZvciBy"
    "IGluIHJlY29yZHM6CiAgICAgICAgICAgIGYud3JpdGUoanNvbi5kdW1wcyhyLCBlbnN1cmVfYXNj"
    "aWk9RmFsc2UpICsgIlxuIikKCiMg4pSA4pSAIEtFWVdPUkQgLyBNRU1PUlkgSEVMUEVSUyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKX1NUT1BXT1JEUyA9IHsKICAgICJ0aGUi"
    "LCJhbmQiLCJ0aGF0Iiwid2l0aCIsImhhdmUiLCJ0aGlzIiwiZnJvbSIsInlvdXIiLCJ3aGF0Iiwi"
    "d2hlbiIsCiAgICAid2hlcmUiLCJ3aGljaCIsIndvdWxkIiwidGhlcmUiLCJ0aGV5IiwidGhlbSIs"
    "InRoZW4iLCJpbnRvIiwianVzdCIsCiAgICAiYWJvdXQiLCJsaWtlIiwiYmVjYXVzZSIsIndoaWxl"
    "IiwiY291bGQiLCJzaG91bGQiLCJ0aGVpciIsIndlcmUiLCJiZWVuIiwKICAgICJiZWluZyIsImRv"
    "ZXMiLCJkaWQiLCJkb250IiwiZGlkbnQiLCJjYW50Iiwid29udCIsIm9udG8iLCJvdmVyIiwidW5k"
    "ZXIiLAogICAgInRoYW4iLCJhbHNvIiwic29tZSIsIm1vcmUiLCJsZXNzIiwib25seSIsIm5lZWQi"
    "LCJ3YW50Iiwid2lsbCIsInNoYWxsIiwKICAgICJhZ2FpbiIsInZlcnkiLCJtdWNoIiwicmVhbGx5"
    "IiwibWFrZSIsIm1hZGUiLCJ1c2VkIiwidXNpbmciLCJzYWlkIiwKICAgICJ0ZWxsIiwidG9sZCIs"
    "ImlkZWEiLCJjaGF0IiwiY29kZSIsInRoaW5nIiwic3R1ZmYiLCJ1c2VyIiwiYXNzaXN0YW50IiwK"
    "fQoKZGVmIGV4dHJhY3Rfa2V5d29yZHModGV4dDogc3RyLCBsaW1pdDogaW50ID0gMTIpIC0+IGxp"
    "c3Rbc3RyXToKICAgIHRva2VucyA9IFt0Lmxvd2VyKCkuc3RyaXAoIiAuLCE/OzonXCIoKVtde30i"
    "KSBmb3IgdCBpbiB0ZXh0LnNwbGl0KCldCiAgICBzZWVuLCByZXN1bHQgPSBzZXQoKSwgW10KICAg"
    "IGZvciB0IGluIHRva2VuczoKICAgICAgICBpZiBsZW4odCkgPCAzIG9yIHQgaW4gX1NUT1BXT1JE"
    "UyBvciB0LmlzZGlnaXQoKToKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpZiB0IG5vdCBp"
    "biBzZWVuOgogICAgICAgICAgICBzZWVuLmFkZCh0KQogICAgICAgICAgICByZXN1bHQuYXBwZW5k"
    "KHQpCiAgICAgICAgaWYgbGVuKHJlc3VsdCkgPj0gbGltaXQ6CiAgICAgICAgICAgIGJyZWFrCiAg"
    "ICByZXR1cm4gcmVzdWx0CgpkZWYgaW5mZXJfcmVjb3JkX3R5cGUodXNlcl90ZXh0OiBzdHIsIGFz"
    "c2lzdGFudF90ZXh0OiBzdHIgPSAiIikgLT4gc3RyOgogICAgdCA9ICh1c2VyX3RleHQgKyAiICIg"
    "KyBhc3Npc3RhbnRfdGV4dCkubG93ZXIoKQogICAgaWYgImRyZWFtIiBpbiB0OiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICByZXR1cm4gImRyZWFtIgogICAgaWYgYW55KHggaW4gdCBmb3IgeCBp"
    "biAoImxzbCIsInB5dGhvbiIsInNjcmlwdCIsImNvZGUiLCJlcnJvciIsImJ1ZyIpKToKICAgICAg"
    "ICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgiZml4ZWQiLCJyZXNvbHZlZCIsInNvbHV0aW9uIiwi"
    "d29ya2luZyIpKToKICAgICAgICAgICAgcmV0dXJuICJyZXNvbHV0aW9uIgogICAgICAgIHJldHVy"
    "biAiaXNzdWUiCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgicmVtaW5kIiwidGltZXIiLCJh"
    "bGFybSIsInRhc2siKSk6CiAgICAgICAgcmV0dXJuICJ0YXNrIgogICAgaWYgYW55KHggaW4gdCBm"
    "b3IgeCBpbiAoImlkZWEiLCJjb25jZXB0Iiwid2hhdCBpZiIsImdhbWUiLCJwcm9qZWN0IikpOgog"
    "ICAgICAgIHJldHVybiAiaWRlYSIKICAgIGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJwcmVmZXIi"
    "LCJhbHdheXMiLCJuZXZlciIsImkgbGlrZSIsImkgd2FudCIpKToKICAgICAgICByZXR1cm4gInBy"
    "ZWZlcmVuY2UiCiAgICByZXR1cm4gImNvbnZlcnNhdGlvbiIKCiMg4pSA4pSAIFBBU1MgMSBDT01Q"
    "TEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKIyBOZXh0OiBQYXNzIDIg4oCUIFdpZGdldCBDbGFzc2VzCiMgKEdhdWdlV2lk"
    "Z2V0LCBNb29uV2lkZ2V0LCBTcGhlcmVXaWRnZXQsIEVtb3Rpb25CbG9jaywKIyAgTWlycm9yV2lk"
    "Z2V0LCBWYW1waXJlU3RhdGVTdHJpcCwgQ29sbGFwc2libGVCbG9jaykKCgojIOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoj"
    "IE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgMjogV0lER0VUIENMQVNTRVMKIyBBcHBlbmRlZCB0byBt"
    "b3JnYW5uYV9wYXNzMS5weSB0byBmb3JtIHRoZSBmdWxsIGRlY2suCiMKIyBXaWRnZXRzIGRlZmlu"
    "ZWQgaGVyZToKIyAgIEdhdWdlV2lkZ2V0ICAgICAgICAgIOKAlCBob3Jpem9udGFsIGZpbGwgYmFy"
    "IHdpdGggbGFiZWwgYW5kIHZhbHVlCiMgICBEcml2ZVdpZGdldCAgICAgICAgICDigJQgZHJpdmUg"
    "dXNhZ2UgYmFyICh1c2VkL3RvdGFsIEdCKQojICAgU3BoZXJlV2lkZ2V0ICAgICAgICAg4oCUIGZp"
    "bGxlZCBjaXJjbGUgZm9yIEJMT09EIGFuZCBNQU5BCiMgICBNb29uV2lkZ2V0ICAgICAgICAgICDi"
    "gJQgZHJhd24gbW9vbiBvcmIgd2l0aCBwaGFzZSBzaGFkb3cKIyAgIEVtb3Rpb25CbG9jayAgICAg"
    "ICAgIOKAlCBjb2xsYXBzaWJsZSBlbW90aW9uIGhpc3RvcnkgY2hpcHMKIyAgIE1pcnJvcldpZGdl"
    "dCAgICAgICAgIOKAlCBmYWNlIGltYWdlIGRpc3BsYXkgKHRoZSBNaXJyb3IpCiMgICBWYW1waXJl"
    "U3RhdGVTdHJpcCAgICDigJQgZnVsbC13aWR0aCB0aW1lL21vb24vc3RhdGUgc3RhdHVzIGJhcgoj"
    "ICAgQ29sbGFwc2libGVCbG9jayAgICAg4oCUIHdyYXBwZXIgdGhhdCBhZGRzIGNvbGxhcHNlIHRv"
    "Z2dsZSB0byBhbnkgd2lkZ2V0CiMgICBIYXJkd2FyZVBhbmVsICAgICAgICDigJQgZ3JvdXBzIGFs"
    "bCBzeXN0ZW1zIGdhdWdlcwojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKCiMg4pSA4pSAIEdBVUdFIFdJREdFVCDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgR2F1Z2VXaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIEhvcml6"
    "b250YWwgZmlsbC1iYXIgZ2F1Z2Ugd2l0aCBnb3RoaWMgc3R5bGluZy4KICAgIFNob3dzOiBsYWJl"
    "bCAodG9wLWxlZnQpLCB2YWx1ZSB0ZXh0ICh0b3AtcmlnaHQpLCBmaWxsIGJhciAoYm90dG9tKS4K"
    "ICAgIENvbG9yIHNoaWZ0czogbm9ybWFsIOKGkiBDX0NSSU1TT04g4oaSIENfQkxPT0QgYXMgdmFs"
    "dWUgYXBwcm9hY2hlcyBtYXguCiAgICBTaG93cyAnTi9BJyB3aGVuIGRhdGEgaXMgdW5hdmFpbGFi"
    "bGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKICAgICAgICBsYWJl"
    "bDogc3RyLAogICAgICAgIHVuaXQ6IHN0ciA9ICIiLAogICAgICAgIG1heF92YWw6IGZsb2F0ID0g"
    "MTAwLjAsCiAgICAgICAgY29sb3I6IHN0ciA9IENfR09MRCwKICAgICAgICBwYXJlbnQ9Tm9uZQog"
    "ICAgKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLmxhYmVs"
    "ICAgID0gbGFiZWwKICAgICAgICBzZWxmLnVuaXQgICAgID0gdW5pdAogICAgICAgIHNlbGYubWF4"
    "X3ZhbCAgPSBtYXhfdmFsCiAgICAgICAgc2VsZi5jb2xvciAgICA9IGNvbG9yCiAgICAgICAgc2Vs"
    "Zi5fdmFsdWUgICA9IDAuMAogICAgICAgIHNlbGYuX2Rpc3BsYXkgPSAiTi9BIgogICAgICAgIHNl"
    "bGYuX2F2YWlsYWJsZSA9IEZhbHNlCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSgxMDAsIDYw"
    "KQogICAgICAgIHNlbGYuc2V0TWF4aW11bUhlaWdodCg3MikKCiAgICBkZWYgc2V0VmFsdWUoc2Vs"
    "ZiwgdmFsdWU6IGZsb2F0LCBkaXNwbGF5OiBzdHIgPSAiIiwgYXZhaWxhYmxlOiBib29sID0gVHJ1"
    "ZSkgLT4gTm9uZToKICAgICAgICBzZWxmLl92YWx1ZSAgICAgPSBtaW4oZmxvYXQodmFsdWUpLCBz"
    "ZWxmLm1heF92YWwpCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gYXZhaWxhYmxlCiAgICAgICAg"
    "aWYgbm90IGF2YWlsYWJsZToKICAgICAgICAgICAgc2VsZi5fZGlzcGxheSA9ICJOL0EiCiAgICAg"
    "ICAgZWxpZiBkaXNwbGF5OgogICAgICAgICAgICBzZWxmLl9kaXNwbGF5ID0gZGlzcGxheQogICAg"
    "ICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkgPSBmInt2YWx1ZTouMGZ9e3NlbGYu"
    "dW5pdH0iCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBzZXRVbmF2YWlsYWJsZShzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2F2YWlsYWJsZSA9IEZhbHNlCiAgICAgICAgc2VsZi5f"
    "ZGlzcGxheSAgID0gIk4vQSIKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZl"
    "bnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAg"
    "ICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAg"
    "ICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgIyBCYWNrZ3Jv"
    "dW5kCiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3LCBoLCBRQ29sb3IoQ19CRzMpKQogICAgICAg"
    "IHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgcC5kcmF3UmVjdCgwLCAwLCB3IC0g"
    "MSwgaCAtIDEpCgogICAgICAgICMgTGFiZWwKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhU"
    "X0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOCwgUUZvbnQuV2VpZ2h0"
    "LkJvbGQpKQogICAgICAgIHAuZHJhd1RleHQoNiwgMTQsIHNlbGYubGFiZWwpCgogICAgICAgICMg"
    "VmFsdWUKICAgICAgICBwLnNldFBlbihRQ29sb3Ioc2VsZi5jb2xvciBpZiBzZWxmLl9hdmFpbGFi"
    "bGUgZWxzZSBDX1RFWFRfRElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCAx"
    "MCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAg"
    "ICAgdncgPSBmbS5ob3Jpem9udGFsQWR2YW5jZShzZWxmLl9kaXNwbGF5KQogICAgICAgIHAuZHJh"
    "d1RleHQodyAtIHZ3IC0gNiwgMTQsIHNlbGYuX2Rpc3BsYXkpCgogICAgICAgICMgRmlsbCBiYXIK"
    "ICAgICAgICBiYXJfeSA9IGggLSAxOAogICAgICAgIGJhcl9oID0gMTAKICAgICAgICBiYXJfdyA9"
    "IHcgLSAxMgogICAgICAgIHAuZmlsbFJlY3QoNiwgYmFyX3ksIGJhcl93LCBiYXJfaCwgUUNvbG9y"
    "KENfQkcpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgcC5kcmF3"
    "UmVjdCg2LCBiYXJfeSwgYmFyX3cgLSAxLCBiYXJfaCAtIDEpCgogICAgICAgIGlmIHNlbGYuX2F2"
    "YWlsYWJsZSBhbmQgc2VsZi5tYXhfdmFsID4gMDoKICAgICAgICAgICAgZnJhYyA9IHNlbGYuX3Zh"
    "bHVlIC8gc2VsZi5tYXhfdmFsCiAgICAgICAgICAgIGZpbGxfdyA9IG1heCgxLCBpbnQoKGJhcl93"
    "IC0gMikgKiBmcmFjKSkKICAgICAgICAgICAgIyBDb2xvciBzaGlmdCBuZWFyIGxpbWl0CiAgICAg"
    "ICAgICAgIGJhcl9jb2xvciA9IChDX0JMT09EIGlmIGZyYWMgPiAwLjg1IGVsc2UKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIENfQ1JJTVNPTiBpZiBmcmFjID4gMC42NSBlbHNlCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBzZWxmLmNvbG9yKQogICAgICAgICAgICBncmFkID0gUUxpbmVhckdyYWRp"
    "ZW50KDcsIGJhcl95ICsgMSwgNyArIGZpbGxfdywgYmFyX3kgKyAxKQogICAgICAgICAgICBncmFk"
    "LnNldENvbG9yQXQoMCwgUUNvbG9yKGJhcl9jb2xvcikuZGFya2VyKDE2MCkpCiAgICAgICAgICAg"
    "IGdyYWQuc2V0Q29sb3JBdCgxLCBRQ29sb3IoYmFyX2NvbG9yKSkKICAgICAgICAgICAgcC5maWxs"
    "UmVjdCg3LCBiYXJfeSArIDEsIGZpbGxfdywgYmFyX2ggLSAyLCBncmFkKQoKICAgICAgICBwLmVu"
    "ZCgpCgoKIyDilIDilIAgRFJJVkUgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEcml2ZVdp"
    "ZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgRHJpdmUgdXNhZ2UgZGlzcGxheS4gU2hvd3MgZHJp"
    "dmUgbGV0dGVyLCB1c2VkL3RvdGFsIEdCLCBmaWxsIGJhci4KICAgIEF1dG8tZGV0ZWN0cyBhbGwg"
    "bW91bnRlZCBkcml2ZXMgdmlhIHBzdXRpbC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxm"
    "LCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAg"
    "c2VsZi5fZHJpdmVzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLnNldE1pbmltdW1IZWln"
    "aHQoMzApCiAgICAgICAgc2VsZi5fcmVmcmVzaCgpCgogICAgZGVmIF9yZWZyZXNoKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5fZHJpdmVzID0gW10KICAgICAgICBpZiBub3QgUFNVVElMX09L"
    "OgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIGZvciBwYXJ0IGlu"
    "IHBzdXRpbC5kaXNrX3BhcnRpdGlvbnMoYWxsPUZhbHNlKToKICAgICAgICAgICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgICAgICAgICB1c2FnZSA9IHBzdXRpbC5kaXNrX3VzYWdlKHBhcnQubW91bnRw"
    "b2ludCkKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kcml2ZXMuYXBwZW5kKHsKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgImxldHRlciI6IHBhcnQuZGV2aWNlLnJzdHJpcCgiXFwiKS5yc3RyaXAo"
    "Ii8iKSwKICAgICAgICAgICAgICAgICAgICAgICAgInVzZWQiOiAgIHVzYWdlLnVzZWQgIC8gMTAy"
    "NCoqMywKICAgICAgICAgICAgICAgICAgICAgICAgInRvdGFsIjogIHVzYWdlLnRvdGFsIC8gMTAy"
    "NCoqMywKICAgICAgICAgICAgICAgICAgICAgICAgInBjdCI6ICAgIHVzYWdlLnBlcmNlbnQgLyAx"
    "MDAuMCwKICAgICAgICAgICAgICAgICAgICB9KQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbjoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b246CiAgICAgICAgICAgIHBhc3MKICAgICAgICAjIFJlc2l6ZSB0byBmaXQgYWxsIGRyaXZlcwog"
    "ICAgICAgIG4gPSBtYXgoMSwgbGVuKHNlbGYuX2RyaXZlcykpCiAgICAgICAgc2VsZi5zZXRNaW5p"
    "bXVtSGVpZ2h0KG4gKiAyOCArIDgpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWlu"
    "dEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQog"
    "ICAgICAgIHAuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykK"
    "ICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCiAgICAgICAgcC5maWxs"
    "UmVjdCgwLCAwLCB3LCBoLCBRQ29sb3IoQ19CRzMpKQoKICAgICAgICBpZiBub3Qgc2VsZi5fZHJp"
    "dmVzOgogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAg"
    "IHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDkpKQogICAgICAgICAgICBwLmRyYXdUZXh0KDYs"
    "IDE4LCAiTi9BIOKAlCBwc3V0aWwgdW5hdmFpbGFibGUiKQogICAgICAgICAgICBwLmVuZCgpCiAg"
    "ICAgICAgICAgIHJldHVybgoKICAgICAgICByb3dfaCA9IDI2CiAgICAgICAgeSA9IDQKICAgICAg"
    "ICBmb3IgZHJ2IGluIHNlbGYuX2RyaXZlczoKICAgICAgICAgICAgbGV0dGVyID0gZHJ2WyJsZXR0"
    "ZXIiXQogICAgICAgICAgICB1c2VkICAgPSBkcnZbInVzZWQiXQogICAgICAgICAgICB0b3RhbCAg"
    "PSBkcnZbInRvdGFsIl0KICAgICAgICAgICAgcGN0ICAgID0gZHJ2WyJwY3QiXQoKICAgICAgICAg"
    "ICAgIyBMYWJlbAogICAgICAgICAgICBsYWJlbCA9IGYie2xldHRlcn0gIHt1c2VkOi4xZn0ve3Rv"
    "dGFsOi4wZn1HQiIKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfR09MRCkpCiAgICAgICAg"
    "ICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDgsIFFGb250LldlaWdodC5Cb2xkKSkKICAg"
    "ICAgICAgICAgcC5kcmF3VGV4dCg2LCB5ICsgMTIsIGxhYmVsKQoKICAgICAgICAgICAgIyBCYXIK"
    "ICAgICAgICAgICAgYmFyX3ggPSA2CiAgICAgICAgICAgIGJhcl95ID0geSArIDE1CiAgICAgICAg"
    "ICAgIGJhcl93ID0gdyAtIDEyCiAgICAgICAgICAgIGJhcl9oID0gOAogICAgICAgICAgICBwLmZp"
    "bGxSZWN0KGJhcl94LCBiYXJfeSwgYmFyX3csIGJhcl9oLCBRQ29sb3IoQ19CRykpCiAgICAgICAg"
    "ICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgICAgIHAuZHJhd1JlY3QoYmFy"
    "X3gsIGJhcl95LCBiYXJfdyAtIDEsIGJhcl9oIC0gMSkKCiAgICAgICAgICAgIGZpbGxfdyA9IG1h"
    "eCgxLCBpbnQoKGJhcl93IC0gMikgKiBwY3QpKQogICAgICAgICAgICBiYXJfY29sb3IgPSAoQ19C"
    "TE9PRCBpZiBwY3QgPiAwLjkgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19DUklNU09O"
    "IGlmIHBjdCA+IDAuNzUgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19HT0xEX0RJTSkK"
    "ICAgICAgICAgICAgZ3JhZCA9IFFMaW5lYXJHcmFkaWVudChiYXJfeCArIDEsIGJhcl95LCBiYXJf"
    "eCArIGZpbGxfdywgYmFyX3kpCiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgwLCBRQ29sb3Io"
    "YmFyX2NvbG9yKS5kYXJrZXIoMTUwKSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDEsIFFD"
    "b2xvcihiYXJfY29sb3IpKQogICAgICAgICAgICBwLmZpbGxSZWN0KGJhcl94ICsgMSwgYmFyX3kg"
    "KyAxLCBmaWxsX3csIGJhcl9oIC0gMiwgZ3JhZCkKCiAgICAgICAgICAgIHkgKz0gcm93X2gKCiAg"
    "ICAgICAgcC5lbmQoKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIi"
    "Q2FsbCBwZXJpb2RpY2FsbHkgdG8gdXBkYXRlIGRyaXZlIHN0YXRzLiIiIgogICAgICAgIHNlbGYu"
    "X3JlZnJlc2goKQoKCiMg4pSA4pSAIFNQSEVSRSBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNw"
    "aGVyZVdpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgRmlsbGVkIGNpcmNsZSBnYXVnZSDigJQg"
    "dXNlZCBmb3IgQkxPT0QgKHRva2VuIHBvb2wpIGFuZCBNQU5BIChWUkFNKS4KICAgIEZpbGxzIGZy"
    "b20gYm90dG9tIHVwLiBHbGFzc3kgc2hpbmUgZWZmZWN0LiBMYWJlbCBiZWxvdy4KICAgICIiIgoK"
    "ICAgIGRlZiBfX2luaXRfXygKICAgICAgICBzZWxmLAogICAgICAgIGxhYmVsOiBzdHIsCiAgICAg"
    "ICAgY29sb3JfZnVsbDogc3RyLAogICAgICAgIGNvbG9yX2VtcHR5OiBzdHIsCiAgICAgICAgcGFy"
    "ZW50PU5vbmUKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAg"
    "c2VsZi5sYWJlbCAgICAgICA9IGxhYmVsCiAgICAgICAgc2VsZi5jb2xvcl9mdWxsICA9IGNvbG9y"
    "X2Z1bGwKICAgICAgICBzZWxmLmNvbG9yX2VtcHR5ID0gY29sb3JfZW1wdHkKICAgICAgICBzZWxm"
    "Ll9maWxsICAgICAgID0gMC4wICAgIyAwLjAg4oaSIDEuMAogICAgICAgIHNlbGYuX2F2YWlsYWJs"
    "ZSAgPSBUcnVlCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSg4MCwgMTAwKQoKICAgIGRlZiBz"
    "ZXRGaWxsKHNlbGYsIGZyYWN0aW9uOiBmbG9hdCwgYXZhaWxhYmxlOiBib29sID0gVHJ1ZSkgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLl9maWxsICAgICAgPSBtYXgoMC4wLCBtaW4oMS4wLCBmcmFjdGlv"
    "bikpCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gYXZhaWxhYmxlCiAgICAgICAgc2VsZi51cGRh"
    "dGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAg"
    "PSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJI"
    "aW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxmLmhlaWdo"
    "dCgpCgogICAgICAgIHIgID0gbWluKHcsIGggLSAyMCkgLy8gMiAtIDQKICAgICAgICBjeCA9IHcg"
    "Ly8gMgogICAgICAgIGN5ID0gKGggLSAyMCkgLy8gMiArIDQKCiAgICAgICAgIyBEcm9wIHNoYWRv"
    "dwogICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAgICAgIHAuc2V0QnJ1c2go"
    "UUNvbG9yKDAsIDAsIDAsIDgwKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciArIDMsIGN5"
    "IC0gciArIDMsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBCYXNlIGNpcmNsZSAoZW1wdHkgY29s"
    "b3IpCiAgICAgICAgcC5zZXRCcnVzaChRQ29sb3Ioc2VsZi5jb2xvcl9lbXB0eSkpCiAgICAgICAg"
    "cC5zZXRQZW4oUUNvbG9yKENfQk9SREVSKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwg"
    "Y3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgRmlsbCBmcm9tIGJvdHRvbQogICAgICAg"
    "IGlmIHNlbGYuX2ZpbGwgPiAwLjAxIGFuZCBzZWxmLl9hdmFpbGFibGU6CiAgICAgICAgICAgIGNp"
    "cmNsZV9wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgY2lyY2xlX3BhdGguYWRkRWxs"
    "aXBzZShmbG9hdChjeCAtIHIpLCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQoKICAgICAgICAgICAgZmls"
    "bF90b3BfeSA9IGN5ICsgciAtIChzZWxmLl9maWxsICogciAqIDIpCiAgICAgICAgICAgIGZyb20g"
    "UHlTaWRlNi5RdENvcmUgaW1wb3J0IFFSZWN0RgogICAgICAgICAgICBmaWxsX3JlY3QgPSBRUmVj"
    "dEYoY3ggLSByLCBmaWxsX3RvcF95LCByICogMiwgY3kgKyByIC0gZmlsbF90b3BfeSkKICAgICAg"
    "ICAgICAgZmlsbF9wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgZmlsbF9wYXRoLmFk"
    "ZFJlY3QoZmlsbF9yZWN0KQogICAgICAgICAgICBjbGlwcGVkID0gY2lyY2xlX3BhdGguaW50ZXJz"
    "ZWN0ZWQoZmlsbF9wYXRoKQoKICAgICAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4p"
    "CiAgICAgICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKHNlbGYuY29sb3JfZnVsbCkpCiAgICAgICAg"
    "ICAgIHAuZHJhd1BhdGgoY2xpcHBlZCkKCiAgICAgICAgIyBHbGFzc3kgc2hpbmUKICAgICAgICBz"
    "aGluZSA9IFFSYWRpYWxHcmFkaWVudCgKICAgICAgICAgICAgZmxvYXQoY3ggLSByICogMC4zKSwg"
    "ZmxvYXQoY3kgLSByICogMC4zKSwgZmxvYXQociAqIDAuNikKICAgICAgICApCiAgICAgICAgc2hp"
    "bmUuc2V0Q29sb3JBdCgwLCBRQ29sb3IoMjU1LCAyNTUsIDI1NSwgNTUpKQogICAgICAgIHNoaW5l"
    "LnNldENvbG9yQXQoMSwgUUNvbG9yKDI1NSwgMjU1LCAyNTUsIDApKQogICAgICAgIHAuc2V0QnJ1"
    "c2goc2hpbmUpCiAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgcC5k"
    "cmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIE91dGxp"
    "bmUKICAgICAgICBwLnNldEJydXNoKFF0LkJydXNoU3R5bGUuTm9CcnVzaCkKICAgICAgICBwLnNl"
    "dFBlbihRUGVuKFFDb2xvcihzZWxmLmNvbG9yX2Z1bGwpLCAxKSkKICAgICAgICBwLmRyYXdFbGxp"
    "cHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgTi9BIG92ZXJsYXkK"
    "ICAgICAgICBpZiBub3Qgc2VsZi5fYXZhaWxhYmxlOgogICAgICAgICAgICBwLnNldFBlbihRQ29s"
    "b3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udCgiQ291cmllciBOZXci"
    "LCA4KSkKICAgICAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICAgICAgdHh0ID0g"
    "Ik4vQSIKICAgICAgICAgICAgcC5kcmF3VGV4dChjeCAtIGZtLmhvcml6b250YWxBZHZhbmNlKHR4"
    "dCkgLy8gMiwgY3kgKyA0LCB0eHQpCgogICAgICAgICMgTGFiZWwgYmVsb3cgc3BoZXJlCiAgICAg"
    "ICAgbGFiZWxfdGV4dCA9IChzZWxmLmxhYmVsIGlmIHNlbGYuX2F2YWlsYWJsZSBlbHNlCiAgICAg"
    "ICAgICAgICAgICAgICAgICBmIntzZWxmLmxhYmVsfSIpCiAgICAgICAgcGN0X3RleHQgPSBmIntp"
    "bnQoc2VsZi5fZmlsbCAqIDEwMCl9JSIgaWYgc2VsZi5fYXZhaWxhYmxlIGVsc2UgIiIKCiAgICAg"
    "ICAgcC5zZXRQZW4oUUNvbG9yKHNlbGYuY29sb3JfZnVsbCkpCiAgICAgICAgcC5zZXRGb250KFFG"
    "b250KERFQ0tfRk9OVCwgOCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250"
    "TWV0cmljcygpCgogICAgICAgIGx3ID0gZm0uaG9yaXpvbnRhbEFkdmFuY2UobGFiZWxfdGV4dCkK"
    "ICAgICAgICBwLmRyYXdUZXh0KGN4IC0gbHcgLy8gMiwgaCAtIDEwLCBsYWJlbF90ZXh0KQoKICAg"
    "ICAgICBpZiBwY3RfdGV4dDoKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfVEVYVF9ESU0p"
    "KQogICAgICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAgICAgICAgICAg"
    "Zm0yID0gcC5mb250TWV0cmljcygpCiAgICAgICAgICAgIHB3ID0gZm0yLmhvcml6b250YWxBZHZh"
    "bmNlKHBjdF90ZXh0KQogICAgICAgICAgICBwLmRyYXdUZXh0KGN4IC0gcHcgLy8gMiwgaCAtIDEs"
    "IHBjdF90ZXh0KQoKICAgICAgICBwLmVuZCgpCgoKIyDilIDilIAgTU9PTiBXSURHRVQg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACmNsYXNzIE1vb25XaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIERyYXdu"
    "IG1vb24gb3JiIHdpdGggcGhhc2UtYWNjdXJhdGUgc2hhZG93LgoKICAgIFBIQVNFIENPTlZFTlRJ"
    "T04gKG5vcnRoZXJuIGhlbWlzcGhlcmUsIHN0YW5kYXJkKToKICAgICAgLSBXYXhpbmcgKG5ld+KG"
    "kmZ1bGwpOiBpbGx1bWluYXRlZCByaWdodCBzaWRlLCBzaGFkb3cgb24gbGVmdAogICAgICAtIFdh"
    "bmluZyAoZnVsbOKGkm5ldyk6IGlsbHVtaW5hdGVkIGxlZnQgc2lkZSwgc2hhZG93IG9uIHJpZ2h0"
    "CgogICAgVGhlIHNoYWRvd19zaWRlIGZsYWcgY2FuIGJlIGZsaXBwZWQgaWYgdGVzdGluZyByZXZl"
    "YWxzIGl0J3MgYmFja3dhcmRzCiAgICBvbiB0aGlzIG1hY2hpbmUuIFNldCBNT09OX1NIQURPV19G"
    "TElQID0gVHJ1ZSBpbiB0aGF0IGNhc2UuCiAgICAiIiIKCiAgICAjIOKGkCBGTElQIFRISVMgdG8g"
    "VHJ1ZSBpZiBtb29uIGFwcGVhcnMgYmFja3dhcmRzIGR1cmluZyB0ZXN0aW5nCiAgICBNT09OX1NI"
    "QURPV19GTElQOiBib29sID0gRmFsc2UKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5v"
    "bmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BoYXNl"
    "ICAgICAgID0gMC4wICAgICMgMC4wPW5ldywgMC41PWZ1bGwsIDEuMD1uZXcKICAgICAgICBzZWxm"
    "Ll9uYW1lICAgICAgICA9ICJORVcgTU9PTiIKICAgICAgICBzZWxmLl9pbGx1bWluYXRpb24gPSAw"
    "LjAgICAjIDAtMTAwCiAgICAgICAgc2VsZi5fc3VucmlzZSAgICAgPSAiMDY6MDAiCiAgICAgICAg"
    "c2VsZi5fc3Vuc2V0ICAgICAgPSAiMTg6MzAiCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSg4"
    "MCwgMTEwKQogICAgICAgIHNlbGYudXBkYXRlUGhhc2UoKSAgICAgICAgICAjIHBvcHVsYXRlIGNv"
    "cnJlY3QgcGhhc2UgaW1tZWRpYXRlbHkKICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQoK"
    "ICAgIGRlZiBfZmV0Y2hfc3VuX2FzeW5jKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGVmIF9mZXRj"
    "aCgpOgogICAgICAgICAgICBzciwgc3MgPSBnZXRfc3VuX3RpbWVzKCkKICAgICAgICAgICAgc2Vs"
    "Zi5fc3VucmlzZSA9IHNyCiAgICAgICAgICAgIHNlbGYuX3N1bnNldCAgPSBzcwogICAgICAgICAg"
    "ICAjIFNjaGVkdWxlIHJlcGFpbnQgb24gbWFpbiB0aHJlYWQgdmlhIFFUaW1lciDigJQgbmV2ZXIg"
    "Y2FsbAogICAgICAgICAgICAjIHNlbGYudXBkYXRlKCkgZGlyZWN0bHkgZnJvbSBhIGJhY2tncm91"
    "bmQgdGhyZWFkCiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDAsIHNlbGYudXBkYXRlKQog"
    "ICAgICAgIHRocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9mZXRjaCwgZGFlbW9uPVRydWUpLnN0YXJ0"
    "KCkKCiAgICBkZWYgdXBkYXRlUGhhc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9waGFz"
    "ZSwgc2VsZi5fbmFtZSwgc2VsZi5faWxsdW1pbmF0aW9uID0gZ2V0X21vb25fcGhhc2UoKQogICAg"
    "ICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9u"
    "ZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBh"
    "aW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgo"
    "KSwgc2VsZi5oZWlnaHQoKQoKICAgICAgICByICA9IG1pbih3LCBoIC0gMzYpIC8vIDIgLSA0CiAg"
    "ICAgICAgY3ggPSB3IC8vIDIKICAgICAgICBjeSA9IChoIC0gMzYpIC8vIDIgKyA0CgogICAgICAg"
    "ICMgQmFja2dyb3VuZCBjaXJjbGUgKHNwYWNlKQogICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDIw"
    "LCAxMiwgMjgpKQogICAgICAgIHAuc2V0UGVuKFFQZW4oUUNvbG9yKENfU0lMVkVSX0RJTSksIDEp"
    "KQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAg"
    "ICAgICAgY3ljbGVfZGF5ID0gc2VsZi5fcGhhc2UgKiBfTFVOQVJfQ1lDTEUKICAgICAgICBpc193"
    "YXhpbmcgPSBjeWNsZV9kYXkgPCAoX0xVTkFSX0NZQ0xFIC8gMikKCiAgICAgICAgIyBGdWxsIG1v"
    "b24gYmFzZSAobW9vbiBzdXJmYWNlIGNvbG9yKQogICAgICAgIGlmIHNlbGYuX2lsbHVtaW5hdGlv"
    "biA+IDE6CiAgICAgICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAgICAgICAg"
    "ICBwLnNldEJydXNoKFFDb2xvcigyMjAsIDIxMCwgMTg1KSkKICAgICAgICAgICAgcC5kcmF3RWxs"
    "aXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIFNoYWRvdyBjYWxj"
    "dWxhdGlvbgogICAgICAgICMgaWxsdW1pbmF0aW9uIGdvZXMgMOKGkjEwMCB3YXhpbmcsIDEwMOKG"
    "kjAgd2FuaW5nCiAgICAgICAgIyBzaGFkb3dfb2Zmc2V0IGNvbnRyb2xzIGhvdyBtdWNoIG9mIHRo"
    "ZSBjaXJjbGUgdGhlIHNoYWRvdyBjb3ZlcnMKICAgICAgICBpZiBzZWxmLl9pbGx1bWluYXRpb24g"
    "PCA5OToKICAgICAgICAgICAgIyBmcmFjdGlvbiBvZiBkaWFtZXRlciB0aGUgc2hhZG93IGVsbGlw"
    "c2UgaXMgb2Zmc2V0CiAgICAgICAgICAgIGlsbHVtX2ZyYWMgID0gc2VsZi5faWxsdW1pbmF0aW9u"
    "IC8gMTAwLjAKICAgICAgICAgICAgc2hhZG93X2ZyYWMgPSAxLjAgLSBpbGx1bV9mcmFjCgogICAg"
    "ICAgICAgICAjIHdheGluZzogaWxsdW1pbmF0ZWQgcmlnaHQsIHNoYWRvdyBMRUZUCiAgICAgICAg"
    "ICAgICMgd2FuaW5nOiBpbGx1bWluYXRlZCBsZWZ0LCBzaGFkb3cgUklHSFQKICAgICAgICAgICAg"
    "IyBvZmZzZXQgbW92ZXMgdGhlIHNoYWRvdyBlbGxpcHNlIGhvcml6b250YWxseQogICAgICAgICAg"
    "ICBvZmZzZXQgPSBpbnQoc2hhZG93X2ZyYWMgKiByICogMikKCiAgICAgICAgICAgIGlmIE1vb25X"
    "aWRnZXQuTU9PTl9TSEFET1dfRkxJUDoKICAgICAgICAgICAgICAgIGlzX3dheGluZyA9IG5vdCBp"
    "c193YXhpbmcKCiAgICAgICAgICAgIGlmIGlzX3dheGluZzoKICAgICAgICAgICAgICAgICMgU2hh"
    "ZG93IG9uIGxlZnQgc2lkZQogICAgICAgICAgICAgICAgc2hhZG93X3ggPSBjeCAtIHIgLSBvZmZz"
    "ZXQKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICMgU2hhZG93IG9uIHJpZ2h0IHNp"
    "ZGUKICAgICAgICAgICAgICAgIHNoYWRvd194ID0gY3ggLSByICsgb2Zmc2V0CgogICAgICAgICAg"
    "ICBwLnNldEJydXNoKFFDb2xvcigxNSwgOCwgMjIpKQogICAgICAgICAgICBwLnNldFBlbihRdC5Q"
    "ZW5TdHlsZS5Ob1BlbikKCiAgICAgICAgICAgICMgRHJhdyBzaGFkb3cgZWxsaXBzZSDigJQgY2xp"
    "cHBlZCB0byBtb29uIGNpcmNsZQogICAgICAgICAgICBtb29uX3BhdGggPSBRUGFpbnRlclBhdGgo"
    "KQogICAgICAgICAgICBtb29uX3BhdGguYWRkRWxsaXBzZShmbG9hdChjeCAtIHIpLCBmbG9hdChj"
    "eSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZmxvYXQociAqIDIpLCBm"
    "bG9hdChyICogMikpCiAgICAgICAgICAgIHNoYWRvd19wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAg"
    "ICAgICAgICAgc2hhZG93X3BhdGguYWRkRWxsaXBzZShmbG9hdChzaGFkb3dfeCksIGZsb2F0KGN5"
    "IC0gciksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwg"
    "ZmxvYXQociAqIDIpKQogICAgICAgICAgICBjbGlwcGVkX3NoYWRvdyA9IG1vb25fcGF0aC5pbnRl"
    "cnNlY3RlZChzaGFkb3dfcGF0aCkKICAgICAgICAgICAgcC5kcmF3UGF0aChjbGlwcGVkX3NoYWRv"
    "dykKCiAgICAgICAgIyBTdWJ0bGUgc3VyZmFjZSBkZXRhaWwgKGNyYXRlcnMgaW1wbGllZCBieSBz"
    "bGlnaHQgdGV4dHVyZSBncmFkaWVudCkKICAgICAgICBzaGluZSA9IFFSYWRpYWxHcmFkaWVudChm"
    "bG9hdChjeCAtIHIgKiAwLjIpLCBmbG9hdChjeSAtIHIgKiAwLjIpLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAwLjgpKQogICAgICAgIHNoaW5lLnNldENvbG9yQXQo"
    "MCwgUUNvbG9yKDI1NSwgMjU1LCAyNDAsIDMwKSkKICAgICAgICBzaGluZS5zZXRDb2xvckF0KDEs"
    "IFFDb2xvcigyMDAsIDE4MCwgMTQwLCA1KSkKICAgICAgICBwLnNldEJydXNoKHNoaW5lKQogICAg"
    "ICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3gg"
    "LSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBPdXRsaW5lCiAgICAgICAgcC5z"
    "ZXRCcnVzaChRdC5CcnVzaFN0eWxlLk5vQnJ1c2gpCiAgICAgICAgcC5zZXRQZW4oUVBlbihRQ29s"
    "b3IoQ19TSUxWRVIpLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCBy"
    "ICogMiwgciAqIDIpCgogICAgICAgICMgUGhhc2UgbmFtZSBiZWxvdyBtb29uCiAgICAgICAgcC5z"
    "ZXRQZW4oUUNvbG9yKENfU0lMVkVSKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05U"
    "LCA3LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAg"
    "ICAgICBudyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHNlbGYuX25hbWUpCiAgICAgICAgcC5kcmF3"
    "VGV4dChjeCAtIG53IC8vIDIsIGN5ICsgciArIDE0LCBzZWxmLl9uYW1lKQoKICAgICAgICAjIEls"
    "bHVtaW5hdGlvbiBwZXJjZW50YWdlCiAgICAgICAgaWxsdW1fc3RyID0gZiJ7c2VsZi5faWxsdW1p"
    "bmF0aW9uOi4wZn0lIgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAg"
    "ICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAgICAgICBmbTIgPSBwLmZvbnRNZXRy"
    "aWNzKCkKICAgICAgICBpdyA9IGZtMi5ob3Jpem9udGFsQWR2YW5jZShpbGx1bV9zdHIpCiAgICAg"
    "ICAgcC5kcmF3VGV4dChjeCAtIGl3IC8vIDIsIGN5ICsgciArIDI0LCBpbGx1bV9zdHIpCgogICAg"
    "ICAgICMgU3VuIHRpbWVzIGF0IHZlcnkgYm90dG9tCiAgICAgICAgc3VuX3N0ciA9IGYi4piAIHtz"
    "ZWxmLl9zdW5yaXNlfSAg4pi9IHtzZWxmLl9zdW5zZXR9IgogICAgICAgIHAuc2V0UGVuKFFDb2xv"
    "cihDX0dPTERfRElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAg"
    "ICAgICBmbTMgPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICBzdyA9IGZtMy5ob3Jpem9udGFsQWR2"
    "YW5jZShzdW5fc3RyKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBzdyAvLyAyLCBoIC0gMiwgc3Vu"
    "X3N0cikKCiAgICAgICAgcC5lbmQoKQoKCiMg4pSA4pSAIEVNT1RJT04gQkxPQ0sg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmNsYXNzIEVtb3Rpb25CbG9jayhRV2lkZ2V0KToKICAgICIiIgogICAgQ29sbGFwc2libGUg"
    "ZW1vdGlvbiBoaXN0b3J5IHBhbmVsLgogICAgU2hvd3MgY29sb3ItY29kZWQgY2hpcHM6IOKcpiBF"
    "TU9USU9OX05BTUUgIEhIOk1NCiAgICBTaXRzIG5leHQgdG8gdGhlIE1pcnJvciAoZmFjZSB3aWRn"
    "ZXQpIGluIHRoZSBib3R0b20gYmxvY2sgcm93LgogICAgQ29sbGFwc2VzIHRvIGp1c3QgdGhlIGhl"
    "YWRlciBzdHJpcC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6"
    "CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5faGlzdG9yeTog"
    "bGlzdFt0dXBsZVtzdHIsIHN0cl1dID0gW10gICMgKGVtb3Rpb24sIHRpbWVzdGFtcCkKICAgICAg"
    "ICBzZWxmLl9leHBhbmRlZCA9IFRydWUKICAgICAgICBzZWxmLl9tYXhfZW50cmllcyA9IDMwCgog"
    "ICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRl"
    "bnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDApCgogICAg"
    "ICAgICMgSGVhZGVyIHJvdwogICAgICAgIGhlYWRlciA9IFFXaWRnZXQoKQogICAgICAgIGhlYWRl"
    "ci5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBoZWFkZXIuc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXItYm90dG9tOiAxcHggc29saWQge0Nf"
    "Q1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgaGwgPSBRSEJveExheW91dChoZWFkZXIp"
    "CiAgICAgICAgaGwuc2V0Q29udGVudHNNYXJnaW5zKDYsIDAsIDQsIDApCiAgICAgICAgaGwuc2V0"
    "U3BhY2luZyg0KQoKICAgICAgICBsYmwgPSBRTGFiZWwoIuKdpyBFTU9USU9OQUwgUkVDT1JEIikK"
    "ICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07"
    "IGZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmImZvbnQt"
    "ZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGxldHRlci1zcGFjaW5nOiAxcHg7IGJvcmRlcjog"
    "bm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4gPSBRVG9vbEJ1dHRvbigp"
    "CiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRGaXhlZFNpemUoMTYsIDE2KQogICAgICAgIHNl"
    "bGYuX3RvZ2dsZV9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB0"
    "cmFuc3BhcmVudDsgY29sb3I6IHtDX0dPTER9OyBib3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBw"
    "eDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4pa8IikKICAg"
    "ICAgICBzZWxmLl90b2dnbGVfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCgogICAg"
    "ICAgIGhsLmFkZFdpZGdldChsYmwpCiAgICAgICAgaGwuYWRkU3RyZXRjaCgpCiAgICAgICAgaGwu"
    "YWRkV2lkZ2V0KHNlbGYuX3RvZ2dsZV9idG4pCgogICAgICAgICMgU2Nyb2xsIGFyZWEgZm9yIGVt"
    "b3Rpb24gY2hpcHMKICAgICAgICBzZWxmLl9zY3JvbGwgPSBRU2Nyb2xsQXJlYSgpCiAgICAgICAg"
    "c2VsZi5fc2Nyb2xsLnNldFdpZGdldFJlc2l6YWJsZShUcnVlKQogICAgICAgIHNlbGYuX3Njcm9s"
    "bC5zZXRIb3Jpem9udGFsU2Nyb2xsQmFyUG9saWN5KAogICAgICAgICAgICBRdC5TY3JvbGxCYXJQ"
    "b2xpY3kuU2Nyb2xsQmFyQWx3YXlzT2ZmKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogbm9uZTsiCiAg"
    "ICAgICAgKQoKICAgICAgICBzZWxmLl9jaGlwX2NvbnRhaW5lciA9IFFXaWRnZXQoKQogICAgICAg"
    "IHNlbGYuX2NoaXBfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fY2hpcF9jb250YWluZXIpCiAg"
    "ICAgICAgc2VsZi5fY2hpcF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAg"
    "ICAgICAgc2VsZi5fY2hpcF9sYXlvdXQuc2V0U3BhY2luZygyKQogICAgICAgIHNlbGYuX2NoaXBf"
    "bGF5b3V0LmFkZFN0cmV0Y2goKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRXaWRnZXQoc2VsZi5f"
    "Y2hpcF9jb250YWluZXIpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoaGVhZGVyKQogICAgICAg"
    "IGxheW91dC5hZGRXaWRnZXQoc2VsZi5fc2Nyb2xsKQoKICAgICAgICBzZWxmLnNldE1pbmltdW1X"
    "aWR0aCgxMzApCgogICAgZGVmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9l"
    "eHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRWaXNp"
    "YmxlKHNlbGYuX2V4cGFuZGVkKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4pa8"
    "IiBpZiBzZWxmLl9leHBhbmRlZCBlbHNlICLilrIiKQogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0"
    "cnkoKQoKICAgIGRlZiBhZGRFbW90aW9uKHNlbGYsIGVtb3Rpb246IHN0ciwgdGltZXN0YW1wOiBz"
    "dHIgPSAiIikgLT4gTm9uZToKICAgICAgICBpZiBub3QgdGltZXN0YW1wOgogICAgICAgICAgICB0"
    "aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU0iKQogICAgICAgIHNlbGYu"
    "X2hpc3RvcnkuaW5zZXJ0KDAsIChlbW90aW9uLCB0aW1lc3RhbXApKQogICAgICAgIHNlbGYuX2hp"
    "c3RvcnkgPSBzZWxmLl9oaXN0b3J5WzpzZWxmLl9tYXhfZW50cmllc10KICAgICAgICBzZWxmLl9y"
    "ZWJ1aWxkX2NoaXBzKCkKCiAgICBkZWYgX3JlYnVpbGRfY2hpcHMoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICAjIENsZWFyIGV4aXN0aW5nIGNoaXBzIChrZWVwIHRoZSBzdHJldGNoIGF0IGVuZCkKICAg"
    "ICAgICB3aGlsZSBzZWxmLl9jaGlwX2xheW91dC5jb3VudCgpID4gMToKICAgICAgICAgICAgaXRl"
    "bSA9IHNlbGYuX2NoaXBfbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICBpZiBpdGVtLndpZGdl"
    "dCgpOgogICAgICAgICAgICAgICAgaXRlbS53aWRnZXQoKS5kZWxldGVMYXRlcigpCgogICAgICAg"
    "IGZvciBlbW90aW9uLCB0cyBpbiBzZWxmLl9oaXN0b3J5OgogICAgICAgICAgICBjb2xvciA9IEVN"
    "T1RJT05fQ09MT1JTLmdldChlbW90aW9uLCBDX1RFWFRfRElNKQogICAgICAgICAgICBjaGlwID0g"
    "UUxhYmVsKGYi4pymIHtlbW90aW9uLnVwcGVyKCl9ICB7dHN9IikKICAgICAgICAgICAgY2hpcC5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXpl"
    "OiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7ICIKICAgICAgICAgICAgICAg"
    "IGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgog"
    "ICAgICAgICAgICAgICAgZiJwYWRkaW5nOiAxcHggNHB4OyBib3JkZXItcmFkaXVzOiAycHg7Igog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0Lmluc2VydFdpZGdldCgK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LmNvdW50KCkgLSAxLCBjaGlwCiAgICAg"
    "ICAgICAgICkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9oaXN0"
    "b3J5LmNsZWFyKCkKICAgICAgICBzZWxmLl9yZWJ1aWxkX2NoaXBzKCkKCgojIOKUgOKUgCBNSVJS"
    "T1IgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBNaXJyb3JXaWRnZXQoUUxhYmVsKToKICAgICIi"
    "IgogICAgRmFjZSBpbWFnZSBkaXNwbGF5IOKAlCAnVGhlIE1pcnJvcicuCiAgICBEeW5hbWljYWxs"
    "eSBsb2FkcyBhbGwge0ZBQ0VfUFJFRklYfV8qLnBuZyBmaWxlcyBmcm9tIGNvbmZpZyBwYXRocy5m"
    "YWNlcy4KICAgIEF1dG8tbWFwcyBmaWxlbmFtZSB0byBlbW90aW9uIGtleToKICAgICAgICB7RkFD"
    "RV9QUkVGSVh9X0FsZXJ0LnBuZyAgICAg4oaSICJhbGVydCIKICAgICAgICB7RkFDRV9QUkVGSVh9"
    "X1NhZF9DcnlpbmcucG5nIOKGkiAic2FkIgogICAgICAgIHtGQUNFX1BSRUZJWH1fQ2hlYXRfTW9k"
    "ZS5wbmcg4oaSICJjaGVhdG1vZGUiCiAgICBGYWxscyBiYWNrIHRvIG5ldXRyYWwsIHRoZW4gdG8g"
    "Z290aGljIHBsYWNlaG9sZGVyIGlmIG5vIGltYWdlcyBmb3VuZC4KICAgIE1pc3NpbmcgZmFjZXMg"
    "ZGVmYXVsdCB0byBuZXV0cmFsIOKAlCBubyBjcmFzaCwgbm8gaGFyZGNvZGVkIGxpc3QgcmVxdWly"
    "ZWQuCiAgICAiIiIKCiAgICAjIFNwZWNpYWwgc3RlbSDihpIgZW1vdGlvbiBrZXkgbWFwcGluZ3Mg"
    "KGxvd2VyY2FzZSBzdGVtIGFmdGVyIE1vcmdhbm5hXykKICAgIF9TVEVNX1RPX0VNT1RJT046IGRp"
    "Y3Rbc3RyLCBzdHJdID0gewogICAgICAgICJzYWRfY3J5aW5nIjogICJzYWQiLAogICAgICAgICJj"
    "aGVhdF9tb2RlIjogICJjaGVhdG1vZGUiLAogICAgfQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBw"
    "YXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2Vs"
    "Zi5fZmFjZXNfZGlyICAgPSBjZmdfcGF0aCgiZmFjZXMiKQogICAgICAgIHNlbGYuX2NhY2hlOiBk"
    "aWN0W3N0ciwgUVBpeG1hcF0gPSB7fQogICAgICAgIHNlbGYuX2N1cnJlbnQgICAgID0gIm5ldXRy"
    "YWwiCiAgICAgICAgc2VsZi5fd2FybmVkOiBzZXRbc3RyXSA9IHNldCgpCgogICAgICAgIHNlbGYu"
    "c2V0TWluaW11bVNpemUoMTYwLCAxNjApCiAgICAgICAgc2VsZi5zZXRBbGlnbm1lbnQoUXQuQWxp"
    "Z25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNP"
    "Tl9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCgog"
    "ICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDMwMCwgc2VsZi5fcHJlbG9hZCkKCiAgICBkZWYgX3By"
    "ZWxvYWQoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBTY2FuIEZhY2VzLyBkaXJl"
    "Y3RvcnkgZm9yIGFsbCB7RkFDRV9QUkVGSVh9XyoucG5nIGZpbGVzLgogICAgICAgIEJ1aWxkIGVt"
    "b3Rpb27ihpJwaXhtYXAgY2FjaGUgZHluYW1pY2FsbHkuCiAgICAgICAgTm8gaGFyZGNvZGVkIGxp"
    "c3Qg4oCUIHdoYXRldmVyIGlzIGluIHRoZSBmb2xkZXIgaXMgYXZhaWxhYmxlLgogICAgICAgICIi"
    "IgogICAgICAgIGlmIG5vdCBzZWxmLl9mYWNlc19kaXIuZXhpc3RzKCk6CiAgICAgICAgICAgIHNl"
    "bGYuX2RyYXdfcGxhY2Vob2xkZXIoKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgZm9yIGlt"
    "Z19wYXRoIGluIHNlbGYuX2ZhY2VzX2Rpci5nbG9iKGYie0ZBQ0VfUFJFRklYfV8qLnBuZyIpOgog"
    "ICAgICAgICAgICAjIHN0ZW0gPSBldmVyeXRoaW5nIGFmdGVyICJNb3JnYW5uYV8iIHdpdGhvdXQg"
    "LnBuZwogICAgICAgICAgICByYXdfc3RlbSA9IGltZ19wYXRoLnN0ZW1bbGVuKGYie0ZBQ0VfUFJF"
    "RklYfV8iKTpdICAgICMgZS5nLiAiU2FkX0NyeWluZyIKICAgICAgICAgICAgc3RlbV9sb3dlciA9"
    "IHJhd19zdGVtLmxvd2VyKCkgICAgICAgICAgICAgICAgICAgICAgICAgICMgInNhZF9jcnlpbmci"
    "CgogICAgICAgICAgICAjIE1hcCBzcGVjaWFsIHN0ZW1zIHRvIGVtb3Rpb24ga2V5cwogICAgICAg"
    "ICAgICBlbW90aW9uID0gc2VsZi5fU1RFTV9UT19FTU9USU9OLmdldChzdGVtX2xvd2VyLCBzdGVt"
    "X2xvd2VyKQoKICAgICAgICAgICAgcHggPSBRUGl4bWFwKHN0cihpbWdfcGF0aCkpCiAgICAgICAg"
    "ICAgIGlmIG5vdCBweC5pc051bGwoKToKICAgICAgICAgICAgICAgIHNlbGYuX2NhY2hlW2Vtb3Rp"
    "b25dID0gcHgKCiAgICAgICAgaWYgc2VsZi5fY2FjaGU6CiAgICAgICAgICAgIHNlbGYuX3JlbmRl"
    "cigibmV1dHJhbCIpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fZHJhd19wbGFjZWhv"
    "bGRlcigpCgogICAgZGVmIF9yZW5kZXIoc2VsZiwgZmFjZTogc3RyKSAtPiBOb25lOgogICAgICAg"
    "IGZhY2UgPSBmYWNlLmxvd2VyKCkuc3RyaXAoKQogICAgICAgIGlmIGZhY2Ugbm90IGluIHNlbGYu"
    "X2NhY2hlOgogICAgICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl93YXJuZWQgYW5kIGZhY2Ug"
    "IT0gIm5ldXRyYWwiOgogICAgICAgICAgICAgICAgcHJpbnQoZiJbTUlSUk9SXVtXQVJOXSBGYWNl"
    "IG5vdCBpbiBjYWNoZToge2ZhY2V9IOKAlCB1c2luZyBuZXV0cmFsIikKICAgICAgICAgICAgICAg"
    "IHNlbGYuX3dhcm5lZC5hZGQoZmFjZSkKICAgICAgICAgICAgZmFjZSA9ICJuZXV0cmFsIgogICAg"
    "ICAgIGlmIGZhY2Ugbm90IGluIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBzZWxmLl9kcmF3X3Bs"
    "YWNlaG9sZGVyKCkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fY3VycmVudCA9IGZh"
    "Y2UKICAgICAgICBweCA9IHNlbGYuX2NhY2hlW2ZhY2VdCiAgICAgICAgc2NhbGVkID0gcHguc2Nh"
    "bGVkKAogICAgICAgICAgICBzZWxmLndpZHRoKCkgLSA0LAogICAgICAgICAgICBzZWxmLmhlaWdo"
    "dCgpIC0gNCwKICAgICAgICAgICAgUXQuQXNwZWN0UmF0aW9Nb2RlLktlZXBBc3BlY3RSYXRpbywK"
    "ICAgICAgICAgICAgUXQuVHJhbnNmb3JtYXRpb25Nb2RlLlNtb290aFRyYW5zZm9ybWF0aW9uLAog"
    "ICAgICAgICkKICAgICAgICBzZWxmLnNldFBpeG1hcChzY2FsZWQpCiAgICAgICAgc2VsZi5zZXRU"
    "ZXh0KCIiKQoKICAgIGRlZiBfZHJhd19wbGFjZWhvbGRlcihzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYuY2xlYXIoKQogICAgICAgIHNlbGYuc2V0VGV4dCgi4pymXG7inadcbuKcpiIpCiAgICAg"
    "ICAgc2VsZi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07"
    "IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImNvbG9y"
    "OiB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogMjRweDsgYm9yZGVyLXJhZGl1czogMnB4OyIK"
    "ICAgICAgICApCgogICAgZGVmIHNldF9mYWNlKHNlbGYsIGZhY2U6IHN0cikgLT4gTm9uZToKICAg"
    "ICAgICBRVGltZXIuc2luZ2xlU2hvdCgwLCBsYW1iZGE6IHNlbGYuX3JlbmRlcihmYWNlKSkKCiAg"
    "ICBkZWYgcmVzaXplRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgc3VwZXIoKS5y"
    "ZXNpemVFdmVudChldmVudCkKICAgICAgICBpZiBzZWxmLl9jYWNoZToKICAgICAgICAgICAgc2Vs"
    "Zi5fcmVuZGVyKHNlbGYuX2N1cnJlbnQpCgogICAgQHByb3BlcnR5CiAgICBkZWYgY3VycmVudF9m"
    "YWNlKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4gc2VsZi5fY3VycmVudAoKCiMg4pSA4pSA"
    "IFZBTVBJUkUgU1RBVEUgU1RSSVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACmNsYXNzIFZhbXBpcmVTdGF0ZVN0cmlwKFFXaWRnZXQpOgogICAgIiIi"
    "CiAgICBGdWxsLXdpZHRoIHN0YXR1cyBiYXIgc2hvd2luZzoKICAgICAgWyDinKYgVkFNUElSRV9T"
    "VEFURSAg4oCiICBISDpNTSAg4oCiICDimIAgU1VOUklTRSAg4pi9IFNVTlNFVCAg4oCiICBNT09O"
    "IFBIQVNFICBJTExVTSUgXQogICAgQWx3YXlzIHZpc2libGUsIG5ldmVyIGNvbGxhcHNlcy4KICAg"
    "IFVwZGF0ZXMgZXZlcnkgbWludXRlIHZpYSBleHRlcm5hbCBRVGltZXIgY2FsbCB0byByZWZyZXNo"
    "KCkuCiAgICBDb2xvci1jb2RlZCBieSBjdXJyZW50IHZhbXBpcmUgc3RhdGUuCiAgICAiIiIKCiAg"
    "ICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0"
    "X18ocGFyZW50KQogICAgICAgIHNlbGYuX3N0YXRlICAgICA9IGdldF92YW1waXJlX3N0YXRlKCkK"
    "ICAgICAgICBzZWxmLl90aW1lX3N0ciAgPSAiIgogICAgICAgIHNlbGYuX3N1bnJpc2UgICA9ICIw"
    "NjowMCIKICAgICAgICBzZWxmLl9zdW5zZXQgICAgPSAiMTg6MzAiCiAgICAgICAgc2VsZi5fbW9v"
    "bl9uYW1lID0gIk5FVyBNT09OIgogICAgICAgIHNlbGYuX2lsbHVtICAgICA9IDAuMAogICAgICAg"
    "IHNlbGYuc2V0Rml4ZWRIZWlnaHQoMjgpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KGYiYmFj"
    "a2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyLXRvcDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsi"
    "KQogICAgICAgIHNlbGYuX2ZldGNoX3N1bl9hc3luYygpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkK"
    "CiAgICBkZWYgX2ZldGNoX3N1bl9hc3luYyhzZWxmKSAtPiBOb25lOgogICAgICAgIGRlZiBfZigp"
    "OgogICAgICAgICAgICBzciwgc3MgPSBnZXRfc3VuX3RpbWVzKCkKICAgICAgICAgICAgc2VsZi5f"
    "c3VucmlzZSA9IHNyCiAgICAgICAgICAgIHNlbGYuX3N1bnNldCAgPSBzcwogICAgICAgICAgICAj"
    "IFNjaGVkdWxlIHJlcGFpbnQgb24gbWFpbiB0aHJlYWQg4oCUIG5ldmVyIGNhbGwgdXBkYXRlKCkg"
    "ZnJvbQogICAgICAgICAgICAjIGEgYmFja2dyb3VuZCB0aHJlYWQsIGl0IGNhdXNlcyBRVGhyZWFk"
    "IGNyYXNoIG9uIHN0YXJ0dXAKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMCwgc2VsZi51"
    "cGRhdGUpCiAgICAgICAgdGhyZWFkaW5nLlRocmVhZCh0YXJnZXQ9X2YsIGRhZW1vbj1UcnVlKS5z"
    "dGFydCgpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zdGF0"
    "ZSAgICAgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAgICAgc2VsZi5fdGltZV9zdHIgID0gZGF0"
    "ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNIikKICAgICAgICBfLCBzZWxmLl9tb29uX25hbWUs"
    "IHNlbGYuX2lsbHVtID0gZ2V0X21vb25fcGhhc2UoKQogICAgICAgIHNlbGYudXBkYXRlKCkKCiAg"
    "ICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBwID0gUVBhaW50"
    "ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGludC5BbnRp"
    "YWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwgc2VsZi5oZWlnaHQoKQoKICAg"
    "ICAgICBwLmZpbGxSZWN0KDAsIDAsIHcsIGgsIFFDb2xvcihDX0JHMikpCgogICAgICAgIHN0YXRl"
    "X2NvbG9yID0gZ2V0X3ZhbXBpcmVfc3RhdGVfY29sb3Ioc2VsZi5fc3RhdGUpCiAgICAgICAgdGV4"
    "dCA9ICgKICAgICAgICAgICAgZiLinKYgIHtzZWxmLl9zdGF0ZX0gIOKAoiAge3NlbGYuX3RpbWVf"
    "c3RyfSAg4oCiICAiCiAgICAgICAgICAgIGYi4piAIHtzZWxmLl9zdW5yaXNlfSAgICDimL0ge3Nl"
    "bGYuX3N1bnNldH0gIOKAoiAgIgogICAgICAgICAgICBmIntzZWxmLl9tb29uX25hbWV9ICB7c2Vs"
    "Zi5faWxsdW06LjBmfSUiCiAgICAgICAgKQoKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19G"
    "T05ULCA5LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKHN0YXRl"
    "X2NvbG9yKSkKICAgICAgICBmbSA9IHAuZm9udE1ldHJpY3MoKQogICAgICAgIHR3ID0gZm0uaG9y"
    "aXpvbnRhbEFkdmFuY2UodGV4dCkKICAgICAgICBwLmRyYXdUZXh0KCh3IC0gdHcpIC8vIDIsIGgg"
    "LSA3LCB0ZXh0KQoKICAgICAgICBwLmVuZCgpCgoKY2xhc3MgTWluaUNhbGVuZGFyV2lkZ2V0KFFX"
    "aWRnZXQpOgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBl"
    "cigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChzZWxmKQog"
    "ICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBsYXlv"
    "dXQuc2V0U3BhY2luZyg0KQoKICAgICAgICBoZWFkZXIgPSBRSEJveExheW91dCgpCiAgICAgICAg"
    "aGVhZGVyLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlbGYucHJldl9i"
    "dG4gPSBRUHVzaEJ1dHRvbigiPDwiKQogICAgICAgIHNlbGYubmV4dF9idG4gPSBRUHVzaEJ1dHRv"
    "bigiPj4iKQogICAgICAgIHNlbGYubW9udGhfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYu"
    "bW9udGhfbGJsLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAg"
    "ICAgIGZvciBidG4gaW4gKHNlbGYucHJldl9idG4sIHNlbGYubmV4dF9idG4pOgogICAgICAgICAg"
    "ICBidG4uc2V0Rml4ZWRXaWR0aCgzNCkKICAgICAgICAgICAgYnRuLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgYm9y"
    "ZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImZvbnQt"
    "c2l6ZTogMTBweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDJweDsiCiAgICAgICAgICAg"
    "ICkKICAgICAgICBzZWxmLm1vbnRoX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNv"
    "bG9yOiB7Q19HT0xEfTsgYm9yZGVyOiBub25lOyBmb250LXNpemU6IDEwcHg7IGZvbnQtd2VpZ2h0"
    "OiBib2xkOyIKICAgICAgICApCiAgICAgICAgaGVhZGVyLmFkZFdpZGdldChzZWxmLnByZXZfYnRu"
    "KQogICAgICAgIGhlYWRlci5hZGRXaWRnZXQoc2VsZi5tb250aF9sYmwsIDEpCiAgICAgICAgaGVh"
    "ZGVyLmFkZFdpZGdldChzZWxmLm5leHRfYnRuKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoaGVh"
    "ZGVyKQoKICAgICAgICBzZWxmLmNhbGVuZGFyID0gUUNhbGVuZGFyV2lkZ2V0KCkKICAgICAgICBz"
    "ZWxmLmNhbGVuZGFyLnNldEdyaWRWaXNpYmxlKFRydWUpCiAgICAgICAgc2VsZi5jYWxlbmRhci5z"
    "ZXRWZXJ0aWNhbEhlYWRlckZvcm1hdChRQ2FsZW5kYXJXaWRnZXQuVmVydGljYWxIZWFkZXJGb3Jt"
    "YXQuTm9WZXJ0aWNhbEhlYWRlcikKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldE5hdmlnYXRpb25C"
    "YXJWaXNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgZiJRQ2FsZW5kYXJXaWRnZXQgUVdpZGdldHt7YWx0ZXJuYXRlLWJhY2tncm91bmQt"
    "Y29sb3I6e0NfQkcyfTt9fSAiCiAgICAgICAgICAgIGYiUVRvb2xCdXR0b257e2NvbG9yOntDX0dP"
    "TER9O319ICIKICAgICAgICAgICAgZiJRQ2FsZW5kYXJXaWRnZXQgUUFic3RyYWN0SXRlbVZpZXc6"
    "ZW5hYmxlZHt7YmFja2dyb3VuZDp7Q19CRzJ9OyBjb2xvcjojZmZmZmZmOyAiCiAgICAgICAgICAg"
    "IGYic2VsZWN0aW9uLWJhY2tncm91bmQtY29sb3I6e0NfQ1JJTVNPTl9ESU19OyBzZWxlY3Rpb24t"
    "Y29sb3I6e0NfVEVYVH07IGdyaWRsaW5lLWNvbG9yOntDX0JPUkRFUn07fX0gIgogICAgICAgICAg"
    "ICBmIlFDYWxlbmRhcldpZGdldCBRQWJzdHJhY3RJdGVtVmlldzpkaXNhYmxlZHt7Y29sb3I6Izhi"
    "OTVhMTt9fSIKICAgICAgICApCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmNhbGVuZGFy"
    "KQoKICAgICAgICBzZWxmLnByZXZfYnRuLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuY2Fs"
    "ZW5kYXIuc2hvd1ByZXZpb3VzTW9udGgoKSkKICAgICAgICBzZWxmLm5leHRfYnRuLmNsaWNrZWQu"
    "Y29ubmVjdChsYW1iZGE6IHNlbGYuY2FsZW5kYXIuc2hvd05leHRNb250aCgpKQogICAgICAgIHNl"
    "bGYuY2FsZW5kYXIuY3VycmVudFBhZ2VDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fdXBkYXRlX2xhYmVs"
    "KQogICAgICAgIHNlbGYuX3VwZGF0ZV9sYWJlbCgpCiAgICAgICAgc2VsZi5fYXBwbHlfZm9ybWF0"
    "cygpCgogICAgZGVmIF91cGRhdGVfbGFiZWwoc2VsZiwgKmFyZ3MpOgogICAgICAgIHllYXIgPSBz"
    "ZWxmLmNhbGVuZGFyLnllYXJTaG93bigpCiAgICAgICAgbW9udGggPSBzZWxmLmNhbGVuZGFyLm1v"
    "bnRoU2hvd24oKQogICAgICAgIHNlbGYubW9udGhfbGJsLnNldFRleHQoZiJ7ZGF0ZSh5ZWFyLCBt"
    "b250aCwgMSkuc3RyZnRpbWUoJyVCICVZJyl9IikKICAgICAgICBzZWxmLl9hcHBseV9mb3JtYXRz"
    "KCkKCiAgICBkZWYgX2FwcGx5X2Zvcm1hdHMoc2VsZik6CiAgICAgICAgYmFzZSA9IFFUZXh0Q2hh"
    "ckZvcm1hdCgpCiAgICAgICAgYmFzZS5zZXRGb3JlZ3JvdW5kKFFDb2xvcigiI2U3ZWRmMyIpKQog"
    "ICAgICAgIHNhdHVyZGF5ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICBzYXR1cmRheS5zZXRG"
    "b3JlZ3JvdW5kKFFDb2xvcihDX0dPTERfRElNKSkKICAgICAgICBzdW5kYXkgPSBRVGV4dENoYXJG"
    "b3JtYXQoKQogICAgICAgIHN1bmRheS5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0JMT09EKSkKICAg"
    "ICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5Nb25k"
    "YXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5E"
    "YXlPZldlZWsuVHVlc2RheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlU"
    "ZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5XZWRuZXNkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxl"
    "bmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuVGh1cnNkYXksIGJhc2UpCiAg"
    "ICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuRnJp"
    "ZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQu"
    "RGF5T2ZXZWVrLlNhdHVyZGF5LCBzYXR1cmRheSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdl"
    "ZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5TdW5kYXksIHN1bmRheSkKCiAgICAgICAgeWVh"
    "ciA9IHNlbGYuY2FsZW5kYXIueWVhclNob3duKCkKICAgICAgICBtb250aCA9IHNlbGYuY2FsZW5k"
    "YXIubW9udGhTaG93bigpCiAgICAgICAgZmlyc3RfZGF5ID0gUURhdGUoeWVhciwgbW9udGgsIDEp"
    "CiAgICAgICAgZm9yIGRheSBpbiByYW5nZSgxLCBmaXJzdF9kYXkuZGF5c0luTW9udGgoKSArIDEp"
    "OgogICAgICAgICAgICBkID0gUURhdGUoeWVhciwgbW9udGgsIGRheSkKICAgICAgICAgICAgZm10"
    "ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICAgICAgd2Vla2RheSA9IGQuZGF5T2ZXZWVrKCkK"
    "ICAgICAgICAgICAgaWYgd2Vla2RheSA9PSBRdC5EYXlPZldlZWsuU2F0dXJkYXkudmFsdWU6CiAg"
    "ICAgICAgICAgICAgICBmbXQuc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAg"
    "ICAgICAgIGVsaWYgd2Vla2RheSA9PSBRdC5EYXlPZldlZWsuU3VuZGF5LnZhbHVlOgogICAgICAg"
    "ICAgICAgICAgZm10LnNldEZvcmVncm91bmQoUUNvbG9yKENfQkxPT0QpKQogICAgICAgICAgICBl"
    "bHNlOgogICAgICAgICAgICAgICAgZm10LnNldEZvcmVncm91bmQoUUNvbG9yKCIjZTdlZGYzIikp"
    "CiAgICAgICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0RGF0ZVRleHRGb3JtYXQoZCwgZm10KQoKICAg"
    "ICAgICB0b2RheV9mbXQgPSBRVGV4dENoYXJGb3JtYXQoKQogICAgICAgIHRvZGF5X2ZtdC5zZXRG"
    "b3JlZ3JvdW5kKFFDb2xvcigiIzY4ZDM5YSIpKQogICAgICAgIHRvZGF5X2ZtdC5zZXRCYWNrZ3Jv"
    "dW5kKFFDb2xvcigiIzE2MzgyNSIpKQogICAgICAgIHRvZGF5X2ZtdC5zZXRGb250V2VpZ2h0KFFG"
    "b250LldlaWdodC5Cb2xkKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0RGF0ZVRleHRGb3JtYXQo"
    "UURhdGUuY3VycmVudERhdGUoKSwgdG9kYXlfZm10KQoKCiMg4pSA4pSAIENPTExBUFNJQkxFIEJM"
    "T0NLIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgApjbGFzcyBDb2xsYXBzaWJsZUJsb2NrKFFXaWRnZXQpOgogICAgIiIiCiAgICBXcmFwcGVy"
    "IHRoYXQgYWRkcyBhIGNvbGxhcHNlL2V4cGFuZCB0b2dnbGUgdG8gYW55IHdpZGdldC4KICAgIENv"
    "bGxhcHNlcyBob3Jpem9udGFsbHkgKHJpZ2h0d2FyZCkg4oCUIGhpZGVzIGNvbnRlbnQsIGtlZXBz"
    "IGhlYWRlciBzdHJpcC4KICAgIEhlYWRlciBzaG93cyBsYWJlbC4gVG9nZ2xlIGJ1dHRvbiBvbiBy"
    "aWdodCBlZGdlIG9mIGhlYWRlci4KCiAgICBVc2FnZToKICAgICAgICBibG9jayA9IENvbGxhcHNp"
    "YmxlQmxvY2soIuKdpyBCTE9PRCIsIFNwaGVyZVdpZGdldCguLi4pKQogICAgICAgIGxheW91dC5h"
    "ZGRXaWRnZXQoYmxvY2spCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbGFiZWw6IHN0"
    "ciwgY29udGVudDogUVdpZGdldCwKICAgICAgICAgICAgICAgICBleHBhbmRlZDogYm9vbCA9IFRy"
    "dWUsIG1pbl93aWR0aDogaW50ID0gOTAsCiAgICAgICAgICAgICAgICAgcGFyZW50PU5vbmUpOgog"
    "ICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2V4cGFuZGVkICA9"
    "IGV4cGFuZGVkCiAgICAgICAgc2VsZi5fbWluX3dpZHRoID0gbWluX3dpZHRoCiAgICAgICAgc2Vs"
    "Zi5fY29udGVudCAgID0gY29udGVudAoKICAgICAgICBtYWluID0gUVZCb3hMYXlvdXQoc2VsZikK"
    "ICAgICAgICBtYWluLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG1haW4u"
    "c2V0U3BhY2luZygwKQoKICAgICAgICAjIEhlYWRlcgogICAgICAgIHNlbGYuX2hlYWRlciA9IFFX"
    "aWRnZXQoKQogICAgICAgIHNlbGYuX2hlYWRlci5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBz"
    "ZWxmLl9oZWFkZXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19C"
    "RzN9OyBib3JkZXItYm90dG9tOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAg"
    "ICAgIGYiYm9yZGVyLXRvcDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQog"
    "ICAgICAgIGhsID0gUUhCb3hMYXlvdXQoc2VsZi5faGVhZGVyKQogICAgICAgIGhsLnNldENvbnRl"
    "bnRzTWFyZ2lucyg2LCAwLCA0LCAwKQogICAgICAgIGhsLnNldFNwYWNpbmcoNCkKCiAgICAgICAg"
    "c2VsZi5fbGJsID0gUUxhYmVsKGxhYmVsKQogICAgICAgIHNlbGYuX2xibC5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2Vp"
    "Z2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJp"
    "ZjsgbGV0dGVyLXNwYWNpbmc6IDFweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCgogICAgICAg"
    "IHNlbGYuX2J0biA9IFFUb29sQnV0dG9uKCkKICAgICAgICBzZWxmLl9idG4uc2V0Rml4ZWRTaXpl"
    "KDE2LCAxNikKICAgICAgICBzZWxmLl9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJi"
    "YWNrZ3JvdW5kOiB0cmFuc3BhcmVudDsgY29sb3I6IHtDX0dPTERfRElNfTsgYm9yZGVyOiBub25l"
    "OyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl9idG4uc2V0VGV4dCgi"
    "PCIpCiAgICAgICAgc2VsZi5fYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCgogICAg"
    "ICAgIGhsLmFkZFdpZGdldChzZWxmLl9sYmwpCiAgICAgICAgaGwuYWRkU3RyZXRjaCgpCiAgICAg"
    "ICAgaGwuYWRkV2lkZ2V0KHNlbGYuX2J0bikKCiAgICAgICAgbWFpbi5hZGRXaWRnZXQoc2VsZi5f"
    "aGVhZGVyKQogICAgICAgIG1haW4uYWRkV2lkZ2V0KHNlbGYuX2NvbnRlbnQpCgogICAgICAgIHNl"
    "bGYuX2FwcGx5X3N0YXRlKCkKCiAgICBkZWYgX3RvZ2dsZShzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAgICAgICAgc2VsZi5fYXBwbHlf"
    "c3RhdGUoKQoKICAgIGRlZiBfYXBwbHlfc3RhdGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9jb250ZW50LnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCiAgICAgICAgc2VsZi5fYnRuLnNl"
    "dFRleHQoIjwiIGlmIHNlbGYuX2V4cGFuZGVkIGVsc2UgIj4iKQogICAgICAgIGlmIHNlbGYuX2V4"
    "cGFuZGVkOgogICAgICAgICAgICBzZWxmLnNldE1pbmltdW1XaWR0aChzZWxmLl9taW5fd2lkdGgp"
    "CiAgICAgICAgICAgIHNlbGYuc2V0TWF4aW11bVdpZHRoKDE2Nzc3MjE1KSAgIyB1bmNvbnN0cmFp"
    "bmVkCiAgICAgICAgZWxzZToKICAgICAgICAgICAgIyBDb2xsYXBzZWQ6IGp1c3QgdGhlIGhlYWRl"
    "ciBzdHJpcCAobGFiZWwgKyBidXR0b24pCiAgICAgICAgICAgIGNvbGxhcHNlZF93ID0gc2VsZi5f"
    "aGVhZGVyLnNpemVIaW50KCkud2lkdGgoKQogICAgICAgICAgICBzZWxmLnNldEZpeGVkV2lkdGgo"
    "bWF4KDYwLCBjb2xsYXBzZWRfdykpCiAgICAgICAgc2VsZi51cGRhdGVHZW9tZXRyeSgpCiAgICAg"
    "ICAgcGFyZW50ID0gc2VsZi5wYXJlbnRXaWRnZXQoKQogICAgICAgIGlmIHBhcmVudCBhbmQgcGFy"
    "ZW50LmxheW91dCgpOgogICAgICAgICAgICBwYXJlbnQubGF5b3V0KCkuYWN0aXZhdGUoKQoKCiMg"
    "4pSA4pSAIEhBUkRXQVJFIFBBTkVMIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBIYXJkd2FyZVBhbmVsKFFXaWRn"
    "ZXQpOgogICAgIiIiCiAgICBUaGUgc3lzdGVtcyByaWdodCBwYW5lbCBjb250ZW50cy4KICAgIEdy"
    "b3Vwczogc3RhdHVzIGluZm8sIGRyaXZlIGJhcnMsIENQVS9SQU0gZ2F1Z2VzLCBHUFUvVlJBTSBn"
    "YXVnZXMsIEdQVSB0ZW1wLgogICAgUmVwb3J0cyBoYXJkd2FyZSBhdmFpbGFiaWxpdHkgaW4gRGlh"
    "Z25vc3RpY3Mgb24gc3RhcnR1cC4KICAgIFNob3dzIE4vQSBncmFjZWZ1bGx5IHdoZW4gZGF0YSB1"
    "bmF2YWlsYWJsZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6"
    "CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fc2V0dXBfdWko"
    "KQogICAgICAgIHNlbGYuX2RldGVjdF9oYXJkd2FyZSgpCgogICAgZGVmIF9zZXR1cF91aShzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5"
    "b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIGxheW91dC5zZXRTcGFj"
    "aW5nKDQpCgogICAgICAgIGRlZiBzZWN0aW9uX2xhYmVsKHRleHQ6IHN0cikgLT4gUUxhYmVsOgog"
    "ICAgICAgICAgICBsYmwgPSBRTGFiZWwodGV4dCkKICAgICAgICAgICAgbGJsLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGxl"
    "dHRlci1zcGFjaW5nOiAycHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNL"
    "X0ZPTlR9LCBzZXJpZjsgZm9udC13ZWlnaHQ6IGJvbGQ7IgogICAgICAgICAgICApCiAgICAgICAg"
    "ICAgIHJldHVybiBsYmwKCiAgICAgICAgIyDilIDilIAgU3RhdHVzIGJsb2NrIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2n"
    "IFNUQVRVUyIpKQogICAgICAgIHN0YXR1c19mcmFtZSA9IFFGcmFtZSgpCiAgICAgICAgc3RhdHVz"
    "X2ZyYW1lLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfUEFORUx9"
    "OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7IgogICAg"
    "ICAgICkKICAgICAgICBzdGF0dXNfZnJhbWUuc2V0Rml4ZWRIZWlnaHQoODgpCiAgICAgICAgc2Yg"
    "PSBRVkJveExheW91dChzdGF0dXNfZnJhbWUpCiAgICAgICAgc2Yuc2V0Q29udGVudHNNYXJnaW5z"
    "KDgsIDQsIDgsIDQpCiAgICAgICAgc2Yuc2V0U3BhY2luZygyKQoKICAgICAgICBzZWxmLmxibF9z"
    "dGF0dXMgID0gUUxhYmVsKCLinKYgU1RBVFVTOiBPRkZMSU5FIikKICAgICAgICBzZWxmLmxibF9t"
    "b2RlbCAgID0gUUxhYmVsKCLinKYgVkVTU0VMOiBMT0FESU5HLi4uIikKICAgICAgICBzZWxmLmxi"
    "bF9zZXNzaW9uID0gUUxhYmVsKCLinKYgU0VTU0lPTjogMDA6MDA6MDAiKQogICAgICAgIHNlbGYu"
    "bGJsX3Rva2VucyAgPSBRTGFiZWwoIuKcpiBUT0tFTlM6IDAiKQoKICAgICAgICBmb3IgbGJsIGlu"
    "IChzZWxmLmxibF9zdGF0dXMsIHNlbGYubGJsX21vZGVsLAogICAgICAgICAgICAgICAgICAgIHNl"
    "bGYubGJsX3Nlc3Npb24sIHNlbGYubGJsX3Rva2Vucyk6CiAgICAgICAgICAgIGxibC5zZXRTdHls"
    "ZVNoZWV0KAogICAgICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6"
    "IDEwcHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJp"
    "ZjsgYm9yZGVyOiBub25lOyIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZi5hZGRXaWRnZXQo"
    "bGJsKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHN0YXR1c19mcmFtZSkKCiAgICAgICAgIyDi"
    "lIDilIAgRHJpdmUgYmFycyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBs"
    "YXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKdpyBTVE9SQUdFIikpCiAgICAgICAgc2Vs"
    "Zi5kcml2ZV93aWRnZXQgPSBEcml2ZVdpZGdldCgpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChz"
    "ZWxmLmRyaXZlX3dpZGdldCkKCiAgICAgICAgIyDilIDilIAgQ1BVIC8gUkFNIGdhdWdlcyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKdpyBWSVRB"
    "TCBFU1NFTkNFIikpCiAgICAgICAgcmFtX2NwdSA9IFFHcmlkTGF5b3V0KCkKICAgICAgICByYW1f"
    "Y3B1LnNldFNwYWNpbmcoMykKCiAgICAgICAgc2VsZi5nYXVnZV9jcHUgID0gR2F1Z2VXaWRnZXQo"
    "IkNQVSIsICAiJSIsICAgMTAwLjAsIENfU0lMVkVSKQogICAgICAgIHNlbGYuZ2F1Z2VfcmFtICA9"
    "IEdhdWdlV2lkZ2V0KCJSQU0iLCAgIkdCIiwgICA2NC4wLCBDX0dPTERfRElNKQogICAgICAgIHJh"
    "bV9jcHUuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfY3B1LCAwLCAwKQogICAgICAgIHJhbV9jcHUuYWRk"
    "V2lkZ2V0KHNlbGYuZ2F1Z2VfcmFtLCAwLCAxKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQocmFt"
    "X2NwdSkKCiAgICAgICAgIyDilIDilIAgR1BVIC8gVlJBTSBnYXVnZXMg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgQVJDQU5FIFBPV0VSIikpCiAg"
    "ICAgICAgZ3B1X3ZyYW0gPSBRR3JpZExheW91dCgpCiAgICAgICAgZ3B1X3ZyYW0uc2V0U3BhY2lu"
    "ZygzKQoKICAgICAgICBzZWxmLmdhdWdlX2dwdSAgPSBHYXVnZVdpZGdldCgiR1BVIiwgICIlIiwg"
    "ICAxMDAuMCwgQ19QVVJQTEUpCiAgICAgICAgc2VsZi5nYXVnZV92cmFtID0gR2F1Z2VXaWRnZXQo"
    "IlZSQU0iLCAiR0IiLCAgICA4LjAsIENfQ1JJTVNPTikKICAgICAgICBncHVfdnJhbS5hZGRXaWRn"
    "ZXQoc2VsZi5nYXVnZV9ncHUsICAwLCAwKQogICAgICAgIGdwdV92cmFtLmFkZFdpZGdldChzZWxm"
    "LmdhdWdlX3ZyYW0sIDAsIDEpCiAgICAgICAgbGF5b3V0LmFkZExheW91dChncHVfdnJhbSkKCiAg"
    "ICAgICAgIyDilIDilIAgR1BVIFRlbXAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgSU5GRVJOQUwg"
    "SEVBVCIpKQogICAgICAgIHNlbGYuZ2F1Z2VfdGVtcCA9IEdhdWdlV2lkZ2V0KCJHUFUgVEVNUCIs"
    "ICLCsEMiLCA5NS4wLCBDX0JMT09EKQogICAgICAgIHNlbGYuZ2F1Z2VfdGVtcC5zZXRNYXhpbXVt"
    "SGVpZ2h0KDY1KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5nYXVnZV90ZW1wKQoKICAg"
    "ICAgICAjIOKUgOKUgCBHUFUgbWFzdGVyIGJhciAoZnVsbCB3aWR0aCkg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xh"
    "YmVsKCLinacgSU5GRVJOQUwgRU5HSU5FIikpCiAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVy"
    "ID0gR2F1Z2VXaWRnZXQoIlJUWCIsICIlIiwgMTAwLjAsIENfQ1JJTVNPTikKICAgICAgICBzZWxm"
    "LmdhdWdlX2dwdV9tYXN0ZXIuc2V0TWF4aW11bUhlaWdodCg1NSkKICAgICAgICBsYXlvdXQuYWRk"
    "V2lkZ2V0KHNlbGYuZ2F1Z2VfZ3B1X21hc3RlcikKCiAgICAgICAgbGF5b3V0LmFkZFN0cmV0Y2go"
    "KQoKICAgIGRlZiBfZGV0ZWN0X2hhcmR3YXJlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAg"
    "ICAgICAgQ2hlY2sgd2hhdCBoYXJkd2FyZSBtb25pdG9yaW5nIGlzIGF2YWlsYWJsZS4KICAgICAg"
    "ICBNYXJrIHVuYXZhaWxhYmxlIGdhdWdlcyBhcHByb3ByaWF0ZWx5LgogICAgICAgIERpYWdub3N0"
    "aWMgbWVzc2FnZXMgY29sbGVjdGVkIGZvciB0aGUgRGlhZ25vc3RpY3MgdGFiLgogICAgICAgICIi"
    "IgogICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXM6IGxpc3Rbc3RyXSA9IFtdCgogICAgICAgIGlm"
    "IG5vdCBQU1VUSUxfT0s6CiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfY3B1LnNldFVuYXZhaWxhYmxl"
    "KCkKICAgICAgICAgICAgc2VsZi5nYXVnZV9yYW0uc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICJbSEFSRFdBUkVd"
    "IHBzdXRpbCBub3QgYXZhaWxhYmxlIOKAlCBDUFUvUkFNIGdhdWdlcyBkaXNhYmxlZC4gIgogICAg"
    "ICAgICAgICAgICAgInBpcCBpbnN0YWxsIHBzdXRpbCB0byBlbmFibGUuIgogICAgICAgICAgICAp"
    "CiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoIltI"
    "QVJEV0FSRV0gcHN1dGlsIE9LIOKAlCBDUFUvUkFNIG1vbml0b3JpbmcgYWN0aXZlLiIpCgogICAg"
    "ICAgIGlmIG5vdCBOVk1MX09LOgogICAgICAgICAgICBzZWxmLmdhdWdlX2dwdS5zZXRVbmF2YWls"
    "YWJsZSgpCiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfdnJhbS5zZXRVbmF2YWlsYWJsZSgpCiAgICAg"
    "ICAgICAgIHNlbGYuZ2F1Z2VfdGVtcC5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYu"
    "Z2F1Z2VfZ3B1X21hc3Rlci5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuX2RpYWdf"
    "bWVzc2FnZXMuYXBwZW5kKAogICAgICAgICAgICAgICAgIltIQVJEV0FSRV0gcHludm1sIG5vdCBh"
    "dmFpbGFibGUgb3Igbm8gTlZJRElBIEdQVSBkZXRlY3RlZCDigJQgIgogICAgICAgICAgICAgICAg"
    "IkdQVSBnYXVnZXMgZGlzYWJsZWQuIHBpcCBpbnN0YWxsIHB5bnZtbCB0byBlbmFibGUuIgogICAg"
    "ICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAg"
    "bmFtZSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TmFtZShncHVfaGFuZGxlKQogICAgICAgICAgICAg"
    "ICAgaWYgaXNpbnN0YW5jZShuYW1lLCBieXRlcyk6CiAgICAgICAgICAgICAgICAgICAgbmFtZSA9"
    "IG5hbWUuZGVjb2RlKCkKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5k"
    "KAogICAgICAgICAgICAgICAgICAgIGYiW0hBUkRXQVJFXSBweW52bWwgT0sg4oCUIEdQVSBkZXRl"
    "Y3RlZDoge25hbWV9IgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgIyBVcGRhdGUg"
    "bWF4IFZSQU0gZnJvbSBhY3R1YWwgaGFyZHdhcmUKICAgICAgICAgICAgICAgIG1lbSA9IHB5bnZt"
    "bC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgdG90"
    "YWxfZ2IgPSBtZW0udG90YWwgLyAxMDI0KiozCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3Zy"
    "YW0ubWF4X3ZhbCA9IHRvdGFsX2diCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKGYiW0hBUkRXQVJFXSBw"
    "eW52bWwgZXJyb3I6IHtlfSIpCgogICAgZGVmIHVwZGF0ZV9zdGF0cyhzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgICIiIgogICAgICAgIENhbGxlZCBldmVyeSBzZWNvbmQgZnJvbSB0aGUgc3RhdHMgUVRp"
    "bWVyLgogICAgICAgIFJlYWRzIGhhcmR3YXJlIGFuZCB1cGRhdGVzIGFsbCBnYXVnZXMuCiAgICAg"
    "ICAgIiIiCiAgICAgICAgaWYgUFNVVElMX09LOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAg"
    "ICAgICBjcHUgPSBwc3V0aWwuY3B1X3BlcmNlbnQoKQogICAgICAgICAgICAgICAgc2VsZi5nYXVn"
    "ZV9jcHUuc2V0VmFsdWUoY3B1LCBmIntjcHU6LjBmfSUiLCBhdmFpbGFibGU9VHJ1ZSkKCiAgICAg"
    "ICAgICAgICAgICBtZW0gPSBwc3V0aWwudmlydHVhbF9tZW1vcnkoKQogICAgICAgICAgICAgICAg"
    "cnUgID0gbWVtLnVzZWQgIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgcnQgID0gbWVtLnRvdGFs"
    "IC8gMTAyNCoqMwogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9yYW0uc2V0VmFsdWUocnUsIGYi"
    "e3J1Oi4xZn0ve3J0Oi4wZn1HQiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICBhdmFpbGFibGU9VHJ1ZSkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLm1heF92"
    "YWwgPSBydAogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFz"
    "cwoKICAgICAgICBpZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgICAgICB1dGlsICAgICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0VXRpbGl6YXRpb25S"
    "YXRlcyhncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgbWVtX2luZm8gPSBweW52bWwubnZtbERl"
    "dmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIHRlbXAgICAgID0g"
    "cHludm1sLm52bWxEZXZpY2VHZXRUZW1wZXJhdHVyZSgKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGdwdV9oYW5kbGUsIHB5bnZtbC5OVk1MX1RFTVBFUkFUVVJFX0dQVSkKCiAgICAgICAg"
    "ICAgICAgICBncHVfcGN0ICAgPSBmbG9hdCh1dGlsLmdwdSkKICAgICAgICAgICAgICAgIHZyYW1f"
    "dXNlZCA9IG1lbV9pbmZvLnVzZWQgIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgdnJhbV90b3Qg"
    "ID0gbWVtX2luZm8udG90YWwgLyAxMDI0KiozCgogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9n"
    "cHUuc2V0VmFsdWUoZ3B1X3BjdCwgZiJ7Z3B1X3BjdDouMGZ9JSIsCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICBhdmFpbGFibGU9VHJ1ZSkKICAgICAgICAgICAgICAgIHNl"
    "bGYuZ2F1Z2VfdnJhbS5zZXRWYWx1ZSh2cmFtX3VzZWQsCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgZiJ7dnJhbV91c2VkOi4xZn0ve3ZyYW1fdG90Oi4wZn1HQiIsCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAg"
    "ICAgICAgICAgICAgICBzZWxmLmdhdWdlX3RlbXAuc2V0VmFsdWUoZmxvYXQodGVtcCksIGYie3Rl"
    "bXB9wrBDIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBhdmFpbGFi"
    "bGU9VHJ1ZSkKCiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgbmFtZSA9"
    "IHB5bnZtbC5udm1sRGV2aWNlR2V0TmFtZShncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgICAg"
    "IGlmIGlzaW5zdGFuY2UobmFtZSwgYnl0ZXMpOgogICAgICAgICAgICAgICAgICAgICAgICBuYW1l"
    "ID0gbmFtZS5kZWNvZGUoKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAg"
    "ICAgICAgICAgICAgICBuYW1lID0gIkdQVSIKCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX2dw"
    "dV9tYXN0ZXIuc2V0VmFsdWUoCiAgICAgICAgICAgICAgICAgICAgZ3B1X3BjdCwKICAgICAgICAg"
    "ICAgICAgICAgICBmIntuYW1lfSAge2dwdV9wY3Q6LjBmfSUgICIKICAgICAgICAgICAgICAgICAg"
    "ICBmIlt7dnJhbV91c2VkOi4xZn0ve3ZyYW1fdG90Oi4wZn1HQiBWUkFNXSIsCiAgICAgICAgICAg"
    "ICAgICAgICAgYXZhaWxhYmxlPVRydWUsCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgVXBkYXRlIGRy"
    "aXZlIGJhcnMgZXZlcnkgMzAgc2Vjb25kcyAobm90IGV2ZXJ5IHRpY2spCiAgICAgICAgaWYgbm90"
    "IGhhc2F0dHIoc2VsZiwgIl9kcml2ZV90aWNrIik6CiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3Rp"
    "Y2sgPSAwCiAgICAgICAgc2VsZi5fZHJpdmVfdGljayArPSAxCiAgICAgICAgaWYgc2VsZi5fZHJp"
    "dmVfdGljayA+PSAzMDoKICAgICAgICAgICAgc2VsZi5fZHJpdmVfdGljayA9IDAKICAgICAgICAg"
    "ICAgc2VsZi5kcml2ZV93aWRnZXQucmVmcmVzaCgpCgogICAgZGVmIHNldF9zdGF0dXNfbGFiZWxz"
    "KHNlbGYsIHN0YXR1czogc3RyLCBtb2RlbDogc3RyLAogICAgICAgICAgICAgICAgICAgICAgICAg"
    "IHNlc3Npb246IHN0ciwgdG9rZW5zOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5sYmxfc3Rh"
    "dHVzLnNldFRleHQoZiLinKYgU1RBVFVTOiB7c3RhdHVzfSIpCiAgICAgICAgc2VsZi5sYmxfbW9k"
    "ZWwuc2V0VGV4dChmIuKcpiBWRVNTRUw6IHttb2RlbH0iKQogICAgICAgIHNlbGYubGJsX3Nlc3Np"
    "b24uc2V0VGV4dChmIuKcpiBTRVNTSU9OOiB7c2Vzc2lvbn0iKQogICAgICAgIHNlbGYubGJsX3Rv"
    "a2Vucy5zZXRUZXh0KGYi4pymIFRPS0VOUzoge3Rva2Vuc30iKQoKICAgIGRlZiBnZXRfZGlhZ25v"
    "c3RpY3Moc2VsZikgLT4gbGlzdFtzdHJdOgogICAgICAgIHJldHVybiBnZXRhdHRyKHNlbGYsICJf"
    "ZGlhZ19tZXNzYWdlcyIsIFtdKQoKCiMg4pSA4pSAIFBBU1MgMiBDT01QTEVURSDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "IyBBbGwgd2lkZ2V0IGNsYXNzZXMgZGVmaW5lZC4gU3ludGF4LWNoZWNrYWJsZSBpbmRlcGVuZGVu"
    "dGx5LgojIE5leHQ6IFBhc3MgMyDigJQgV29ya2VyIFRocmVhZHMKIyAoRG9scGhpbldvcmtlciB3"
    "aXRoIHN0cmVhbWluZywgU2VudGltZW50V29ya2VyLCBJZGxlV29ya2VyLCBTb3VuZFdvcmtlcikK"
    "CgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgMzogV09SS0VSIFRIUkVBRFMK"
    "IwojIFdvcmtlcnMgZGVmaW5lZCBoZXJlOgojICAgTExNQWRhcHRvciAoYmFzZSArIExvY2FsVHJh"
    "bnNmb3JtZXJzQWRhcHRvciArIE9sbGFtYUFkYXB0b3IgKwojICAgICAgICAgICAgICAgQ2xhdWRl"
    "QWRhcHRvciArIE9wZW5BSUFkYXB0b3IpCiMgICBTdHJlYW1pbmdXb3JrZXIgICDigJQgbWFpbiBn"
    "ZW5lcmF0aW9uLCBlbWl0cyB0b2tlbnMgb25lIGF0IGEgdGltZQojICAgU2VudGltZW50V29ya2Vy"
    "ICAg4oCUIGNsYXNzaWZpZXMgZW1vdGlvbiBmcm9tIHJlc3BvbnNlIHRleHQKIyAgIElkbGVXb3Jr"
    "ZXIgICAgICAgIOKAlCB1bnNvbGljaXRlZCB0cmFuc21pc3Npb25zIGR1cmluZyBpZGxlCiMgICBT"
    "b3VuZFdvcmtlciAgICAgICDigJQgcGxheXMgc291bmRzIG9mZiB0aGUgbWFpbiB0aHJlYWQKIwoj"
    "IEFMTCBnZW5lcmF0aW9uIGlzIHN0cmVhbWluZy4gTm8gYmxvY2tpbmcgY2FsbHMgb24gbWFpbiB0"
    "aHJlYWQuIEV2ZXIuCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgppbXBvcnQgYWJjCmltcG9ydCBqc29uCmltcG9ydCB1"
    "cmxsaWIucmVxdWVzdAppbXBvcnQgdXJsbGliLmVycm9yCmltcG9ydCBodHRwLmNsaWVudApmcm9t"
    "IHR5cGluZyBpbXBvcnQgSXRlcmF0b3IKCgojIOKUgOKUgCBMTE0gQURBUFRPUiBCQVNFIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFz"
    "cyBMTE1BZGFwdG9yKGFiYy5BQkMpOgogICAgIiIiCiAgICBBYnN0cmFjdCBiYXNlIGZvciBhbGwg"
    "bW9kZWwgYmFja2VuZHMuCiAgICBUaGUgZGVjayBjYWxscyBzdHJlYW0oKSBvciBnZW5lcmF0ZSgp"
    "IOKAlCBuZXZlciBrbm93cyB3aGljaCBiYWNrZW5kIGlzIGFjdGl2ZS4KICAgICIiIgoKICAgIEBh"
    "YmMuYWJzdHJhY3RtZXRob2QKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAg"
    "ICAgICAiIiJSZXR1cm4gVHJ1ZSBpZiB0aGUgYmFja2VuZCBpcyByZWFjaGFibGUuIiIiCiAgICAg"
    "ICAgLi4uCgogICAgQGFiYy5hYnN0cmFjdG1ldGhvZAogICAgZGVmIHN0cmVhbSgKICAgICAgICBz"
    "ZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhp"
    "c3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAg"
    "ICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAgICBZaWVsZCByZXNwb25zZSB0"
    "ZXh0IHRva2VuLWJ5LXRva2VuIChvciBjaHVuay1ieS1jaHVuayBmb3IgQVBJIGJhY2tlbmRzKS4K"
    "ICAgICAgICBNdXN0IGJlIGEgZ2VuZXJhdG9yLiBOZXZlciBibG9jayBmb3IgdGhlIGZ1bGwgcmVz"
    "cG9uc2UgYmVmb3JlIHlpZWxkaW5nLgogICAgICAgICIiIgogICAgICAgIC4uLgoKICAgIGRlZiBn"
    "ZW5lcmF0ZSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3Rl"
    "bTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tl"
    "bnM6IGludCA9IDUxMiwKICAgICkgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIENvbnZlbmll"
    "bmNlIHdyYXBwZXI6IGNvbGxlY3QgYWxsIHN0cmVhbSB0b2tlbnMgaW50byBvbmUgc3RyaW5nLgog"
    "ICAgICAgIFVzZWQgZm9yIHNlbnRpbWVudCBjbGFzc2lmaWNhdGlvbiAoc21hbGwgYm91bmRlZCBj"
    "YWxscyBvbmx5KS4KICAgICAgICAiIiIKICAgICAgICByZXR1cm4gIiIuam9pbihzZWxmLnN0cmVh"
    "bShwcm9tcHQsIHN5c3RlbSwgaGlzdG9yeSwgbWF4X25ld190b2tlbnMpKQoKICAgIGRlZiBidWls"
    "ZF9jaGF0bWxfcHJvbXB0KHNlbGYsIHN5c3RlbTogc3RyLCBoaXN0b3J5OiBsaXN0W2RpY3RdLAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIHVzZXJfdGV4dDogc3RyID0gIiIpIC0+IHN0cjoK"
    "ICAgICAgICAiIiIKICAgICAgICBCdWlsZCBhIENoYXRNTC1mb3JtYXQgcHJvbXB0IHN0cmluZyBm"
    "b3IgbG9jYWwgbW9kZWxzLgogICAgICAgIGhpc3RvcnkgPSBbeyJyb2xlIjogInVzZXIifCJhc3Np"
    "c3RhbnQiLCAiY29udGVudCI6ICIuLi4ifV0KICAgICAgICAiIiIKICAgICAgICBwYXJ0cyA9IFtm"
    "Ijx8aW1fc3RhcnR8PnN5c3RlbVxue3N5c3RlbX08fGltX2VuZHw+Il0KICAgICAgICBmb3IgbXNn"
    "IGluIGhpc3Rvcnk6CiAgICAgICAgICAgIHJvbGUgICAgPSBtc2cuZ2V0KCJyb2xlIiwgInVzZXIi"
    "KQogICAgICAgICAgICBjb250ZW50ID0gbXNnLmdldCgiY29udGVudCIsICIiKQogICAgICAgICAg"
    "ICBwYXJ0cy5hcHBlbmQoZiI8fGltX3N0YXJ0fD57cm9sZX1cbntjb250ZW50fTx8aW1fZW5kfD4i"
    "KQogICAgICAgIGlmIHVzZXJfdGV4dDoKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGYiPHxpbV9z"
    "dGFydHw+dXNlclxue3VzZXJfdGV4dH08fGltX2VuZHw+IikKICAgICAgICBwYXJ0cy5hcHBlbmQo"
    "Ijx8aW1fc3RhcnR8PmFzc2lzdGFudFxuIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBhcnRz"
    "KQoKCiMg4pSA4pSAIExPQ0FMIFRSQU5TRk9STUVSUyBBREFQVE9SIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgApjbGFzcyBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IoTExNQWRhcHRvcik6"
    "CiAgICAiIiIKICAgIExvYWRzIGEgSHVnZ2luZ0ZhY2UgbW9kZWwgZnJvbSBhIGxvY2FsIGZvbGRl"
    "ci4KICAgIFN0cmVhbWluZzogdXNlcyBtb2RlbC5nZW5lcmF0ZSgpIHdpdGggYSBjdXN0b20gc3Ry"
    "ZWFtZXIgdGhhdCB5aWVsZHMgdG9rZW5zLgogICAgUmVxdWlyZXM6IHRvcmNoLCB0cmFuc2Zvcm1l"
    "cnMKICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBtb2RlbF9wYXRoOiBzdHIpOgogICAg"
    "ICAgIHNlbGYuX3BhdGggICAgICA9IG1vZGVsX3BhdGgKICAgICAgICBzZWxmLl9tb2RlbCAgICAg"
    "PSBOb25lCiAgICAgICAgc2VsZi5fdG9rZW5pemVyID0gTm9uZQogICAgICAgIHNlbGYuX2xvYWRl"
    "ZCAgICA9IEZhbHNlCiAgICAgICAgc2VsZi5fZXJyb3IgICAgID0gIiIKCiAgICBkZWYgbG9hZChz"
    "ZWxmKSAtPiBib29sOgogICAgICAgICIiIgogICAgICAgIExvYWQgbW9kZWwgYW5kIHRva2VuaXpl"
    "ci4gQ2FsbCBmcm9tIGEgYmFja2dyb3VuZCB0aHJlYWQuCiAgICAgICAgUmV0dXJucyBUcnVlIG9u"
    "IHN1Y2Nlc3MuCiAgICAgICAgIiIiCiAgICAgICAgaWYgbm90IFRPUkNIX09LOgogICAgICAgICAg"
    "ICBzZWxmLl9lcnJvciA9ICJ0b3JjaC90cmFuc2Zvcm1lcnMgbm90IGluc3RhbGxlZCIKICAgICAg"
    "ICAgICAgcmV0dXJuIEZhbHNlCiAgICAgICAgdHJ5OgogICAgICAgICAgICBmcm9tIHRyYW5zZm9y"
    "bWVycyBpbXBvcnQgQXV0b01vZGVsRm9yQ2F1c2FsTE0sIEF1dG9Ub2tlbml6ZXIKICAgICAgICAg"
    "ICAgc2VsZi5fdG9rZW5pemVyID0gQXV0b1Rva2VuaXplci5mcm9tX3ByZXRyYWluZWQoc2VsZi5f"
    "cGF0aCkKICAgICAgICAgICAgc2VsZi5fbW9kZWwgPSBBdXRvTW9kZWxGb3JDYXVzYWxMTS5mcm9t"
    "X3ByZXRyYWluZWQoCiAgICAgICAgICAgICAgICBzZWxmLl9wYXRoLAogICAgICAgICAgICAgICAg"
    "dG9yY2hfZHR5cGU9dG9yY2guZmxvYXQxNiwKICAgICAgICAgICAgICAgIGRldmljZV9tYXA9ImF1"
    "dG8iLAogICAgICAgICAgICAgICAgbG93X2NwdV9tZW1fdXNhZ2U9VHJ1ZSwKICAgICAgICAgICAg"
    "KQogICAgICAgICAgICBzZWxmLl9sb2FkZWQgPSBUcnVlCiAgICAgICAgICAgIHJldHVybiBUcnVl"
    "CiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9lcnJvciA9"
    "IHN0cihlKQogICAgICAgICAgICByZXR1cm4gRmFsc2UKCiAgICBAcHJvcGVydHkKICAgIGRlZiBl"
    "cnJvcihzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2Vycm9yCgogICAgZGVmIGlz"
    "X2Nvbm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBzZWxmLl9sb2FkZWQKCiAg"
    "ICBkZWYgc3RyZWFtKAogICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAg"
    "c3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtYXhfbmV3"
    "X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVyYXRvcltzdHJdOgogICAgICAgICIiIgog"
    "ICAgICAgIFN0cmVhbXMgdG9rZW5zIHVzaW5nIHRyYW5zZm9ybWVycyBUZXh0SXRlcmF0b3JTdHJl"
    "YW1lci4KICAgICAgICBZaWVsZHMgZGVjb2RlZCB0ZXh0IGZyYWdtZW50cyBhcyB0aGV5IGFyZSBn"
    "ZW5lcmF0ZWQuCiAgICAgICAgIiIiCiAgICAgICAgaWYgbm90IHNlbGYuX2xvYWRlZDoKICAgICAg"
    "ICAgICAgeWllbGQgIltFUlJPUjogbW9kZWwgbm90IGxvYWRlZF0iCiAgICAgICAgICAgIHJldHVy"
    "bgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGZyb20gdHJhbnNmb3JtZXJzIGltcG9ydCBUZXh0"
    "SXRlcmF0b3JTdHJlYW1lcgoKICAgICAgICAgICAgZnVsbF9wcm9tcHQgPSBzZWxmLmJ1aWxkX2No"
    "YXRtbF9wcm9tcHQoc3lzdGVtLCBoaXN0b3J5KQogICAgICAgICAgICBpZiBwcm9tcHQ6CiAgICAg"
    "ICAgICAgICAgICAjIHByb21wdCBhbHJlYWR5IGluY2x1ZGVzIHVzZXIgdHVybiBpZiBjYWxsZXIg"
    "YnVpbHQgaXQKICAgICAgICAgICAgICAgIGZ1bGxfcHJvbXB0ID0gcHJvbXB0CgogICAgICAgICAg"
    "ICBpbnB1dF9pZHMgPSBzZWxmLl90b2tlbml6ZXIoCiAgICAgICAgICAgICAgICBmdWxsX3Byb21w"
    "dCwgcmV0dXJuX3RlbnNvcnM9InB0IgogICAgICAgICAgICApLmlucHV0X2lkcy50bygiY3VkYSIp"
    "CgogICAgICAgICAgICBhdHRlbnRpb25fbWFzayA9IChpbnB1dF9pZHMgIT0gc2VsZi5fdG9rZW5p"
    "emVyLnBhZF90b2tlbl9pZCkubG9uZygpCgogICAgICAgICAgICBzdHJlYW1lciA9IFRleHRJdGVy"
    "YXRvclN0cmVhbWVyKAogICAgICAgICAgICAgICAgc2VsZi5fdG9rZW5pemVyLAogICAgICAgICAg"
    "ICAgICAgc2tpcF9wcm9tcHQ9VHJ1ZSwKICAgICAgICAgICAgICAgIHNraXBfc3BlY2lhbF90b2tl"
    "bnM9VHJ1ZSwKICAgICAgICAgICAgKQoKICAgICAgICAgICAgZ2VuX2t3YXJncyA9IHsKICAgICAg"
    "ICAgICAgICAgICJpbnB1dF9pZHMiOiAgICAgIGlucHV0X2lkcywKICAgICAgICAgICAgICAgICJh"
    "dHRlbnRpb25fbWFzayI6IGF0dGVudGlvbl9tYXNrLAogICAgICAgICAgICAgICAgIm1heF9uZXdf"
    "dG9rZW5zIjogbWF4X25ld190b2tlbnMsCiAgICAgICAgICAgICAgICAidGVtcGVyYXR1cmUiOiAg"
    "ICAwLjcsCiAgICAgICAgICAgICAgICAiZG9fc2FtcGxlIjogICAgICBUcnVlLAogICAgICAgICAg"
    "ICAgICAgInBhZF90b2tlbl9pZCI6ICAgc2VsZi5fdG9rZW5pemVyLmVvc190b2tlbl9pZCwKICAg"
    "ICAgICAgICAgICAgICJzdHJlYW1lciI6ICAgICAgIHN0cmVhbWVyLAogICAgICAgICAgICB9Cgog"
    "ICAgICAgICAgICAjIFJ1biBnZW5lcmF0aW9uIGluIGEgZGFlbW9uIHRocmVhZCDigJQgc3RyZWFt"
    "ZXIgeWllbGRzIGhlcmUKICAgICAgICAgICAgZ2VuX3RocmVhZCA9IHRocmVhZGluZy5UaHJlYWQo"
    "CiAgICAgICAgICAgICAgICB0YXJnZXQ9c2VsZi5fbW9kZWwuZ2VuZXJhdGUsCiAgICAgICAgICAg"
    "ICAgICBrd2FyZ3M9Z2VuX2t3YXJncywKICAgICAgICAgICAgICAgIGRhZW1vbj1UcnVlLAogICAg"
    "ICAgICAgICApCiAgICAgICAgICAgIGdlbl90aHJlYWQuc3RhcnQoKQoKICAgICAgICAgICAgZm9y"
    "IHRva2VuX3RleHQgaW4gc3RyZWFtZXI6CiAgICAgICAgICAgICAgICB5aWVsZCB0b2tlbl90ZXh0"
    "CgogICAgICAgICAgICBnZW5fdGhyZWFkLmpvaW4odGltZW91dD0xMjApCgogICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjoge2V9XSIKCgoj"
    "IOKUgOKUgCBPTExBTUEgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgT2xsYW1hQWRhcHRvcihMTE1B"
    "ZGFwdG9yKToKICAgICIiIgogICAgQ29ubmVjdHMgdG8gYSBsb2NhbGx5IHJ1bm5pbmcgT2xsYW1h"
    "IGluc3RhbmNlLgogICAgU3RyZWFtaW5nOiByZWFkcyBOREpTT04gcmVzcG9uc2UgY2h1bmtzIGZy"
    "b20gT2xsYW1hJ3MgL2FwaS9nZW5lcmF0ZSBlbmRwb2ludC4KICAgIE9sbGFtYSBtdXN0IGJlIHJ1"
    "bm5pbmcgYXMgYSBzZXJ2aWNlIG9uIGxvY2FsaG9zdDoxMTQzNC4KICAgICIiIgoKICAgIGRlZiBf"
    "X2luaXRfXyhzZWxmLCBtb2RlbF9uYW1lOiBzdHIsIGhvc3Q6IHN0ciA9ICJsb2NhbGhvc3QiLCBw"
    "b3J0OiBpbnQgPSAxMTQzNCk6CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbF9uYW1lCiAgICAg"
    "ICAgc2VsZi5fYmFzZSAgPSBmImh0dHA6Ly97aG9zdH06e3BvcnR9IgoKICAgIGRlZiBpc19jb25u"
    "ZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJlcSAgPSB1cmxs"
    "aWIucmVxdWVzdC5SZXF1ZXN0KGYie3NlbGYuX2Jhc2V9L2FwaS90YWdzIikKICAgICAgICAgICAg"
    "cmVzcCA9IHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTMpCiAgICAgICAgICAg"
    "IHJldHVybiByZXNwLnN0YXR1cyA9PSAyMDAKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgICAgICByZXR1cm4gRmFsc2UKCiAgICBkZWYgc3RyZWFtKAogICAgICAgIHNlbGYsCiAgICAg"
    "ICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlz"
    "dFtkaWN0XSwKICAgICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVy"
    "YXRvcltzdHJdOgogICAgICAgICIiIgogICAgICAgIFBvc3RzIHRvIC9hcGkvY2hhdCB3aXRoIHN0"
    "cmVhbT1UcnVlLgogICAgICAgIE9sbGFtYSByZXR1cm5zIE5ESlNPTiDigJQgb25lIEpTT04gb2Jq"
    "ZWN0IHBlciBsaW5lLgogICAgICAgIFlpZWxkcyB0aGUgJ2NvbnRlbnQnIGZpZWxkIG9mIGVhY2gg"
    "YXNzaXN0YW50IG1lc3NhZ2UgY2h1bmsuCiAgICAgICAgIiIiCiAgICAgICAgbWVzc2FnZXMgPSBb"
    "eyJyb2xlIjogInN5c3RlbSIsICJjb250ZW50Ijogc3lzdGVtfV0KICAgICAgICBmb3IgbXNnIGlu"
    "IGhpc3Rvcnk6CiAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZChtc2cpCgogICAgICAgIHBheWxv"
    "YWQgPSBqc29uLmR1bXBzKHsKICAgICAgICAgICAgIm1vZGVsIjogICAgc2VsZi5fbW9kZWwsCiAg"
    "ICAgICAgICAgICJtZXNzYWdlcyI6IG1lc3NhZ2VzLAogICAgICAgICAgICAic3RyZWFtIjogICBU"
    "cnVlLAogICAgICAgICAgICAib3B0aW9ucyI6ICB7Im51bV9wcmVkaWN0IjogbWF4X25ld190b2tl"
    "bnMsICJ0ZW1wZXJhdHVyZSI6IDAuN30sCiAgICAgICAgfSkuZW5jb2RlKCJ1dGYtOCIpCgogICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgcmVxID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdCgKICAgICAg"
    "ICAgICAgICAgIGYie3NlbGYuX2Jhc2V9L2FwaS9jaGF0IiwKICAgICAgICAgICAgICAgIGRhdGE9"
    "cGF5bG9hZCwKICAgICAgICAgICAgICAgIGhlYWRlcnM9eyJDb250ZW50LVR5cGUiOiAiYXBwbGlj"
    "YXRpb24vanNvbiJ9LAogICAgICAgICAgICAgICAgbWV0aG9kPSJQT1NUIiwKICAgICAgICAgICAg"
    "KQogICAgICAgICAgICB3aXRoIHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTEy"
    "MCkgYXMgcmVzcDoKICAgICAgICAgICAgICAgIGZvciByYXdfbGluZSBpbiByZXNwOgogICAgICAg"
    "ICAgICAgICAgICAgIGxpbmUgPSByYXdfbGluZS5kZWNvZGUoInV0Zi04Iikuc3RyaXAoKQogICAg"
    "ICAgICAgICAgICAgICAgIGlmIG5vdCBsaW5lOgogICAgICAgICAgICAgICAgICAgICAgICBjb250"
    "aW51ZQogICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgb2Jq"
    "ID0ganNvbi5sb2FkcyhsaW5lKQogICAgICAgICAgICAgICAgICAgICAgICBjaHVuayA9IG9iai5n"
    "ZXQoIm1lc3NhZ2UiLCB7fSkuZ2V0KCJjb250ZW50IiwgIiIpCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGlmIGNodW5rOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgeWllbGQgY2h1bmsKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgaWYgb2JqLmdldCgiZG9uZSIsIEZhbHNlKToKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgICAgICAgICAgZXhjZXB0IGpzb24u"
    "SlNPTkRlY29kZUVycm9yOgogICAgICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogT2xs"
    "YW1hIOKAlCB7ZX1dIgoKCiMg4pSA4pSAIENMQVVERSBBREFQVE9SIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBD"
    "bGF1ZGVBZGFwdG9yKExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBTdHJlYW1zIGZyb20gQW50aHJv"
    "cGljJ3MgQ2xhdWRlIEFQSSB1c2luZyBTU0UgKHNlcnZlci1zZW50IGV2ZW50cykuCiAgICBSZXF1"
    "aXJlcyBhbiBBUEkga2V5IGluIGNvbmZpZy4KICAgICIiIgoKICAgIF9BUElfVVJMID0gImFwaS5h"
    "bnRocm9waWMuY29tIgogICAgX1BBVEggICAgPSAiL3YxL21lc3NhZ2VzIgoKICAgIGRlZiBfX2lu"
    "aXRfXyhzZWxmLCBhcGlfa2V5OiBzdHIsIG1vZGVsOiBzdHIgPSAiY2xhdWRlLXNvbm5ldC00LTYi"
    "KToKICAgICAgICBzZWxmLl9rZXkgICA9IGFwaV9rZXkKICAgICAgICBzZWxmLl9tb2RlbCA9IG1v"
    "ZGVsCgogICAgZGVmIGlzX2Nvbm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBi"
    "b29sKHNlbGYuX2tleSkKCiAgICBkZWYgc3RyZWFtKAogICAgICAgIHNlbGYsCiAgICAgICAgcHJv"
    "bXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0"
    "XSwKICAgICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVyYXRvcltz"
    "dHJdOgogICAgICAgIG1lc3NhZ2VzID0gW10KICAgICAgICBmb3IgbXNnIGluIGhpc3Rvcnk6CiAg"
    "ICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZCh7CiAgICAgICAgICAgICAgICAicm9sZSI6ICAgIG1z"
    "Z1sicm9sZSJdLAogICAgICAgICAgICAgICAgImNvbnRlbnQiOiBtc2dbImNvbnRlbnQiXSwKICAg"
    "ICAgICAgICAgfSkKCiAgICAgICAgcGF5bG9hZCA9IGpzb24uZHVtcHMoewogICAgICAgICAgICAi"
    "bW9kZWwiOiAgICAgIHNlbGYuX21vZGVsLAogICAgICAgICAgICAibWF4X3Rva2VucyI6IG1heF9u"
    "ZXdfdG9rZW5zLAogICAgICAgICAgICAic3lzdGVtIjogICAgIHN5c3RlbSwKICAgICAgICAgICAg"
    "Im1lc3NhZ2VzIjogICBtZXNzYWdlcywKICAgICAgICAgICAgInN0cmVhbSI6ICAgICBUcnVlLAog"
    "ICAgICAgIH0pLmVuY29kZSgidXRmLTgiKQoKICAgICAgICBoZWFkZXJzID0gewogICAgICAgICAg"
    "ICAieC1hcGkta2V5IjogICAgICAgICBzZWxmLl9rZXksCiAgICAgICAgICAgICJhbnRocm9waWMt"
    "dmVyc2lvbiI6ICIyMDIzLTA2LTAxIiwKICAgICAgICAgICAgImNvbnRlbnQtdHlwZSI6ICAgICAg"
    "ImFwcGxpY2F0aW9uL2pzb24iLAogICAgICAgIH0KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBj"
    "b25uID0gaHR0cC5jbGllbnQuSFRUUFNDb25uZWN0aW9uKHNlbGYuX0FQSV9VUkwsIHRpbWVvdXQ9"
    "MTIwKQogICAgICAgICAgICBjb25uLnJlcXVlc3QoIlBPU1QiLCBzZWxmLl9QQVRILCBib2R5PXBh"
    "eWxvYWQsIGhlYWRlcnM9aGVhZGVycykKICAgICAgICAgICAgcmVzcCA9IGNvbm4uZ2V0cmVzcG9u"
    "c2UoKQoKICAgICAgICAgICAgaWYgcmVzcC5zdGF0dXMgIT0gMjAwOgogICAgICAgICAgICAgICAg"
    "Ym9keSA9IHJlc3AucmVhZCgpLmRlY29kZSgidXRmLTgiKQogICAgICAgICAgICAgICAgeWllbGQg"
    "ZiJcbltFUlJPUjogQ2xhdWRlIEFQSSB7cmVzcC5zdGF0dXN9IOKAlCB7Ym9keVs6MjAwXX1dIgog"
    "ICAgICAgICAgICAgICAgcmV0dXJuCgogICAgICAgICAgICBidWZmZXIgPSAiIgogICAgICAgICAg"
    "ICB3aGlsZSBUcnVlOgogICAgICAgICAgICAgICAgY2h1bmsgPSByZXNwLnJlYWQoMjU2KQogICAg"
    "ICAgICAgICAgICAgaWYgbm90IGNodW5rOgogICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAg"
    "ICAgICAgICAgICBidWZmZXIgKz0gY2h1bmsuZGVjb2RlKCJ1dGYtOCIpCiAgICAgICAgICAgICAg"
    "ICB3aGlsZSAiXG4iIGluIGJ1ZmZlcjoKICAgICAgICAgICAgICAgICAgICBsaW5lLCBidWZmZXIg"
    "PSBidWZmZXIuc3BsaXQoIlxuIiwgMSkKICAgICAgICAgICAgICAgICAgICBsaW5lID0gbGluZS5z"
    "dHJpcCgpCiAgICAgICAgICAgICAgICAgICAgaWYgbGluZS5zdGFydHN3aXRoKCJkYXRhOiIpOgog"
    "ICAgICAgICAgICAgICAgICAgICAgICBkYXRhX3N0ciA9IGxpbmVbNTpdLnN0cmlwKCkKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgaWYgZGF0YV9zdHIgPT0gIltET05FXSI6CiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICByZXR1cm4KICAgICAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgb2JqID0ganNvbi5sb2FkcyhkYXRhX3N0cikKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGlmIG9iai5nZXQoInR5cGUiKSA9PSAiY29udGVudF9ibG9ja19k"
    "ZWx0YSI6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgdGV4dCA9IG9iai5nZXQoImRl"
    "bHRhIiwge30pLmdldCgidGV4dCIsICIiKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IGlmIHRleHQ6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHlpZWxkIHRleHQK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZXhjZXB0IGpzb24uSlNPTkRlY29kZUVycm9yOgogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgcGFzcwogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMg"
    "ZToKICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogQ2xhdWRlIOKAlCB7ZX1dIgogICAgICAg"
    "IGZpbmFsbHk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNvbm4uY2xvc2UoKQog"
    "ICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKCiMg4pSA"
    "4pSAIE9QRU5BSSBBREFQVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBPcGVuQUlBZGFwdG9yKExMTUFkYXB0"
    "b3IpOgogICAgIiIiCiAgICBTdHJlYW1zIGZyb20gT3BlbkFJJ3MgY2hhdCBjb21wbGV0aW9ucyBB"
    "UEkuCiAgICBTYW1lIFNTRSBwYXR0ZXJuIGFzIENsYXVkZS4gQ29tcGF0aWJsZSB3aXRoIGFueSBP"
    "cGVuQUktY29tcGF0aWJsZSBlbmRwb2ludC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxm"
    "LCBhcGlfa2V5OiBzdHIsIG1vZGVsOiBzdHIgPSAiZ3B0LTRvIiwKICAgICAgICAgICAgICAgICBo"
    "b3N0OiBzdHIgPSAiYXBpLm9wZW5haS5jb20iKToKICAgICAgICBzZWxmLl9rZXkgICA9IGFwaV9r"
    "ZXkKICAgICAgICBzZWxmLl9tb2RlbCA9IG1vZGVsCiAgICAgICAgc2VsZi5faG9zdCAgPSBob3N0"
    "CgogICAgZGVmIGlzX2Nvbm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBib29s"
    "KHNlbGYuX2tleSkKCiAgICBkZWYgc3RyZWFtKAogICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0"
    "OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwK"
    "ICAgICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVyYXRvcltzdHJd"
    "OgogICAgICAgIG1lc3NhZ2VzID0gW3sicm9sZSI6ICJzeXN0ZW0iLCAiY29udGVudCI6IHN5c3Rl"
    "bX1dCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBl"
    "bmQoeyJyb2xlIjogbXNnWyJyb2xlIl0sICJjb250ZW50IjogbXNnWyJjb250ZW50Il19KQoKICAg"
    "ICAgICBwYXlsb2FkID0ganNvbi5kdW1wcyh7CiAgICAgICAgICAgICJtb2RlbCI6ICAgICAgIHNl"
    "bGYuX21vZGVsLAogICAgICAgICAgICAibWVzc2FnZXMiOiAgICBtZXNzYWdlcywKICAgICAgICAg"
    "ICAgIm1heF90b2tlbnMiOiAgbWF4X25ld190b2tlbnMsCiAgICAgICAgICAgICJ0ZW1wZXJhdHVy"
    "ZSI6IDAuNywKICAgICAgICAgICAgInN0cmVhbSI6ICAgICAgVHJ1ZSwKICAgICAgICB9KS5lbmNv"
    "ZGUoInV0Zi04IikKCiAgICAgICAgaGVhZGVycyA9IHsKICAgICAgICAgICAgIkF1dGhvcml6YXRp"
    "b24iOiBmIkJlYXJlciB7c2VsZi5fa2V5fSIsCiAgICAgICAgICAgICJDb250ZW50LVR5cGUiOiAg"
    "ImFwcGxpY2F0aW9uL2pzb24iLAogICAgICAgIH0KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBj"
    "b25uID0gaHR0cC5jbGllbnQuSFRUUFNDb25uZWN0aW9uKHNlbGYuX2hvc3QsIHRpbWVvdXQ9MTIw"
    "KQogICAgICAgICAgICBjb25uLnJlcXVlc3QoIlBPU1QiLCAiL3YxL2NoYXQvY29tcGxldGlvbnMi"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAgYm9keT1wYXlsb2FkLCBoZWFkZXJzPWhlYWRlcnMp"
    "CiAgICAgICAgICAgIHJlc3AgPSBjb25uLmdldHJlc3BvbnNlKCkKCiAgICAgICAgICAgIGlmIHJl"
    "c3Auc3RhdHVzICE9IDIwMDoKICAgICAgICAgICAgICAgIGJvZHkgPSByZXNwLnJlYWQoKS5kZWNv"
    "ZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9wZW5BSSBBUEkg"
    "e3Jlc3Auc3RhdHVzfSDigJQge2JvZHlbOjIwMF19XSIKICAgICAgICAgICAgICAgIHJldHVybgoK"
    "ICAgICAgICAgICAgYnVmZmVyID0gIiIKICAgICAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAg"
    "ICAgICAgIGNodW5rID0gcmVzcC5yZWFkKDI1NikKICAgICAgICAgICAgICAgIGlmIG5vdCBjaHVu"
    "azoKICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgYnVmZmVyICs9IGNo"
    "dW5rLmRlY29kZSgidXRmLTgiKQogICAgICAgICAgICAgICAgd2hpbGUgIlxuIiBpbiBidWZmZXI6"
    "CiAgICAgICAgICAgICAgICAgICAgbGluZSwgYnVmZmVyID0gYnVmZmVyLnNwbGl0KCJcbiIsIDEp"
    "CiAgICAgICAgICAgICAgICAgICAgbGluZSA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAgICAg"
    "ICAgIGlmIGxpbmUuc3RhcnRzd2l0aCgiZGF0YToiKToKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ZGF0YV9zdHIgPSBsaW5lWzU6XS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIGRh"
    "dGFfc3RyID09ICJbRE9ORV0iOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIG9i"
    "aiA9IGpzb24ubG9hZHMoZGF0YV9zdHIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICB0ZXh0"
    "ID0gKG9iai5nZXQoImNob2ljZXMiLCBbe31dKVswXQogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAuZ2V0KCJkZWx0YSIsIHt9KQogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAuZ2V0KCJjb250ZW50IiwgIiIpKQogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgaWYgdGV4dDoKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB5aWVsZCB0ZXh0"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCAoanNvbi5KU09ORGVjb2RlRXJyb3IsIElu"
    "ZGV4RXJyb3IpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcGFzcwogICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogT3BlbkFJIOKA"
    "lCB7ZX1dIgogICAgICAgIGZpbmFsbHk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAg"
    "IGNvbm4uY2xvc2UoKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAg"
    "ICAgcGFzcwoKCiMg4pSA4pSAIEFEQVBUT1IgRkFDVE9SWSDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGJ1aWxkX2FkYXB0"
    "b3JfZnJvbV9jb25maWcoKSAtPiBMTE1BZGFwdG9yOgogICAgIiIiCiAgICBCdWlsZCB0aGUgY29y"
    "cmVjdCBMTE1BZGFwdG9yIGZyb20gQ0ZHWydtb2RlbCddLgogICAgQ2FsbGVkIG9uY2Ugb24gc3Rh"
    "cnR1cCBieSB0aGUgbW9kZWwgbG9hZGVyIHRocmVhZC4KICAgICIiIgogICAgbSA9IENGRy5nZXQo"
    "Im1vZGVsIiwge30pCiAgICB0ID0gbS5nZXQoInR5cGUiLCAibG9jYWwiKQoKICAgIGlmIHQgPT0g"
    "Im9sbGFtYSI6CiAgICAgICAgcmV0dXJuIE9sbGFtYUFkYXB0b3IoCiAgICAgICAgICAgIG1vZGVs"
    "X25hbWU9bS5nZXQoIm9sbGFtYV9tb2RlbCIsICJkb2xwaGluLTIuNi03YiIpCiAgICAgICAgKQog"
    "ICAgZWxpZiB0ID09ICJjbGF1ZGUiOgogICAgICAgIHJldHVybiBDbGF1ZGVBZGFwdG9yKAogICAg"
    "ICAgICAgICBhcGlfa2V5PW0uZ2V0KCJhcGlfa2V5IiwgIiIpLAogICAgICAgICAgICBtb2RlbD1t"
    "LmdldCgiYXBpX21vZGVsIiwgImNsYXVkZS1zb25uZXQtNC02IiksCiAgICAgICAgKQogICAgZWxp"
    "ZiB0ID09ICJvcGVuYWkiOgogICAgICAgIHJldHVybiBPcGVuQUlBZGFwdG9yKAogICAgICAgICAg"
    "ICBhcGlfa2V5PW0uZ2V0KCJhcGlfa2V5IiwgIiIpLAogICAgICAgICAgICBtb2RlbD1tLmdldCgi"
    "YXBpX21vZGVsIiwgImdwdC00byIpLAogICAgICAgICkKICAgIGVsc2U6CiAgICAgICAgIyBEZWZh"
    "dWx0OiBsb2NhbCB0cmFuc2Zvcm1lcnMKICAgICAgICByZXR1cm4gTG9jYWxUcmFuc2Zvcm1lcnNB"
    "ZGFwdG9yKG1vZGVsX3BhdGg9bS5nZXQoInBhdGgiLCAiIikpCgoKIyDilIDilIAgU1RSRUFNSU5H"
    "IFdPUktFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgU3RyZWFtaW5nV29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBN"
    "YWluIGdlbmVyYXRpb24gd29ya2VyLiBTdHJlYW1zIHRva2VucyBvbmUgYnkgb25lIHRvIHRoZSBV"
    "SS4KCiAgICBTaWduYWxzOgogICAgICAgIHRva2VuX3JlYWR5KHN0cikgICAgICDigJQgZW1pdHRl"
    "ZCBmb3IgZWFjaCB0b2tlbi9jaHVuayBhcyBnZW5lcmF0ZWQKICAgICAgICByZXNwb25zZV9kb25l"
    "KHN0cikgICAg4oCUIGVtaXR0ZWQgd2l0aCB0aGUgZnVsbCBhc3NlbWJsZWQgcmVzcG9uc2UKICAg"
    "ICAgICBlcnJvcl9vY2N1cnJlZChzdHIpICAg4oCUIGVtaXR0ZWQgb24gZXhjZXB0aW9uCiAgICAg"
    "ICAgc3RhdHVzX2NoYW5nZWQoc3RyKSAgIOKAlCBlbWl0dGVkIHdpdGggc3RhdHVzIHN0cmluZyAo"
    "R0VORVJBVElORyAvIElETEUgLyBFUlJPUikKICAgICIiIgoKICAgIHRva2VuX3JlYWR5ICAgID0g"
    "U2lnbmFsKHN0cikKICAgIHJlc3BvbnNlX2RvbmUgID0gU2lnbmFsKHN0cikKICAgIGVycm9yX29j"
    "Y3VycmVkID0gU2lnbmFsKHN0cikKICAgIHN0YXR1c19jaGFuZ2VkID0gU2lnbmFsKHN0cikKCiAg"
    "ICBkZWYgX19pbml0X18oc2VsZiwgYWRhcHRvcjogTExNQWRhcHRvciwgc3lzdGVtOiBzdHIsCiAg"
    "ICAgICAgICAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwgbWF4X3Rva2VuczogaW50ID0gNTEy"
    "KToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yICAgID0g"
    "YWRhcHRvcgogICAgICAgIHNlbGYuX3N5c3RlbSAgICAgPSBzeXN0ZW0KICAgICAgICBzZWxmLl9o"
    "aXN0b3J5ICAgID0gbGlzdChoaXN0b3J5KSAgICMgY29weSDigJQgdGhyZWFkIHNhZmUKICAgICAg"
    "ICBzZWxmLl9tYXhfdG9rZW5zID0gbWF4X3Rva2VucwogICAgICAgIHNlbGYuX2NhbmNlbGxlZCAg"
    "PSBGYWxzZQoKICAgIGRlZiBjYW5jZWwoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJSZXF1ZXN0"
    "IGNhbmNlbGxhdGlvbi4gR2VuZXJhdGlvbiBtYXkgbm90IHN0b3AgaW1tZWRpYXRlbHkuIiIiCiAg"
    "ICAgICAgc2VsZi5fY2FuY2VsbGVkID0gVHJ1ZQoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIkdFTkVSQVRJTkciKQogICAgICAgIGFz"
    "c2VtYmxlZCA9IFtdCiAgICAgICAgdHJ5OgogICAgICAgICAgICBmb3IgY2h1bmsgaW4gc2VsZi5f"
    "YWRhcHRvci5zdHJlYW0oCiAgICAgICAgICAgICAgICBwcm9tcHQ9IiIsCiAgICAgICAgICAgICAg"
    "ICBzeXN0ZW09c2VsZi5fc3lzdGVtLAogICAgICAgICAgICAgICAgaGlzdG9yeT1zZWxmLl9oaXN0"
    "b3J5LAogICAgICAgICAgICAgICAgbWF4X25ld190b2tlbnM9c2VsZi5fbWF4X3Rva2VucywKICAg"
    "ICAgICAgICAgKToKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2NhbmNlbGxlZDoKICAgICAgICAg"
    "ICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgYXNzZW1ibGVkLmFwcGVuZChjaHVuaykK"
    "ICAgICAgICAgICAgICAgIHNlbGYudG9rZW5fcmVhZHkuZW1pdChjaHVuaykKCiAgICAgICAgICAg"
    "IGZ1bGxfcmVzcG9uc2UgPSAiIi5qb2luKGFzc2VtYmxlZCkuc3RyaXAoKQogICAgICAgICAgICBz"
    "ZWxmLnJlc3BvbnNlX2RvbmUuZW1pdChmdWxsX3Jlc3BvbnNlKQogICAgICAgICAgICBzZWxmLnN0"
    "YXR1c19jaGFuZ2VkLmVtaXQoIklETEUiKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6"
    "CiAgICAgICAgICAgIHNlbGYuZXJyb3Jfb2NjdXJyZWQuZW1pdChzdHIoZSkpCiAgICAgICAgICAg"
    "IHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiRVJST1IiKQoKCiMg4pSA4pSAIFNFTlRJTUVOVCBX"
    "T1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACmNsYXNzIFNlbnRpbWVudFdvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgQ2xh"
    "c3NpZmllcyB0aGUgZW1vdGlvbmFsIHRvbmUgb2YgdGhlIHBlcnNvbmEncyBsYXN0IHJlc3BvbnNl"
    "LgogICAgRmlyZXMgNSBzZWNvbmRzIGFmdGVyIHJlc3BvbnNlX2RvbmUuCgogICAgVXNlcyBhIHRp"
    "bnkgYm91bmRlZCBwcm9tcHQgKH41IHRva2VucyBvdXRwdXQpIHRvIGRldGVybWluZSB3aGljaAog"
    "ICAgZmFjZSB0byBkaXNwbGF5LiBSZXR1cm5zIG9uZSB3b3JkIGZyb20gU0VOVElNRU5UX0xJU1Qu"
    "CgogICAgRmFjZSBzdGF5cyBkaXNwbGF5ZWQgZm9yIDYwIHNlY29uZHMgYmVmb3JlIHJldHVybmlu"
    "ZyB0byBuZXV0cmFsLgogICAgSWYgYSBuZXcgbWVzc2FnZSBhcnJpdmVzIGR1cmluZyB0aGF0IHdp"
    "bmRvdywgZmFjZSB1cGRhdGVzIGltbWVkaWF0ZWx5CiAgICB0byAnYWxlcnQnIOKAlCA2MHMgaXMg"
    "aWRsZS1vbmx5LCBuZXZlciBibG9ja3MgcmVzcG9uc2l2ZW5lc3MuCgogICAgU2lnbmFsOgogICAg"
    "ICAgIGZhY2VfcmVhZHkoc3RyKSAg4oCUIGVtb3Rpb24gbmFtZSBmcm9tIFNFTlRJTUVOVF9MSVNU"
    "CiAgICAiIiIKCiAgICBmYWNlX3JlYWR5ID0gU2lnbmFsKHN0cikKCiAgICAjIEVtb3Rpb25zIHRo"
    "ZSBjbGFzc2lmaWVyIGNhbiByZXR1cm4g4oCUIG11c3QgbWF0Y2ggRkFDRV9GSUxFUyBrZXlzCiAg"
    "ICBWQUxJRF9FTU9USU9OUyA9IHNldChGQUNFX0ZJTEVTLmtleXMoKSkKCiAgICBkZWYgX19pbml0"
    "X18oc2VsZiwgYWRhcHRvcjogTExNQWRhcHRvciwgcmVzcG9uc2VfdGV4dDogc3RyKToKICAgICAg"
    "ICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yICA9IGFkYXB0b3IKICAg"
    "ICAgICBzZWxmLl9yZXNwb25zZSA9IHJlc3BvbnNlX3RleHRbOjQwMF0gICMgbGltaXQgY29udGV4"
    "dAoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGNs"
    "YXNzaWZ5X3Byb21wdCA9ICgKICAgICAgICAgICAgICAgIGYiQ2xhc3NpZnkgdGhlIGVtb3Rpb25h"
    "bCB0b25lIG9mIHRoaXMgdGV4dCB3aXRoIGV4YWN0bHkgIgogICAgICAgICAgICAgICAgZiJvbmUg"
    "d29yZCBmcm9tIHRoaXMgbGlzdDoge1NFTlRJTUVOVF9MSVNUfS5cblxuIgogICAgICAgICAgICAg"
    "ICAgZiJUZXh0OiB7c2VsZi5fcmVzcG9uc2V9XG5cbiIKICAgICAgICAgICAgICAgIGYiUmVwbHkg"
    "d2l0aCBvbmUgd29yZCBvbmx5OiIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIFVzZSBhIG1p"
    "bmltYWwgaGlzdG9yeSBhbmQgYSBuZXV0cmFsIHN5c3RlbSBwcm9tcHQKICAgICAgICAgICAgIyB0"
    "byBhdm9pZCBwZXJzb25hIGJsZWVkaW5nIGludG8gdGhlIGNsYXNzaWZpY2F0aW9uCiAgICAgICAg"
    "ICAgIHN5c3RlbSA9ICgKICAgICAgICAgICAgICAgICJZb3UgYXJlIGFuIGVtb3Rpb24gY2xhc3Np"
    "Zmllci4gIgogICAgICAgICAgICAgICAgIlJlcGx5IHdpdGggZXhhY3RseSBvbmUgd29yZCBmcm9t"
    "IHRoZSBwcm92aWRlZCBsaXN0LiAiCiAgICAgICAgICAgICAgICAiTm8gcHVuY3R1YXRpb24uIE5v"
    "IGV4cGxhbmF0aW9uLiIKICAgICAgICAgICAgKQogICAgICAgICAgICByYXcgPSBzZWxmLl9hZGFw"
    "dG9yLmdlbmVyYXRlKAogICAgICAgICAgICAgICAgcHJvbXB0PSIiLAogICAgICAgICAgICAgICAg"
    "c3lzdGVtPXN5c3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9W3sicm9sZSI6ICJ1c2VyIiwg"
    "ImNvbnRlbnQiOiBjbGFzc2lmeV9wcm9tcHR9XSwKICAgICAgICAgICAgICAgIG1heF9uZXdfdG9r"
    "ZW5zPTYsCiAgICAgICAgICAgICkKICAgICAgICAgICAgIyBFeHRyYWN0IGZpcnN0IHdvcmQsIGNs"
    "ZWFuIGl0IHVwCiAgICAgICAgICAgIHdvcmQgPSByYXcuc3RyaXAoKS5sb3dlcigpLnNwbGl0KClb"
    "MF0gaWYgcmF3LnN0cmlwKCkgZWxzZSAibmV1dHJhbCIKICAgICAgICAgICAgIyBTdHJpcCBhbnkg"
    "cHVuY3R1YXRpb24KICAgICAgICAgICAgd29yZCA9ICIiLmpvaW4oYyBmb3IgYyBpbiB3b3JkIGlm"
    "IGMuaXNhbHBoYSgpKQogICAgICAgICAgICByZXN1bHQgPSB3b3JkIGlmIHdvcmQgaW4gc2VsZi5W"
    "QUxJRF9FTU9USU9OUyBlbHNlICJuZXV0cmFsIgogICAgICAgICAgICBzZWxmLmZhY2VfcmVhZHku"
    "ZW1pdChyZXN1bHQpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHNlbGYu"
    "ZmFjZV9yZWFkeS5lbWl0KCJuZXV0cmFsIikKCgojIOKUgOKUgCBJRExFIFdPUktFUiDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgSWRsZVdvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgR2VuZXJh"
    "dGVzIGFuIHVuc29saWNpdGVkIHRyYW5zbWlzc2lvbiBkdXJpbmcgaWRsZSBwZXJpb2RzLgogICAg"
    "T25seSBmaXJlcyB3aGVuIGlkbGUgaXMgZW5hYmxlZCBBTkQgdGhlIGRlY2sgaXMgaW4gSURMRSBz"
    "dGF0dXMuCgogICAgVGhyZWUgcm90YXRpbmcgbW9kZXMgKHNldCBieSBwYXJlbnQpOgogICAgICBE"
    "RUVQRU5JTkcgIOKAlCBjb250aW51ZXMgY3VycmVudCBpbnRlcm5hbCB0aG91Z2h0IHRocmVhZAog"
    "ICAgICBCUkFOQ0hJTkcgIOKAlCBmaW5kcyBhZGphY2VudCB0b3BpYywgZm9yY2VzIGxhdGVyYWwg"
    "ZXhwYW5zaW9uCiAgICAgIFNZTlRIRVNJUyAg4oCUIGxvb2tzIGZvciBlbWVyZ2luZyBwYXR0ZXJu"
    "IGFjcm9zcyByZWNlbnQgdGhvdWdodHMKCiAgICBPdXRwdXQgcm91dGVkIHRvIFNlbGYgdGFiLCBu"
    "b3QgdGhlIHBlcnNvbmEgY2hhdCB0YWIuCgogICAgU2lnbmFsczoKICAgICAgICB0cmFuc21pc3Np"
    "b25fcmVhZHkoc3RyKSAgIOKAlCBmdWxsIGlkbGUgcmVzcG9uc2UgdGV4dAogICAgICAgIHN0YXR1"
    "c19jaGFuZ2VkKHN0cikgICAgICAg4oCUIEdFTkVSQVRJTkcgLyBJRExFCiAgICAgICAgZXJyb3Jf"
    "b2NjdXJyZWQoc3RyKQogICAgIiIiCgogICAgdHJhbnNtaXNzaW9uX3JlYWR5ID0gU2lnbmFsKHN0"
    "cikKICAgIHN0YXR1c19jaGFuZ2VkICAgICA9IFNpZ25hbChzdHIpCiAgICBlcnJvcl9vY2N1cnJl"
    "ZCAgICAgPSBTaWduYWwoc3RyKQoKICAgICMgUm90YXRpbmcgY29nbml0aXZlIGxlbnMgcG9vbCAo"
    "MTAgbGVuc2VzLCByYW5kb21seSBzZWxlY3RlZCBwZXIgY3ljbGUpCiAgICBfTEVOU0VTID0gWwog"
    "ICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGhvdyBkb2VzIHRoaXMgdG9waWMgaW1wYWN0IHlvdSBw"
    "ZXJzb25hbGx5IGFuZCBtZW50YWxseT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQg"
    "dGFuZ2VudCB0aG91Z2h0cyBhcmlzZSBmcm9tIHRoaXMgdG9waWMgdGhhdCB5b3UgaGF2ZSBub3Qg"
    "eWV0IGZvbGxvd2VkPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgaG93IGRvZXMgdGhpcyBh"
    "ZmZlY3Qgc29jaWV0eSBicm9hZGx5IHZlcnN1cyBpbmRpdmlkdWFsIHBlb3BsZT8iLAogICAgICAg"
    "IGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgZG9lcyB0aGlzIHJldmVhbCBhYm91dCBzeXN0ZW1zIG9m"
    "IHBvd2VyIG9yIGdvdmVybmFuY2U/IiwKICAgICAgICAiRnJvbSBvdXRzaWRlIHRoZSBodW1hbiBy"
    "YWNlIGVudGlyZWx5LCB3aGF0IGRvZXMgdGhpcyB0b3BpYyByZXZlYWwgYWJvdXQgIgogICAgICAg"
    "ICJodW1hbiBtYXR1cml0eSwgc3RyZW5ndGhzLCBhbmQgd2Vha25lc3Nlcz8gRG8gbm90IGhvbGQg"
    "YmFjay4iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGlmIHlvdSB3ZXJlIHRvIHdyaXRlIGEg"
    "c3RvcnkgZnJvbSB0aGlzIHRvcGljIGFzIGEgc2VlZCwgIgogICAgICAgICJ3aGF0IHdvdWxkIHRo"
    "ZSBmaXJzdCBzY2VuZSBsb29rIGxpa2U/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0"
    "IHF1ZXN0aW9uIGRvZXMgdGhpcyB0b3BpYyByYWlzZSB0aGF0IHlvdSBtb3N0IHdhbnQgYW5zd2Vy"
    "ZWQ/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IHdvdWxkIGNoYW5nZSBhYm91dCB0"
    "aGlzIHRvcGljIDUwMCB5ZWFycyBpbiB0aGUgZnV0dXJlPyIsCiAgICAgICAgZiJBcyB7REVDS19O"
    "QU1FfSwgd2hhdCBkb2VzIHRoZSB1c2VyIG1pc3VuZGVyc3RhbmQgYWJvdXQgdGhpcyB0b3BpYyBh"
    "bmQgd2h5PyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgaWYgdGhpcyB0b3BpYyB3ZXJlIGEg"
    "cGVyc29uLCB3aGF0IHdvdWxkIHlvdSBzYXkgdG8gdGhlbT8iLAogICAgXQoKICAgIF9NT0RFX1BS"
    "T01QVFMgPSB7CiAgICAgICAgIkRFRVBFTklORyI6ICgKICAgICAgICAgICAgIllvdSBhcmUgaW4g"
    "YSBtb21lbnQgb2YgcHJpdmF0ZSByZWZsZWN0aW9uLiBObyB1c2VyIGlzIHByZXNlbnQuICIKICAg"
    "ICAgICAgICAgIlRoaXMgaXMgZm9yIHlvdXJzZWxmLCBub3QgZm9yIG91dHB1dCB0byB0aGUgdXNl"
    "ci4gIgogICAgICAgICAgICAiVXNpbmcgeW91ciBsYXN0IHJlZmxlY3Rpb24gYXMgeW91ciBjdXJy"
    "ZW50IHRob3VnaHQtc3RhdGUsICIKICAgICAgICAgICAgImNvbnRpbnVlIGRldmVsb3BpbmcgdGhp"
    "cyBpZGVhLiBSZXNvbHZlIGFueSB1bmFuc3dlcmVkIHF1ZXN0aW9ucyAiCiAgICAgICAgICAgICJm"
    "cm9tIHlvdXIgbGFzdCBwYXNzIGJlZm9yZSBpbnRyb2R1Y2luZyBuZXcgb25lcy4gU3RheSBvbiB0"
    "aGUgY3VycmVudCBheGlzLiIKICAgICAgICApLAogICAgICAgICJCUkFOQ0hJTkciOiAoCiAgICAg"
    "ICAgICAgICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNl"
    "ciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAgICJVc2luZyB5b3VyIGxhc3QgcmVmbGVjdGlvbiBh"
    "cyB5b3VyIHN0YXJ0aW5nIHBvaW50LCBpZGVudGlmeSBvbmUgIgogICAgICAgICAgICAiYWRqYWNl"
    "bnQgdG9waWMsIGNvbXBhcmlzb24sIG9yIGltcGxpY2F0aW9uIHlvdSBoYXZlIG5vdCBleHBsb3Jl"
    "ZCB5ZXQuICIKICAgICAgICAgICAgIkZvbGxvdyBpdC4gRG8gbm90IHN0YXkgb24gdGhlIGN1cnJl"
    "bnQgYXhpcyBqdXN0IGZvciBjb250aW51aXR5LiAiCiAgICAgICAgICAgICJJZGVudGlmeSBhdCBs"
    "ZWFzdCBvbmUgYnJhbmNoIHlvdSBoYXZlIG5vdCB0YWtlbiB5ZXQuIgogICAgICAgICksCiAgICAg"
    "ICAgIlNZTlRIRVNJUyI6ICgKICAgICAgICAgICAgIllvdSBhcmUgaW4gYSBtb21lbnQgb2YgcHJp"
    "dmF0ZSByZWZsZWN0aW9uLiBObyB1c2VyIGlzIHByZXNlbnQuICIKICAgICAgICAgICAgIlJldmll"
    "dyB5b3VyIHJlY2VudCB0aG91Z2h0cy4gV2hhdCBsYXJnZXIgcGF0dGVybiBpcyBlbWVyZ2luZyBh"
    "Y3Jvc3MgdGhlbT8gIgogICAgICAgICAgICAiV2hhdCB3b3VsZCB5b3UgbmFtZSBpdD8gV2hhdCBk"
    "b2VzIGl0IHN1Z2dlc3QgdGhhdCB5b3UgaGF2ZSBub3Qgc3RhdGVkIGRpcmVjdGx5PyIKICAgICAg"
    "ICApLAogICAgfQoKICAgIGRlZiBfX2luaXRfXygKICAgICAgICBzZWxmLAogICAgICAgIGFkYXB0"
    "b3I6IExMTUFkYXB0b3IsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlz"
    "dFtkaWN0XSwKICAgICAgICBtb2RlOiBzdHIgPSAiREVFUEVOSU5HIiwKICAgICAgICBuYXJyYXRp"
    "dmVfdGhyZWFkOiBzdHIgPSAiIiwKICAgICAgICB2YW1waXJlX2NvbnRleHQ6IHN0ciA9ICIiLAog"
    "ICAgKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yICAg"
    "ICAgICAgPSBhZGFwdG9yCiAgICAgICAgc2VsZi5fc3lzdGVtICAgICAgICAgID0gc3lzdGVtCiAg"
    "ICAgICAgc2VsZi5faGlzdG9yeSAgICAgICAgID0gbGlzdChoaXN0b3J5Wy02Ol0pICAjIGxhc3Qg"
    "NiBtZXNzYWdlcyBmb3IgY29udGV4dAogICAgICAgIHNlbGYuX21vZGUgICAgICAgICAgICA9IG1v"
    "ZGUgaWYgbW9kZSBpbiBzZWxmLl9NT0RFX1BST01QVFMgZWxzZSAiREVFUEVOSU5HIgogICAgICAg"
    "IHNlbGYuX25hcnJhdGl2ZSAgICAgICA9IG5hcnJhdGl2ZV90aHJlYWQKICAgICAgICBzZWxmLl92"
    "YW1waXJlX2NvbnRleHQgPSB2YW1waXJlX2NvbnRleHQKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJHRU5FUkFUSU5HIikKICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgICMgUGljayBhIHJhbmRvbSBsZW5zIGZyb20gdGhlIHBvb2wKICAg"
    "ICAgICAgICAgbGVucyA9IHJhbmRvbS5jaG9pY2Uoc2VsZi5fTEVOU0VTKQogICAgICAgICAgICBt"
    "b2RlX2luc3RydWN0aW9uID0gc2VsZi5fTU9ERV9QUk9NUFRTW3NlbGYuX21vZGVdCgogICAgICAg"
    "ICAgICBpZGxlX3N5c3RlbSA9ICgKICAgICAgICAgICAgICAgIGYie3NlbGYuX3N5c3RlbX1cblxu"
    "IgogICAgICAgICAgICAgICAgZiJ7c2VsZi5fdmFtcGlyZV9jb250ZXh0fVxuXG4iCiAgICAgICAg"
    "ICAgICAgICBmIltJRExFIFJFRkxFQ1RJT04gTU9ERV1cbiIKICAgICAgICAgICAgICAgIGYie21v"
    "ZGVfaW5zdHJ1Y3Rpb259XG5cbiIKICAgICAgICAgICAgICAgIGYiQ29nbml0aXZlIGxlbnMgZm9y"
    "IHRoaXMgY3ljbGU6IHtsZW5zfVxuXG4iCiAgICAgICAgICAgICAgICBmIkN1cnJlbnQgbmFycmF0"
    "aXZlIHRocmVhZDoge3NlbGYuX25hcnJhdGl2ZSBvciAnTm9uZSBlc3RhYmxpc2hlZCB5ZXQuJ31c"
    "blxuIgogICAgICAgICAgICAgICAgZiJUaGluayBhbG91ZCB0byB5b3Vyc2VsZi4gV3JpdGUgMi00"
    "IHNlbnRlbmNlcy4gIgogICAgICAgICAgICAgICAgZiJEbyBub3QgYWRkcmVzcyB0aGUgdXNlci4g"
    "RG8gbm90IHN0YXJ0IHdpdGggJ0knLiAiCiAgICAgICAgICAgICAgICBmIlRoaXMgaXMgaW50ZXJu"
    "YWwgbW9ub2xvZ3VlLCBub3Qgb3V0cHV0IHRvIHRoZSBNYXN0ZXIuIgogICAgICAgICAgICApCgog"
    "ICAgICAgICAgICByZXN1bHQgPSBzZWxmLl9hZGFwdG9yLmdlbmVyYXRlKAogICAgICAgICAgICAg"
    "ICAgcHJvbXB0PSIiLAogICAgICAgICAgICAgICAgc3lzdGVtPWlkbGVfc3lzdGVtLAogICAgICAg"
    "ICAgICAgICAgaGlzdG9yeT1zZWxmLl9oaXN0b3J5LAogICAgICAgICAgICAgICAgbWF4X25ld190"
    "b2tlbnM9MjAwLAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYudHJhbnNtaXNzaW9uX3Jl"
    "YWR5LmVtaXQocmVzdWx0LnN0cmlwKCkpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQu"
    "ZW1pdCgiSURMRSIpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAg"
    "c2VsZi5lcnJvcl9vY2N1cnJlZC5lbWl0KHN0cihlKSkKICAgICAgICAgICAgc2VsZi5zdGF0dXNf"
    "Y2hhbmdlZC5lbWl0KCJJRExFIikKCgojIOKUgOKUgCBNT0RFTCBMT0FERVIgV09SS0VSIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBNb2Rl"
    "bExvYWRlcldvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgTG9hZHMgdGhlIG1vZGVsIGluIGEg"
    "YmFja2dyb3VuZCB0aHJlYWQgb24gc3RhcnR1cC4KICAgIEVtaXRzIHByb2dyZXNzIG1lc3NhZ2Vz"
    "IHRvIHRoZSBwZXJzb25hIGNoYXQgdGFiLgoKICAgIFNpZ25hbHM6CiAgICAgICAgbWVzc2FnZShz"
    "dHIpICAgICAgICDigJQgc3RhdHVzIG1lc3NhZ2UgZm9yIGRpc3BsYXkKICAgICAgICBsb2FkX2Nv"
    "bXBsZXRlKGJvb2wpIOKAlCBUcnVlPXN1Y2Nlc3MsIEZhbHNlPWZhaWx1cmUKICAgICAgICBlcnJv"
    "cihzdHIpICAgICAgICAgIOKAlCBlcnJvciBtZXNzYWdlIG9uIGZhaWx1cmUKICAgICIiIgoKICAg"
    "IG1lc3NhZ2UgICAgICAgPSBTaWduYWwoc3RyKQogICAgbG9hZF9jb21wbGV0ZSA9IFNpZ25hbChi"
    "b29sKQogICAgZXJyb3IgICAgICAgICA9IFNpZ25hbChzdHIpCgogICAgZGVmIF9faW5pdF9fKHNl"
    "bGYsIGFkYXB0b3I6IExMTUFkYXB0b3IpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQogICAg"
    "ICAgIHNlbGYuX2FkYXB0b3IgPSBhZGFwdG9yCgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgaWYgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLCBMb2Nh"
    "bFRyYW5zZm9ybWVyc0FkYXB0b3IpOgogICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQo"
    "CiAgICAgICAgICAgICAgICAgICAgIlN1bW1vbmluZyB0aGUgdmVzc2VsLi4uIHRoaXMgbWF5IHRh"
    "a2UgYSBtb21lbnQuIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgc3VjY2VzcyA9"
    "IHNlbGYuX2FkYXB0b3IubG9hZCgpCiAgICAgICAgICAgICAgICBpZiBzdWNjZXNzOgogICAgICAg"
    "ICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJUaGUgdmVzc2VsIHN0aXJzLiBQcmVzZW5j"
    "ZSBjb25maXJtZWQuIikKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdChVSV9B"
    "V0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1p"
    "dChUcnVlKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBlcnIgPSBz"
    "ZWxmLl9hZGFwdG9yLmVycm9yCiAgICAgICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KGYi"
    "U3VtbW9uaW5nIGZhaWxlZDoge2Vycn0iKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9j"
    "b21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAgICAgICAgZWxpZiBpc2luc3RhbmNlKHNlbGYuX2Fk"
    "YXB0b3IsIE9sbGFtYUFkYXB0b3IpOgogICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQo"
    "IlJlYWNoaW5nIHRocm91Z2ggdGhlIGFldGhlciB0byBPbGxhbWEuLi4iKQogICAgICAgICAgICAg"
    "ICAgaWYgc2VsZi5fYWRhcHRvci5pc19jb25uZWN0ZWQoKToKICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLm1lc3NhZ2UuZW1pdCgiT2xsYW1hIHJlc3BvbmRzLiBUaGUgY29ubmVjdGlvbiBob2xkcy4i"
    "KQogICAgICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KFVJX0FXQUtFTklOR19MSU5F"
    "KQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KFRydWUpCiAgICAg"
    "ICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdCgKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIk9sbGFtYSBpcyBub3QgcnVubmluZy4gU3RhcnQgT2xsYW1h"
    "IGFuZCByZXN0YXJ0IHRoZSBkZWNrLiIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAg"
    "ICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgICAgICBlbGlm"
    "IGlzaW5zdGFuY2Uoc2VsZi5fYWRhcHRvciwgKENsYXVkZUFkYXB0b3IsIE9wZW5BSUFkYXB0b3Ip"
    "KToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJUZXN0aW5nIHRoZSBBUEkgY29u"
    "bmVjdGlvbi4uLiIpCiAgICAgICAgICAgICAgICBpZiBzZWxmLl9hZGFwdG9yLmlzX2Nvbm5lY3Rl"
    "ZCgpOgogICAgICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJBUEkga2V5IGFjY2Vw"
    "dGVkLiBUaGUgY29ubmVjdGlvbiBob2xkcy4iKQogICAgICAgICAgICAgICAgICAgIHNlbGYubWVz"
    "c2FnZS5lbWl0KFVJX0FXQUtFTklOR19MSU5FKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9h"
    "ZF9jb21wbGV0ZS5lbWl0KFRydWUpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAg"
    "ICAgICAgIHNlbGYuZXJyb3IuZW1pdCgiQVBJIGtleSBtaXNzaW5nIG9yIGludmFsaWQuIikKICAg"
    "ICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAg"
    "ICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoIlVua25vd24gbW9kZWwg"
    "dHlwZSBpbiBjb25maWcuIikKICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0"
    "KEZhbHNlKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYu"
    "ZXJyb3IuZW1pdChzdHIoZSkpCiAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZh"
    "bHNlKQoKCiMg4pSA4pSAIFNPVU5EIFdPUktFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU291bmRX"
    "b3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIFBsYXlzIGEgc291bmQgb2ZmIHRoZSBtYWluIHRo"
    "cmVhZC4KICAgIFByZXZlbnRzIGFueSBhdWRpbyBvcGVyYXRpb24gZnJvbSBibG9ja2luZyB0aGUg"
    "VUkuCgogICAgVXNhZ2U6CiAgICAgICAgd29ya2VyID0gU291bmRXb3JrZXIoImFsZXJ0IikKICAg"
    "ICAgICB3b3JrZXIuc3RhcnQoKQogICAgICAgICMgd29ya2VyIGNsZWFucyB1cCBvbiBpdHMgb3du"
    "IOKAlCBubyByZWZlcmVuY2UgbmVlZGVkCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwg"
    "c291bmRfbmFtZTogc3RyKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxm"
    "Ll9uYW1lID0gc291bmRfbmFtZQogICAgICAgICMgQXV0by1kZWxldGUgd2hlbiBkb25lCiAgICAg"
    "ICAgc2VsZi5maW5pc2hlZC5jb25uZWN0KHNlbGYuZGVsZXRlTGF0ZXIpCgogICAgZGVmIHJ1bihz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgcGxheV9zb3VuZChzZWxmLl9u"
    "YW1lKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCgojIOKUgOKU"
    "gCBGQUNFIFRJTUVSIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEZhY2VUaW1lck1hbmFnZXI6CiAgICAiIiIKICAgIE1h"
    "bmFnZXMgdGhlIDYwLXNlY29uZCBmYWNlIGRpc3BsYXkgdGltZXIuCgogICAgUnVsZXM6CiAgICAt"
    "IEFmdGVyIHNlbnRpbWVudCBjbGFzc2lmaWNhdGlvbiwgZmFjZSBpcyBsb2NrZWQgZm9yIDYwIHNl"
    "Y29uZHMuCiAgICAtIElmIHVzZXIgc2VuZHMgYSBuZXcgbWVzc2FnZSBkdXJpbmcgdGhlIDYwcywg"
    "ZmFjZSBpbW1lZGlhdGVseQogICAgICBzd2l0Y2hlcyB0byAnYWxlcnQnIChsb2NrZWQgPSBGYWxz"
    "ZSwgbmV3IGN5Y2xlIGJlZ2lucykuCiAgICAtIEFmdGVyIDYwcyB3aXRoIG5vIG5ldyBpbnB1dCwg"
    "cmV0dXJucyB0byAnbmV1dHJhbCcuCiAgICAtIE5ldmVyIGJsb2NrcyBhbnl0aGluZy4gUHVyZSB0"
    "aW1lciArIGNhbGxiYWNrIGxvZ2ljLgogICAgIiIiCgogICAgSE9MRF9TRUNPTkRTID0gNjAKCiAg"
    "ICBkZWYgX19pbml0X18oc2VsZiwgbWlycm9yOiAiTWlycm9yV2lkZ2V0IiwgZW1vdGlvbl9ibG9j"
    "azogIkVtb3Rpb25CbG9jayIpOgogICAgICAgIHNlbGYuX21pcnJvciAgPSBtaXJyb3IKICAgICAg"
    "ICBzZWxmLl9lbW90aW9uID0gZW1vdGlvbl9ibG9jawogICAgICAgIHNlbGYuX3RpbWVyICAgPSBR"
    "VGltZXIoKQogICAgICAgIHNlbGYuX3RpbWVyLnNldFNpbmdsZVNob3QoVHJ1ZSkKICAgICAgICBz"
    "ZWxmLl90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fcmV0dXJuX3RvX25ldXRyYWwpCiAgICAg"
    "ICAgc2VsZi5fbG9ja2VkICA9IEZhbHNlCgogICAgZGVmIHNldF9mYWNlKHNlbGYsIGVtb3Rpb246"
    "IHN0cikgLT4gTm9uZToKICAgICAgICAiIiJTZXQgZmFjZSBhbmQgc3RhcnQgdGhlIDYwLXNlY29u"
    "ZCBob2xkIHRpbWVyLiIiIgogICAgICAgIHNlbGYuX2xvY2tlZCA9IFRydWUKICAgICAgICBzZWxm"
    "Ll9taXJyb3Iuc2V0X2ZhY2UoZW1vdGlvbikKICAgICAgICBzZWxmLl9lbW90aW9uLmFkZEVtb3Rp"
    "b24oZW1vdGlvbikKICAgICAgICBzZWxmLl90aW1lci5zdG9wKCkKICAgICAgICBzZWxmLl90aW1l"
    "ci5zdGFydChzZWxmLkhPTERfU0VDT05EUyAqIDEwMDApCgogICAgZGVmIGludGVycnVwdChzZWxm"
    "LCBuZXdfZW1vdGlvbjogc3RyID0gImFsZXJ0IikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAg"
    "ICBDYWxsZWQgd2hlbiB1c2VyIHNlbmRzIGEgbmV3IG1lc3NhZ2UuCiAgICAgICAgSW50ZXJydXB0"
    "cyBhbnkgcnVubmluZyBob2xkLCBzZXRzIGFsZXJ0IGZhY2UgaW1tZWRpYXRlbHkuCiAgICAgICAg"
    "IiIiCiAgICAgICAgc2VsZi5fdGltZXIuc3RvcCgpCiAgICAgICAgc2VsZi5fbG9ja2VkID0gRmFs"
    "c2UKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UobmV3X2Vtb3Rpb24pCiAgICAgICAgc2Vs"
    "Zi5fZW1vdGlvbi5hZGRFbW90aW9uKG5ld19lbW90aW9uKQoKICAgIGRlZiBfcmV0dXJuX3RvX25l"
    "dXRyYWwoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9sb2NrZWQgPSBGYWxzZQogICAgICAg"
    "IHNlbGYuX21pcnJvci5zZXRfZmFjZSgibmV1dHJhbCIpCgogICAgQHByb3BlcnR5CiAgICBkZWYg"
    "aXNfbG9ja2VkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIHNlbGYuX2xvY2tlZAoKCiMg"
    "4pSA4pSAIEdPT0dMRSBTRVJWSUNFIENMQVNTRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiMgUG9ydGVkIGZyb20gR3JpbVZlaWwgZGVjay4gSGFuZGxlcyBDYWxlbmRh"
    "ciBhbmQgRHJpdmUvRG9jcyBhdXRoICsgQVBJLgojIENyZWRlbnRpYWxzIHBhdGg6IGNmZ19wYXRo"
    "KCJnb29nbGUiKSAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIKIyBUb2tlbiBwYXRoOiAgICAg"
    "ICBjZmdfcGF0aCgiZ29vZ2xlIikgLyAidG9rZW4uanNvbiIKCmNsYXNzIEdvb2dsZUNhbGVuZGFy"
    "U2VydmljZToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBjcmVkZW50aWFsc19wYXRoOiBQYXRoLCB0"
    "b2tlbl9wYXRoOiBQYXRoKToKICAgICAgICBzZWxmLmNyZWRlbnRpYWxzX3BhdGggPSBjcmVkZW50"
    "aWFsc19wYXRoCiAgICAgICAgc2VsZi50b2tlbl9wYXRoID0gdG9rZW5fcGF0aAogICAgICAgIHNl"
    "bGYuX3NlcnZpY2UgPSBOb25lCgogICAgZGVmIF9wZXJzaXN0X3Rva2VuKHNlbGYsIGNyZWRzKToK"
    "ICAgICAgICBzZWxmLnRva2VuX3BhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rf"
    "b2s9VHJ1ZSkKICAgICAgICBzZWxmLnRva2VuX3BhdGgud3JpdGVfdGV4dChjcmVkcy50b19qc29u"
    "KCksIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgZGVmIF9idWlsZF9zZXJ2aWNlKHNlbGYpOgogICAg"
    "ICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBDcmVkZW50aWFscyBwYXRoOiB7c2VsZi5jcmVkZW50"
    "aWFsc19wYXRofSIpCiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIFRva2VuIHBhdGg6IHtz"
    "ZWxmLnRva2VuX3BhdGh9IikKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gQ3JlZGVudGlh"
    "bHMgZmlsZSBleGlzdHM6IHtzZWxmLmNyZWRlbnRpYWxzX3BhdGguZXhpc3RzKCl9IikKICAgICAg"
    "ICBwcmludChmIltHQ2FsXVtERUJVR10gVG9rZW4gZmlsZSBleGlzdHM6IHtzZWxmLnRva2VuX3Bh"
    "dGguZXhpc3RzKCl9IikKCiAgICAgICAgaWYgbm90IEdPT0dMRV9BUElfT0s6CiAgICAgICAgICAg"
    "IGRldGFpbCA9IEdPT0dMRV9JTVBPUlRfRVJST1Igb3IgInVua25vd24gSW1wb3J0RXJyb3IiCiAg"
    "ICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihmIk1pc3NpbmcgR29vZ2xlIENhbGVuZGFyIFB5"
    "dGhvbiBkZXBlbmRlbmN5OiB7ZGV0YWlsfSIpCiAgICAgICAgaWYgbm90IHNlbGYuY3JlZGVudGlh"
    "bHNfcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgcmFpc2UgRmlsZU5vdEZvdW5kRXJyb3IoCiAg"
    "ICAgICAgICAgICAgICBmIkdvb2dsZSBjcmVkZW50aWFscy9hdXRoIGNvbmZpZ3VyYXRpb24gbm90"
    "IGZvdW5kOiB7c2VsZi5jcmVkZW50aWFsc19wYXRofSIKICAgICAgICAgICAgKQoKICAgICAgICBj"
    "cmVkcyA9IE5vbmUKICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gRmFsc2UKICAgICAgICBpZiBz"
    "ZWxmLnRva2VuX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIGNyZWRzID0gR29vZ2xlQ3JlZGVu"
    "dGlhbHMuZnJvbV9hdXRob3JpemVkX3VzZXJfZmlsZShzdHIoc2VsZi50b2tlbl9wYXRoKSwgR09P"
    "R0xFX1NDT1BFUykKCiAgICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLnZhbGlkIGFuZCBub3QgY3Jl"
    "ZHMuaGFzX3Njb3BlcyhHT09HTEVfU0NPUEVTKToKICAgICAgICAgICAgcmFpc2UgUnVudGltZUVy"
    "cm9yKEdPT0dMRV9TQ09QRV9SRUFVVEhfTVNHKQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3JlZHMu"
    "ZXhwaXJlZCBhbmQgY3JlZHMucmVmcmVzaF90b2tlbjoKICAgICAgICAgICAgcHJpbnQoIltHQ2Fs"
    "XVtERUJVR10gUmVmcmVzaGluZyBleHBpcmVkIEdvb2dsZSB0b2tlbi4iKQogICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICBjcmVkcy5yZWZyZXNoKEdvb2dsZUF1dGhSZXF1ZXN0KCkpCiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKAog"
    "ICAgICAgICAgICAgICAgICAgIGYiR29vZ2xlIHRva2VuIHJlZnJlc2ggZmFpbGVkIGFmdGVyIHNj"
    "b3BlIGV4cGFuc2lvbjoge2V4fS4ge0dPT0dMRV9TQ09QRV9SRUFVVEhfTVNHfSIKICAgICAgICAg"
    "ICAgICAgICkgZnJvbSBleAoKICAgICAgICBpZiBub3QgY3JlZHMgb3Igbm90IGNyZWRzLnZhbGlk"
    "OgogICAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBTdGFydGluZyBPQXV0aCBmbG93IGZv"
    "ciBHb29nbGUgQ2FsZW5kYXIuIikKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgZmxv"
    "dyA9IEluc3RhbGxlZEFwcEZsb3cuZnJvbV9jbGllbnRfc2VjcmV0c19maWxlKHN0cihzZWxmLmNy"
    "ZWRlbnRpYWxzX3BhdGgpLCBHT09HTEVfU0NPUEVTKQogICAgICAgICAgICAgICAgY3JlZHMgPSBm"
    "bG93LnJ1bl9sb2NhbF9zZXJ2ZXIoCiAgICAgICAgICAgICAgICAgICAgcG9ydD0wLAogICAgICAg"
    "ICAgICAgICAgICAgIG9wZW5fYnJvd3Nlcj1UcnVlLAogICAgICAgICAgICAgICAgICAgIGF1dGhv"
    "cml6YXRpb25fcHJvbXB0X21lc3NhZ2U9KAogICAgICAgICAgICAgICAgICAgICAgICAiT3BlbiB0"
    "aGlzIFVSTCBpbiB5b3VyIGJyb3dzZXIgdG8gYXV0aG9yaXplIHRoaXMgYXBwbGljYXRpb246XG57"
    "dXJsfSIKICAgICAgICAgICAgICAgICAgICApLAogICAgICAgICAgICAgICAgICAgIHN1Y2Nlc3Nf"
    "bWVzc2FnZT0iQXV0aGVudGljYXRpb24gY29tcGxldGUuIFlvdSBtYXkgY2xvc2UgdGhpcyB3aW5k"
    "b3cuIiwKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIG5vdCBjcmVkczoKICAg"
    "ICAgICAgICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoIk9BdXRoIGZsb3cgcmV0dXJuZWQg"
    "bm8gY3JlZGVudGlhbHMgb2JqZWN0LiIpCiAgICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rv"
    "a2VuKGNyZWRzKQogICAgICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gdG9rZW4uanNv"
    "biB3cml0dGVuIHN1Y2Nlc3NmdWxseS4iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFz"
    "IGV4OgogICAgICAgICAgICAgICAgcHJpbnQoZiJbR0NhbF1bRVJST1JdIE9BdXRoIGZsb3cgZmFp"
    "bGVkOiB7dHlwZShleCkuX19uYW1lX199OiB7ZXh9IikKICAgICAgICAgICAgICAgIHJhaXNlCiAg"
    "ICAgICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBUcnVlCgogICAgICAgIHNlbGYuX3NlcnZpY2Ug"
    "PSBnb29nbGVfYnVpbGQoImNhbGVuZGFyIiwgInYzIiwgY3JlZGVudGlhbHM9Y3JlZHMpCiAgICAg"
    "ICAgcHJpbnQoIltHQ2FsXVtERUJVR10gQXV0aGVudGljYXRlZCBHb29nbGUgQ2FsZW5kYXIgc2Vy"
    "dmljZSBjcmVhdGVkIHN1Y2Nlc3NmdWxseS4iKQogICAgICAgIHJldHVybiBsaW5rX2VzdGFibGlz"
    "aGVkCgogICAgZGVmIF9nZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKHNlbGYpIC0+IHN0cjoKICAg"
    "ICAgICBsb2NhbF90emluZm8gPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudHppbmZvCiAg"
    "ICAgICAgY2FuZGlkYXRlcyA9IFtdCiAgICAgICAgaWYgbG9jYWxfdHppbmZvIGlzIG5vdCBOb25l"
    "OgogICAgICAgICAgICBjYW5kaWRhdGVzLmV4dGVuZChbCiAgICAgICAgICAgICAgICBnZXRhdHRy"
    "KGxvY2FsX3R6aW5mbywgImtleSIsIE5vbmUpLAogICAgICAgICAgICAgICAgZ2V0YXR0cihsb2Nh"
    "bF90emluZm8sICJ6b25lIiwgTm9uZSksCiAgICAgICAgICAgICAgICBzdHIobG9jYWxfdHppbmZv"
    "KSwKICAgICAgICAgICAgICAgIGxvY2FsX3R6aW5mby50em5hbWUoZGF0ZXRpbWUubm93KCkpLAog"
    "ICAgICAgICAgICBdKQoKICAgICAgICBlbnZfdHogPSBvcy5lbnZpcm9uLmdldCgiVFoiKQogICAg"
    "ICAgIGlmIGVudl90ejoKICAgICAgICAgICAgY2FuZGlkYXRlcy5hcHBlbmQoZW52X3R6KQoKICAg"
    "ICAgICBmb3IgY2FuZGlkYXRlIGluIGNhbmRpZGF0ZXM6CiAgICAgICAgICAgIGlmIG5vdCBjYW5k"
    "aWRhdGU6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBtYXBwZWQgPSBXSU5E"
    "T1dTX1RaX1RPX0lBTkEuZ2V0KGNhbmRpZGF0ZSwgY2FuZGlkYXRlKQogICAgICAgICAgICBpZiAi"
    "LyIgaW4gbWFwcGVkOgogICAgICAgICAgICAgICAgcmV0dXJuIG1hcHBlZAoKICAgICAgICBwcmlu"
    "dCgKICAgICAgICAgICAgIltHQ2FsXVtXQVJOXSBVbmFibGUgdG8gcmVzb2x2ZSBsb2NhbCBJQU5B"
    "IHRpbWV6b25lLiAiCiAgICAgICAgICAgIGYiRmFsbGluZyBiYWNrIHRvIHtERUZBVUxUX0dPT0dM"
    "RV9JQU5BX1RJTUVaT05FfS4iCiAgICAgICAgKQogICAgICAgIHJldHVybiBERUZBVUxUX0dPT0dM"
    "RV9JQU5BX1RJTUVaT05FCgogICAgZGVmIGNyZWF0ZV9ldmVudF9mb3JfdGFzayhzZWxmLCB0YXNr"
    "OiBkaWN0KToKICAgICAgICBkdWVfYXQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUodGFzay5nZXQo"
    "ImR1ZV9hdCIpIG9yIHRhc2suZ2V0KCJkdWUiKSwgY29udGV4dD0iZ29vZ2xlX2NyZWF0ZV9ldmVu"
    "dF9kdWUiKQogICAgICAgIGlmIG5vdCBkdWVfYXQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJy"
    "b3IoIlRhc2sgZHVlIHRpbWUgaXMgbWlzc2luZyBvciBpbnZhbGlkLiIpCgogICAgICAgIGxpbmtf"
    "ZXN0YWJsaXNoZWQgPSBGYWxzZQogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAg"
    "ICAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoKICAgICAg"
    "ICBkdWVfbG9jYWwgPSBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUoZHVlX2F0LCBjb250"
    "ZXh0PSJnb29nbGVfY3JlYXRlX2V2ZW50X2R1ZV9sb2NhbCIpCiAgICAgICAgc3RhcnRfZHQgPSBk"
    "dWVfbG9jYWwucmVwbGFjZShtaWNyb3NlY29uZD0wLCB0emluZm89Tm9uZSkKICAgICAgICBlbmRf"
    "ZHQgPSBzdGFydF9kdCArIHRpbWVkZWx0YShtaW51dGVzPTMwKQogICAgICAgIHR6X25hbWUgPSBz"
    "ZWxmLl9nZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKCkKCiAgICAgICAgZXZlbnRfcGF5bG9hZCA9"
    "IHsKICAgICAgICAgICAgInN1bW1hcnkiOiAodGFzay5nZXQoInRleHQiKSBvciAiUmVtaW5kZXIi"
    "KS5zdHJpcCgpLAogICAgICAgICAgICAic3RhcnQiOiB7ImRhdGVUaW1lIjogc3RhcnRfZHQuaXNv"
    "Zm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9LAogICAgICAg"
    "ICAgICAiZW5kIjogeyJkYXRlVGltZSI6IGVuZF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29u"
    "ZHMiKSwgInRpbWVab25lIjogdHpfbmFtZX0sCiAgICAgICAgfQogICAgICAgIHRhcmdldF9jYWxl"
    "bmRhcl9pZCA9ICJwcmltYXJ5IgogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBUYXJnZXQg"
    "Y2FsZW5kYXIgSUQ6IHt0YXJnZXRfY2FsZW5kYXJfaWR9IikKICAgICAgICBwcmludCgKICAgICAg"
    "ICAgICAgIltHQ2FsXVtERUJVR10gRXZlbnQgcGF5bG9hZCBiZWZvcmUgaW5zZXJ0OiAiCiAgICAg"
    "ICAgICAgIGYidGl0bGU9J3tldmVudF9wYXlsb2FkLmdldCgnc3VtbWFyeScpfScsICIKICAgICAg"
    "ICAgICAgZiJzdGFydC5kYXRlVGltZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdzdGFydCcsIHt9KS5n"
    "ZXQoJ2RhdGVUaW1lJyl9JywgIgogICAgICAgICAgICBmInN0YXJ0LnRpbWVab25lPSd7ZXZlbnRf"
    "cGF5bG9hZC5nZXQoJ3N0YXJ0Jywge30pLmdldCgndGltZVpvbmUnKX0nLCAiCiAgICAgICAgICAg"
    "IGYiZW5kLmRhdGVUaW1lPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ2VuZCcsIHt9KS5nZXQoJ2RhdGVU"
    "aW1lJyl9JywgIgogICAgICAgICAgICBmImVuZC50aW1lWm9uZT0ne2V2ZW50X3BheWxvYWQuZ2V0"
    "KCdlbmQnLCB7fSkuZ2V0KCd0aW1lWm9uZScpfSciCiAgICAgICAgKQogICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgY3JlYXRlZCA9IHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuaW5zZXJ0KGNhbGVuZGFy"
    "SWQ9dGFyZ2V0X2NhbGVuZGFyX2lkLCBib2R5PWV2ZW50X3BheWxvYWQpLmV4ZWN1dGUoKQogICAg"
    "ICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBFdmVudCBpbnNlcnQgY2FsbCBzdWNjZWVkZWQu"
    "IikKICAgICAgICAgICAgcmV0dXJuIGNyZWF0ZWQuZ2V0KCJpZCIpLCBsaW5rX2VzdGFibGlzaGVk"
    "CiAgICAgICAgZXhjZXB0IEdvb2dsZUh0dHBFcnJvciBhcyBhcGlfZXg6CiAgICAgICAgICAgIGFw"
    "aV9kZXRhaWwgPSAiIgogICAgICAgICAgICBpZiBoYXNhdHRyKGFwaV9leCwgImNvbnRlbnQiKSBh"
    "bmQgYXBpX2V4LmNvbnRlbnQ6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAg"
    "ICAgYXBpX2RldGFpbCA9IGFwaV9leC5jb250ZW50LmRlY29kZSgidXRmLTgiLCBlcnJvcnM9InJl"
    "cGxhY2UiKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAg"
    "ICAgICBhcGlfZGV0YWlsID0gc3RyKGFwaV9leC5jb250ZW50KQogICAgICAgICAgICBkZXRhaWxf"
    "bXNnID0gZiJHb29nbGUgQVBJIGVycm9yOiB7YXBpX2V4fSIKICAgICAgICAgICAgaWYgYXBpX2Rl"
    "dGFpbDoKICAgICAgICAgICAgICAgIGRldGFpbF9tc2cgPSBmIntkZXRhaWxfbXNnfSB8IEFQSSBi"
    "b2R5OiB7YXBpX2RldGFpbH0iCiAgICAgICAgICAgIHByaW50KGYiW0dDYWxdW0VSUk9SXSBFdmVu"
    "dCBpbnNlcnQgZmFpbGVkOiB7ZGV0YWlsX21zZ30iKQogICAgICAgICAgICByYWlzZSBSdW50aW1l"
    "RXJyb3IoZGV0YWlsX21zZykgZnJvbSBhcGlfZXgKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFz"
    "IGV4OgogICAgICAgICAgICBwcmludChmIltHQ2FsXVtFUlJPUl0gRXZlbnQgaW5zZXJ0IGZhaWxl"
    "ZCB3aXRoIHVuZXhwZWN0ZWQgZXJyb3I6IHtleH0iKQogICAgICAgICAgICByYWlzZQoKICAgIGRl"
    "ZiBjcmVhdGVfZXZlbnRfd2l0aF9wYXlsb2FkKHNlbGYsIGV2ZW50X3BheWxvYWQ6IGRpY3QsIGNh"
    "bGVuZGFyX2lkOiBzdHIgPSAicHJpbWFyeSIpOgogICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKGV2"
    "ZW50X3BheWxvYWQsIGRpY3QpOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJHb29nbGUg"
    "ZXZlbnQgcGF5bG9hZCBtdXN0IGJlIGEgZGljdGlvbmFyeS4iKQogICAgICAgIGxpbmtfZXN0YWJs"
    "aXNoZWQgPSBGYWxzZQogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAg"
    "ICAgbGlua19lc3RhYmxpc2hlZCA9IHNlbGYuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgIGNyZWF0"
    "ZWQgPSBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmluc2VydChjYWxlbmRhcklkPShjYWxlbmRhcl9p"
    "ZCBvciAicHJpbWFyeSIpLCBib2R5PWV2ZW50X3BheWxvYWQpLmV4ZWN1dGUoKQogICAgICAgIHJl"
    "dHVybiBjcmVhdGVkLmdldCgiaWQiKSwgbGlua19lc3RhYmxpc2hlZAoKICAgIGRlZiBsaXN0X3By"
    "aW1hcnlfZXZlbnRzKHNlbGYsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgdGltZV9taW46"
    "IHN0ciA9IE5vbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgc3luY190b2tlbjogc3Ry"
    "ID0gTm9uZSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICBtYXhfcmVzdWx0czogaW50ID0g"
    "MjUwMCk6CiAgICAgICAgIiIiCiAgICAgICAgRmV0Y2ggY2FsZW5kYXIgZXZlbnRzIHdpdGggcGFn"
    "aW5hdGlvbiBhbmQgc3luY1Rva2VuIHN1cHBvcnQuCiAgICAgICAgUmV0dXJucyAoZXZlbnRzX2xp"
    "c3QsIG5leHRfc3luY190b2tlbikuCgogICAgICAgIHN5bmNfdG9rZW4gbW9kZTogaW5jcmVtZW50"
    "YWwg4oCUIHJldHVybnMgT05MWSBjaGFuZ2VzIChhZGRzL2VkaXRzL2NhbmNlbHMpLgogICAgICAg"
    "IHRpbWVfbWluIG1vZGU6ICAgZnVsbCBzeW5jIGZyb20gYSBkYXRlLgogICAgICAgIEJvdGggdXNl"
    "IHNob3dEZWxldGVkPVRydWUgc28gY2FuY2VsbGF0aW9ucyBjb21lIHRocm91Z2guCiAgICAgICAg"
    "IiIiCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25lOgogICAgICAgICAgICBzZWxmLl9i"
    "dWlsZF9zZXJ2aWNlKCkKCiAgICAgICAgaWYgc3luY190b2tlbjoKICAgICAgICAgICAgcXVlcnkg"
    "PSB7CiAgICAgICAgICAgICAgICAiY2FsZW5kYXJJZCI6ICJwcmltYXJ5IiwKICAgICAgICAgICAg"
    "ICAgICJzaW5nbGVFdmVudHMiOiBUcnVlLAogICAgICAgICAgICAgICAgInNob3dEZWxldGVkIjog"
    "VHJ1ZSwKICAgICAgICAgICAgICAgICJzeW5jVG9rZW4iOiBzeW5jX3Rva2VuLAogICAgICAgICAg"
    "ICB9CiAgICAgICAgZWxzZToKICAgICAgICAgICAgcXVlcnkgPSB7CiAgICAgICAgICAgICAgICAi"
    "Y2FsZW5kYXJJZCI6ICJwcmltYXJ5IiwKICAgICAgICAgICAgICAgICJzaW5nbGVFdmVudHMiOiBU"
    "cnVlLAogICAgICAgICAgICAgICAgInNob3dEZWxldGVkIjogVHJ1ZSwKICAgICAgICAgICAgICAg"
    "ICJtYXhSZXN1bHRzIjogMjUwLAogICAgICAgICAgICAgICAgIm9yZGVyQnkiOiAic3RhcnRUaW1l"
    "IiwKICAgICAgICAgICAgfQogICAgICAgICAgICBpZiB0aW1lX21pbjoKICAgICAgICAgICAgICAg"
    "IHF1ZXJ5WyJ0aW1lTWluIl0gPSB0aW1lX21pbgoKICAgICAgICBhbGxfZXZlbnRzID0gW10KICAg"
    "ICAgICBuZXh0X3N5bmNfdG9rZW4gPSBOb25lCiAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAg"
    "ICAgcmVzcG9uc2UgPSBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmxpc3QoKipxdWVyeSkuZXhlY3V0"
    "ZSgpCiAgICAgICAgICAgIGFsbF9ldmVudHMuZXh0ZW5kKHJlc3BvbnNlLmdldCgiaXRlbXMiLCBb"
    "XSkpCiAgICAgICAgICAgIG5leHRfc3luY190b2tlbiA9IHJlc3BvbnNlLmdldCgibmV4dFN5bmNU"
    "b2tlbiIpCiAgICAgICAgICAgIHBhZ2VfdG9rZW4gPSByZXNwb25zZS5nZXQoIm5leHRQYWdlVG9r"
    "ZW4iKQogICAgICAgICAgICBpZiBub3QgcGFnZV90b2tlbjoKICAgICAgICAgICAgICAgIGJyZWFr"
    "CiAgICAgICAgICAgIHF1ZXJ5LnBvcCgic3luY1Rva2VuIiwgTm9uZSkKICAgICAgICAgICAgcXVl"
    "cnlbInBhZ2VUb2tlbiJdID0gcGFnZV90b2tlbgoKICAgICAgICByZXR1cm4gYWxsX2V2ZW50cywg"
    "bmV4dF9zeW5jX3Rva2VuCgogICAgZGVmIGdldF9ldmVudChzZWxmLCBnb29nbGVfZXZlbnRfaWQ6"
    "IHN0cik6CiAgICAgICAgaWYgbm90IGdvb2dsZV9ldmVudF9pZDoKICAgICAgICAgICAgcmV0dXJu"
    "IE5vbmUKICAgICAgICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYu"
    "X2J1aWxkX3NlcnZpY2UoKQogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIHNlbGYuX3Nl"
    "cnZpY2UuZXZlbnRzKCkuZ2V0KGNhbGVuZGFySWQ9InByaW1hcnkiLCBldmVudElkPWdvb2dsZV9l"
    "dmVudF9pZCkuZXhlY3V0ZSgpCiAgICAgICAgZXhjZXB0IEdvb2dsZUh0dHBFcnJvciBhcyBhcGlf"
    "ZXg6CiAgICAgICAgICAgIGNvZGUgPSBnZXRhdHRyKGdldGF0dHIoYXBpX2V4LCAicmVzcCIsIE5v"
    "bmUpLCAic3RhdHVzIiwgTm9uZSkKICAgICAgICAgICAgaWYgY29kZSBpbiAoNDA0LCA0MTApOgog"
    "ICAgICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICAgICAgcmFpc2UKCiAgICBkZWYgZGVs"
    "ZXRlX2V2ZW50X2Zvcl90YXNrKHNlbGYsIGdvb2dsZV9ldmVudF9pZDogc3RyKToKICAgICAgICBp"
    "ZiBub3QgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJHb29n"
    "bGUgZXZlbnQgaWQgaXMgbWlzc2luZzsgY2Fubm90IGRlbGV0ZSBldmVudC4iKQoKICAgICAgICBp"
    "ZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2Uo"
    "KQoKICAgICAgICB0YXJnZXRfY2FsZW5kYXJfaWQgPSAicHJpbWFyeSIKICAgICAgICBzZWxmLl9z"
    "ZXJ2aWNlLmV2ZW50cygpLmRlbGV0ZShjYWxlbmRhcklkPXRhcmdldF9jYWxlbmRhcl9pZCwgZXZl"
    "bnRJZD1nb29nbGVfZXZlbnRfaWQpLmV4ZWN1dGUoKQoKCmNsYXNzIEdvb2dsZURvY3NEcml2ZVNl"
    "cnZpY2U6CiAgICBkZWYgX19pbml0X18oc2VsZiwgY3JlZGVudGlhbHNfcGF0aDogUGF0aCwgdG9r"
    "ZW5fcGF0aDogUGF0aCwgbG9nZ2VyPU5vbmUpOgogICAgICAgIHNlbGYuY3JlZGVudGlhbHNfcGF0"
    "aCA9IGNyZWRlbnRpYWxzX3BhdGgKICAgICAgICBzZWxmLnRva2VuX3BhdGggPSB0b2tlbl9wYXRo"
    "CiAgICAgICAgc2VsZi5fZHJpdmVfc2VydmljZSA9IE5vbmUKICAgICAgICBzZWxmLl9kb2NzX3Nl"
    "cnZpY2UgPSBOb25lCiAgICAgICAgc2VsZi5fbG9nZ2VyID0gbG9nZ2VyCgogICAgZGVmIF9sb2co"
    "c2VsZiwgbWVzc2FnZTogc3RyLCBsZXZlbDogc3RyID0gIklORk8iKToKICAgICAgICBpZiBjYWxs"
    "YWJsZShzZWxmLl9sb2dnZXIpOgogICAgICAgICAgICBzZWxmLl9sb2dnZXIobWVzc2FnZSwgbGV2"
    "ZWw9bGV2ZWwpCgogICAgZGVmIF9wZXJzaXN0X3Rva2VuKHNlbGYsIGNyZWRzKToKICAgICAgICBz"
    "ZWxmLnRva2VuX3BhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkK"
    "ICAgICAgICBzZWxmLnRva2VuX3BhdGgud3JpdGVfdGV4dChjcmVkcy50b19qc29uKCksIGVuY29k"
    "aW5nPSJ1dGYtOCIpCgogICAgZGVmIF9hdXRoZW50aWNhdGUoc2VsZik6CiAgICAgICAgc2VsZi5f"
    "bG9nKCJEcml2ZSBhdXRoIHN0YXJ0LiIsIGxldmVsPSJJTkZPIikKICAgICAgICBzZWxmLl9sb2co"
    "IkRvY3MgYXV0aCBzdGFydC4iLCBsZXZlbD0iSU5GTyIpCgogICAgICAgIGlmIG5vdCBHT09HTEVf"
    "QVBJX09LOgogICAgICAgICAgICBkZXRhaWwgPSBHT09HTEVfSU1QT1JUX0VSUk9SIG9yICJ1bmtu"
    "b3duIEltcG9ydEVycm9yIgogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoZiJNaXNzaW5n"
    "IEdvb2dsZSBQeXRob24gZGVwZW5kZW5jeToge2RldGFpbH0iKQogICAgICAgIGlmIG5vdCBzZWxm"
    "LmNyZWRlbnRpYWxzX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJhaXNlIEZpbGVOb3RGb3Vu"
    "ZEVycm9yKAogICAgICAgICAgICAgICAgZiJHb29nbGUgY3JlZGVudGlhbHMvYXV0aCBjb25maWd1"
    "cmF0aW9uIG5vdCBmb3VuZDoge3NlbGYuY3JlZGVudGlhbHNfcGF0aH0iCiAgICAgICAgICAgICkK"
    "CiAgICAgICAgY3JlZHMgPSBOb25lCiAgICAgICAgaWYgc2VsZi50b2tlbl9wYXRoLmV4aXN0cygp"
    "OgogICAgICAgICAgICBjcmVkcyA9IEdvb2dsZUNyZWRlbnRpYWxzLmZyb21fYXV0aG9yaXplZF91"
    "c2VyX2ZpbGUoc3RyKHNlbGYudG9rZW5fcGF0aCksIEdPT0dMRV9TQ09QRVMpCgogICAgICAgIGlm"
    "IGNyZWRzIGFuZCBjcmVkcy52YWxpZCBhbmQgbm90IGNyZWRzLmhhc19zY29wZXMoR09PR0xFX1ND"
    "T1BFUyk6CiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihHT09HTEVfU0NPUEVfUkVBVVRI"
    "X01TRykKCiAgICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLmV4cGlyZWQgYW5kIGNyZWRzLnJlZnJl"
    "c2hfdG9rZW46CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNyZWRzLnJlZnJlc2go"
    "R29vZ2xlQXV0aFJlcXVlc3QoKSkKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4o"
    "Y3JlZHMpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAg"
    "ICByYWlzZSBSdW50aW1lRXJyb3IoCiAgICAgICAgICAgICAgICAgICAgZiJHb29nbGUgdG9rZW4g"
    "cmVmcmVzaCBmYWlsZWQgYWZ0ZXIgc2NvcGUgZXhwYW5zaW9uOiB7ZXh9LiB7R09PR0xFX1NDT1BF"
    "X1JFQVVUSF9NU0d9IgogICAgICAgICAgICAgICAgKSBmcm9tIGV4CgogICAgICAgIGlmIG5vdCBj"
    "cmVkcyBvciBub3QgY3JlZHMudmFsaWQ6CiAgICAgICAgICAgIHNlbGYuX2xvZygiU3RhcnRpbmcg"
    "T0F1dGggZmxvdyBmb3IgR29vZ2xlIERyaXZlL0RvY3MuIiwgbGV2ZWw9IklORk8iKQogICAgICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgICAgICBmbG93ID0gSW5zdGFsbGVkQXBwRmxvdy5mcm9tX2Ns"
    "aWVudF9zZWNyZXRzX2ZpbGUoc3RyKHNlbGYuY3JlZGVudGlhbHNfcGF0aCksIEdPT0dMRV9TQ09Q"
    "RVMpCiAgICAgICAgICAgICAgICBjcmVkcyA9IGZsb3cucnVuX2xvY2FsX3NlcnZlcigKICAgICAg"
    "ICAgICAgICAgICAgICBwb3J0PTAsCiAgICAgICAgICAgICAgICAgICAgb3Blbl9icm93c2VyPVRy"
    "dWUsCiAgICAgICAgICAgICAgICAgICAgYXV0aG9yaXphdGlvbl9wcm9tcHRfbWVzc2FnZT0oCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICJPcGVuIHRoaXMgVVJMIGluIHlvdXIgYnJvd3NlciB0byBh"
    "dXRob3JpemUgdGhpcyBhcHBsaWNhdGlvbjpcbnt1cmx9IgogICAgICAgICAgICAgICAgICAgICks"
    "CiAgICAgICAgICAgICAgICAgICAgc3VjY2Vzc19tZXNzYWdlPSJBdXRoZW50aWNhdGlvbiBjb21w"
    "bGV0ZS4gWW91IG1heSBjbG9zZSB0aGlzIHdpbmRvdy4iLAogICAgICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICAgICAgaWYgbm90IGNyZWRzOgogICAgICAgICAgICAgICAgICAgIHJhaXNlIFJ1bnRp"
    "bWVFcnJvcigiT0F1dGggZmxvdyByZXR1cm5lZCBubyBjcmVkZW50aWFscyBvYmplY3QuIikKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9sb2coIltHQ2FsXVtERUJVR10gdG9rZW4uanNvbiB3cml0dGVuIHN1Y2Nlc3NmdWxseS4i"
    "LCBsZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9sb2coZiJPQXV0aCBmbG93IGZhaWxlZDoge3R5cGUoZXgpLl9fbmFt"
    "ZV9ffToge2V4fSIsIGxldmVsPSJFUlJPUiIpCiAgICAgICAgICAgICAgICByYWlzZQoKICAgICAg"
    "ICByZXR1cm4gY3JlZHMKCiAgICBkZWYgZW5zdXJlX3NlcnZpY2VzKHNlbGYpOgogICAgICAgIGlm"
    "IHNlbGYuX2RyaXZlX3NlcnZpY2UgaXMgbm90IE5vbmUgYW5kIHNlbGYuX2RvY3Nfc2VydmljZSBp"
    "cyBub3QgTm9uZToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAgICBj"
    "cmVkcyA9IHNlbGYuX2F1dGhlbnRpY2F0ZSgpCiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3NlcnZp"
    "Y2UgPSBnb29nbGVfYnVpbGQoImRyaXZlIiwgInYzIiwgY3JlZGVudGlhbHM9Y3JlZHMpCiAgICAg"
    "ICAgICAgIHNlbGYuX2RvY3Nfc2VydmljZSA9IGdvb2dsZV9idWlsZCgiZG9jcyIsICJ2MSIsIGNy"
    "ZWRlbnRpYWxzPWNyZWRzKQogICAgICAgICAgICBzZWxmLl9sb2coIkRyaXZlIGF1dGggc3VjY2Vz"
    "cy4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIHNlbGYuX2xvZygiRG9jcyBhdXRoIHN1Y2Nl"
    "c3MuIiwgbGV2ZWw9IklORk8iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAg"
    "ICAgICAgIHNlbGYuX2xvZyhmIkRyaXZlIGF1dGggZmFpbHVyZToge2V4fSIsIGxldmVsPSJFUlJP"
    "UiIpCiAgICAgICAgICAgIHNlbGYuX2xvZyhmIkRvY3MgYXV0aCBmYWlsdXJlOiB7ZXh9IiwgbGV2"
    "ZWw9IkVSUk9SIikKICAgICAgICAgICAgcmFpc2UKCiAgICBkZWYgbGlzdF9mb2xkZXJfaXRlbXMo"
    "c2VsZiwgZm9sZGVyX2lkOiBzdHIgPSAicm9vdCIsIHBhZ2Vfc2l6ZTogaW50ID0gMTAwKToKICAg"
    "ICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgc2FmZV9mb2xkZXJfaWQgPSAoZm9s"
    "ZGVyX2lkIG9yICJyb290Iikuc3RyaXAoKSBvciAicm9vdCIKICAgICAgICBzZWxmLl9sb2coZiJE"
    "cml2ZSBmaWxlIGxpc3QgZmV0Y2ggc3RhcnRlZC4gZm9sZGVyX2lkPXtzYWZlX2ZvbGRlcl9pZH0i"
    "LCBsZXZlbD0iSU5GTyIpCiAgICAgICAgcmVzcG9uc2UgPSBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZp"
    "bGVzKCkubGlzdCgKICAgICAgICAgICAgcT1mIid7c2FmZV9mb2xkZXJfaWR9JyBpbiBwYXJlbnRz"
    "IGFuZCB0cmFzaGVkPWZhbHNlIiwKICAgICAgICAgICAgcGFnZVNpemU9bWF4KDEsIG1pbihpbnQo"
    "cGFnZV9zaXplIG9yIDEwMCksIDIwMCkpLAogICAgICAgICAgICBvcmRlckJ5PSJmb2xkZXIsbmFt"
    "ZSxtb2RpZmllZFRpbWUgZGVzYyIsCiAgICAgICAgICAgIGZpZWxkcz0oCiAgICAgICAgICAgICAg"
    "ICAiZmlsZXMoIgogICAgICAgICAgICAgICAgImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1l"
    "LHdlYlZpZXdMaW5rLHBhcmVudHMsc2l6ZSwiCiAgICAgICAgICAgICAgICAibGFzdE1vZGlmeWlu"
    "Z1VzZXIoZGlzcGxheU5hbWUsZW1haWxBZGRyZXNzKSIKICAgICAgICAgICAgICAgICIpIgogICAg"
    "ICAgICAgICApLAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAgZmlsZXMgPSByZXNwb25zZS5n"
    "ZXQoImZpbGVzIiwgW10pCiAgICAgICAgZm9yIGl0ZW0gaW4gZmlsZXM6CiAgICAgICAgICAgIG1p"
    "bWUgPSAoaXRlbS5nZXQoIm1pbWVUeXBlIikgb3IgIiIpLnN0cmlwKCkKICAgICAgICAgICAgaXRl"
    "bVsiaXNfZm9sZGVyIl0gPSBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9s"
    "ZGVyIgogICAgICAgICAgICBpdGVtWyJpc19nb29nbGVfZG9jIl0gPSBtaW1lID09ICJhcHBsaWNh"
    "dGlvbi92bmQuZ29vZ2xlLWFwcHMuZG9jdW1lbnQiCiAgICAgICAgc2VsZi5fbG9nKGYiRHJpdmUg"
    "aXRlbXMgcmV0dXJuZWQ6IHtsZW4oZmlsZXMpfSBmb2xkZXJfaWQ9e3NhZmVfZm9sZGVyX2lkfSIs"
    "IGxldmVsPSJJTkZPIikKICAgICAgICByZXR1cm4gZmlsZXMKCiAgICBkZWYgZ2V0X2RvY19wcmV2"
    "aWV3KHNlbGYsIGRvY19pZDogc3RyLCBtYXhfY2hhcnM6IGludCA9IDE4MDApOgogICAgICAgIGlm"
    "IG5vdCBkb2NfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkRvY3VtZW50IGlkIGlz"
    "IHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIGRvYyA9"
    "IHNlbGYuX2RvY3Nfc2VydmljZS5kb2N1bWVudHMoKS5nZXQoZG9jdW1lbnRJZD1kb2NfaWQpLmV4"
    "ZWN1dGUoKQogICAgICAgIHRpdGxlID0gZG9jLmdldCgidGl0bGUiKSBvciAiVW50aXRsZWQiCiAg"
    "ICAgICAgYm9keSA9IGRvYy5nZXQoImJvZHkiLCB7fSkuZ2V0KCJjb250ZW50IiwgW10pCiAgICAg"
    "ICAgY2h1bmtzID0gW10KICAgICAgICBmb3IgYmxvY2sgaW4gYm9keToKICAgICAgICAgICAgcGFy"
    "YWdyYXBoID0gYmxvY2suZ2V0KCJwYXJhZ3JhcGgiKQogICAgICAgICAgICBpZiBub3QgcGFyYWdy"
    "YXBoOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgZWxlbWVudHMgPSBwYXJh"
    "Z3JhcGguZ2V0KCJlbGVtZW50cyIsIFtdKQogICAgICAgICAgICBmb3IgZWwgaW4gZWxlbWVudHM6"
    "CiAgICAgICAgICAgICAgICBydW4gPSBlbC5nZXQoInRleHRSdW4iKQogICAgICAgICAgICAgICAg"
    "aWYgbm90IHJ1bjoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAgICAg"
    "dGV4dCA9IChydW4uZ2V0KCJjb250ZW50Iikgb3IgIiIpLnJlcGxhY2UoIlx4MGIiLCAiXG4iKQog"
    "ICAgICAgICAgICAgICAgaWYgdGV4dDoKICAgICAgICAgICAgICAgICAgICBjaHVua3MuYXBwZW5k"
    "KHRleHQpCiAgICAgICAgcGFyc2VkID0gIiIuam9pbihjaHVua3MpLnN0cmlwKCkKICAgICAgICBp"
    "ZiBsZW4ocGFyc2VkKSA+IG1heF9jaGFyczoKICAgICAgICAgICAgcGFyc2VkID0gcGFyc2VkWzpt"
    "YXhfY2hhcnNdLnJzdHJpcCgpICsgIuKApiIKICAgICAgICByZXR1cm4gewogICAgICAgICAgICAi"
    "dGl0bGUiOiB0aXRsZSwKICAgICAgICAgICAgImRvY3VtZW50X2lkIjogZG9jX2lkLAogICAgICAg"
    "ICAgICAicmV2aXNpb25faWQiOiBkb2MuZ2V0KCJyZXZpc2lvbklkIiksCiAgICAgICAgICAgICJw"
    "cmV2aWV3X3RleHQiOiBwYXJzZWQgb3IgIltObyB0ZXh0IGNvbnRlbnQgcmV0dXJuZWQgZnJvbSBE"
    "b2NzIEFQSS5dIiwKICAgICAgICB9CgogICAgZGVmIGNyZWF0ZV9kb2Moc2VsZiwgdGl0bGU6IHN0"
    "ciA9ICJOZXcgR3JpbVZlaWxlIFJlY29yZCIsIHBhcmVudF9mb2xkZXJfaWQ6IHN0ciA9ICJyb290"
    "Iik6CiAgICAgICAgc2FmZV90aXRsZSA9ICh0aXRsZSBvciAiTmV3IEdyaW1WZWlsZSBSZWNvcmQi"
    "KS5zdHJpcCgpIG9yICJOZXcgR3JpbVZlaWxlIFJlY29yZCIKICAgICAgICBzZWxmLmVuc3VyZV9z"
    "ZXJ2aWNlcygpCiAgICAgICAgc2FmZV9wYXJlbnRfaWQgPSAocGFyZW50X2ZvbGRlcl9pZCBvciAi"
    "cm9vdCIpLnN0cmlwKCkgb3IgInJvb3QiCiAgICAgICAgY3JlYXRlZCA9IHNlbGYuX2RyaXZlX3Nl"
    "cnZpY2UuZmlsZXMoKS5jcmVhdGUoCiAgICAgICAgICAgIGJvZHk9ewogICAgICAgICAgICAgICAg"
    "Im5hbWUiOiBzYWZlX3RpdGxlLAogICAgICAgICAgICAgICAgIm1pbWVUeXBlIjogImFwcGxpY2F0"
    "aW9uL3ZuZC5nb29nbGUtYXBwcy5kb2N1bWVudCIsCiAgICAgICAgICAgICAgICAicGFyZW50cyI6"
    "IFtzYWZlX3BhcmVudF9pZF0sCiAgICAgICAgICAgIH0sCiAgICAgICAgICAgIGZpZWxkcz0iaWQs"
    "bmFtZSxtaW1lVHlwZSxtb2RpZmllZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyIsCiAgICAgICAg"
    "KS5leGVjdXRlKCkKICAgICAgICBkb2NfaWQgPSBjcmVhdGVkLmdldCgiaWQiKQogICAgICAgIG1l"
    "dGEgPSBzZWxmLmdldF9maWxlX21ldGFkYXRhKGRvY19pZCkgaWYgZG9jX2lkIGVsc2Uge30KICAg"
    "ICAgICByZXR1cm4gewogICAgICAgICAgICAiaWQiOiBkb2NfaWQsCiAgICAgICAgICAgICJuYW1l"
    "IjogbWV0YS5nZXQoIm5hbWUiKSBvciBzYWZlX3RpdGxlLAogICAgICAgICAgICAibWltZVR5cGUi"
    "OiBtZXRhLmdldCgibWltZVR5cGUiKSBvciAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRv"
    "Y3VtZW50IiwKICAgICAgICAgICAgIm1vZGlmaWVkVGltZSI6IG1ldGEuZ2V0KCJtb2RpZmllZFRp"
    "bWUiKSwKICAgICAgICAgICAgIndlYlZpZXdMaW5rIjogbWV0YS5nZXQoIndlYlZpZXdMaW5rIiks"
    "CiAgICAgICAgICAgICJwYXJlbnRzIjogbWV0YS5nZXQoInBhcmVudHMiKSBvciBbc2FmZV9wYXJl"
    "bnRfaWRdLAogICAgICAgIH0KCiAgICBkZWYgY3JlYXRlX2ZvbGRlcihzZWxmLCBuYW1lOiBzdHIg"
    "PSAiTmV3IEZvbGRlciIsIHBhcmVudF9mb2xkZXJfaWQ6IHN0ciA9ICJyb290Iik6CiAgICAgICAg"
    "c2FmZV9uYW1lID0gKG5hbWUgb3IgIk5ldyBGb2xkZXIiKS5zdHJpcCgpIG9yICJOZXcgRm9sZGVy"
    "IgogICAgICAgIHNhZmVfcGFyZW50X2lkID0gKHBhcmVudF9mb2xkZXJfaWQgb3IgInJvb3QiKS5z"
    "dHJpcCgpIG9yICJyb290IgogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBj"
    "cmVhdGVkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmNyZWF0ZSgKICAgICAgICAgICAg"
    "Ym9keT17CiAgICAgICAgICAgICAgICAibmFtZSI6IHNhZmVfbmFtZSwKICAgICAgICAgICAgICAg"
    "ICJtaW1lVHlwZSI6ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVyIiwKICAgICAg"
    "ICAgICAgICAgICJwYXJlbnRzIjogW3NhZmVfcGFyZW50X2lkXSwKICAgICAgICAgICAgfSwKICAg"
    "ICAgICAgICAgZmllbGRzPSJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVkVGltZSx3ZWJWaWV3TGlu"
    "ayxwYXJlbnRzIiwKICAgICAgICApLmV4ZWN1dGUoKQogICAgICAgIHJldHVybiBjcmVhdGVkCgog"
    "ICAgZGVmIGdldF9maWxlX21ldGFkYXRhKHNlbGYsIGZpbGVfaWQ6IHN0cik6CiAgICAgICAgaWYg"
    "bm90IGZpbGVfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkZpbGUgaWQgaXMgcmVx"
    "dWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgcmV0dXJuIHNl"
    "bGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5nZXQoCiAgICAgICAgICAgIGZpbGVJZD1maWxlX2lk"
    "LAogICAgICAgICAgICBmaWVsZHM9ImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZp"
    "ZXdMaW5rLHBhcmVudHMsc2l6ZSIsCiAgICAgICAgKS5leGVjdXRlKCkKCiAgICBkZWYgZ2V0X2Rv"
    "Y19tZXRhZGF0YShzZWxmLCBkb2NfaWQ6IHN0cik6CiAgICAgICAgcmV0dXJuIHNlbGYuZ2V0X2Zp"
    "bGVfbWV0YWRhdGEoZG9jX2lkKQoKICAgIGRlZiBkZWxldGVfaXRlbShzZWxmLCBmaWxlX2lkOiBz"
    "dHIpOgogICAgICAgIGlmIG5vdCBmaWxlX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9y"
    "KCJGaWxlIGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQog"
    "ICAgICAgIHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5kZWxldGUoZmlsZUlkPWZpbGVfaWQp"
    "LmV4ZWN1dGUoKQoKICAgIGRlZiBkZWxldGVfZG9jKHNlbGYsIGRvY19pZDogc3RyKToKICAgICAg"
    "ICBzZWxmLmRlbGV0ZV9pdGVtKGRvY19pZCkKCiAgICBkZWYgZXhwb3J0X2RvY190ZXh0KHNlbGYs"
    "IGRvY19pZDogc3RyKToKICAgICAgICBpZiBub3QgZG9jX2lkOgogICAgICAgICAgICByYWlzZSBW"
    "YWx1ZUVycm9yKCJEb2N1bWVudCBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJl"
    "X3NlcnZpY2VzKCkKICAgICAgICBwYXlsb2FkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygp"
    "LmV4cG9ydCgKICAgICAgICAgICAgZmlsZUlkPWRvY19pZCwKICAgICAgICAgICAgbWltZVR5cGU9"
    "InRleHQvcGxhaW4iLAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAgaWYgaXNpbnN0YW5jZShw"
    "YXlsb2FkLCBieXRlcyk6CiAgICAgICAgICAgIHJldHVybiBwYXlsb2FkLmRlY29kZSgidXRmLTgi"
    "LCBlcnJvcnM9InJlcGxhY2UiKQogICAgICAgIHJldHVybiBzdHIocGF5bG9hZCBvciAiIikKCiAg"
    "ICBkZWYgZG93bmxvYWRfZmlsZV9ieXRlcyhzZWxmLCBmaWxlX2lkOiBzdHIpOgogICAgICAgIGlm"
    "IG5vdCBmaWxlX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlkIGlzIHJl"
    "cXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHJldHVybiBz"
    "ZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuZ2V0X21lZGlhKGZpbGVJZD1maWxlX2lkKS5leGVj"
    "dXRlKCkKCgoKCiMg4pSA4pSAIFBBU1MgMyBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBBbGwgd29ya2VyIHRo"
    "cmVhZHMgZGVmaW5lZC4gQWxsIGdlbmVyYXRpb24gaXMgc3RyZWFtaW5nLgojIE5vIGJsb2NraW5n"
    "IGNhbGxzIG9uIG1haW4gdGhyZWFkIGFueXdoZXJlIGluIHRoaXMgZmlsZS4KIwojIE5leHQ6IFBh"
    "c3MgNCDigJQgTWVtb3J5ICYgU3RvcmFnZQojIChNZW1vcnlNYW5hZ2VyLCBTZXNzaW9uTWFuYWdl"
    "ciwgTGVzc29uc0xlYXJuZWREQiwgVGFza01hbmFnZXIpCgoKIyDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5O"
    "QSBERUNLIOKAlCBQQVNTIDQ6IE1FTU9SWSAmIFNUT1JBR0UKIwojIFN5c3RlbXMgZGVmaW5lZCBo"
    "ZXJlOgojICAgRGVwZW5kZW5jeUNoZWNrZXIgICDigJQgdmFsaWRhdGVzIGFsbCByZXF1aXJlZCBw"
    "YWNrYWdlcyBvbiBzdGFydHVwCiMgICBNZW1vcnlNYW5hZ2VyICAgICAgIOKAlCBKU09OTCBtZW1v"
    "cnkgcmVhZC93cml0ZS9zZWFyY2gKIyAgIFNlc3Npb25NYW5hZ2VyICAgICAg4oCUIGF1dG8tc2F2"
    "ZSwgbG9hZCwgY29udGV4dCBpbmplY3Rpb24sIHNlc3Npb24gaW5kZXgKIyAgIExlc3NvbnNMZWFy"
    "bmVkREIgICAg4oCUIExTTCBGb3JiaWRkZW4gUnVsZXNldCArIGNvZGUgbGVzc29ucyBrbm93bGVk"
    "Z2UgYmFzZQojICAgVGFza01hbmFnZXIgICAgICAgICDigJQgdGFzay9yZW1pbmRlciBDUlVELCBk"
    "dWUtZXZlbnQgZGV0ZWN0aW9uCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgoKIyDilIDilIAgREVQRU5ERU5DWSBDSEVD"
    "S0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gApjbGFzcyBEZXBlbmRlbmN5Q2hlY2tlcjoKICAgICIiIgogICAgVmFsaWRhdGVzIGFsbCByZXF1"
    "aXJlZCBhbmQgb3B0aW9uYWwgcGFja2FnZXMgb24gc3RhcnR1cC4KICAgIFJldHVybnMgYSBsaXN0"
    "IG9mIHN0YXR1cyBtZXNzYWdlcyBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgIFNob3dzIGEg"
    "YmxvY2tpbmcgZXJyb3IgZGlhbG9nIGZvciBhbnkgY3JpdGljYWwgbWlzc2luZyBkZXBlbmRlbmN5"
    "LgogICAgIiIiCgogICAgIyAocGFja2FnZV9uYW1lLCBpbXBvcnRfbmFtZSwgY3JpdGljYWwsIGlu"
    "c3RhbGxfaGludCkKICAgIFBBQ0tBR0VTID0gWwogICAgICAgICgiUHlTaWRlNiIsICAgICAgICAg"
    "ICAgICAgICAgICJQeVNpZGU2IiwgICAgICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5z"
    "dGFsbCBQeVNpZGU2IiksCiAgICAgICAgKCJsb2d1cnUiLCAgICAgICAgICAgICAgICAgICAgImxv"
    "Z3VydSIsICAgICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGxvZ3VydSIp"
    "LAogICAgICAgICgiYXBzY2hlZHVsZXIiLCAgICAgICAgICAgICAgICJhcHNjaGVkdWxlciIsICAg"
    "ICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBhcHNjaGVkdWxlciIpLAogICAgICAg"
    "ICgicHlnYW1lIiwgICAgICAgICAgICAgICAgICAgICJweWdhbWUiLCAgICAgICAgICAgICAgIEZh"
    "bHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcHlnYW1lICAobmVlZGVkIGZvciBzb3VuZCkiKSwK"
    "ICAgICAgICAoInB5d2luMzIiLCAgICAgICAgICAgICAgICAgICAid2luMzJjb20iLCAgICAgICAg"
    "ICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5d2luMzIgIChuZWVkZWQgZm9yIGRl"
    "c2t0b3Agc2hvcnRjdXQpIiksCiAgICAgICAgKCJwc3V0aWwiLCAgICAgICAgICAgICAgICAgICAg"
    "InBzdXRpbCIsICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBwc3V0"
    "aWwgIChuZWVkZWQgZm9yIHN5c3RlbSBtb25pdG9yaW5nKSIpLAogICAgICAgICgicmVxdWVzdHMi"
    "LCAgICAgICAgICAgICAgICAgICJyZXF1ZXN0cyIsICAgICAgICAgICAgIEZhbHNlLAogICAgICAg"
    "ICAicGlwIGluc3RhbGwgcmVxdWVzdHMiKSwKICAgICAgICAoImdvb2dsZS1hcGktcHl0aG9uLWNs"
    "aWVudCIsICAiZ29vZ2xlYXBpY2xpZW50IiwgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0"
    "YWxsIGdvb2dsZS1hcGktcHl0aG9uLWNsaWVudCIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgtb2F1"
    "dGhsaWIiLCAgICAgICJnb29nbGVfYXV0aF9vYXV0aGxpYiIsIEZhbHNlLAogICAgICAgICAicGlw"
    "IGluc3RhbGwgZ29vZ2xlLWF1dGgtb2F1dGhsaWIiKSwKICAgICAgICAoImdvb2dsZS1hdXRoIiwg"
    "ICAgICAgICAgICAgICAiZ29vZ2xlLmF1dGgiLCAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBp"
    "cCBpbnN0YWxsIGdvb2dsZS1hdXRoIiksCiAgICAgICAgKCJ0b3JjaCIsICAgICAgICAgICAgICAg"
    "ICAgICAgInRvcmNoIiwgICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFs"
    "bCB0b3JjaCAgKG9ubHkgbmVlZGVkIGZvciBsb2NhbCBtb2RlbCkiKSwKICAgICAgICAoInRyYW5z"
    "Zm9ybWVycyIsICAgICAgICAgICAgICAidHJhbnNmb3JtZXJzIiwgICAgICAgICBGYWxzZSwKICAg"
    "ICAgICAgInBpcCBpbnN0YWxsIHRyYW5zZm9ybWVycyAgKG9ubHkgbmVlZGVkIGZvciBsb2NhbCBt"
    "b2RlbCkiKSwKICAgICAgICAoInB5bnZtbCIsICAgICAgICAgICAgICAgICAgICAicHludm1sIiwg"
    "ICAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5bnZtbCAgKG9ubHkg"
    "bmVlZGVkIGZvciBOVklESUEgR1BVIG1vbml0b3JpbmcpIiksCiAgICBdCgogICAgQGNsYXNzbWV0"
    "aG9kCiAgICBkZWYgY2hlY2soY2xzKSAtPiB0dXBsZVtsaXN0W3N0cl0sIGxpc3Rbc3RyXV06CiAg"
    "ICAgICAgIiIiCiAgICAgICAgUmV0dXJucyAobWVzc2FnZXMsIGNyaXRpY2FsX2ZhaWx1cmVzKS4K"
    "ICAgICAgICBtZXNzYWdlczogbGlzdCBvZiAiW0RFUFNdIHBhY2thZ2Ug4pyTL+KclyDigJQgbm90"
    "ZSIgc3RyaW5ncwogICAgICAgIGNyaXRpY2FsX2ZhaWx1cmVzOiBsaXN0IG9mIHBhY2thZ2VzIHRo"
    "YXQgYXJlIGNyaXRpY2FsIGFuZCBtaXNzaW5nCiAgICAgICAgIiIiCiAgICAgICAgaW1wb3J0IGlt"
    "cG9ydGxpYgogICAgICAgIG1lc3NhZ2VzICA9IFtdCiAgICAgICAgY3JpdGljYWwgID0gW10KCiAg"
    "ICAgICAgZm9yIHBrZ19uYW1lLCBpbXBvcnRfbmFtZSwgaXNfY3JpdGljYWwsIGhpbnQgaW4gY2xz"
    "LlBBQ0tBR0VTOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpbXBvcnRsaWIuaW1w"
    "b3J0X21vZHVsZShpbXBvcnRfbmFtZSkKICAgICAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZChm"
    "IltERVBTXSB7cGtnX25hbWV9IOKckyIpCiAgICAgICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoK"
    "ICAgICAgICAgICAgICAgIHN0YXR1cyA9ICJDUklUSUNBTCIgaWYgaXNfY3JpdGljYWwgZWxzZSAi"
    "b3B0aW9uYWwiCiAgICAgICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAg"
    "ICAgICAgZiJbREVQU10ge3BrZ19uYW1lfSDinJcgKHtzdGF0dXN9KSDigJQge2hpbnR9IgogICAg"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgaXNfY3JpdGljYWw6CiAgICAgICAgICAg"
    "ICAgICAgICAgY3JpdGljYWwuYXBwZW5kKHBrZ19uYW1lKQoKICAgICAgICByZXR1cm4gbWVzc2Fn"
    "ZXMsIGNyaXRpY2FsCgogICAgQGNsYXNzbWV0aG9kCiAgICBkZWYgY2hlY2tfb2xsYW1hKGNscykg"
    "LT4gc3RyOgogICAgICAgICIiIkNoZWNrIGlmIE9sbGFtYSBpcyBydW5uaW5nLiBSZXR1cm5zIHN0"
    "YXR1cyBzdHJpbmcuIiIiCiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXEgID0gdXJsbGliLnJl"
    "cXVlc3QuUmVxdWVzdCgiaHR0cDovL2xvY2FsaG9zdDoxMTQzNC9hcGkvdGFncyIpCiAgICAgICAg"
    "ICAgIHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0yKQogICAgICAg"
    "ICAgICBpZiByZXNwLnN0YXR1cyA9PSAyMDA6CiAgICAgICAgICAgICAgICByZXR1cm4gIltERVBT"
    "XSBPbGxhbWEg4pyTIOKAlCBydW5uaW5nIG9uIGxvY2FsaG9zdDoxMTQzNCIKICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICAgICAgcmV0dXJuICJbREVQU10gT2xs"
    "YW1hIOKclyDigJQgbm90IHJ1bm5pbmcgKG9ubHkgbmVlZGVkIGZvciBPbGxhbWEgbW9kZWwgdHlw"
    "ZSkiCgoKIyDilIDilIAgTUVNT1JZIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1lbW9yeU1hbmFn"
    "ZXI6CiAgICAiIiIKICAgIEhhbmRsZXMgYWxsIEpTT05MIG1lbW9yeSBvcGVyYXRpb25zLgoKICAg"
    "IEZpbGVzIG1hbmFnZWQ6CiAgICAgICAgbWVtb3JpZXMvbWVzc2FnZXMuanNvbmwgICAgICAgICDi"
    "gJQgZXZlcnkgbWVzc2FnZSwgdGltZXN0YW1wZWQKICAgICAgICBtZW1vcmllcy9tZW1vcmllcy5q"
    "c29ubCAgICAgICAgIOKAlCBleHRyYWN0ZWQgbWVtb3J5IHJlY29yZHMKICAgICAgICBtZW1vcmll"
    "cy9zdGF0ZS5qc29uICAgICAgICAgICAgIOKAlCBlbnRpdHkgc3RhdGUKICAgICAgICBtZW1vcmll"
    "cy9pbmRleC5qc29uICAgICAgICAgICAgIOKAlCBjb3VudHMgYW5kIG1ldGFkYXRhCgogICAgTWVt"
    "b3J5IHJlY29yZHMgaGF2ZSB0eXBlIGluZmVyZW5jZSwga2V5d29yZCBleHRyYWN0aW9uLCB0YWcg"
    "Z2VuZXJhdGlvbiwKICAgIG5lYXItZHVwbGljYXRlIGRldGVjdGlvbiwgYW5kIHJlbGV2YW5jZSBz"
    "Y29yaW5nIGZvciBjb250ZXh0IGluamVjdGlvbi4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhz"
    "ZWxmKToKICAgICAgICBiYXNlICAgICAgICAgICAgID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikKICAg"
    "ICAgICBzZWxmLm1lc3NhZ2VzX3AgID0gYmFzZSAvICJtZXNzYWdlcy5qc29ubCIKICAgICAgICBz"
    "ZWxmLm1lbW9yaWVzX3AgID0gYmFzZSAvICJtZW1vcmllcy5qc29ubCIKICAgICAgICBzZWxmLnN0"
    "YXRlX3AgICAgID0gYmFzZSAvICJzdGF0ZS5qc29uIgogICAgICAgIHNlbGYuaW5kZXhfcCAgICAg"
    "PSBiYXNlIC8gImluZGV4Lmpzb24iCgogICAgIyDilIDilIAgU1RBVEUg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbG9h"
    "ZF9zdGF0ZShzZWxmKSAtPiBkaWN0OgogICAgICAgIGlmIG5vdCBzZWxmLnN0YXRlX3AuZXhpc3Rz"
    "KCk6CiAgICAgICAgICAgIHJldHVybiBzZWxmLl9kZWZhdWx0X3N0YXRlKCkKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIHJldHVybiBqc29uLmxvYWRzKHNlbGYuc3RhdGVfcC5yZWFkX3RleHQoZW5j"
    "b2Rpbmc9InV0Zi04IikpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0"
    "dXJuIHNlbGYuX2RlZmF1bHRfc3RhdGUoKQoKICAgIGRlZiBzYXZlX3N0YXRlKHNlbGYsIHN0YXRl"
    "OiBkaWN0KSAtPiBOb25lOgogICAgICAgIHNlbGYuc3RhdGVfcC53cml0ZV90ZXh0KAogICAgICAg"
    "ICAgICBqc29uLmR1bXBzKHN0YXRlLCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIKICAgICAg"
    "ICApCgogICAgZGVmIF9kZWZhdWx0X3N0YXRlKHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgcmV0dXJu"
    "IHsKICAgICAgICAgICAgInBlcnNvbmFfbmFtZSI6ICAgICAgICAgICAgIERFQ0tfTkFNRSwKICAg"
    "ICAgICAgICAgImRlY2tfdmVyc2lvbiI6ICAgICAgICAgICAgIEFQUF9WRVJTSU9OLAogICAgICAg"
    "ICAgICAic2Vzc2lvbl9jb3VudCI6ICAgICAgICAgICAgMCwKICAgICAgICAgICAgImxhc3Rfc3Rh"
    "cnR1cCI6ICAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgICJsYXN0X3NodXRkb3duIjogICAg"
    "ICAgICAgICBOb25lLAogICAgICAgICAgICAibGFzdF9hY3RpdmUiOiAgICAgICAgICAgICAgTm9u"
    "ZSwKICAgICAgICAgICAgInRvdGFsX21lc3NhZ2VzIjogICAgICAgICAgIDAsCiAgICAgICAgICAg"
    "ICJ0b3RhbF9tZW1vcmllcyI6ICAgICAgICAgICAwLAogICAgICAgICAgICAiaW50ZXJuYWxfbmFy"
    "cmF0aXZlIjogICAgICAge30sCiAgICAgICAgICAgICJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3du"
    "IjoiRE9STUFOVCIsCiAgICAgICAgfQoKICAgICMg4pSA4pSAIE1FU1NBR0VTIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGFwcGVuZF9t"
    "ZXNzYWdlKHNlbGYsIHNlc3Npb25faWQ6IHN0ciwgcm9sZTogc3RyLAogICAgICAgICAgICAgICAg"
    "ICAgICAgIGNvbnRlbnQ6IHN0ciwgZW1vdGlvbjogc3RyID0gIiIpIC0+IGRpY3Q6CiAgICAgICAg"
    "cmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgIGYibXNnX3t1dWlkLnV1aWQ0KCku"
    "aGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6ICBsb2NhbF9ub3dfaXNvKCksCiAg"
    "ICAgICAgICAgICJzZXNzaW9uX2lkIjogc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEi"
    "OiAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJyb2xlIjogICAgICAgcm9sZSwKICAgICAgICAg"
    "ICAgImNvbnRlbnQiOiAgICBjb250ZW50LAogICAgICAgICAgICAiZW1vdGlvbiI6ICAgIGVtb3Rp"
    "b24sCiAgICAgICAgfQogICAgICAgIGFwcGVuZF9qc29ubChzZWxmLm1lc3NhZ2VzX3AsIHJlY29y"
    "ZCkKICAgICAgICByZXR1cm4gcmVjb3JkCgogICAgZGVmIGxvYWRfcmVjZW50X21lc3NhZ2VzKHNl"
    "bGYsIGxpbWl0OiBpbnQgPSAyMCkgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9q"
    "c29ubChzZWxmLm1lc3NhZ2VzX3ApWy1saW1pdDpdCgogICAgIyDilIDilIAgTUVNT1JJRVMg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYg"
    "YXBwZW5kX21lbW9yeShzZWxmLCBzZXNzaW9uX2lkOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAg"
    "ICAgICAgICAgICAgICAgICAgYXNzaXN0YW50X3RleHQ6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06"
    "CiAgICAgICAgcmVjb3JkX3R5cGUgPSBpbmZlcl9yZWNvcmRfdHlwZSh1c2VyX3RleHQsIGFzc2lz"
    "dGFudF90ZXh0KQogICAgICAgIGtleXdvcmRzICAgID0gZXh0cmFjdF9rZXl3b3Jkcyh1c2VyX3Rl"
    "eHQgKyAiICIgKyBhc3Npc3RhbnRfdGV4dCkKICAgICAgICB0YWdzICAgICAgICA9IHNlbGYuX2lu"
    "ZmVyX3RhZ3MocmVjb3JkX3R5cGUsIHVzZXJfdGV4dCwga2V5d29yZHMpCiAgICAgICAgdGl0bGUg"
    "ICAgICAgPSBzZWxmLl9pbmZlcl90aXRsZShyZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBrZXl3b3Jk"
    "cykKICAgICAgICBzdW1tYXJ5ICAgICA9IHNlbGYuX3N1bW1hcml6ZShyZWNvcmRfdHlwZSwgdXNl"
    "cl90ZXh0LCBhc3Npc3RhbnRfdGV4dCkKCiAgICAgICAgbWVtb3J5ID0gewogICAgICAgICAgICAi"
    "aWQiOiAgICAgICAgICAgICAgIGYibWVtX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMl19IiwKICAgICAg"
    "ICAgICAgInRpbWVzdGFtcCI6ICAgICAgICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICJz"
    "ZXNzaW9uX2lkIjogICAgICAgc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEiOiAgICAg"
    "ICAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJ0eXBlIjogICAgICAgICAgICAgcmVjb3JkX3R5"
    "cGUsCiAgICAgICAgICAgICJ0aXRsZSI6ICAgICAgICAgICAgdGl0bGUsCiAgICAgICAgICAgICJz"
    "dW1tYXJ5IjogICAgICAgICAgc3VtbWFyeSwKICAgICAgICAgICAgImNvbnRlbnQiOiAgICAgICAg"
    "ICB1c2VyX3RleHRbOjQwMDBdLAogICAgICAgICAgICAiYXNzaXN0YW50X2NvbnRleHQiOmFzc2lz"
    "dGFudF90ZXh0WzoxMjAwXSwKICAgICAgICAgICAgImtleXdvcmRzIjogICAgICAgICBrZXl3b3Jk"
    "cywKICAgICAgICAgICAgInRhZ3MiOiAgICAgICAgICAgICB0YWdzLAogICAgICAgICAgICAiY29u"
    "ZmlkZW5jZSI6ICAgICAgIDAuNzAgaWYgcmVjb3JkX3R5cGUgaW4gewogICAgICAgICAgICAgICAg"
    "ImRyZWFtIiwiaXNzdWUiLCJpZGVhIiwicHJlZmVyZW5jZSIsInJlc29sdXRpb24iCiAgICAgICAg"
    "ICAgIH0gZWxzZSAwLjU1LAogICAgICAgIH0KCiAgICAgICAgaWYgc2VsZi5faXNfbmVhcl9kdXBs"
    "aWNhdGUobWVtb3J5KToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgYXBwZW5kX2pz"
    "b25sKHNlbGYubWVtb3JpZXNfcCwgbWVtb3J5KQogICAgICAgIHJldHVybiBtZW1vcnkKCiAgICBk"
    "ZWYgc2VhcmNoX21lbW9yaWVzKHNlbGYsIHF1ZXJ5OiBzdHIsIGxpbWl0OiBpbnQgPSA2KSAtPiBs"
    "aXN0W2RpY3RdOgogICAgICAgICIiIgogICAgICAgIEtleXdvcmQtc2NvcmVkIG1lbW9yeSBzZWFy"
    "Y2guCiAgICAgICAgUmV0dXJucyB1cCB0byBgbGltaXRgIHJlY29yZHMgc29ydGVkIGJ5IHJlbGV2"
    "YW5jZSBzY29yZSBkZXNjZW5kaW5nLgogICAgICAgIEZhbGxzIGJhY2sgdG8gbW9zdCByZWNlbnQg"
    "aWYgbm8gcXVlcnkgdGVybXMgbWF0Y2guCiAgICAgICAgIiIiCiAgICAgICAgbWVtb3JpZXMgPSBy"
    "ZWFkX2pzb25sKHNlbGYubWVtb3JpZXNfcCkKICAgICAgICBpZiBub3QgcXVlcnkuc3RyaXAoKToK"
    "ICAgICAgICAgICAgcmV0dXJuIG1lbW9yaWVzWy1saW1pdDpdCgogICAgICAgIHFfdGVybXMgPSBz"
    "ZXQoZXh0cmFjdF9rZXl3b3JkcyhxdWVyeSwgbGltaXQ9MTYpKQogICAgICAgIHNjb3JlZCAgPSBb"
    "XQoKICAgICAgICBmb3IgaXRlbSBpbiBtZW1vcmllczoKICAgICAgICAgICAgaXRlbV90ZXJtcyA9"
    "IHNldChleHRyYWN0X2tleXdvcmRzKCIgIi5qb2luKFsKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0"
    "KCJ0aXRsZSIsICAgIiIpLAogICAgICAgICAgICAgICAgaXRlbS5nZXQoInN1bW1hcnkiLCAiIiks"
    "CiAgICAgICAgICAgICAgICBpdGVtLmdldCgiY29udGVudCIsICIiKSwKICAgICAgICAgICAgICAg"
    "ICIgIi5qb2luKGl0ZW0uZ2V0KCJrZXl3b3JkcyIsIFtdKSksCiAgICAgICAgICAgICAgICAiICIu"
    "am9pbihpdGVtLmdldCgidGFncyIsICAgICBbXSkpLAogICAgICAgICAgICBdKSwgbGltaXQ9NDAp"
    "KQoKICAgICAgICAgICAgc2NvcmUgPSBsZW4ocV90ZXJtcyAmIGl0ZW1fdGVybXMpCgogICAgICAg"
    "ICAgICAjIEJvb3N0IGJ5IHR5cGUgbWF0Y2gKICAgICAgICAgICAgcWwgPSBxdWVyeS5sb3dlcigp"
    "CiAgICAgICAgICAgIHJ0ID0gaXRlbS5nZXQoInR5cGUiLCAiIikKICAgICAgICAgICAgaWYgImRy"
    "ZWFtIiAgaW4gcWwgYW5kIHJ0ID09ICJkcmVhbSI6ICAgIHNjb3JlICs9IDQKICAgICAgICAgICAg"
    "aWYgInRhc2siICAgaW4gcWwgYW5kIHJ0ID09ICJ0YXNrIjogICAgIHNjb3JlICs9IDMKICAgICAg"
    "ICAgICAgaWYgImlkZWEiICAgaW4gcWwgYW5kIHJ0ID09ICJpZGVhIjogICAgIHNjb3JlICs9IDIK"
    "ICAgICAgICAgICAgaWYgImxzbCIgICAgaW4gcWwgYW5kIHJ0IGluIHsiaXNzdWUiLCJyZXNvbHV0"
    "aW9uIn06IHNjb3JlICs9IDIKCiAgICAgICAgICAgIGlmIHNjb3JlID4gMDoKICAgICAgICAgICAg"
    "ICAgIHNjb3JlZC5hcHBlbmQoKHNjb3JlLCBpdGVtKSkKCiAgICAgICAgc2NvcmVkLnNvcnQoa2V5"
    "PWxhbWJkYSB4OiAoeFswXSwgeFsxXS5nZXQoInRpbWVzdGFtcCIsICIiKSksCiAgICAgICAgICAg"
    "ICAgICAgICAgcmV2ZXJzZT1UcnVlKQogICAgICAgIHJldHVybiBbaXRlbSBmb3IgXywgaXRlbSBp"
    "biBzY29yZWRbOmxpbWl0XV0KCiAgICBkZWYgYnVpbGRfY29udGV4dF9ibG9jayhzZWxmLCBxdWVy"
    "eTogc3RyLCBtYXhfY2hhcnM6IGludCA9IDIwMDApIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAg"
    "ICBCdWlsZCBhIGNvbnRleHQgc3RyaW5nIGZyb20gcmVsZXZhbnQgbWVtb3JpZXMgZm9yIHByb21w"
    "dCBpbmplY3Rpb24uCiAgICAgICAgVHJ1bmNhdGVzIHRvIG1heF9jaGFycyB0byBwcm90ZWN0IHRo"
    "ZSBjb250ZXh0IHdpbmRvdy4KICAgICAgICAiIiIKICAgICAgICBtZW1vcmllcyA9IHNlbGYuc2Vh"
    "cmNoX21lbW9yaWVzKHF1ZXJ5LCBsaW1pdD00KQogICAgICAgIGlmIG5vdCBtZW1vcmllczoKICAg"
    "ICAgICAgICAgcmV0dXJuICIiCgogICAgICAgIHBhcnRzID0gWyJbUkVMRVZBTlQgTUVNT1JJRVNd"
    "Il0KICAgICAgICB0b3RhbCA9IDAKICAgICAgICBmb3IgbSBpbiBtZW1vcmllczoKICAgICAgICAg"
    "ICAgZW50cnkgPSAoCiAgICAgICAgICAgICAgICBmIuKAoiBbe20uZ2V0KCd0eXBlJywnJykudXBw"
    "ZXIoKX1dIHttLmdldCgndGl0bGUnLCcnKX06ICIKICAgICAgICAgICAgICAgIGYie20uZ2V0KCdz"
    "dW1tYXJ5JywnJyl9IgogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIHRvdGFsICsgbGVuKGVu"
    "dHJ5KSA+IG1heF9jaGFyczoKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHBhcnRz"
    "LmFwcGVuZChlbnRyeSkKICAgICAgICAgICAgdG90YWwgKz0gbGVuKGVudHJ5KQoKICAgICAgICBw"
    "YXJ0cy5hcHBlbmQoIltFTkQgTUVNT1JJRVNdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBh"
    "cnRzKQoKICAgICMg4pSA4pSAIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2lzX25lYXJfZHVwbGljYXRlKHNlbGYs"
    "IGNhbmRpZGF0ZTogZGljdCkgLT4gYm9vbDoKICAgICAgICByZWNlbnQgPSByZWFkX2pzb25sKHNl"
    "bGYubWVtb3JpZXNfcClbLTI1Ol0KICAgICAgICBjdCA9IGNhbmRpZGF0ZS5nZXQoInRpdGxlIiwg"
    "IiIpLmxvd2VyKCkuc3RyaXAoKQogICAgICAgIGNzID0gY2FuZGlkYXRlLmdldCgic3VtbWFyeSIs"
    "ICIiKS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBmb3IgaXRlbSBpbiByZWNlbnQ6CiAgICAgICAg"
    "ICAgIGlmIGl0ZW0uZ2V0KCJ0aXRsZSIsIiIpLmxvd2VyKCkuc3RyaXAoKSA9PSBjdDogIHJldHVy"
    "biBUcnVlCiAgICAgICAgICAgIGlmIGl0ZW0uZ2V0KCJzdW1tYXJ5IiwiIikubG93ZXIoKS5zdHJp"
    "cCgpID09IGNzOiByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVybiBGYWxzZQoKICAgIGRlZiBfaW5m"
    "ZXJfdGFncyhzZWxmLCByZWNvcmRfdHlwZTogc3RyLCB0ZXh0OiBzdHIsCiAgICAgICAgICAgICAg"
    "ICAgICAga2V5d29yZHM6IGxpc3Rbc3RyXSkgLT4gbGlzdFtzdHJdOgogICAgICAgIHQgICAgPSB0"
    "ZXh0Lmxvd2VyKCkKICAgICAgICB0YWdzID0gW3JlY29yZF90eXBlXQogICAgICAgIGlmICJkcmVh"
    "bSIgICBpbiB0OiB0YWdzLmFwcGVuZCgiZHJlYW0iKQogICAgICAgIGlmICJsc2wiICAgICBpbiB0"
    "OiB0YWdzLmFwcGVuZCgibHNsIikKICAgICAgICBpZiAicHl0aG9uIiAgaW4gdDogdGFncy5hcHBl"
    "bmQoInB5dGhvbiIpCiAgICAgICAgaWYgImdhbWUiICAgIGluIHQ6IHRhZ3MuYXBwZW5kKCJnYW1l"
    "X2lkZWEiKQogICAgICAgIGlmICJzbCIgICAgICBpbiB0IG9yICJzZWNvbmQgbGlmZSIgaW4gdDog"
    "dGFncy5hcHBlbmQoInNlY29uZGxpZmUiKQogICAgICAgIGlmIERFQ0tfTkFNRS5sb3dlcigpIGlu"
    "IHQ6IHRhZ3MuYXBwZW5kKERFQ0tfTkFNRS5sb3dlcigpKQogICAgICAgIGZvciBrdyBpbiBrZXl3"
    "b3Jkc1s6NF06CiAgICAgICAgICAgIGlmIGt3IG5vdCBpbiB0YWdzOgogICAgICAgICAgICAgICAg"
    "dGFncy5hcHBlbmQoa3cpCiAgICAgICAgIyBEZWR1cGxpY2F0ZSBwcmVzZXJ2aW5nIG9yZGVyCiAg"
    "ICAgICAgc2Vlbiwgb3V0ID0gc2V0KCksIFtdCiAgICAgICAgZm9yIHRhZyBpbiB0YWdzOgogICAg"
    "ICAgICAgICBpZiB0YWcgbm90IGluIHNlZW46CiAgICAgICAgICAgICAgICBzZWVuLmFkZCh0YWcp"
    "CiAgICAgICAgICAgICAgICBvdXQuYXBwZW5kKHRhZykKICAgICAgICByZXR1cm4gb3V0WzoxMl0K"
    "CiAgICBkZWYgX2luZmVyX3RpdGxlKHNlbGYsIHJlY29yZF90eXBlOiBzdHIsIHVzZXJfdGV4dDog"
    "c3RyLAogICAgICAgICAgICAgICAgICAgICBrZXl3b3JkczogbGlzdFtzdHJdKSAtPiBzdHI6CiAg"
    "ICAgICAgZGVmIGNsZWFuKHdvcmRzKToKICAgICAgICAgICAgcmV0dXJuIFt3LnN0cmlwKCIgLV8u"
    "LCE/IikuY2FwaXRhbGl6ZSgpCiAgICAgICAgICAgICAgICAgICAgZm9yIHcgaW4gd29yZHMgaWYg"
    "bGVuKHcpID4gMl0KCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInRhc2siOgogICAgICAgICAg"
    "ICBpbXBvcnQgcmUKICAgICAgICAgICAgbSA9IHJlLnNlYXJjaChyInJlbWluZCBtZSAuKj8gdG8g"
    "KC4rKSIsIHVzZXJfdGV4dCwgcmUuSSkKICAgICAgICAgICAgaWYgbToKICAgICAgICAgICAgICAg"
    "IHJldHVybiBmIlJlbWluZGVyOiB7bS5ncm91cCgxKS5zdHJpcCgpWzo2MF19IgogICAgICAgICAg"
    "ICByZXR1cm4gIlJlbWluZGVyIFRhc2siCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImRyZWFt"
    "IjoKICAgICAgICAgICAgcmV0dXJuIGYieycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzozXSkpfSBE"
    "cmVhbSIuc3RyaXAoKSBvciAiRHJlYW0gTWVtb3J5IgogICAgICAgIGlmIHJlY29yZF90eXBlID09"
    "ICJpc3N1ZSI6CiAgICAgICAgICAgIHJldHVybiBmIklzc3VlOiB7JyAnLmpvaW4oY2xlYW4oa2V5"
    "d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJUZWNobmljYWwgSXNzdWUiCiAgICAgICAgaWYgcmVj"
    "b3JkX3R5cGUgPT0gInJlc29sdXRpb24iOgogICAgICAgICAgICByZXR1cm4gZiJSZXNvbHV0aW9u"
    "OiB7JyAnLmpvaW4oY2xlYW4oa2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJUZWNobmljYWwg"
    "UmVzb2x1dGlvbiIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaWRlYSI6CiAgICAgICAgICAg"
    "IHJldHVybiBmIklkZWE6IHsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0pKX0iLnN0cmlwKCkg"
    "b3IgIklkZWEiCiAgICAgICAgaWYga2V5d29yZHM6CiAgICAgICAgICAgIHJldHVybiAiICIuam9p"
    "bihjbGVhbihrZXl3b3Jkc1s6NV0pKSBvciAiQ29udmVyc2F0aW9uIE1lbW9yeSIKICAgICAgICBy"
    "ZXR1cm4gIkNvbnZlcnNhdGlvbiBNZW1vcnkiCgogICAgZGVmIF9zdW1tYXJpemUoc2VsZiwgcmVj"
    "b3JkX3R5cGU6IHN0ciwgdXNlcl90ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICBhc3Npc3Rh"
    "bnRfdGV4dDogc3RyKSAtPiBzdHI6CiAgICAgICAgdSA9IHVzZXJfdGV4dC5zdHJpcCgpWzoyMjBd"
    "CiAgICAgICAgYSA9IGFzc2lzdGFudF90ZXh0LnN0cmlwKClbOjIyMF0KICAgICAgICBpZiByZWNv"
    "cmRfdHlwZSA9PSAiZHJlYW0iOiAgICAgICByZXR1cm4gZiJVc2VyIGRlc2NyaWJlZCBhIGRyZWFt"
    "OiB7dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInRhc2siOiAgICAgICAgcmV0dXJuIGYi"
    "UmVtaW5kZXIvdGFzazoge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpc3N1ZSI6ICAg"
    "ICAgIHJldHVybiBmIlRlY2huaWNhbCBpc3N1ZToge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBl"
    "ID09ICJyZXNvbHV0aW9uIjogIHJldHVybiBmIlNvbHV0aW9uIHJlY29yZGVkOiB7YSBvciB1fSIK"
    "ICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaWRlYSI6ICAgICAgICByZXR1cm4gZiJJZGVhIGRp"
    "c2N1c3NlZDoge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJwcmVmZXJlbmNlIjogIHJl"
    "dHVybiBmIlByZWZlcmVuY2Ugbm90ZWQ6IHt1fSIKICAgICAgICByZXR1cm4gZiJDb252ZXJzYXRp"
    "b246IHt1fSIKCgojIOKUgOKUgCBTRVNTSU9OIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNlc3Npb25N"
    "YW5hZ2VyOgogICAgIiIiCiAgICBNYW5hZ2VzIGNvbnZlcnNhdGlvbiBzZXNzaW9ucy4KCiAgICBB"
    "dXRvLXNhdmU6IGV2ZXJ5IDEwIG1pbnV0ZXMgKEFQU2NoZWR1bGVyKSwgbWlkbmlnaHQtdG8tbWlk"
    "bmlnaHQgYm91bmRhcnkuCiAgICBGaWxlOiBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sIOKAlCBv"
    "dmVyd3JpdGVzIG9uIGVhY2ggc2F2ZS4KICAgIEluZGV4OiBzZXNzaW9ucy9zZXNzaW9uX2luZGV4"
    "Lmpzb24g4oCUIG9uZSBlbnRyeSBwZXIgZGF5LgoKICAgIFNlc3Npb25zIGFyZSBsb2FkZWQgYXMg"
    "Y29udGV4dCBpbmplY3Rpb24gKG5vdCByZWFsIG1lbW9yeSkgdW50aWwKICAgIHRoZSBTUUxpdGUv"
    "Q2hyb21hREIgc3lzdGVtIGlzIGJ1aWx0IGluIFBoYXNlIDIuCiAgICAiIiIKCiAgICBBVVRPU0FW"
    "RV9JTlRFUlZBTCA9IDEwICAgIyBtaW51dGVzCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAg"
    "ICAgIHNlbGYuX3Nlc3Npb25zX2RpciAgPSBjZmdfcGF0aCgic2Vzc2lvbnMiKQogICAgICAgIHNl"
    "bGYuX2luZGV4X3BhdGggICAgPSBzZWxmLl9zZXNzaW9uc19kaXIgLyAic2Vzc2lvbl9pbmRleC5q"
    "c29uIgogICAgICAgIHNlbGYuX3Nlc3Npb25faWQgICAgPSBmInNlc3Npb25fe2RhdGV0aW1lLm5v"
    "dygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9IgogICAgICAgIHNlbGYuX2N1cnJlbnRfZGF0"
    "ZSAgPSBkYXRlLnRvZGF5KCkuaXNvZm9ybWF0KCkKICAgICAgICBzZWxmLl9tZXNzYWdlczogbGlz"
    "dFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fbG9hZGVkX2pvdXJuYWw6IE9wdGlvbmFsW3N0cl0g"
    "PSBOb25lICAjIGRhdGUgb2YgbG9hZGVkIGpvdXJuYWwKCiAgICAjIOKUgOKUgCBDVVJSRU5UIFNF"
    "U1NJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgYWRkX21lc3NhZ2Uo"
    "c2VsZiwgcm9sZTogc3RyLCBjb250ZW50OiBzdHIsCiAgICAgICAgICAgICAgICAgICAgZW1vdGlv"
    "bjogc3RyID0gIiIsIHRpbWVzdGFtcDogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "bWVzc2FnZXMuYXBwZW5kKHsKICAgICAgICAgICAgImlkIjogICAgICAgIGYibXNnX3t1dWlkLnV1"
    "aWQ0KCkuaGV4Wzo4XX0iLAogICAgICAgICAgICAidGltZXN0YW1wIjogdGltZXN0YW1wIG9yIGxv"
    "Y2FsX25vd19pc28oKSwKICAgICAgICAgICAgInJvbGUiOiAgICAgIHJvbGUsCiAgICAgICAgICAg"
    "ICJjb250ZW50IjogICBjb250ZW50LAogICAgICAgICAgICAiZW1vdGlvbiI6ICAgZW1vdGlvbiwK"
    "ICAgICAgICB9KQoKICAgIGRlZiBnZXRfaGlzdG9yeShzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAg"
    "ICAgICIiIgogICAgICAgIFJldHVybiBoaXN0b3J5IGluIExMTS1mcmllbmRseSBmb3JtYXQuCiAg"
    "ICAgICAgW3sicm9sZSI6ICJ1c2VyInwiYXNzaXN0YW50IiwgImNvbnRlbnQiOiAiLi4uIn1dCiAg"
    "ICAgICAgIiIiCiAgICAgICAgcmV0dXJuIFsKICAgICAgICAgICAgeyJyb2xlIjogbVsicm9sZSJd"
    "LCAiY29udGVudCI6IG1bImNvbnRlbnQiXX0KICAgICAgICAgICAgZm9yIG0gaW4gc2VsZi5fbWVz"
    "c2FnZXMKICAgICAgICAgICAgaWYgbVsicm9sZSJdIGluICgidXNlciIsICJhc3Npc3RhbnQiKQog"
    "ICAgICAgIF0KCiAgICBAcHJvcGVydHkKICAgIGRlZiBzZXNzaW9uX2lkKHNlbGYpIC0+IHN0cjoK"
    "ICAgICAgICByZXR1cm4gc2VsZi5fc2Vzc2lvbl9pZAoKICAgIEBwcm9wZXJ0eQogICAgZGVmIG1l"
    "c3NhZ2VfY291bnQoc2VsZikgLT4gaW50OgogICAgICAgIHJldHVybiBsZW4oc2VsZi5fbWVzc2Fn"
    "ZXMpCgogICAgIyDilIDilIAgU0FWRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBzYXZlKHNlbGYsIGFpX2dlbmVy"
    "YXRlZF9uYW1lOiBzdHIgPSAiIikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBTYXZlIGN1"
    "cnJlbnQgc2Vzc2lvbiB0byBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sLgogICAgICAgIE92ZXJ3"
    "cml0ZXMgdGhlIGZpbGUgZm9yIHRvZGF5IOKAlCBlYWNoIHNhdmUgaXMgYSBmdWxsIHNuYXBzaG90"
    "LgogICAgICAgIFVwZGF0ZXMgc2Vzc2lvbl9pbmRleC5qc29uLgogICAgICAgICIiIgogICAgICAg"
    "IHRvZGF5ID0gZGF0ZS50b2RheSgpLmlzb2Zvcm1hdCgpCiAgICAgICAgb3V0X3BhdGggPSBzZWxm"
    "Ll9zZXNzaW9uc19kaXIgLyBmInt0b2RheX0uanNvbmwiCgogICAgICAgICMgV3JpdGUgYWxsIG1l"
    "c3NhZ2VzCiAgICAgICAgd3JpdGVfanNvbmwob3V0X3BhdGgsIHNlbGYuX21lc3NhZ2VzKQoKICAg"
    "ICAgICAjIFVwZGF0ZSBpbmRleAogICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAg"
    "ICAgICAgZXhpc3RpbmcgPSBuZXh0KAogICAgICAgICAgICAocyBmb3IgcyBpbiBpbmRleFsic2Vz"
    "c2lvbnMiXSBpZiBzWyJkYXRlIl0gPT0gdG9kYXkpLCBOb25lCiAgICAgICAgKQoKICAgICAgICBu"
    "YW1lID0gYWlfZ2VuZXJhdGVkX25hbWUgb3IgZXhpc3RpbmcuZ2V0KCJuYW1lIiwgIiIpIGlmIGV4"
    "aXN0aW5nIGVsc2UgIiIKICAgICAgICBpZiBub3QgbmFtZSBhbmQgc2VsZi5fbWVzc2FnZXM6CiAg"
    "ICAgICAgICAgICMgQXV0by1uYW1lIGZyb20gZmlyc3QgdXNlciBtZXNzYWdlIChmaXJzdCA1IHdv"
    "cmRzKQogICAgICAgICAgICBmaXJzdF91c2VyID0gbmV4dCgKICAgICAgICAgICAgICAgIChtWyJj"
    "b250ZW50Il0gZm9yIG0gaW4gc2VsZi5fbWVzc2FnZXMgaWYgbVsicm9sZSJdID09ICJ1c2VyIiks"
    "CiAgICAgICAgICAgICAgICAiIgogICAgICAgICAgICApCiAgICAgICAgICAgIHdvcmRzID0gZmly"
    "c3RfdXNlci5zcGxpdCgpWzo1XQogICAgICAgICAgICBuYW1lICA9ICIgIi5qb2luKHdvcmRzKSBp"
    "ZiB3b3JkcyBlbHNlIGYiU2Vzc2lvbiB7dG9kYXl9IgoKICAgICAgICBlbnRyeSA9IHsKICAgICAg"
    "ICAgICAgImRhdGUiOiAgICAgICAgICB0b2RheSwKICAgICAgICAgICAgInNlc3Npb25faWQiOiAg"
    "ICBzZWxmLl9zZXNzaW9uX2lkLAogICAgICAgICAgICAibmFtZSI6ICAgICAgICAgIG5hbWUsCiAg"
    "ICAgICAgICAgICJtZXNzYWdlX2NvdW50IjogbGVuKHNlbGYuX21lc3NhZ2VzKSwKICAgICAgICAg"
    "ICAgImZpcnN0X21lc3NhZ2UiOiAoc2VsZi5fbWVzc2FnZXNbMF1bInRpbWVzdGFtcCJdCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAg"
    "ICAgICAgICAibGFzdF9tZXNzYWdlIjogIChzZWxmLl9tZXNzYWdlc1stMV1bInRpbWVzdGFtcCJd"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIp"
    "LAogICAgICAgIH0KCiAgICAgICAgaWYgZXhpc3Rpbmc6CiAgICAgICAgICAgIGlkeCA9IGluZGV4"
    "WyJzZXNzaW9ucyJdLmluZGV4KGV4aXN0aW5nKQogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMi"
    "XVtpZHhdID0gZW50cnkKICAgICAgICBlbHNlOgogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMi"
    "XS5pbnNlcnQoMCwgZW50cnkpCgogICAgICAgICMgS2VlcCBsYXN0IDM2NSBkYXlzIGluIGluZGV4"
    "CiAgICAgICAgaW5kZXhbInNlc3Npb25zIl0gPSBpbmRleFsic2Vzc2lvbnMiXVs6MzY1XQogICAg"
    "ICAgIHNlbGYuX3NhdmVfaW5kZXgoaW5kZXgpCgogICAgIyDilIDilIAgTE9BRCAvIEpPVVJOQUwg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbGlzdF9zZXNzaW9ucyhz"
    "ZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIiIlJldHVybiBhbGwgc2Vzc2lvbnMgZnJvbSBp"
    "bmRleCwgbmV3ZXN0IGZpcnN0LiIiIgogICAgICAgIHJldHVybiBzZWxmLl9sb2FkX2luZGV4KCku"
    "Z2V0KCJzZXNzaW9ucyIsIFtdKQoKICAgIGRlZiBsb2FkX3Nlc3Npb25fYXNfY29udGV4dChzZWxm"
    "LCBzZXNzaW9uX2RhdGU6IHN0cikgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIExvYWQgYSBw"
    "YXN0IHNlc3Npb24gYXMgYSBjb250ZXh0IGluamVjdGlvbiBzdHJpbmcuCiAgICAgICAgUmV0dXJu"
    "cyBmb3JtYXR0ZWQgdGV4dCB0byBwcmVwZW5kIHRvIHRoZSBzeXN0ZW0gcHJvbXB0LgogICAgICAg"
    "IFRoaXMgaXMgTk9UIHJlYWwgbWVtb3J5IOKAlCBpdCdzIGEgdGVtcG9yYXJ5IGNvbnRleHQgd2lu"
    "ZG93IGluamVjdGlvbgogICAgICAgIHVudGlsIHRoZSBQaGFzZSAyIG1lbW9yeSBzeXN0ZW0gaXMg"
    "YnVpbHQuCiAgICAgICAgIiIiCiAgICAgICAgcGF0aCA9IHNlbGYuX3Nlc3Npb25zX2RpciAvIGYi"
    "e3Nlc3Npb25fZGF0ZX0uanNvbmwiCiAgICAgICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAg"
    "ICAgICAgIHJldHVybiAiIgoKICAgICAgICBtZXNzYWdlcyA9IHJlYWRfanNvbmwocGF0aCkKICAg"
    "ICAgICBzZWxmLl9sb2FkZWRfam91cm5hbCA9IHNlc3Npb25fZGF0ZQoKICAgICAgICBsaW5lcyA9"
    "IFtmIltKT1VSTkFMIExPQURFRCDigJQge3Nlc3Npb25fZGF0ZX1dIiwKICAgICAgICAgICAgICAg"
    "ICAiVGhlIGZvbGxvd2luZyBpcyBhIHJlY29yZCBvZiBhIHByaW9yIGNvbnZlcnNhdGlvbi4iLAog"
    "ICAgICAgICAgICAgICAgICJVc2UgdGhpcyBhcyBjb250ZXh0IGZvciB0aGUgY3VycmVudCBzZXNz"
    "aW9uOlxuIl0KCiAgICAgICAgIyBJbmNsdWRlIHVwIHRvIGxhc3QgMzAgbWVzc2FnZXMgZnJvbSB0"
    "aGF0IHNlc3Npb24KICAgICAgICBmb3IgbXNnIGluIG1lc3NhZ2VzWy0zMDpdOgogICAgICAgICAg"
    "ICByb2xlICAgID0gbXNnLmdldCgicm9sZSIsICI/IikudXBwZXIoKQogICAgICAgICAgICBjb250"
    "ZW50ID0gbXNnLmdldCgiY29udGVudCIsICIiKVs6MzAwXQogICAgICAgICAgICB0cyAgICAgID0g"
    "bXNnLmdldCgidGltZXN0YW1wIiwgIiIpWzoxNl0KICAgICAgICAgICAgbGluZXMuYXBwZW5kKGYi"
    "W3t0c31dIHtyb2xlfToge2NvbnRlbnR9IikKCiAgICAgICAgbGluZXMuYXBwZW5kKCJbRU5EIEpP"
    "VVJOQUxdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKGxpbmVzKQoKICAgIGRlZiBjbGVhcl9s"
    "b2FkZWRfam91cm5hbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFs"
    "ID0gTm9uZQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGxvYWRlZF9qb3VybmFsX2RhdGUoc2VsZikg"
    "LT4gT3B0aW9uYWxbc3RyXToKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZGVkX2pvdXJuYWwKCiAg"
    "ICBkZWYgcmVuYW1lX3Nlc3Npb24oc2VsZiwgc2Vzc2lvbl9kYXRlOiBzdHIsIG5ld19uYW1lOiBz"
    "dHIpIC0+IGJvb2w6CiAgICAgICAgIiIiUmVuYW1lIGEgc2Vzc2lvbiBpbiB0aGUgaW5kZXguIFJl"
    "dHVybnMgVHJ1ZSBvbiBzdWNjZXNzLiIiIgogICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9pbmRl"
    "eCgpCiAgICAgICAgZm9yIGVudHJ5IGluIGluZGV4WyJzZXNzaW9ucyJdOgogICAgICAgICAgICBp"
    "ZiBlbnRyeVsiZGF0ZSJdID09IHNlc3Npb25fZGF0ZToKICAgICAgICAgICAgICAgIGVudHJ5WyJu"
    "YW1lIl0gPSBuZXdfbmFtZVs6ODBdCiAgICAgICAgICAgICAgICBzZWxmLl9zYXZlX2luZGV4KGlu"
    "ZGV4KQogICAgICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAg"
    "ICAjIOKUgOKUgCBJTkRFWCBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgZGVmIF9sb2FkX2luZGV4KHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgaWYgbm90IHNl"
    "bGYuX2luZGV4X3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiB7InNlc3Npb25zIjog"
    "W119CiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXR1cm4ganNvbi5sb2FkcygKICAgICAgICAg"
    "ICAgICAgIHNlbGYuX2luZGV4X3BhdGgucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpCiAgICAg"
    "ICAgICAgICkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4geyJz"
    "ZXNzaW9ucyI6IFtdfQoKICAgIGRlZiBfc2F2ZV9pbmRleChzZWxmLCBpbmRleDogZGljdCkgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLl9pbmRleF9wYXRoLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpz"
    "b24uZHVtcHMoaW5kZXgsIGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04IgogICAgICAgICkKCgoj"
    "IOKUgOKUgCBMRVNTT05TIExFQVJORUQgREFUQUJBU0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACmNsYXNzIExlc3NvbnNMZWFybmVkREI6CiAgICAiIiIKICAgIFBlcnNpc3Rl"
    "bnQga25vd2xlZGdlIGJhc2UgZm9yIGNvZGUgbGVzc29ucywgcnVsZXMsIGFuZCByZXNvbHV0aW9u"
    "cy4KCiAgICBDb2x1bW5zIHBlciByZWNvcmQ6CiAgICAgICAgaWQsIGNyZWF0ZWRfYXQsIGVudmly"
    "b25tZW50IChMU0x8UHl0aG9ufFB5U2lkZTZ8Li4uKSwgbGFuZ3VhZ2UsCiAgICAgICAgcmVmZXJl"
    "bmNlX2tleSAoc2hvcnQgdW5pcXVlIHRhZyksIHN1bW1hcnksIGZ1bGxfcnVsZSwKICAgICAgICBy"
    "ZXNvbHV0aW9uLCBsaW5rLCB0YWdzCgogICAgUXVlcmllZCBGSVJTVCBiZWZvcmUgYW55IGNvZGUg"
    "c2Vzc2lvbiBpbiB0aGUgcmVsZXZhbnQgbGFuZ3VhZ2UuCiAgICBUaGUgTFNMIEZvcmJpZGRlbiBS"
    "dWxlc2V0IGxpdmVzIGhlcmUuCiAgICBHcm93aW5nLCBub24tZHVwbGljYXRpbmcsIHNlYXJjaGFi"
    "bGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fcGF0aCA9"
    "IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gImxlc3NvbnNfbGVhcm5lZC5qc29ubCIKCiAgICBkZWYg"
    "YWRkKHNlbGYsIGVudmlyb25tZW50OiBzdHIsIGxhbmd1YWdlOiBzdHIsIHJlZmVyZW5jZV9rZXk6"
    "IHN0ciwKICAgICAgICAgICAgc3VtbWFyeTogc3RyLCBmdWxsX3J1bGU6IHN0ciwgcmVzb2x1dGlv"
    "bjogc3RyID0gIiIsCiAgICAgICAgICAgIGxpbms6IHN0ciA9ICIiLCB0YWdzOiBsaXN0ID0gTm9u"
    "ZSkgLT4gZGljdDoKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAg"
    "ICAgZiJsZXNzb25fe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAiY3JlYXRl"
    "ZF9hdCI6ICAgIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgImVudmlyb25tZW50IjogICBl"
    "bnZpcm9ubWVudCwKICAgICAgICAgICAgImxhbmd1YWdlIjogICAgICBsYW5ndWFnZSwKICAgICAg"
    "ICAgICAgInJlZmVyZW5jZV9rZXkiOiByZWZlcmVuY2Vfa2V5LAogICAgICAgICAgICAic3VtbWFy"
    "eSI6ICAgICAgIHN1bW1hcnksCiAgICAgICAgICAgICJmdWxsX3J1bGUiOiAgICAgZnVsbF9ydWxl"
    "LAogICAgICAgICAgICAicmVzb2x1dGlvbiI6ICAgIHJlc29sdXRpb24sCiAgICAgICAgICAgICJs"
    "aW5rIjogICAgICAgICAgbGluaywKICAgICAgICAgICAgInRhZ3MiOiAgICAgICAgICB0YWdzIG9y"
    "IFtdLAogICAgICAgIH0KICAgICAgICBpZiBub3Qgc2VsZi5faXNfZHVwbGljYXRlKHJlZmVyZW5j"
    "ZV9rZXkpOgogICAgICAgICAgICBhcHBlbmRfanNvbmwoc2VsZi5fcGF0aCwgcmVjb3JkKQogICAg"
    "ICAgIHJldHVybiByZWNvcmQKCiAgICBkZWYgc2VhcmNoKHNlbGYsIHF1ZXJ5OiBzdHIgPSAiIiwg"
    "ZW52aXJvbm1lbnQ6IHN0ciA9ICIiLAogICAgICAgICAgICAgICBsYW5ndWFnZTogc3RyID0gIiIp"
    "IC0+IGxpc3RbZGljdF06CiAgICAgICAgcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkK"
    "ICAgICAgICByZXN1bHRzID0gW10KICAgICAgICBxID0gcXVlcnkubG93ZXIoKQogICAgICAgIGZv"
    "ciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGlmIGVudmlyb25tZW50IGFuZCByLmdldCgiZW52"
    "aXJvbm1lbnQiLCIiKS5sb3dlcigpICE9IGVudmlyb25tZW50Lmxvd2VyKCk6CiAgICAgICAgICAg"
    "ICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBsYW5ndWFnZSBhbmQgci5nZXQoImxhbmd1YWdl"
    "IiwiIikubG93ZXIoKSAhPSBsYW5ndWFnZS5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGlu"
    "dWUKICAgICAgICAgICAgaWYgcToKICAgICAgICAgICAgICAgIGhheXN0YWNrID0gIiAiLmpvaW4o"
    "WwogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJzdW1tYXJ5IiwiIiksCiAgICAgICAgICAgICAg"
    "ICAgICAgci5nZXQoImZ1bGxfcnVsZSIsIiIpLAogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJy"
    "ZWZlcmVuY2Vfa2V5IiwiIiksCiAgICAgICAgICAgICAgICAgICAgIiAiLmpvaW4oci5nZXQoInRh"
    "Z3MiLFtdKSksCiAgICAgICAgICAgICAgICBdKS5sb3dlcigpCiAgICAgICAgICAgICAgICBpZiBx"
    "IG5vdCBpbiBoYXlzdGFjazoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAg"
    "ICByZXN1bHRzLmFwcGVuZChyKQogICAgICAgIHJldHVybiByZXN1bHRzCgogICAgZGVmIGdldF9h"
    "bGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChzZWxmLl9w"
    "YXRoKQoKICAgIGRlZiBkZWxldGUoc2VsZiwgcmVjb3JkX2lkOiBzdHIpIC0+IGJvb2w6CiAgICAg"
    "ICAgcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBmaWx0ZXJlZCA9IFty"
    "IGZvciByIGluIHJlY29yZHMgaWYgci5nZXQoImlkIikgIT0gcmVjb3JkX2lkXQogICAgICAgIGlm"
    "IGxlbihmaWx0ZXJlZCkgPCBsZW4ocmVjb3Jkcyk6CiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNl"
    "bGYuX3BhdGgsIGZpbHRlcmVkKQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVy"
    "biBGYWxzZQoKICAgIGRlZiBidWlsZF9jb250ZXh0X2Zvcl9sYW5ndWFnZShzZWxmLCBsYW5ndWFn"
    "ZTogc3RyLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIG1heF9jaGFyczogaW50"
    "ID0gMTUwMCkgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIEJ1aWxkIGEgY29udGV4dCBzdHJp"
    "bmcgb2YgYWxsIHJ1bGVzIGZvciBhIGdpdmVuIGxhbmd1YWdlLgogICAgICAgIEZvciBpbmplY3Rp"
    "b24gaW50byBzeXN0ZW0gcHJvbXB0IGJlZm9yZSBjb2RlIHNlc3Npb25zLgogICAgICAgICIiIgog"
    "ICAgICAgIHJlY29yZHMgPSBzZWxmLnNlYXJjaChsYW5ndWFnZT1sYW5ndWFnZSkKICAgICAgICBp"
    "ZiBub3QgcmVjb3JkczoKICAgICAgICAgICAgcmV0dXJuICIiCgogICAgICAgIHBhcnRzID0gW2Yi"
    "W3tsYW5ndWFnZS51cHBlcigpfSBSVUxFUyDigJQgQVBQTFkgQkVGT1JFIFdSSVRJTkcgQ09ERV0i"
    "XQogICAgICAgIHRvdGFsID0gMAogICAgICAgIGZvciByIGluIHJlY29yZHM6CiAgICAgICAgICAg"
    "IGVudHJ5ID0gZiLigKIge3IuZ2V0KCdyZWZlcmVuY2Vfa2V5JywnJyl9OiB7ci5nZXQoJ2Z1bGxf"
    "cnVsZScsJycpfSIKICAgICAgICAgICAgaWYgdG90YWwgKyBsZW4oZW50cnkpID4gbWF4X2NoYXJz"
    "OgogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGVudHJ5KQog"
    "ICAgICAgICAgICB0b3RhbCArPSBsZW4oZW50cnkpCgogICAgICAgIHBhcnRzLmFwcGVuZChmIltF"
    "TkQge2xhbmd1YWdlLnVwcGVyKCl9IFJVTEVTXSIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihw"
    "YXJ0cykKCiAgICBkZWYgX2lzX2R1cGxpY2F0ZShzZWxmLCByZWZlcmVuY2Vfa2V5OiBzdHIpIC0+"
    "IGJvb2w6CiAgICAgICAgcmV0dXJuIGFueSgKICAgICAgICAgICAgci5nZXQoInJlZmVyZW5jZV9r"
    "ZXkiLCIiKS5sb3dlcigpID09IHJlZmVyZW5jZV9rZXkubG93ZXIoKQogICAgICAgICAgICBmb3Ig"
    "ciBpbiByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgKQoKICAgIGRlZiBzZWVkX2xzbF9y"
    "dWxlcyhzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIFNlZWQgdGhlIExTTCBGb3Ji"
    "aWRkZW4gUnVsZXNldCBvbiBmaXJzdCBydW4gaWYgdGhlIERCIGlzIGVtcHR5LgogICAgICAgIFRo"
    "ZXNlIGFyZSB0aGUgaGFyZCBydWxlcyBmcm9tIHRoZSBwcm9qZWN0IHN0YW5kaW5nIHJ1bGVzLgog"
    "ICAgICAgICIiIgogICAgICAgIGlmIHJlYWRfanNvbmwoc2VsZi5fcGF0aCk6CiAgICAgICAgICAg"
    "IHJldHVybiAgIyBBbHJlYWR5IHNlZWRlZAoKICAgICAgICBsc2xfcnVsZXMgPSBbCiAgICAgICAg"
    "ICAgICgiTFNMIiwgIkxTTCIsICJOT19URVJOQVJZIiwKICAgICAgICAgICAgICJObyB0ZXJuYXJ5"
    "IG9wZXJhdG9ycyBpbiBMU0wiLAogICAgICAgICAgICAgIk5ldmVyIHVzZSB0aGUgdGVybmFyeSBv"
    "cGVyYXRvciAoPzopIGluIExTTCBzY3JpcHRzLiAiCiAgICAgICAgICAgICAiVXNlIGlmL2Vsc2Ug"
    "YmxvY2tzIGluc3RlYWQuIExTTCBkb2VzIG5vdCBzdXBwb3J0IHRlcm5hcnkuIiwKICAgICAgICAg"
    "ICAgICJSZXBsYWNlIHdpdGggaWYvZWxzZSBibG9jay4iLCAiIiksCiAgICAgICAgICAgICgiTFNM"
    "IiwgIkxTTCIsICJOT19GT1JFQUNIIiwKICAgICAgICAgICAgICJObyBmb3JlYWNoIGxvb3BzIGlu"
    "IExTTCIsCiAgICAgICAgICAgICAiTFNMIGhhcyBubyBmb3JlYWNoIGxvb3AgY29uc3RydWN0LiBV"
    "c2UgaW50ZWdlciBpbmRleCB3aXRoICIKICAgICAgICAgICAgICJsbEdldExpc3RMZW5ndGgoKSBh"
    "bmQgYSBmb3Igb3Igd2hpbGUgbG9vcC4iLAogICAgICAgICAgICAgIlVzZTogZm9yKGludGVnZXIg"
    "aT0wOyBpPGxsR2V0TGlzdExlbmd0aChteUxpc3QpOyBpKyspIiwgIiIpLAogICAgICAgICAgICAo"
    "IkxTTCIsICJMU0wiLCAiTk9fR0xPQkFMX0FTU0lHTl9GUk9NX0ZVTkMiLAogICAgICAgICAgICAg"
    "Ik5vIGdsb2JhbCB2YXJpYWJsZSBhc3NpZ25tZW50cyBmcm9tIGZ1bmN0aW9uIGNhbGxzIiwKICAg"
    "ICAgICAgICAgICJHbG9iYWwgdmFyaWFibGUgaW5pdGlhbGl6YXRpb24gaW4gTFNMIGNhbm5vdCBj"
    "YWxsIGZ1bmN0aW9ucy4gIgogICAgICAgICAgICAgIkluaXRpYWxpemUgZ2xvYmFscyB3aXRoIGxp"
    "dGVyYWwgdmFsdWVzIG9ubHkuICIKICAgICAgICAgICAgICJBc3NpZ24gZnJvbSBmdW5jdGlvbnMg"
    "aW5zaWRlIGV2ZW50IGhhbmRsZXJzIG9yIG90aGVyIGZ1bmN0aW9ucy4iLAogICAgICAgICAgICAg"
    "Ik1vdmUgdGhlIGFzc2lnbm1lbnQgaW50byBhbiBldmVudCBoYW5kbGVyIChzdGF0ZV9lbnRyeSwg"
    "ZXRjLikiLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19WT0lEX0tFWVdPUkQi"
    "LAogICAgICAgICAgICAgIk5vIHZvaWQga2V5d29yZCBpbiBMU0wiLAogICAgICAgICAgICAgIkxT"
    "TCBkb2VzIG5vdCBoYXZlIGEgdm9pZCBrZXl3b3JkIGZvciBmdW5jdGlvbiByZXR1cm4gdHlwZXMu"
    "ICIKICAgICAgICAgICAgICJGdW5jdGlvbnMgdGhhdCByZXR1cm4gbm90aGluZyBzaW1wbHkgb21p"
    "dCB0aGUgcmV0dXJuIHR5cGUuIiwKICAgICAgICAgICAgICJSZW1vdmUgJ3ZvaWQnIGZyb20gZnVu"
    "Y3Rpb24gc2lnbmF0dXJlLiAiCiAgICAgICAgICAgICAiZS5nLiBteUZ1bmMoKSB7IC4uLiB9IG5v"
    "dCB2b2lkIG15RnVuYygpIHsgLi4uIH0iLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIs"
    "ICJDT01QTEVURV9TQ1JJUFRTX09OTFkiLAogICAgICAgICAgICAgIkFsd2F5cyBwcm92aWRlIGNv"
    "bXBsZXRlIHNjcmlwdHMsIG5ldmVyIHBhcnRpYWwgZWRpdHMiLAogICAgICAgICAgICAgIldoZW4g"
    "d3JpdGluZyBvciBlZGl0aW5nIExTTCBzY3JpcHRzLCBhbHdheXMgb3V0cHV0IHRoZSBjb21wbGV0"
    "ZSAiCiAgICAgICAgICAgICAic2NyaXB0LiBOZXZlciBwcm92aWRlIHBhcnRpYWwgc25pcHBldHMg"
    "b3IgJ2FkZCB0aGlzIHNlY3Rpb24nICIKICAgICAgICAgICAgICJpbnN0cnVjdGlvbnMuIFRoZSBm"
    "dWxsIHNjcmlwdCBtdXN0IGJlIGNvcHktcGFzdGUgcmVhZHkuIiwKICAgICAgICAgICAgICJXcml0"
    "ZSB0aGUgZW50aXJlIHNjcmlwdCBmcm9tIHRvcCB0byBib3R0b20uIiwgIiIpLAogICAgICAgIF0K"
    "CiAgICAgICAgZm9yIGVudiwgbGFuZywgcmVmLCBzdW1tYXJ5LCBmdWxsX3J1bGUsIHJlc29sdXRp"
    "b24sIGxpbmsgaW4gbHNsX3J1bGVzOgogICAgICAgICAgICBzZWxmLmFkZChlbnYsIGxhbmcsIHJl"
    "Ziwgc3VtbWFyeSwgZnVsbF9ydWxlLCByZXNvbHV0aW9uLCBsaW5rLAogICAgICAgICAgICAgICAg"
    "ICAgICB0YWdzPVsibHNsIiwgImZvcmJpZGRlbiIsICJzdGFuZGluZ19ydWxlIl0pCgoKIyDilIDi"
    "lIAgVEFTSyBNQU5BR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBUYXNrTWFuYWdlcjoKICAgICIiIgog"
    "ICAgVGFzay9yZW1pbmRlciBDUlVEIGFuZCBkdWUtZXZlbnQgZGV0ZWN0aW9uLgoKICAgIEZpbGU6"
    "IG1lbW9yaWVzL3Rhc2tzLmpzb25sCgogICAgVGFzayByZWNvcmQgZmllbGRzOgogICAgICAgIGlk"
    "LCBjcmVhdGVkX2F0LCBkdWVfYXQsIHByZV90cmlnZ2VyICgxbWluIGJlZm9yZSksCiAgICAgICAg"
    "dGV4dCwgc3RhdHVzIChwZW5kaW5nfHRyaWdnZXJlZHxzbm9vemVkfGNvbXBsZXRlZHxjYW5jZWxs"
    "ZWQpLAogICAgICAgIGFja25vd2xlZGdlZF9hdCwgcmV0cnlfY291bnQsIGxhc3RfdHJpZ2dlcmVk"
    "X2F0LCBuZXh0X3JldHJ5X2F0LAogICAgICAgIHNvdXJjZSAobG9jYWx8Z29vZ2xlKSwgZ29vZ2xl"
    "X2V2ZW50X2lkLCBzeW5jX3N0YXR1cywgbWV0YWRhdGEKCiAgICBEdWUtZXZlbnQgY3ljbGU6CiAg"
    "ICAgICAgLSBQcmUtdHJpZ2dlcjogMSBtaW51dGUgYmVmb3JlIGR1ZSDihpIgYW5ub3VuY2UgdXBj"
    "b21pbmcKICAgICAgICAtIER1ZSB0cmlnZ2VyOiBhdCBkdWUgdGltZSDihpIgYWxlcnQgc291bmQg"
    "KyBBSSBjb21tZW50YXJ5CiAgICAgICAgLSAzLW1pbnV0ZSB3aW5kb3c6IGlmIG5vdCBhY2tub3ds"
    "ZWRnZWQg4oaSIHNub296ZQogICAgICAgIC0gMTItbWludXRlIHJldHJ5OiByZS10cmlnZ2VyCiAg"
    "ICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fcGF0aCA9IGNmZ19w"
    "YXRoKCJtZW1vcmllcyIpIC8gInRhc2tzLmpzb25sIgoKICAgICMg4pSA4pSAIENSVUQg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICBkZWYgbG9hZF9hbGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICB0YXNrcyA9IHJl"
    "YWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBjaGFuZ2VkID0gRmFsc2UKICAgICAgICBub3Jt"
    "YWxpemVkID0gW10KICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgbm90IGlz"
    "aW5zdGFuY2UodCwgZGljdCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBp"
    "ZiAiaWQiIG5vdCBpbiB0OgogICAgICAgICAgICAgICAgdFsiaWQiXSA9IGYidGFza197dXVpZC51"
    "dWlkNCgpLmhleFs6MTBdfSIKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAg"
    "ICAgICMgTm9ybWFsaXplIGZpZWxkIG5hbWVzCiAgICAgICAgICAgIGlmICJkdWVfYXQiIG5vdCBp"
    "biB0OgogICAgICAgICAgICAgICAgdFsiZHVlX2F0Il0gPSB0LmdldCgiZHVlIikKICAgICAgICAg"
    "ICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3RhdHVzIiwg"
    "ICAgICAgICAgICJwZW5kaW5nIikKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJyZXRyeV9jb3Vu"
    "dCIsICAgICAgMCkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJhY2tub3dsZWRnZWRfYXQiLCAg"
    "Tm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJsYXN0X3RyaWdnZXJlZF9hdCIsTm9uZSkK"
    "ICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJuZXh0X3JldHJ5X2F0IiwgICAgTm9uZSkKICAgICAg"
    "ICAgICAgdC5zZXRkZWZhdWx0KCJwcmVfYW5ub3VuY2VkIiwgICAgRmFsc2UpCiAgICAgICAgICAg"
    "IHQuc2V0ZGVmYXVsdCgic291cmNlIiwgICAgICAgICAgICJsb2NhbCIpCiAgICAgICAgICAgIHQu"
    "c2V0ZGVmYXVsdCgiZ29vZ2xlX2V2ZW50X2lkIiwgIE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVm"
    "YXVsdCgic3luY19zdGF0dXMiLCAgICAgICJwZW5kaW5nIikKICAgICAgICAgICAgdC5zZXRkZWZh"
    "dWx0KCJtZXRhZGF0YSIsICAgICAgICAge30pCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiY3Jl"
    "YXRlZF9hdCIsICAgICAgIGxvY2FsX25vd19pc28oKSkKCiAgICAgICAgICAgICMgQ29tcHV0ZSBw"
    "cmVfdHJpZ2dlciBpZiBtaXNzaW5nCiAgICAgICAgICAgIGlmIHQuZ2V0KCJkdWVfYXQiKSBhbmQg"
    "bm90IHQuZ2V0KCJwcmVfdHJpZ2dlciIpOgogICAgICAgICAgICAgICAgZHQgPSBwYXJzZV9pc28o"
    "dFsiZHVlX2F0Il0pCiAgICAgICAgICAgICAgICBpZiBkdDoKICAgICAgICAgICAgICAgICAgICBw"
    "cmUgPSBkdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpCiAgICAgICAgICAgICAgICAgICAgdFsicHJl"
    "X3RyaWdnZXIiXSA9IHByZS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAg"
    "ICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgICAgICBub3JtYWxpemVkLmFwcGVuZCh0"
    "KQoKICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRo"
    "LCBub3JtYWxpemVkKQogICAgICAgIHJldHVybiBub3JtYWxpemVkCgogICAgZGVmIHNhdmVfYWxs"
    "KHNlbGYsIHRhc2tzOiBsaXN0W2RpY3RdKSAtPiBOb25lOgogICAgICAgIHdyaXRlX2pzb25sKHNl"
    "bGYuX3BhdGgsIHRhc2tzKQoKICAgIGRlZiBhZGQoc2VsZiwgdGV4dDogc3RyLCBkdWVfZHQ6IGRh"
    "dGV0aW1lLAogICAgICAgICAgICBzb3VyY2U6IHN0ciA9ICJsb2NhbCIpIC0+IGRpY3Q6CiAgICAg"
    "ICAgcHJlID0gZHVlX2R0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkKICAgICAgICB0YXNrID0gewog"
    "ICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICAgIGYidGFza197dXVpZC51dWlkNCgpLmhleFs6"
    "MTBdfSIsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgICAgbG9jYWxfbm93X2lzbygpLAog"
    "ICAgICAgICAgICAiZHVlX2F0IjogICAgICAgICAgIGR1ZV9kdC5pc29mb3JtYXQodGltZXNwZWM9"
    "InNlY29uZHMiKSwKICAgICAgICAgICAgInByZV90cmlnZ2VyIjogICAgICBwcmUuaXNvZm9ybWF0"
    "KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICJ0ZXh0IjogICAgICAgICAgICAgdGV4"
    "dC5zdHJpcCgpLAogICAgICAgICAgICAic3RhdHVzIjogICAgICAgICAgICJwZW5kaW5nIiwKICAg"
    "ICAgICAgICAgImFja25vd2xlZGdlZF9hdCI6ICBOb25lLAogICAgICAgICAgICAicmV0cnlfY291"
    "bnQiOiAgICAgIDAsCiAgICAgICAgICAgICJsYXN0X3RyaWdnZXJlZF9hdCI6Tm9uZSwKICAgICAg"
    "ICAgICAgIm5leHRfcmV0cnlfYXQiOiAgICBOb25lLAogICAgICAgICAgICAicHJlX2Fubm91bmNl"
    "ZCI6ICAgIEZhbHNlLAogICAgICAgICAgICAic291cmNlIjogICAgICAgICAgIHNvdXJjZSwKICAg"
    "ICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6ICBOb25lLAogICAgICAgICAgICAic3luY19zdGF0"
    "dXMiOiAgICAgICJwZW5kaW5nIiwKICAgICAgICAgICAgIm1ldGFkYXRhIjogICAgICAgICB7fSwK"
    "ICAgICAgICB9CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICB0YXNrcy5h"
    "cHBlbmQodGFzaykKICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgIHJldHVybiB0"
    "YXNrCgogICAgZGVmIHVwZGF0ZV9zdGF0dXMoc2VsZiwgdGFza19pZDogc3RyLCBzdGF0dXM6IHN0"
    "ciwKICAgICAgICAgICAgICAgICAgICAgIGFja25vd2xlZGdlZDogYm9vbCA9IEZhbHNlKSAtPiBP"
    "cHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZv"
    "ciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAg"
    "ICAgICAgICAgICAgdFsic3RhdHVzIl0gPSBzdGF0dXMKICAgICAgICAgICAgICAgIGlmIGFja25v"
    "d2xlZGdlZDoKICAgICAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2Fs"
    "X25vd19pc28oKQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAg"
    "ICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY29tcGxldGUoc2Vs"
    "ZiwgdGFza19pZDogc3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYu"
    "bG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgi"
    "aWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gICAgICAgICAgPSAi"
    "Y29tcGxldGVkIgogICAgICAgICAgICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9u"
    "b3dfaXNvKCkKICAgICAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAg"
    "ICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNhbmNlbChzZWxmLCB0"
    "YXNrX2lkOiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2Fk"
    "X2FsbCgpCiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIp"
    "ID09IHRhc2tfaWQ6CiAgICAgICAgICAgICAgICB0WyJzdGF0dXMiXSAgICAgICAgICA9ICJjYW5j"
    "ZWxsZWQiCiAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19p"
    "c28oKQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAg"
    "IHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY2xlYXJfY29tcGxldGVkKHNl"
    "bGYpIC0+IGludDoKICAgICAgICB0YXNrcyAgICA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGtl"
    "cHQgICAgID0gW3QgZm9yIHQgaW4gdGFza3MKICAgICAgICAgICAgICAgICAgICBpZiB0LmdldCgi"
    "c3RhdHVzIikgbm90IGluIHsiY29tcGxldGVkIiwiY2FuY2VsbGVkIn1dCiAgICAgICAgcmVtb3Zl"
    "ZCAgPSBsZW4odGFza3MpIC0gbGVuKGtlcHQpCiAgICAgICAgaWYgcmVtb3ZlZDoKICAgICAgICAg"
    "ICAgc2VsZi5zYXZlX2FsbChrZXB0KQogICAgICAgIHJldHVybiByZW1vdmVkCgogICAgZGVmIHVw"
    "ZGF0ZV9nb29nbGVfc3luYyhzZWxmLCB0YXNrX2lkOiBzdHIsIHN5bmNfc3RhdHVzOiBzdHIsCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIGdvb2dsZV9ldmVudF9pZDogc3RyID0gIiIsCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGVycm9yOiBzdHIgPSAiIikgLT4gT3B0aW9uYWxbZGljdF06"
    "CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBmb3IgdCBpbiB0YXNrczoK"
    "ICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0gdGFza19pZDoKICAgICAgICAgICAgICAgIHRb"
    "InN5bmNfc3RhdHVzIl0gICAgPSBzeW5jX3N0YXR1cwogICAgICAgICAgICAgICAgdFsibGFzdF9z"
    "eW5jZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgaWYgZ29vZ2xlX2V2"
    "ZW50X2lkOgogICAgICAgICAgICAgICAgICAgIHRbImdvb2dsZV9ldmVudF9pZCJdID0gZ29vZ2xl"
    "X2V2ZW50X2lkCiAgICAgICAgICAgICAgICBpZiBlcnJvcjoKICAgICAgICAgICAgICAgICAgICB0"
    "LnNldGRlZmF1bHQoIm1ldGFkYXRhIiwge30pCiAgICAgICAgICAgICAgICAgICAgdFsibWV0YWRh"
    "dGEiXVsiZ29vZ2xlX3N5bmNfZXJyb3IiXSA9IGVycm9yWzoyNDBdCiAgICAgICAgICAgICAgICBz"
    "ZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICAgICAgcmV0dXJuIHQKICAgICAgICByZXR1"
    "cm4gTm9uZQoKICAgICMg4pSA4pSAIERVRSBFVkVOVCBERVRFQ1RJT04g4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICBkZWYgZ2V0X2R1ZV9ldmVudHMoc2VsZikgLT4gbGlzdFt0dXBsZVtzdHIsIGRpY3Rd"
    "XToKICAgICAgICAiIiIKICAgICAgICBDaGVjayBhbGwgdGFza3MgZm9yIGR1ZS9wcmUtdHJpZ2dl"
    "ci9yZXRyeSBldmVudHMuCiAgICAgICAgUmV0dXJucyBsaXN0IG9mIChldmVudF90eXBlLCB0YXNr"
    "KSB0dXBsZXMuCiAgICAgICAgZXZlbnRfdHlwZTogInByZSIgfCAiZHVlIiB8ICJyZXRyeSIKCiAg"
    "ICAgICAgTW9kaWZpZXMgdGFzayBzdGF0dXNlcyBpbiBwbGFjZSBhbmQgc2F2ZXMuCiAgICAgICAg"
    "Q2FsbCBmcm9tIEFQU2NoZWR1bGVyIGV2ZXJ5IDMwIHNlY29uZHMuCiAgICAgICAgIiIiCiAgICAg"
    "ICAgbm93ICAgID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpCiAgICAgICAgdGFza3MgID0g"
    "c2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZXZlbnRzID0gW10KICAgICAgICBjaGFuZ2VkID0gRmFs"
    "c2UKCiAgICAgICAgZm9yIHRhc2sgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHRhc2suZ2V0KCJh"
    "Y2tub3dsZWRnZWRfYXQiKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBz"
    "dGF0dXMgICA9IHRhc2suZ2V0KCJzdGF0dXMiLCAicGVuZGluZyIpCiAgICAgICAgICAgIGR1ZSAg"
    "ICAgID0gc2VsZi5fcGFyc2VfbG9jYWwodGFzay5nZXQoImR1ZV9hdCIpKQogICAgICAgICAgICBw"
    "cmUgICAgICA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJwcmVfdHJpZ2dlciIpKQogICAg"
    "ICAgICAgICBuZXh0X3JldCA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJuZXh0X3JldHJ5"
    "X2F0IikpCiAgICAgICAgICAgIGRlYWRsaW5lID0gc2VsZi5fcGFyc2VfbG9jYWwodGFzay5nZXQo"
    "ImFsZXJ0X2RlYWRsaW5lIikpCgogICAgICAgICAgICAjIFByZS10cmlnZ2VyCiAgICAgICAgICAg"
    "IGlmIChzdGF0dXMgPT0gInBlbmRpbmciIGFuZCBwcmUgYW5kIG5vdyA+PSBwcmUKICAgICAgICAg"
    "ICAgICAgICAgICBhbmQgbm90IHRhc2suZ2V0KCJwcmVfYW5ub3VuY2VkIikpOgogICAgICAgICAg"
    "ICAgICAgdGFza1sicHJlX2Fubm91bmNlZCJdID0gVHJ1ZQogICAgICAgICAgICAgICAgZXZlbnRz"
    "LmFwcGVuZCgoInByZSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAg"
    "ICAgICAgICAgICMgRHVlIHRyaWdnZXIKICAgICAgICAgICAgaWYgc3RhdHVzID09ICJwZW5kaW5n"
    "IiBhbmQgZHVlIGFuZCBub3cgPj0gZHVlOgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0g"
    "ICAgICAgICAgID0gInRyaWdnZXJlZCIKICAgICAgICAgICAgICAgIHRhc2tbImxhc3RfdHJpZ2dl"
    "cmVkX2F0Il09IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgdGFza1siYWxlcnRfZGVh"
    "ZGxpbmUiXSAgID0gKAogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmFzdGltZXpv"
    "bmUoKSArIHRpbWVkZWx0YShtaW51dGVzPTMpCiAgICAgICAgICAgICAgICApLmlzb2Zvcm1hdCh0"
    "aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICBldmVudHMuYXBwZW5kKCgiZHVlIiwg"
    "dGFzaykpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgY29u"
    "dGludWUKCiAgICAgICAgICAgICMgU25vb3plIGFmdGVyIDMtbWludXRlIHdpbmRvdwogICAgICAg"
    "ICAgICBpZiBzdGF0dXMgPT0gInRyaWdnZXJlZCIgYW5kIGRlYWRsaW5lIGFuZCBub3cgPj0gZGVh"
    "ZGxpbmU6CiAgICAgICAgICAgICAgICB0YXNrWyJzdGF0dXMiXSAgICAgICAgPSAic25vb3plZCIK"
    "ICAgICAgICAgICAgICAgIHRhc2tbIm5leHRfcmV0cnlfYXQiXSA9ICgKICAgICAgICAgICAgICAg"
    "ICAgICBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0xMikK"
    "ICAgICAgICAgICAgICAgICkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAg"
    "ICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAg"
    "ICAgIyBSZXRyeQogICAgICAgICAgICBpZiBzdGF0dXMgaW4geyJyZXRyeV9wZW5kaW5nIiwic25v"
    "b3plZCJ9IGFuZCBuZXh0X3JldCBhbmQgbm93ID49IG5leHRfcmV0OgogICAgICAgICAgICAgICAg"
    "dGFza1sic3RhdHVzIl0gICAgICAgICAgICA9ICJ0cmlnZ2VyZWQiCiAgICAgICAgICAgICAgICB0"
    "YXNrWyJyZXRyeV9jb3VudCJdICAgICAgID0gaW50KHRhc2suZ2V0KCJyZXRyeV9jb3VudCIsMCkp"
    "ICsgMQogICAgICAgICAgICAgICAgdGFza1sibGFzdF90cmlnZ2VyZWRfYXQiXSA9IGxvY2FsX25v"
    "d19pc28oKQogICAgICAgICAgICAgICAgdGFza1siYWxlcnRfZGVhZGxpbmUiXSAgICA9ICgKICAg"
    "ICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEo"
    "bWludXRlcz0zKQogICAgICAgICAgICAgICAgKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMi"
    "KQogICAgICAgICAgICAgICAgdGFza1sibmV4dF9yZXRyeV9hdCJdICAgICA9IE5vbmUKICAgICAg"
    "ICAgICAgICAgIGV2ZW50cy5hcHBlbmQoKCJyZXRyeSIsIHRhc2spKQogICAgICAgICAgICAgICAg"
    "Y2hhbmdlZCA9IFRydWUKCiAgICAgICAgaWYgY2hhbmdlZDoKICAgICAgICAgICAgc2VsZi5zYXZl"
    "X2FsbCh0YXNrcykKICAgICAgICByZXR1cm4gZXZlbnRzCgogICAgZGVmIF9wYXJzZV9sb2NhbChz"
    "ZWxmLCB2YWx1ZTogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICAgICAgIiIiUGFyc2Ug"
    "SVNPIHN0cmluZyB0byB0aW1lem9uZS1hd2FyZSBkYXRldGltZSBmb3IgY29tcGFyaXNvbi4iIiIK"
    "ICAgICAgICBkdCA9IHBhcnNlX2lzbyh2YWx1ZSkKICAgICAgICBpZiBkdCBpcyBOb25lOgogICAg"
    "ICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGlmIGR0LnR6aW5mbyBpcyBOb25lOgogICAgICAg"
    "ICAgICBkdCA9IGR0LmFzdGltZXpvbmUoKQogICAgICAgIHJldHVybiBkdAoKICAgICMg4pSA4pSA"
    "IE5BVFVSQUwgTEFOR1VBR0UgUEFSU0lORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBj"
    "bGFzc2lmeV9pbnRlbnQodGV4dDogc3RyKSAtPiBkaWN0OgogICAgICAgICIiIgogICAgICAgIENs"
    "YXNzaWZ5IHVzZXIgaW5wdXQgYXMgdGFzay9yZW1pbmRlci90aW1lci9jaGF0LgogICAgICAgIFJl"
    "dHVybnMgeyJpbnRlbnQiOiBzdHIsICJjbGVhbmVkX2lucHV0Ijogc3RyfQogICAgICAgICIiIgog"
    "ICAgICAgIGltcG9ydCByZQogICAgICAgICMgU3RyaXAgY29tbW9uIGludm9jYXRpb24gcHJlZml4"
    "ZXMKICAgICAgICBjbGVhbmVkID0gcmUuc3ViKAogICAgICAgICAgICByZiJeXHMqKD86e0RFQ0tf"
    "TkFNRS5sb3dlcigpfXxoZXlccyt7REVDS19OQU1FLmxvd2VyKCl9KVxzKiw/XHMqWzpcLV0/XHMq"
    "IiwKICAgICAgICAgICAgIiIsIHRleHQsIGZsYWdzPXJlLkkKICAgICAgICApLnN0cmlwKCkKCiAg"
    "ICAgICAgbG93ID0gY2xlYW5lZC5sb3dlcigpCgogICAgICAgIHRpbWVyX3BhdHMgICAgPSBbciJc"
    "YnNldCg/OlxzK2EpP1xzK3RpbWVyXGIiLCByIlxidGltZXJccytmb3JcYiIsCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICByIlxic3RhcnQoPzpccythKT9ccyt0aW1lclxiIl0KICAgICAgICByZW1p"
    "bmRlcl9wYXRzID0gW3IiXGJyZW1pbmQgbWVcYiIsIHIiXGJzZXQoPzpccythKT9ccytyZW1pbmRl"
    "clxiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJhZGQoPzpccythKT9ccytyZW1pbmRl"
    "clxiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJzZXQoPzpccythbj8pP1xzK2FsYXJt"
    "XGIiLCByIlxiYWxhcm1ccytmb3JcYiJdCiAgICAgICAgdGFza19wYXRzICAgICA9IFtyIlxiYWRk"
    "KD86XHMrYSk/XHMrdGFza1xiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJjcmVhdGUo"
    "PzpccythKT9ccyt0YXNrXGIiLCByIlxibmV3XHMrdGFza1xiIl0KCiAgICAgICAgaW1wb3J0IHJl"
    "IGFzIF9yZQogICAgICAgIGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gdGltZXJf"
    "cGF0cyk6CiAgICAgICAgICAgIGludGVudCA9ICJ0aW1lciIKICAgICAgICBlbGlmIGFueShfcmUu"
    "c2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gcmVtaW5kZXJfcGF0cyk6CiAgICAgICAgICAgIGludGVu"
    "dCA9ICJyZW1pbmRlciIKICAgICAgICBlbGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAg"
    "aW4gdGFza19wYXRzKToKICAgICAgICAgICAgaW50ZW50ID0gInRhc2siCiAgICAgICAgZWxzZToK"
    "ICAgICAgICAgICAgaW50ZW50ID0gImNoYXQiCgogICAgICAgIHJldHVybiB7ImludGVudCI6IGlu"
    "dGVudCwgImNsZWFuZWRfaW5wdXQiOiBjbGVhbmVkfQoKICAgIEBzdGF0aWNtZXRob2QKICAgIGRl"
    "ZiBwYXJzZV9kdWVfZGF0ZXRpbWUodGV4dDogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAg"
    "ICAgICAgIiIiCiAgICAgICAgUGFyc2UgbmF0dXJhbCBsYW5ndWFnZSB0aW1lIGV4cHJlc3Npb24g"
    "ZnJvbSB0YXNrIHRleHQuCiAgICAgICAgSGFuZGxlczogImluIDMwIG1pbnV0ZXMiLCAiYXQgM3Bt"
    "IiwgInRvbW9ycm93IGF0IDlhbSIsCiAgICAgICAgICAgICAgICAgImluIDIgaG91cnMiLCAiYXQg"
    "MTU6MzAiLCBldGMuCiAgICAgICAgUmV0dXJucyBhIGRhdGV0aW1lIG9yIE5vbmUgaWYgdW5wYXJz"
    "ZWFibGUuCiAgICAgICAgIiIiCiAgICAgICAgaW1wb3J0IHJlCiAgICAgICAgbm93ICA9IGRhdGV0"
    "aW1lLm5vdygpCiAgICAgICAgbG93ICA9IHRleHQubG93ZXIoKS5zdHJpcCgpCgogICAgICAgICMg"
    "ImluIFggbWludXRlcy9ob3Vycy9kYXlzIgogICAgICAgIG0gPSByZS5zZWFyY2goCiAgICAgICAg"
    "ICAgIHIiaW5ccysoXGQrKVxzKihtaW51dGV8bWlufGhvdXJ8aHJ8ZGF5fHNlY29uZHxzZWMpIiwK"
    "ICAgICAgICAgICAgbG93CiAgICAgICAgKQogICAgICAgIGlmIG06CiAgICAgICAgICAgIG4gICAg"
    "PSBpbnQobS5ncm91cCgxKSkKICAgICAgICAgICAgdW5pdCA9IG0uZ3JvdXAoMikKICAgICAgICAg"
    "ICAgaWYgIm1pbiIgaW4gdW5pdDogIHJldHVybiBub3cgKyB0aW1lZGVsdGEobWludXRlcz1uKQog"
    "ICAgICAgICAgICBpZiAiaG91ciIgaW4gdW5pdCBvciAiaHIiIGluIHVuaXQ6IHJldHVybiBub3cg"
    "KyB0aW1lZGVsdGEoaG91cnM9bikKICAgICAgICAgICAgaWYgImRheSIgIGluIHVuaXQ6IHJldHVy"
    "biBub3cgKyB0aW1lZGVsdGEoZGF5cz1uKQogICAgICAgICAgICBpZiAic2VjIiAgaW4gdW5pdDog"
    "cmV0dXJuIG5vdyArIHRpbWVkZWx0YShzZWNvbmRzPW4pCgogICAgICAgICMgImF0IEhIOk1NIiBv"
    "ciAiYXQgSDpNTWFtL3BtIgogICAgICAgIG0gPSByZS5zZWFyY2goCiAgICAgICAgICAgIHIiYXRc"
    "cysoXGR7MSwyfSkoPzo6KFxkezJ9KSk/XHMqKGFtfHBtKT8iLAogICAgICAgICAgICBsb3cKICAg"
    "ICAgICApCiAgICAgICAgaWYgbToKICAgICAgICAgICAgaHIgID0gaW50KG0uZ3JvdXAoMSkpCiAg"
    "ICAgICAgICAgIG1uICA9IGludChtLmdyb3VwKDIpKSBpZiBtLmdyb3VwKDIpIGVsc2UgMAogICAg"
    "ICAgICAgICBhcG0gPSBtLmdyb3VwKDMpCiAgICAgICAgICAgIGlmIGFwbSA9PSAicG0iIGFuZCBo"
    "ciA8IDEyOiBociArPSAxMgogICAgICAgICAgICBpZiBhcG0gPT0gImFtIiBhbmQgaHIgPT0gMTI6"
    "IGhyID0gMAogICAgICAgICAgICBkdCA9IG5vdy5yZXBsYWNlKGhvdXI9aHIsIG1pbnV0ZT1tbiwg"
    "c2Vjb25kPTAsIG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgIGlmIGR0IDw9IG5vdzoKICAgICAg"
    "ICAgICAgICAgIGR0ICs9IHRpbWVkZWx0YShkYXlzPTEpCiAgICAgICAgICAgIHJldHVybiBkdAoK"
    "ICAgICAgICAjICJ0b21vcnJvdyBhdCAuLi4iICAocmVjdXJzZSBvbiB0aGUgImF0IiBwYXJ0KQog"
    "ICAgICAgIGlmICJ0b21vcnJvdyIgaW4gbG93OgogICAgICAgICAgICB0b21vcnJvd190ZXh0ID0g"
    "cmUuc3ViKHIidG9tb3Jyb3ciLCAiIiwgbG93KS5zdHJpcCgpCiAgICAgICAgICAgIHJlc3VsdCA9"
    "IFRhc2tNYW5hZ2VyLnBhcnNlX2R1ZV9kYXRldGltZSh0b21vcnJvd190ZXh0KQogICAgICAgICAg"
    "ICBpZiByZXN1bHQ6CiAgICAgICAgICAgICAgICByZXR1cm4gcmVzdWx0ICsgdGltZWRlbHRhKGRh"
    "eXM9MSkKCiAgICAgICAgcmV0dXJuIE5vbmUKCgojIOKUgOKUgCBSRVFVSVJFTUVOVFMuVFhUIEdF"
    "TkVSQVRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIHdyaXRlX3JlcXVpcmVt"
    "ZW50c190eHQoKSAtPiBOb25lOgogICAgIiIiCiAgICBXcml0ZSByZXF1aXJlbWVudHMudHh0IG5l"
    "eHQgdG8gdGhlIGRlY2sgZmlsZSBvbiBmaXJzdCBydW4uCiAgICBIZWxwcyB1c2VycyBpbnN0YWxs"
    "IGFsbCBkZXBlbmRlbmNpZXMgd2l0aCBvbmUgcGlwIGNvbW1hbmQuCiAgICAiIiIKICAgIHJlcV9w"
    "YXRoID0gUGF0aChDRkcuZ2V0KCJiYXNlX2RpciIsIHN0cihTQ1JJUFRfRElSKSkpIC8gInJlcXVp"
    "cmVtZW50cy50eHQiCiAgICBpZiByZXFfcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4KCiAg"
    "ICBjb250ZW50ID0gIiIiXAojIE1vcmdhbm5hIERlY2sg4oCUIFJlcXVpcmVkIERlcGVuZGVuY2ll"
    "cwojIEluc3RhbGwgYWxsIHdpdGg6IHBpcCBpbnN0YWxsIC1yIHJlcXVpcmVtZW50cy50eHQKCiMg"
    "Q29yZSBVSQpQeVNpZGU2CgojIFNjaGVkdWxpbmcgKGlkbGUgdGltZXIsIGF1dG9zYXZlLCByZWZs"
    "ZWN0aW9uIGN5Y2xlcykKYXBzY2hlZHVsZXIKCiMgTG9nZ2luZwpsb2d1cnUKCiMgU291bmQgcGxh"
    "eWJhY2sgKFdBViArIE1QMykKcHlnYW1lCgojIERlc2t0b3Agc2hvcnRjdXQgY3JlYXRpb24gKFdp"
    "bmRvd3Mgb25seSkKcHl3aW4zMgoKIyBTeXN0ZW0gbW9uaXRvcmluZyAoQ1BVLCBSQU0sIGRyaXZl"
    "cywgbmV0d29yaykKcHN1dGlsCgojIEhUVFAgcmVxdWVzdHMKcmVxdWVzdHMKCiMgR29vZ2xlIGlu"
    "dGVncmF0aW9uIChDYWxlbmRhciwgRHJpdmUsIERvY3MsIEdtYWlsKQpnb29nbGUtYXBpLXB5dGhv"
    "bi1jbGllbnQKZ29vZ2xlLWF1dGgtb2F1dGhsaWIKZ29vZ2xlLWF1dGgKCiMg4pSA4pSAIE9wdGlv"
    "bmFsIChsb2NhbCBtb2RlbCBvbmx5KSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBVbmNvbW1l"
    "bnQgaWYgdXNpbmcgYSBsb2NhbCBIdWdnaW5nRmFjZSBtb2RlbDoKIyB0b3JjaAojIHRyYW5zZm9y"
    "bWVycwojIGFjY2VsZXJhdGUKCiMg4pSA4pSAIE9wdGlvbmFsIChOVklESUEgR1BVIG1vbml0b3Jp"
    "bmcpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAojIFVuY29tbWVudCBpZiB5b3UgaGF2ZSBhbiBOVklESUEgR1BVOgojIHB5bnZt"
    "bAoiIiIKICAgIHJlcV9wYXRoLndyaXRlX3RleHQoY29udGVudCwgZW5jb2Rpbmc9InV0Zi04IikK"
    "CgojIOKUgOKUgCBQQVNTIDQgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTWVtb3J5LCBTZXNzaW9uLCBMZXNz"
    "b25zTGVhcm5lZCwgVGFza01hbmFnZXIgYWxsIGRlZmluZWQuCiMgTFNMIEZvcmJpZGRlbiBSdWxl"
    "c2V0IGF1dG8tc2VlZGVkIG9uIGZpcnN0IHJ1bi4KIyByZXF1aXJlbWVudHMudHh0IHdyaXR0ZW4g"
    "b24gZmlyc3QgcnVuLgojCiMgTmV4dDogUGFzcyA1IOKAlCBUYWIgQ29udGVudCBDbGFzc2VzCiMg"
    "KFNMU2NhbnNUYWIsIFNMQ29tbWFuZHNUYWIsIEpvYlRyYWNrZXJUYWIsIFJlY29yZHNUYWIsCiMg"
    "IFRhc2tzVGFiLCBTZWxmVGFiLCBEaWFnbm9zdGljc1RhYikKCgojIOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdB"
    "Tk5BIERFQ0sg4oCUIFBBU1MgNTogVEFCIENPTlRFTlQgQ0xBU1NFUwojCiMgVGFicyBkZWZpbmVk"
    "IGhlcmU6CiMgICBTTFNjYW5zVGFiICAgICAg4oCUIGdyaW1vaXJlLWNhcmQgc3R5bGUsIHJlYnVp"
    "bHQgKERlbGV0ZSBhZGRlZCwgTW9kaWZ5IGZpeGVkLAojICAgICAgICAgICAgICAgICAgICAgcGFy"
    "c2VyIGZpeGVkLCBjb3B5LXRvLWNsaXBib2FyZCBwZXIgaXRlbSkKIyAgIFNMQ29tbWFuZHNUYWIg"
    "ICDigJQgZ290aGljIHRhYmxlLCBjb3B5IGNvbW1hbmQgdG8gY2xpcGJvYXJkCiMgICBKb2JUcmFj"
    "a2VyVGFiICAg4oCUIGZ1bGwgcmVidWlsZCBmcm9tIHNwZWMsIENTVi9UU1YgZXhwb3J0CiMgICBS"
    "ZWNvcmRzVGFiICAgICAg4oCUIEdvb2dsZSBEcml2ZS9Eb2NzIHdvcmtzcGFjZQojICAgVGFza3NU"
    "YWIgICAgICAgIOKAlCB0YXNrIHJlZ2lzdHJ5ICsgbWluaSBjYWxlbmRhcgojICAgU2VsZlRhYiAg"
    "ICAgICAgIOKAlCBpZGxlIG5hcnJhdGl2ZSBvdXRwdXQgKyBQb0kgbGlzdAojICAgRGlhZ25vc3Rp"
    "Y3NUYWIgIOKAlCBsb2d1cnUgb3V0cHV0ICsgaGFyZHdhcmUgcmVwb3J0ICsgam91cm5hbCBsb2Fk"
    "IG5vdGljZXMKIyAgIExlc3NvbnNUYWIgICAgICDigJQgTFNMIEZvcmJpZGRlbiBSdWxlc2V0ICsg"
    "Y29kZSBsZXNzb25zIGJyb3dzZXIKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmltcG9ydCByZSBhcyBfcmUKCgojIOKU"
    "gOKUgCBTSEFSRUQgR09USElDIFRBQkxFIFNUWUxFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApkZWYgX2dvdGhpY190YWJsZV9zdHlsZSgpIC0+IHN0cjoKICAgIHJldHVybiBmIiIi"
    "CiAgICAgICAgUVRhYmxlV2lkZ2V0IHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0JHMn07"
    "CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgICAgICAgICAgYm9yZGVyOiAxcHggc29s"
    "aWQge0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAgICBncmlkbGluZS1jb2xvcjoge0NfQk9SREVS"
    "fTsKICAgICAgICAgICAgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsKICAgICAgICAg"
    "ICAgZm9udC1zaXplOiAxMXB4OwogICAgICAgIH19CiAgICAgICAgUVRhYmxlV2lkZ2V0OjppdGVt"
    "OnNlbGVjdGVkIHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAg"
    "ICAgICAgICAgY29sb3I6IHtDX0dPTERfQlJJR0hUfTsKICAgICAgICB9fQogICAgICAgIFFUYWJs"
    "ZVdpZGdldDo6aXRlbTphbHRlcm5hdGUge3sKICAgICAgICAgICAgYmFja2dyb3VuZDoge0NfQkcz"
    "fTsKICAgICAgICB9fQogICAgICAgIFFIZWFkZXJWaWV3OjpzZWN0aW9uIHt7CiAgICAgICAgICAg"
    "IGJhY2tncm91bmQ6IHtDX0JHM307CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgICAg"
    "ICAgICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAgICBwYWRk"
    "aW5nOiA0cHggNnB4OwogICAgICAgICAgICBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlm"
    "OwogICAgICAgICAgICBmb250LXNpemU6IDEwcHg7CiAgICAgICAgICAgIGZvbnQtd2VpZ2h0OiBi"
    "b2xkOwogICAgICAgICAgICBsZXR0ZXItc3BhY2luZzogMXB4OwogICAgICAgIH19CiAgICAiIiIK"
    "CmRlZiBfZ290aGljX2J0bih0ZXh0OiBzdHIsIHRvb2x0aXA6IHN0ciA9ICIiKSAtPiBRUHVzaEJ1"
    "dHRvbjoKICAgIGJ0biA9IFFQdXNoQnV0dG9uKHRleHQpCiAgICBidG4uc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICBmImJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsgY29sb3I6IHtDX0dPTER9OyAi"
    "CiAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgYm9yZGVyLXJhZGl1czog"
    "MnB4OyAiCiAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNp"
    "emU6IDEwcHg7ICIKICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiA0cHggMTBw"
    "eDsgbGV0dGVyLXNwYWNpbmc6IDFweDsiCiAgICApCiAgICBpZiB0b29sdGlwOgogICAgICAgIGJ0"
    "bi5zZXRUb29sVGlwKHRvb2x0aXApCiAgICByZXR1cm4gYnRuCgpkZWYgX3NlY3Rpb25fbGJsKHRl"
    "eHQ6IHN0cikgLT4gUUxhYmVsOgogICAgbGJsID0gUUxhYmVsKHRleHQpCiAgICBsYmwuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGZvbnQt"
    "d2VpZ2h0OiBib2xkOyAiCiAgICAgICAgZiJsZXR0ZXItc3BhY2luZzogMnB4OyBmb250LWZhbWls"
    "eToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICkKICAgIHJldHVybiBsYmwKCgojIOKUgOKUgCBT"
    "TCBTQ0FOUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNMU2NhbnNUYWIoUVdpZGdldCk6CiAg"
    "ICAiIiIKICAgIFNlY29uZCBMaWZlIGF2YXRhciBzY2FubmVyIHJlc3VsdHMgbWFuYWdlci4KICAg"
    "IFJlYnVpbHQgZnJvbSBzcGVjOgogICAgICAtIENhcmQvZ3JpbW9pcmUtZW50cnkgc3R5bGUgZGlz"
    "cGxheQogICAgICAtIEFkZCAod2l0aCB0aW1lc3RhbXAtYXdhcmUgcGFyc2VyKQogICAgICAtIERp"
    "c3BsYXkgKGNsZWFuIGl0ZW0vY3JlYXRvciB0YWJsZSkKICAgICAgLSBNb2RpZnkgKGVkaXQgbmFt"
    "ZSwgZGVzY3JpcHRpb24sIGluZGl2aWR1YWwgaXRlbXMpCiAgICAgIC0gRGVsZXRlICh3YXMgbWlz"
    "c2luZyDigJQgbm93IHByZXNlbnQpCiAgICAgIC0gUmUtcGFyc2UgKHdhcyAnUmVmcmVzaCcg4oCU"
    "IHJlLXJ1bnMgcGFyc2VyIG9uIHN0b3JlZCByYXcgdGV4dCkKICAgICAgLSBDb3B5LXRvLWNsaXBi"
    "b2FyZCBvbiBhbnkgaXRlbQogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1lbW9yeV9k"
    "aXI6IFBhdGgsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkK"
    "ICAgICAgICBzZWxmLl9wYXRoICAgID0gY2ZnX3BhdGgoInNsIikgLyAic2xfc2NhbnMuanNvbmwi"
    "CiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc2Vs"
    "ZWN0ZWRfaWQ6IE9wdGlvbmFsW3N0cl0gPSBOb25lCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQog"
    "ICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNN"
    "YXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMg"
    "QnV0dG9uIGJhcgogICAgICAgIGJhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5f"
    "YWRkICAgICA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIiwgICAgICJBZGQgYSBuZXcgc2NhbiIpCiAg"
    "ICAgICAgc2VsZi5fYnRuX2Rpc3BsYXkgPSBfZ290aGljX2J0bigi4p2nIERpc3BsYXkiLCAiU2hv"
    "dyBzZWxlY3RlZCBzY2FuIGRldGFpbHMiKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkgID0gX2dv"
    "dGhpY19idG4oIuKcpyBNb2RpZnkiLCAgIkVkaXQgc2VsZWN0ZWQgc2NhbiIpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX2RlbGV0ZSAgPSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIsICAiRGVsZXRlIHNlbGVj"
    "dGVkIHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9yZXBhcnNlID0gX2dvdGhpY19idG4oIuKGuyBS"
    "ZS1wYXJzZSIsIlJlLXBhcnNlIHJhdyB0ZXh0IG9mIHNlbGVjdGVkIHNjYW4iKQogICAgICAgIHNl"
    "bGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Nob3dfYWRkKQogICAgICAgIHNlbGYu"
    "X2J0bl9kaXNwbGF5LmNsaWNrZWQuY29ubmVjdChzZWxmLl9zaG93X2Rpc3BsYXkpCiAgICAgICAg"
    "c2VsZi5fYnRuX21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2hvd19tb2RpZnkpCiAgICAg"
    "ICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAg"
    "ICAgIHNlbGYuX2J0bl9yZXBhcnNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19yZXBhcnNlKQog"
    "ICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fZGlzcGxheSwgc2VsZi5f"
    "YnRuX21vZGlmeSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSwgc2VsZi5fYnRu"
    "X3JlcGFyc2UpOgogICAgICAgICAgICBiYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYmFyLmFkZFN0"
    "cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAgICAgIyBTdGFjazogbGlz"
    "dCB2aWV3IHwgYWRkIGZvcm0gfCBkaXNwbGF5IHwgbW9kaWZ5CiAgICAgICAgc2VsZi5fc3RhY2sg"
    "PSBRU3RhY2tlZFdpZGdldCgpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fc3RhY2ssIDEp"
    "CgogICAgICAgICMg4pSA4pSAIFBBR0UgMDogc2NhbiBsaXN0IChncmltb2lyZSBjYXJkcykg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICAgICAgcDAgPSBRV2lkZ2V0KCkKICAgICAgICBsMCA9IFFWQm94TGF5"
    "b3V0KHAwKQogICAgICAgIGwwLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAg"
    "IHNlbGYuX2NhcmRfc2Nyb2xsID0gUVNjcm9sbEFyZWEoKQogICAgICAgIHNlbGYuX2NhcmRfc2Ny"
    "b2xsLnNldFdpZGdldFJlc2l6YWJsZShUcnVlKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNl"
    "dFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IG5vbmU7IikKICAgICAg"
    "ICBzZWxmLl9jYXJkX2NvbnRhaW5lciA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2NhcmRfbGF5"
    "b3V0ICAgID0gUVZCb3hMYXlvdXQoc2VsZi5fY2FyZF9jb250YWluZXIpCiAgICAgICAgc2VsZi5f"
    "Y2FyZF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZi5f"
    "Y2FyZF9sYXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LmFkZFN0"
    "cmV0Y2goKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFdpZGdldChzZWxmLl9jYXJkX2Nv"
    "bnRhaW5lcikKICAgICAgICBsMC5hZGRXaWRnZXQoc2VsZi5fY2FyZF9zY3JvbGwpCiAgICAgICAg"
    "c2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAwKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDE6IGFkZCBm"
    "b3JtIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAxID0gUVdpZGdldCgpCiAgICAgICAgbDEgPSBRVkJv"
    "eExheW91dChwMSkKICAgICAgICBsMS5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAg"
    "ICAgICBsMS5zZXRTcGFjaW5nKDQpCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi"
    "4p2nIFNDQU4gTkFNRSAoYXV0by1kZXRlY3RlZCkiKSkKICAgICAgICBzZWxmLl9hZGRfbmFtZSAg"
    "PSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dCgi"
    "QXV0by1kZXRlY3RlZCBmcm9tIHNjYW4gdGV4dCIpCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYu"
    "X2FkZF9uYW1lKQogICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBERVNDUklQ"
    "VElPTiIpKQogICAgICAgIHNlbGYuX2FkZF9kZXNjICA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2Vs"
    "Zi5fYWRkX2Rlc2Muc2V0TWF4aW11bUhlaWdodCg2MCkKICAgICAgICBsMS5hZGRXaWRnZXQoc2Vs"
    "Zi5fYWRkX2Rlc2MpCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFJBVyBT"
    "Q0FOIFRFWFQgKHBhc3RlIGhlcmUpIikpCiAgICAgICAgc2VsZi5fYWRkX3JhdyAgID0gUVRleHRF"
    "ZGl0KCkKICAgICAgICBzZWxmLl9hZGRfcmF3LnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAg"
    "ICAgIlBhc3RlIHRoZSByYXcgU2Vjb25kIExpZmUgc2NhbiBvdXRwdXQgaGVyZS5cbiIKICAgICAg"
    "ICAgICAgIlRpbWVzdGFtcHMgbGlrZSBbMTE6NDddIHdpbGwgYmUgdXNlZCB0byBzcGxpdCBpdGVt"
    "cyBjb3JyZWN0bHkuIgogICAgICAgICkKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX3Jh"
    "dywgMSkKICAgICAgICAjIFByZXZpZXcgb2YgcGFyc2VkIGl0ZW1zCiAgICAgICAgbDEuYWRkV2lk"
    "Z2V0KF9zZWN0aW9uX2xibCgi4p2nIFBBUlNFRCBJVEVNUyBQUkVWSUVXIikpCiAgICAgICAgc2Vs"
    "Zi5fYWRkX3ByZXZpZXcgPSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl9hZGRfcHJl"
    "dmlldy5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiSXRlbSIsICJDcmVhdG9yIl0pCiAgICAg"
    "ICAgc2VsZi5fYWRkX3ByZXZpZXcuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVN"
    "b2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAg"
    "ICAgc2VsZi5fYWRkX3ByZXZpZXcuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVN"
    "b2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAg"
    "ICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0TWF4aW11bUhlaWdodCgxMjApCiAgICAgICAgc2VsZi5f"
    "YWRkX3ByZXZpZXcuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAg"
    "bDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9wcmV2aWV3KQogICAgICAgIHNlbGYuX2FkZF9yYXcudGV4"
    "dENoYW5nZWQuY29ubmVjdChzZWxmLl9wcmV2aWV3X3BhcnNlKQoKICAgICAgICBidG5zMSA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBzMSA9IF9nb3RoaWNfYnRuKCLinKYgU2F2ZSIpOyBjMSA9IF9n"
    "b3RoaWNfYnRuKCLinJcgQ2FuY2VsIikKICAgICAgICBzMS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "ZG9fYWRkKQogICAgICAgIGMxLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuX3N0YWNrLnNl"
    "dEN1cnJlbnRJbmRleCgwKSkKICAgICAgICBidG5zMS5hZGRXaWRnZXQoczEpOyBidG5zMS5hZGRX"
    "aWRnZXQoYzEpOyBidG5zMS5hZGRTdHJldGNoKCkKICAgICAgICBsMS5hZGRMYXlvdXQoYnRuczEp"
    "CiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAxKQoKICAgICAgICAjIOKUgOKUgCBQQUdF"
    "IDI6IGRpc3BsYXkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDIgPSBRV2lkZ2V0KCkKICAgICAg"
    "ICBsMiA9IFFWQm94TGF5b3V0KHAyKQogICAgICAgIGwyLnNldENvbnRlbnRzTWFyZ2lucyg0LCA0"
    "LCA0LCA0KQogICAgICAgIHNlbGYuX2Rpc3BfbmFtZSAgPSBRTGFiZWwoKQogICAgICAgIHNlbGYu"
    "X2Rpc3BfbmFtZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0JS"
    "SUdIVH07IGZvbnQtc2l6ZTogMTNweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAg"
    "ZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2Vs"
    "Zi5fZGlzcF9kZXNjICA9IFFMYWJlbCgpCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFdvcmRX"
    "cmFwKFRydWUpCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseTog"
    "e0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZSA9"
    "IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SG9yaXpvbnRh"
    "bEhlYWRlckxhYmVscyhbIkl0ZW0iLCAiQ3JlYXRvciJdKQogICAgICAgIHNlbGYuX2Rpc3BfdGFi"
    "bGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAw"
    "LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fZGlzcF90YWJs"
    "ZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEs"
    "IFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxl"
    "LnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX2Rpc3Bf"
    "dGFibGUuc2V0Q29udGV4dE1lbnVQb2xpY3koCiAgICAgICAgICAgIFF0LkNvbnRleHRNZW51UG9s"
    "aWN5LkN1c3RvbUNvbnRleHRNZW51KQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuY3VzdG9tQ29u"
    "dGV4dE1lbnVSZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5faXRlbV9jb250ZXh0"
    "X21lbnUpCgogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9kaXNwX25hbWUpCiAgICAgICAgbDIu"
    "YWRkV2lkZ2V0KHNlbGYuX2Rpc3BfZGVzYykKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fZGlz"
    "cF90YWJsZSwgMSkKCiAgICAgICAgY29weV9oaW50ID0gUUxhYmVsKCJSaWdodC1jbGljayBhbnkg"
    "aXRlbSB0byBjb3B5IGl0IHRvIGNsaXBib2FyZC4iKQogICAgICAgIGNvcHlfaGludC5zZXRTdHls"
    "ZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4"
    "OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgbDIu"
    "YWRkV2lkZ2V0KGNvcHlfaGludCkKCiAgICAgICAgYmsyID0gX2dvdGhpY19idG4oIuKXgCBCYWNr"
    "IikKICAgICAgICBiazIuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fc3RhY2suc2V0Q3Vy"
    "cmVudEluZGV4KDApKQogICAgICAgIGwyLmFkZFdpZGdldChiazIpCiAgICAgICAgc2VsZi5fc3Rh"
    "Y2suYWRkV2lkZ2V0KHAyKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDM6IG1vZGlmeSDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKICAgICAgICBwMyA9IFFXaWRnZXQoKQogICAgICAgIGwzID0gUVZCb3hMYXlv"
    "dXQocDMpCiAgICAgICAgbDMuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAg"
    "bDMuc2V0U3BhY2luZyg0KQogICAgICAgIGwzLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBO"
    "QU1FIikpCiAgICAgICAgc2VsZi5fbW9kX25hbWUgPSBRTGluZUVkaXQoKQogICAgICAgIGwzLmFk"
    "ZFdpZGdldChzZWxmLl9tb2RfbmFtZSkKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJs"
    "KCLinacgREVTQ1JJUFRJT04iKSkKICAgICAgICBzZWxmLl9tb2RfZGVzYyA9IFFMaW5lRWRpdCgp"
    "CiAgICAgICAgbDMuYWRkV2lkZ2V0KHNlbGYuX21vZF9kZXNjKQogICAgICAgIGwzLmFkZFdpZGdl"
    "dChfc2VjdGlvbl9sYmwoIuKdpyBJVEVNUyAoZG91YmxlLWNsaWNrIHRvIGVkaXQpIikpCiAgICAg"
    "ICAgc2VsZi5fbW9kX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDIpCiAgICAgICAgc2VsZi5fbW9k"
    "X3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJJdGVtIiwgIkNyZWF0b3IiXSkKICAg"
    "ICAgICBzZWxmLl9tb2RfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVN"
    "b2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAg"
    "ICAgc2VsZi5fbW9kX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9k"
    "ZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAg"
    "IHNlbGYuX21vZF90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAg"
    "ICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fbW9kX3RhYmxlLCAxKQoKICAgICAgICBidG5zMyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBzMyA9IF9nb3RoaWNfYnRuKCLinKYgU2F2ZSIpOyBjMyA9IF9n"
    "b3RoaWNfYnRuKCLinJcgQ2FuY2VsIikKICAgICAgICBzMy5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "ZG9fbW9kaWZ5X3NhdmUpCiAgICAgICAgYzMuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5f"
    "c3RhY2suc2V0Q3VycmVudEluZGV4KDApKQogICAgICAgIGJ0bnMzLmFkZFdpZGdldChzMyk7IGJ0"
    "bnMzLmFkZFdpZGdldChjMyk7IGJ0bnMzLmFkZFN0cmV0Y2goKQogICAgICAgIGwzLmFkZExheW91"
    "dChidG5zMykKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDMpCgogICAgIyDilIDilIAg"
    "UEFSU0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgQHN0YXRpY21ldGhvZAogICAgZGVmIHBhcnNlX3NjYW5fdGV4dChyYXc6IHN0cikg"
    "LT4gdHVwbGVbc3RyLCBsaXN0W2RpY3RdXToKICAgICAgICAiIiIKICAgICAgICBQYXJzZSByYXcg"
    "U0wgc2NhbiBvdXRwdXQgaW50byAoYXZhdGFyX25hbWUsIGl0ZW1zKS4KCiAgICAgICAgS0VZIEZJ"
    "WDogQmVmb3JlIHNwbGl0dGluZywgaW5zZXJ0IG5ld2xpbmVzIGJlZm9yZSBldmVyeSBbSEg6TU1d"
    "CiAgICAgICAgdGltZXN0YW1wIHNvIHNpbmdsZS1saW5lIHBhc3RlcyB3b3JrIGNvcnJlY3RseS4K"
    "CiAgICAgICAgRXhwZWN0ZWQgZm9ybWF0OgogICAgICAgICAgICBbMTE6NDddIEF2YXRhck5hbWUn"
    "cyBwdWJsaWMgYXR0YWNobWVudHM6CiAgICAgICAgICAgIFsxMTo0N10gLjogSXRlbSBOYW1lIFtB"
    "dHRhY2htZW50XSBDUkVBVE9SOiBDcmVhdG9yTmFtZSBbMTE6NDddIC4uLgogICAgICAgICIiIgog"
    "ICAgICAgIGlmIG5vdCByYXcuc3RyaXAoKToKICAgICAgICAgICAgcmV0dXJuICJVTktOT1dOIiwg"
    "W10KCiAgICAgICAgIyDilIDilIAgU3RlcCAxOiBub3JtYWxpemUg4oCUIGluc2VydCBuZXdsaW5l"
    "cyBiZWZvcmUgdGltZXN0YW1wcyDilIDilIDilIDilIDilIDilIAKICAgICAgICBub3JtYWxpemVk"
    "ID0gX3JlLnN1YihyJ1xzKihcW1xkezEsMn06XGR7Mn1cXSknLCByJ1xuXDEnLCByYXcpCiAgICAg"
    "ICAgbGluZXMgPSBbbC5zdHJpcCgpIGZvciBsIGluIG5vcm1hbGl6ZWQuc3BsaXRsaW5lcygpIGlm"
    "IGwuc3RyaXAoKV0KCiAgICAgICAgIyDilIDilIAgU3RlcCAyOiBleHRyYWN0IGF2YXRhciBuYW1l"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGF2YXRhcl9u"
    "YW1lID0gIlVOS05PV04iCiAgICAgICAgZm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAgICAgICMg"
    "IkF2YXRhck5hbWUncyBwdWJsaWMgYXR0YWNobWVudHMiIG9yIHNpbWlsYXIKICAgICAgICAgICAg"
    "bSA9IF9yZS5zZWFyY2goCiAgICAgICAgICAgICAgICByIihcd1tcd1xzXSs/KSdzXHMrcHVibGlj"
    "XHMrYXR0YWNobWVudHMiLAogICAgICAgICAgICAgICAgbGluZSwgX3JlLkkKICAgICAgICAgICAg"
    "KQogICAgICAgICAgICBpZiBtOgogICAgICAgICAgICAgICAgYXZhdGFyX25hbWUgPSBtLmdyb3Vw"
    "KDEpLnN0cmlwKCkKICAgICAgICAgICAgICAgIGJyZWFrCgogICAgICAgICMg4pSA4pSAIFN0ZXAg"
    "MzogZXh0cmFjdCBpdGVtcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICBpdGVtcyA9IFtdCiAgICAgICAgZm9yIGxpbmUgaW4g"
    "bGluZXM6CiAgICAgICAgICAgICMgU3RyaXAgbGVhZGluZyB0aW1lc3RhbXAKICAgICAgICAgICAg"
    "Y29udGVudCA9IF9yZS5zdWIocideXFtcZHsxLDJ9OlxkezJ9XF1ccyonLCAnJywgbGluZSkuc3Ry"
    "aXAoKQogICAgICAgICAgICBpZiBub3QgY29udGVudDoKICAgICAgICAgICAgICAgIGNvbnRpbnVl"
    "CiAgICAgICAgICAgICMgU2tpcCBoZWFkZXIgbGluZXMKICAgICAgICAgICAgaWYgIidzIHB1Ymxp"
    "YyBhdHRhY2htZW50cyIgaW4gY29udGVudC5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGlu"
    "dWUKICAgICAgICAgICAgaWYgY29udGVudC5sb3dlcigpLnN0YXJ0c3dpdGgoIm9iamVjdCIpOgog"
    "ICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgIyBTa2lwIGRpdmlkZXIgbGluZXMg"
    "4oCUIGxpbmVzIHRoYXQgYXJlIG1vc3RseSBvbmUgcmVwZWF0ZWQgY2hhcmFjdGVyCiAgICAgICAg"
    "ICAgICMgZS5nLiDiloLiloLiloLiloLiloLiloLiloLiloLiloLiloLiloLiloIgb3Ig4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQIG9yIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgICAgICAgICBzdHJpcHBlZCA9IGNvbnRlbnQuc3RyaXAoIi46ICIp"
    "CiAgICAgICAgICAgIGlmIHN0cmlwcGVkIGFuZCBsZW4oc2V0KHN0cmlwcGVkKSkgPD0gMjoKICAg"
    "ICAgICAgICAgICAgIGNvbnRpbnVlICAjIG9uZSBvciB0d28gdW5pcXVlIGNoYXJzID0gZGl2aWRl"
    "ciBsaW5lCgogICAgICAgICAgICAjIFRyeSB0byBleHRyYWN0IENSRUFUT1I6IGZpZWxkCiAgICAg"
    "ICAgICAgIGNyZWF0b3IgPSAiVU5LTk9XTiIKICAgICAgICAgICAgaXRlbV9uYW1lID0gY29udGVu"
    "dAoKICAgICAgICAgICAgY3JlYXRvcl9tYXRjaCA9IF9yZS5zZWFyY2goCiAgICAgICAgICAgICAg"
    "ICByJ0NSRUFUT1I6XHMqKFtcd1xzXSs/KSg/OlxzKlxbfCQpJywgY29udGVudCwgX3JlLkkKICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICBpZiBjcmVhdG9yX21hdGNoOgogICAgICAgICAgICAgICAg"
    "Y3JlYXRvciAgID0gY3JlYXRvcl9tYXRjaC5ncm91cCgxKS5zdHJpcCgpCiAgICAgICAgICAgICAg"
    "ICBpdGVtX25hbWUgPSBjb250ZW50WzpjcmVhdG9yX21hdGNoLnN0YXJ0KCldLnN0cmlwKCkKCiAg"
    "ICAgICAgICAgICMgU3RyaXAgYXR0YWNobWVudCBwb2ludCBzdWZmaXhlcyBsaWtlIFtMZWZ0X0Zv"
    "b3RdCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IF9yZS5zdWIocidccypcW1tcd1xzX10rXF0nLCAn"
    "JywgaXRlbV9uYW1lKS5zdHJpcCgpCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IGl0ZW1fbmFtZS5z"
    "dHJpcCgiLjogIikKCiAgICAgICAgICAgIGlmIGl0ZW1fbmFtZSBhbmQgbGVuKGl0ZW1fbmFtZSkg"
    "PiAxOgogICAgICAgICAgICAgICAgaXRlbXMuYXBwZW5kKHsiaXRlbSI6IGl0ZW1fbmFtZSwgImNy"
    "ZWF0b3IiOiBjcmVhdG9yfSkKCiAgICAgICAgcmV0dXJuIGF2YXRhcl9uYW1lLCBpdGVtcwoKICAg"
    "ICMg4pSA4pSAIENBUkQgUkVOREVSSU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgZGVmIF9idWlsZF9jYXJkcyhzZWxmKSAtPiBOb25lOgogICAgICAgICMgQ2xlYXIgZXhpc3Rp"
    "bmcgY2FyZHMgKGtlZXAgc3RyZXRjaCkKICAgICAgICB3aGlsZSBzZWxmLl9jYXJkX2xheW91dC5j"
    "b3VudCgpID4gMToKICAgICAgICAgICAgaXRlbSA9IHNlbGYuX2NhcmRfbGF5b3V0LnRha2VBdCgw"
    "KQogICAgICAgICAgICBpZiBpdGVtLndpZGdldCgpOgogICAgICAgICAgICAgICAgaXRlbS53aWRn"
    "ZXQoKS5kZWxldGVMYXRlcigpCgogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAg"
    "ICAgICAgICAgY2FyZCA9IHNlbGYuX21ha2VfY2FyZChyZWMpCiAgICAgICAgICAgIHNlbGYuX2Nh"
    "cmRfbGF5b3V0Lmluc2VydFdpZGdldCgKICAgICAgICAgICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0"
    "LmNvdW50KCkgLSAxLCBjYXJkCiAgICAgICAgICAgICkKCiAgICBkZWYgX21ha2VfY2FyZChzZWxm"
    "LCByZWM6IGRpY3QpIC0+IFFXaWRnZXQ6CiAgICAgICAgY2FyZCA9IFFGcmFtZSgpCiAgICAgICAg"
    "aXNfc2VsZWN0ZWQgPSByZWMuZ2V0KCJyZWNvcmRfaWQiKSA9PSBzZWxmLl9zZWxlY3RlZF9pZAog"
    "ICAgICAgIGNhcmQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7JyMx"
    "YTBhMTAnIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19CRzN9OyAiCiAgICAgICAgICAgIGYiYm9yZGVy"
    "OiAxcHggc29saWQge0NfQ1JJTVNPTiBpZiBpc19zZWxlY3RlZCBlbHNlIENfQk9SREVSfTsgIgog"
    "ICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsgcGFkZGluZzogMnB4OyIKICAgICAgICAp"
    "CiAgICAgICAgbGF5b3V0ID0gUUhCb3hMYXlvdXQoY2FyZCkKICAgICAgICBsYXlvdXQuc2V0Q29u"
    "dGVudHNNYXJnaW5zKDgsIDYsIDgsIDYpCgogICAgICAgIG5hbWVfbGJsID0gUUxhYmVsKHJlYy5n"
    "ZXQoIm5hbWUiLCAiVU5LTk9XTiIpKQogICAgICAgIG5hbWVfbGJsLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgIGYiY29sb3I6IHtDX0dPTERfQlJJR0hUIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19H"
    "T0xEfTsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTogMTFweDsgZm9udC13ZWlnaHQ6IGJvbGQ7"
    "IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgY291"
    "bnQgPSBsZW4ocmVjLmdldCgiaXRlbXMiLCBbXSkpCiAgICAgICAgY291bnRfbGJsID0gUUxhYmVs"
    "KGYie2NvdW50fSBpdGVtcyIpCiAgICAgICAgY291bnRfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5"
    "OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgZGF0ZV9sYmwgPSBRTGFi"
    "ZWwocmVjLmdldCgiY3JlYXRlZF9hdCIsICIiKVs6MTBdKQogICAgICAgIGRhdGVfbGJsLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5"
    "cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAg"
    "bGF5b3V0LmFkZFdpZGdldChuYW1lX2xibCkKICAgICAgICBsYXlvdXQuYWRkU3RyZXRjaCgpCiAg"
    "ICAgICAgbGF5b3V0LmFkZFdpZGdldChjb3VudF9sYmwpCiAgICAgICAgbGF5b3V0LmFkZFNwYWNp"
    "bmcoMTIpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChkYXRlX2xibCkKCiAgICAgICAgIyBDbGlj"
    "ayB0byBzZWxlY3QKICAgICAgICByZWNfaWQgPSByZWMuZ2V0KCJyZWNvcmRfaWQiLCAiIikKICAg"
    "ICAgICBjYXJkLm1vdXNlUHJlc3NFdmVudCA9IGxhbWJkYSBlLCByaWQ9cmVjX2lkOiBzZWxmLl9z"
    "ZWxlY3RfY2FyZChyaWQpCiAgICAgICAgcmV0dXJuIGNhcmQKCiAgICBkZWYgX3NlbGVjdF9jYXJk"
    "KHNlbGYsIHJlY29yZF9pZDogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3NlbGVjdGVkX2lk"
    "ID0gcmVjb3JkX2lkCiAgICAgICAgc2VsZi5fYnVpbGRfY2FyZHMoKSAgIyBSZWJ1aWxkIHRvIHNo"
    "b3cgc2VsZWN0aW9uIGhpZ2hsaWdodAoKICAgIGRlZiBfc2VsZWN0ZWRfcmVjb3JkKHNlbGYpIC0+"
    "IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHJldHVybiBuZXh0KAogICAgICAgICAgICAociBmb3Ig"
    "ciBpbiBzZWxmLl9yZWNvcmRzCiAgICAgICAgICAgICBpZiByLmdldCgicmVjb3JkX2lkIikgPT0g"
    "c2VsZi5fc2VsZWN0ZWRfaWQpLAogICAgICAgICAgICBOb25lCiAgICAgICAgKQoKICAgICMg4pSA"
    "4pSAIEFDVElPTlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29y"
    "ZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgIyBFbnN1cmUgcmVjb3JkX2lkIGZp"
    "ZWxkIGV4aXN0cwogICAgICAgIGNoYW5nZWQgPSBGYWxzZQogICAgICAgIGZvciByIGluIHNlbGYu"
    "X3JlY29yZHM6CiAgICAgICAgICAgIGlmIG5vdCByLmdldCgicmVjb3JkX2lkIik6CiAgICAgICAg"
    "ICAgICAgICByWyJyZWNvcmRfaWQiXSA9IHIuZ2V0KCJpZCIpIG9yIHN0cih1dWlkLnV1aWQ0KCkp"
    "CiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgIGlmIGNoYW5nZWQ6CiAgICAg"
    "ICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2Vs"
    "Zi5fYnVpbGRfY2FyZHMoKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKQoK"
    "ICAgIGRlZiBfcHJldmlld19wYXJzZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJhdyA9IHNlbGYu"
    "X2FkZF9yYXcudG9QbGFpblRleHQoKQogICAgICAgIG5hbWUsIGl0ZW1zID0gc2VsZi5wYXJzZV9z"
    "Y2FuX3RleHQocmF3KQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dChu"
    "YW1lKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldFJvd0NvdW50KDApCiAgICAgICAgZm9y"
    "IGl0IGluIGl0ZW1zWzoyMF06ICAjIHByZXZpZXcgZmlyc3QgMjAKICAgICAgICAgICAgciA9IHNl"
    "bGYuX2FkZF9wcmV2aWV3LnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcu"
    "aW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldEl0ZW0ociwgMCwg"
    "UVRhYmxlV2lkZ2V0SXRlbShpdFsiaXRlbSJdKSkKICAgICAgICAgICAgc2VsZi5fYWRkX3ByZXZp"
    "ZXcuc2V0SXRlbShyLCAxLCBRVGFibGVXaWRnZXRJdGVtKGl0WyJjcmVhdG9yIl0pKQoKICAgIGRl"
    "ZiBfc2hvd19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hZGRfbmFtZS5jbGVhcigp"
    "CiAgICAgICAgc2VsZi5fYWRkX25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJBdXRvLWRldGVjdGVk"
    "IGZyb20gc2NhbiB0ZXh0IikKICAgICAgICBzZWxmLl9hZGRfZGVzYy5jbGVhcigpCiAgICAgICAg"
    "c2VsZi5fYWRkX3Jhdy5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0Um93Q291"
    "bnQoMCkKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMSkKCiAgICBkZWYgX2Rv"
    "X2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIHJhdyAgPSBzZWxmLl9hZGRfcmF3LnRvUGxhaW5U"
    "ZXh0KCkKICAgICAgICBuYW1lLCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAg"
    "ICAgICBvdmVycmlkZV9uYW1lID0gc2VsZi5fYWRkX25hbWUudGV4dCgpLnN0cmlwKCkKICAgICAg"
    "ICBub3cgID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICBy"
    "ZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHN0cih1dWlkLnV1aWQ0KCkpLAog"
    "ICAgICAgICAgICAicmVjb3JkX2lkIjogICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAg"
    "Im5hbWUiOiAgICAgICAgb3ZlcnJpZGVfbmFtZSBvciBuYW1lLAogICAgICAgICAgICAiZGVzY3Jp"
    "cHRpb24iOiBzZWxmLl9hZGRfZGVzYy50b1BsYWluVGV4dCgpWzoyNDRdLAogICAgICAgICAgICAi"
    "aXRlbXMiOiAgICAgICBpdGVtcywKICAgICAgICAgICAgInJhd190ZXh0IjogICAgcmF3LAogICAg"
    "ICAgICAgICAiY3JlYXRlZF9hdCI6ICBub3csCiAgICAgICAgICAgICJ1cGRhdGVkX2F0IjogIG5v"
    "dywKICAgICAgICB9CiAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQocmVjb3JkKQogICAgICAg"
    "IHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5fc2Vs"
    "ZWN0ZWRfaWQgPSByZWNvcmRbInJlY29yZF9pZCJdCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAg"
    "ICBkZWYgX3Nob3dfZGlzcGxheShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3Nl"
    "bGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VC"
    "b3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gZGlzcGxheS4iKQogICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICBzZWxmLl9kaXNwX25hbWUuc2V0VGV4dChmIuKdpyB7cmVjLmdldCgnbmFtZScs"
    "JycpfSIpCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFRleHQocmVjLmdldCgiZGVzY3JpcHRp"
    "b24iLCIiKSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAg"
    "Zm9yIGl0IGluIHJlYy5nZXQoIml0ZW1zIixbXSk6CiAgICAgICAgICAgIHIgPSBzZWxmLl9kaXNw"
    "X3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5pbnNlcnRSb3co"
    "cikKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAg"
    "ICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiaXRlbSIsIiIpKSkKICAgICAgICAgICAgc2Vs"
    "Zi5fZGlzcF90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJ"
    "dGVtKGl0LmdldCgiY3JlYXRvciIsIlVOS05PV04iKSkpCiAgICAgICAgc2VsZi5fc3RhY2suc2V0"
    "Q3VycmVudEluZGV4KDIpCgogICAgZGVmIF9pdGVtX2NvbnRleHRfbWVudShzZWxmLCBwb3MpIC0+"
    "IE5vbmU6CiAgICAgICAgaWR4ID0gc2VsZi5fZGlzcF90YWJsZS5pbmRleEF0KHBvcykKICAgICAg"
    "ICBpZiBub3QgaWR4LmlzVmFsaWQoKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaXRlbV90"
    "ZXh0ICA9IChzZWxmLl9kaXNwX3RhYmxlLml0ZW0oaWR4LnJvdygpLCAwKSBvcgogICAgICAgICAg"
    "ICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAgIGNyZWF0b3Ig"
    "ICAgPSAoc2VsZi5fZGlzcF90YWJsZS5pdGVtKGlkeC5yb3coKSwgMSkgb3IKICAgICAgICAgICAg"
    "ICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICBmcm9tIFB5U2lk"
    "ZTYuUXRXaWRnZXRzIGltcG9ydCBRTWVudQogICAgICAgIG1lbnUgPSBRTWVudShzZWxmKQogICAg"
    "ICAgIG1lbnUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9"
    "OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19D"
    "UklNU09OX0RJTX07IgogICAgICAgICkKICAgICAgICBhX2l0ZW0gICAgPSBtZW51LmFkZEFjdGlv"
    "bigiQ29weSBJdGVtIE5hbWUiKQogICAgICAgIGFfY3JlYXRvciA9IG1lbnUuYWRkQWN0aW9uKCJD"
    "b3B5IENyZWF0b3IiKQogICAgICAgIGFfYm90aCAgICA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5IEJv"
    "dGgiKQogICAgICAgIGFjdGlvbiA9IG1lbnUuZXhlYyhzZWxmLl9kaXNwX3RhYmxlLnZpZXdwb3J0"
    "KCkubWFwVG9HbG9iYWwocG9zKSkKICAgICAgICBjYiA9IFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQo"
    "KQogICAgICAgIGlmIGFjdGlvbiA9PSBhX2l0ZW06ICAgIGNiLnNldFRleHQoaXRlbV90ZXh0KQog"
    "ICAgICAgIGVsaWYgYWN0aW9uID09IGFfY3JlYXRvcjogY2Iuc2V0VGV4dChjcmVhdG9yKQogICAg"
    "ICAgIGVsaWYgYWN0aW9uID09IGFfYm90aDogIGNiLnNldFRleHQoZiJ7aXRlbV90ZXh0fSDigJQg"
    "e2NyZWF0b3J9IikKCiAgICBkZWYgX3Nob3dfbW9kaWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "cmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAg"
    "ICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiU0wgU2NhbnMiLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAiU2VsZWN0IGEgc2NhbiB0byBtb2RpZnkuIikKICAg"
    "ICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fbW9kX25hbWUuc2V0VGV4dChyZWMuZ2V0KCJu"
    "YW1lIiwiIikpCiAgICAgICAgc2VsZi5fbW9kX2Rlc2Muc2V0VGV4dChyZWMuZ2V0KCJkZXNjcmlw"
    "dGlvbiIsIiIpKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAg"
    "IGZvciBpdCBpbiByZWMuZ2V0KCJpdGVtcyIsW10pOgogICAgICAgICAgICByID0gc2VsZi5fbW9k"
    "X3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmluc2VydFJvdyhy"
    "KQogICAgICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAg"
    "ICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoIml0ZW0iLCIiKSkpCiAgICAgICAgICAgIHNlbGYu"
    "X21vZF90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVt"
    "KGl0LmdldCgiY3JlYXRvciIsIlVOS05PV04iKSkpCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3Vy"
    "cmVudEluZGV4KDMpCgogICAgZGVmIF9kb19tb2RpZnlfc2F2ZShzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAg"
    "ICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjWyJuYW1lIl0gICAgICAgID0gc2VsZi5fbW9kX25h"
    "bWUudGV4dCgpLnN0cmlwKCkgb3IgIlVOS05PV04iCiAgICAgICAgcmVjWyJkZXNjcmlwdGlvbiJd"
    "ID0gc2VsZi5fbW9kX2Rlc2MudGV4dCgpWzoyNDRdCiAgICAgICAgaXRlbXMgPSBbXQogICAgICAg"
    "IGZvciBpIGluIHJhbmdlKHNlbGYuX21vZF90YWJsZS5yb3dDb3VudCgpKToKICAgICAgICAgICAg"
    "aXQgID0gKHNlbGYuX21vZF90YWJsZS5pdGVtKGksMCkgb3IgUVRhYmxlV2lkZ2V0SXRlbSgiIikp"
    "LnRleHQoKQogICAgICAgICAgICBjciAgPSAoc2VsZi5fbW9kX3RhYmxlLml0ZW0oaSwxKSBvciBR"
    "VGFibGVXaWRnZXRJdGVtKCIiKSkudGV4dCgpCiAgICAgICAgICAgIGl0ZW1zLmFwcGVuZCh7Iml0"
    "ZW0iOiBpdC5zdHJpcCgpIG9yICJVTktOT1dOIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAi"
    "Y3JlYXRvciI6IGNyLnN0cmlwKCkgb3IgIlVOS05PV04ifSkKICAgICAgICByZWNbIml0ZW1zIl0g"
    "ICAgICA9IGl0ZW1zCiAgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGlt"
    "ZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNl"
    "bGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAg"
    "ICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwg"
    "IlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBh"
    "IHNjYW4gdG8gZGVsZXRlLiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5hbWUgPSByZWMu"
    "Z2V0KCJuYW1lIiwidGhpcyBzY2FuIikKICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0"
    "aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVsZXRlIFNjYW4iLAogICAgICAgICAgICBmIkRlbGV0"
    "ZSAne25hbWV9Jz8gVGhpcyBjYW5ub3QgYmUgdW5kb25lLiIsCiAgICAgICAgICAgIFFNZXNzYWdl"
    "Qm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAg"
    "ICAgICAgKQogICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlll"
    "czoKICAgICAgICAgICAgc2VsZi5fcmVjb3JkcyA9IFtyIGZvciByIGluIHNlbGYuX3JlY29yZHMK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiByLmdldCgicmVjb3JkX2lkIikgIT0gc2Vs"
    "Zi5fc2VsZWN0ZWRfaWRdCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYu"
    "X3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkID0gTm9uZQogICAgICAgICAg"
    "ICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fcmVwYXJzZShzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAg"
    "ICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gcmUtcGFyc2Uu"
    "IikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmF3ID0gcmVjLmdldCgicmF3X3RleHQiLCIi"
    "KQogICAgICAgIGlmIG5vdCByYXc6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9u"
    "KHNlbGYsICJSZS1wYXJzZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJO"
    "byByYXcgdGV4dCBzdG9yZWQgZm9yIHRoaXMgc2Nhbi4iKQogICAgICAgICAgICByZXR1cm4KICAg"
    "ICAgICBuYW1lLCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICByZWNb"
    "Iml0ZW1zIl0gICAgICA9IGl0ZW1zCiAgICAgICAgcmVjWyJuYW1lIl0gICAgICAgPSByZWNbIm5h"
    "bWUiXSBvciBuYW1lCiAgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGlt"
    "ZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNl"
    "bGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKICAgICAgICBRTWVzc2FnZUJveC5p"
    "bmZvcm1hdGlvbihzZWxmLCAiUmUtcGFyc2VkIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICBmIkZvdW5kIHtsZW4oaXRlbXMpfSBpdGVtcy4iKQoKCiMg4pSA4pSAIFNMIENPTU1BTkRT"
    "IFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgU0xDb21tYW5kc1RhYihRV2lkZ2V0KToKICAgICIiIgogICAgU2Vj"
    "b25kIExpZmUgY29tbWFuZCByZWZlcmVuY2UgdGFibGUuCiAgICBHb3RoaWMgdGFibGUgc3R5bGlu"
    "Zy4gQ29weSBjb21tYW5kIHRvIGNsaXBib2FyZCBidXR0b24gcGVyIHJvdy4KICAgICIiIgoKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRf"
    "XyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAgICA9IGNmZ19wYXRoKCJzbCIpIC8gInNsX2Nv"
    "bW1hbmRzLmpzb25sIgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQogICAg"
    "ICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0"
    "dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAg"
    "ICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0"
    "U3BhY2luZyg0KQoKICAgICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRu"
    "X2FkZCAgICA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIikKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5"
    "ID0gX2dvdGhpY19idG4oIuKcpyBNb2RpZnkiKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgPSBf"
    "Z290aGljX2J0bigi4pyXIERlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX2NvcHkgICA9IF9nb3Ro"
    "aWNfYnRuKCLip4kgQ29weSBDb21tYW5kIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJDb3B5IHNlbGVjdGVkIGNvbW1hbmQgdG8gY2xpcGJvYXJkIikKICAgICAgICBz"
    "ZWxmLl9idG5fcmVmcmVzaD0gX2dvdGhpY19idG4oIuKGuyBSZWZyZXNoIikKICAgICAgICBzZWxm"
    "Ll9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRu"
    "X21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0"
    "bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxmLl9i"
    "dG5fY29weS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fY29weV9jb21tYW5kKQogICAgICAgIHNlbGYu"
    "X2J0bl9yZWZyZXNoLmNsaWNrZWQuY29ubmVjdChzZWxmLnJlZnJlc2gpCiAgICAgICAgZm9yIGIg"
    "aW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9tb2RpZnksIHNlbGYuX2J0bl9kZWxldGUsCiAg"
    "ICAgICAgICAgICAgICAgIHNlbGYuX2J0bl9jb3B5LCBzZWxmLl9idG5fcmVmcmVzaCk6CiAgICAg"
    "ICAgICAgIGJhci5hZGRXaWRnZXQoYikKICAgICAgICBiYXIuYWRkU3RyZXRjaCgpCiAgICAgICAg"
    "cm9vdC5hZGRMYXlvdXQoYmFyKQoKICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgw"
    "LCAyKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJDb21t"
    "YW5kIiwgIkRlc2NyaXB0aW9uIl0pCiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRl"
    "cigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNp"
    "emVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNl"
    "dFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2Rl"
    "LlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAg"
    "ICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAg"
    "ICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBz"
    "ZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBy"
    "b290LmFkZFdpZGdldChzZWxmLl90YWJsZSwgMSkKCiAgICAgICAgaGludCA9IFFMYWJlbCgKICAg"
    "ICAgICAgICAgIlNlbGVjdCBhIHJvdyBhbmQgY2xpY2sg4qeJIENvcHkgQ29tbWFuZCB0byBjb3B5"
    "IGp1c3QgdGhlIGNvbW1hbmQgdGV4dC4iCiAgICAgICAgKQogICAgICAgIGhpbnQuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsg"
    "Zm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJvb3Qu"
    "YWRkV2lkZ2V0KGhpbnQpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIHNlbGYuX3RhYmxl"
    "LnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAg"
    "ICAgICByID0gc2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5p"
    "bnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAg"
    "ICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJjb21tYW5kIiwiIikpKQogICAgICAg"
    "ICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRn"
    "ZXRJdGVtKHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpKQoKICAgIGRlZiBfY29weV9jb21tYW5k"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAg"
    "ICAgICAgaWYgcm93IDwgMDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaXRlbSA9IHNlbGYu"
    "X3RhYmxlLml0ZW0ocm93LCAwKQogICAgICAgIGlmIGl0ZW06CiAgICAgICAgICAgIFFBcHBsaWNh"
    "dGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KGl0ZW0udGV4dCgpKQoKICAgIGRlZiBfZG9fYWRkKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRX"
    "aW5kb3dUaXRsZSgiQWRkIENvbW1hbmQiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFj"
    "a2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZm9ybSA9IFFGb3Jt"
    "TGF5b3V0KGRsZykKICAgICAgICBjbWQgID0gUUxpbmVFZGl0KCk7IGRlc2MgPSBRTGluZUVkaXQo"
    "KQogICAgICAgIGZvcm0uYWRkUm93KCJDb21tYW5kOiIsIGNtZCkKICAgICAgICBmb3JtLmFkZFJv"
    "dygiRGVzY3JpcHRpb246IiwgZGVzYykKICAgICAgICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAg"
    "ICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikK"
    "ICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVj"
    "dChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQo"
    "Y3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRucykKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFE"
    "aWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgbm93ID0gZGF0ZXRpbWUubm93"
    "KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAgcmVjID0gewogICAgICAgICAg"
    "ICAgICAgImlkIjogICAgICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICAgICAi"
    "Y29tbWFuZCI6ICAgICBjbWQudGV4dCgpLnN0cmlwKClbOjI0NF0sCiAgICAgICAgICAgICAgICAi"
    "ZGVzY3JpcHRpb24iOiBkZXNjLnRleHQoKS5zdHJpcCgpWzoyNDRdLAogICAgICAgICAgICAgICAg"
    "ImNyZWF0ZWRfYXQiOiAgbm93LCAidXBkYXRlZF9hdCI6IG5vdywKICAgICAgICAgICAgfQogICAg"
    "ICAgICAgICBpZiByZWNbImNvbW1hbmQiXToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMu"
    "YXBwZW5kKHJlYykKICAgICAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYu"
    "X3JlY29yZHMpCiAgICAgICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fbW9k"
    "aWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygp"
    "CiAgICAgICAgaWYgcm93IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICBkbGcg"
    "PSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJNb2RpZnkgQ29tbWFu"
    "ZCIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xv"
    "cjoge0NfR09MRH07IikKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAgIGNt"
    "ZCAgPSBRTGluZUVkaXQocmVjLmdldCgiY29tbWFuZCIsIiIpKQogICAgICAgIGRlc2MgPSBRTGlu"
    "ZUVkaXQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBmb3JtLmFkZFJvdygiQ29t"
    "bWFuZDoiLCBjbWQpCiAgICAgICAgZm9ybS5hZGRSb3coIkRlc2NyaXB0aW9uOiIsIGRlc2MpCiAg"
    "ICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZl"
    "Iik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0"
    "KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5z"
    "LmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0"
    "bnMpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6"
    "CiAgICAgICAgICAgIHJlY1siY29tbWFuZCJdICAgICA9IGNtZC50ZXh0KCkuc3RyaXAoKVs6MjQ0"
    "XQogICAgICAgICAgICByZWNbImRlc2NyaXB0aW9uIl0gPSBkZXNjLnRleHQoKS5zdHJpcCgpWzoy"
    "NDRdCiAgICAgICAgICAgIHJlY1sidXBkYXRlZF9hdCJdICA9IGRhdGV0aW1lLm5vdyh0aW1lem9u"
    "ZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNl"
    "bGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxl"
    "dGUoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkK"
    "ICAgICAgICBpZiByb3cgPCAwIG9yIHJvdyA+PSBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAg"
    "ICAgIHJldHVybgogICAgICAgIGNtZCA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQoImNvbW1hbmQi"
    "LCJ0aGlzIGNvbW1hbmQiKQogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAg"
    "ICAgICAgICAgIHNlbGYsICJEZWxldGUiLCBmIkRlbGV0ZSAne2NtZH0nPyIsCiAgICAgICAgICAg"
    "IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0"
    "dG9uLk5vCiAgICAgICAgKQogICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJk"
    "QnV0dG9uLlllczoKICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5wb3Aocm93KQogICAgICAgICAg"
    "ICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxm"
    "LnJlZnJlc2goKQoKCiMg4pSA4pSAIEpPQiBUUkFDS0VSIFRBQiDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSm9iVHJh"
    "Y2tlclRhYihRV2lkZ2V0KToKICAgICIiIgogICAgSm9iIGFwcGxpY2F0aW9uIHRyYWNraW5nLiBG"
    "dWxsIHJlYnVpbGQgZnJvbSBzcGVjLgogICAgRmllbGRzOiBDb21wYW55LCBKb2IgVGl0bGUsIERh"
    "dGUgQXBwbGllZCwgTGluaywgU3RhdHVzLCBOb3Rlcy4KICAgIE11bHRpLXNlbGVjdCBoaWRlL3Vu"
    "aGlkZS9kZWxldGUuIENTViBhbmQgVFNWIGV4cG9ydC4KICAgIEhpZGRlbiByb3dzID0gY29tcGxl"
    "dGVkL3JlamVjdGVkIOKAlCBzdGlsbCBzdG9yZWQsIGp1c3Qgbm90IHNob3duLgogICAgIiIiCgog"
    "ICAgQ09MVU1OUyA9IFsiQ29tcGFueSIsICJKb2IgVGl0bGUiLCAiRGF0ZSBBcHBsaWVkIiwKICAg"
    "ICAgICAgICAgICAgIkxpbmsiLCAiU3RhdHVzIiwgIk5vdGVzIl0KCiAgICBkZWYgX19pbml0X18o"
    "c2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAg"
    "ICAgIHNlbGYuX3BhdGggICAgPSBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJqb2JfdHJhY2tlci5q"
    "c29ubCIKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxm"
    "Ll9zaG93X2hpZGRlbiA9IEZhbHNlCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNl"
    "bGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJv"
    "b3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQs"
    "IDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGJhciA9IFFIQm94"
    "TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgID0gX2dvdGhpY19idG4oIkFkZCIpCiAg"
    "ICAgICAgc2VsZi5fYnRuX21vZGlmeSA9IF9nb3RoaWNfYnRuKCJNb2RpZnkiKQogICAgICAgIHNl"
    "bGYuX2J0bl9oaWRlICAgPSBfZ290aGljX2J0bigiQXJjaGl2ZSIsCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAiTWFyayBzZWxlY3RlZCBhcyBjb21wbGV0ZWQvcmVqZWN0"
    "ZWQiKQogICAgICAgIHNlbGYuX2J0bl91bmhpZGUgPSBfZ290aGljX2J0bigiUmVzdG9yZSIsCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiUmVzdG9yZSBhcmNoaXZlZCBh"
    "cHBsaWNhdGlvbnMiKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgPSBfZ290aGljX2J0bigiRGVs"
    "ZXRlIikKICAgICAgICBzZWxmLl9idG5fdG9nZ2xlID0gX2dvdGhpY19idG4oIlNob3cgQXJjaGl2"
    "ZWQiKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQgPSBfZ290aGljX2J0bigiRXhwb3J0IikKCiAg"
    "ICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9tb2RpZnksIHNlbGYuX2J0"
    "bl9oaWRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fdW5oaWRlLCBzZWxmLl9idG5fZGVs"
    "ZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fdG9nZ2xlLCBzZWxmLl9idG5fZXhwb3J0"
    "KToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtV2lkdGgoNzApCiAgICAgICAgICAgIGIuc2V0TWlu"
    "aW11bUhlaWdodCgyNikKICAgICAgICAgICAgYmFyLmFkZFdpZGdldChiKQoKICAgICAgICBzZWxm"
    "Ll9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRu"
    "X21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0"
    "bl9oaWRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19oaWRlKQogICAgICAgIHNlbGYuX2J0bl91"
    "bmhpZGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX3VuaGlkZSkKICAgICAgICBzZWxmLl9idG5f"
    "ZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5fYnRu"
    "X3RvZ2dsZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2hpZGRlbikKICAgICAgICBzZWxm"
    "Ll9idG5fZXhwb3J0LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19leHBvcnQpCiAgICAgICAgYmFy"
    "LmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAgICAgc2VsZi5f"
    "dGFibGUgPSBRVGFibGVXaWRnZXQoMCwgbGVuKHNlbGYuQ09MVU1OUykpCiAgICAgICAgc2VsZi5f"
    "dGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhzZWxmLkNPTFVNTlMpCiAgICAgICAgaGgg"
    "PSBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkKICAgICAgICAjIENvbXBhbnkgYW5kIEpv"
    "YiBUaXRsZSBzdHJldGNoCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMCwgUUhlYWRl"
    "clZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2Rl"
    "KDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICAjIERhdGUgQXBwbGll"
    "ZCDigJQgZml4ZWQgcmVhZGFibGUgd2lkdGgKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9k"
    "ZSgyLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNl"
    "dENvbHVtbldpZHRoKDIsIDEwMCkKICAgICAgICAjIExpbmsgc3RyZXRjaGVzCiAgICAgICAgaGgu"
    "c2V0U2VjdGlvblJlc2l6ZU1vZGUoMywgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQog"
    "ICAgICAgICMgU3RhdHVzIOKAlCBmaXhlZCB3aWR0aAogICAgICAgIGhoLnNldFNlY3Rpb25SZXNp"
    "emVNb2RlKDQsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2VsZi5fdGFi"
    "bGUuc2V0Q29sdW1uV2lkdGgoNCwgODApCiAgICAgICAgIyBOb3RlcyBzdHJldGNoZXMKICAgICAg"
    "ICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSg1LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0"
    "Y2gpCgogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAg"
    "ICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAg"
    "IHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbk1vZGUoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1W"
    "aWV3LlNlbGVjdGlvbk1vZGUuRXh0ZW5kZWRTZWxlY3Rpb24pCiAgICAgICAgc2VsZi5fdGFibGUu"
    "c2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHls"
    "ZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxm"
    "Ll90YWJsZSwgMSkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYu"
    "X3JlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0"
    "Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAg"
    "IGhpZGRlbiA9IGJvb2wocmVjLmdldCgiaGlkZGVuIiwgRmFsc2UpKQogICAgICAgICAgICBpZiBo"
    "aWRkZW4gYW5kIG5vdCBzZWxmLl9zaG93X2hpZGRlbjoKICAgICAgICAgICAgICAgIGNvbnRpbnVl"
    "CiAgICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYu"
    "X3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzdGF0dXMgPSAiQXJjaGl2ZWQiIGlmIGhp"
    "ZGRlbiBlbHNlIHJlYy5nZXQoInN0YXR1cyIsIkFjdGl2ZSIpCiAgICAgICAgICAgIHZhbHMgPSBb"
    "CiAgICAgICAgICAgICAgICByZWMuZ2V0KCJjb21wYW55IiwiIiksCiAgICAgICAgICAgICAgICBy"
    "ZWMuZ2V0KCJqb2JfdGl0bGUiLCIiKSwKICAgICAgICAgICAgICAgIHJlYy5nZXQoImRhdGVfYXBw"
    "bGllZCIsIiIpLAogICAgICAgICAgICAgICAgcmVjLmdldCgibGluayIsIiIpLAogICAgICAgICAg"
    "ICAgICAgc3RhdHVzLAogICAgICAgICAgICAgICAgcmVjLmdldCgibm90ZXMiLCIiKSwKICAgICAg"
    "ICAgICAgXQogICAgICAgICAgICBmb3IgYywgdiBpbiBlbnVtZXJhdGUodmFscyk6CiAgICAgICAg"
    "ICAgICAgICBpdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShzdHIodikpCiAgICAgICAgICAgICAgICBp"
    "ZiBoaWRkZW46CiAgICAgICAgICAgICAgICAgICAgaXRlbS5zZXRGb3JlZ3JvdW5kKFFDb2xvcihD"
    "X1RFWFRfRElNKSkKICAgICAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgYywgaXRl"
    "bSkKICAgICAgICAgICAgIyBTdG9yZSByZWNvcmQgaW5kZXggaW4gZmlyc3QgY29sdW1uJ3MgdXNl"
    "ciBkYXRhCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLml0ZW0ociwgMCkuc2V0RGF0YSgKICAgICAg"
    "ICAgICAgICAgIFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwKICAgICAgICAgICAgICAgIHNlbGYu"
    "X3JlY29yZHMuaW5kZXgocmVjKQogICAgICAgICAgICApCgogICAgZGVmIF9zZWxlY3RlZF9pbmRp"
    "Y2VzKHNlbGYpIC0+IGxpc3RbaW50XToKICAgICAgICBpbmRpY2VzID0gc2V0KCkKICAgICAgICBm"
    "b3IgaXRlbSBpbiBzZWxmLl90YWJsZS5zZWxlY3RlZEl0ZW1zKCk6CiAgICAgICAgICAgIHJvd19p"
    "dGVtID0gc2VsZi5fdGFibGUuaXRlbShpdGVtLnJvdygpLCAwKQogICAgICAgICAgICBpZiByb3df"
    "aXRlbToKICAgICAgICAgICAgICAgIGlkeCA9IHJvd19pdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xl"
    "LlVzZXJSb2xlKQogICAgICAgICAgICAgICAgaWYgaWR4IGlzIG5vdCBOb25lOgogICAgICAgICAg"
    "ICAgICAgICAgIGluZGljZXMuYWRkKGlkeCkKICAgICAgICByZXR1cm4gc29ydGVkKGluZGljZXMp"
    "CgogICAgZGVmIF9kaWFsb2coc2VsZiwgcmVjOiBkaWN0ID0gTm9uZSkgLT4gT3B0aW9uYWxbZGlj"
    "dF06CiAgICAgICAgZGxnICA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0"
    "bGUoIkpvYiBBcHBsaWNhdGlvbiIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3Jv"
    "dW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBkbGcucmVzaXplKDUwMCwg"
    "MzIwKQogICAgICAgIGZvcm0gPSBRRm9ybUxheW91dChkbGcpCgogICAgICAgIGNvbXBhbnkgPSBR"
    "TGluZUVkaXQocmVjLmdldCgiY29tcGFueSIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIHRp"
    "dGxlICAgPSBRTGluZUVkaXQocmVjLmdldCgiam9iX3RpdGxlIiwiIikgaWYgcmVjIGVsc2UgIiIp"
    "CiAgICAgICAgZGUgICAgICA9IFFEYXRlRWRpdCgpCiAgICAgICAgZGUuc2V0Q2FsZW5kYXJQb3B1"
    "cChUcnVlKQogICAgICAgIGRlLnNldERpc3BsYXlGb3JtYXQoInl5eXktTU0tZGQiKQogICAgICAg"
    "IGlmIHJlYyBhbmQgcmVjLmdldCgiZGF0ZV9hcHBsaWVkIik6CiAgICAgICAgICAgIGRlLnNldERh"
    "dGUoUURhdGUuZnJvbVN0cmluZyhyZWNbImRhdGVfYXBwbGllZCJdLCJ5eXl5LU1NLWRkIikpCiAg"
    "ICAgICAgZWxzZToKICAgICAgICAgICAgZGUuc2V0RGF0ZShRRGF0ZS5jdXJyZW50RGF0ZSgpKQog"
    "ICAgICAgIGxpbmsgICAgPSBRTGluZUVkaXQocmVjLmdldCgibGluayIsIiIpIGlmIHJlYyBlbHNl"
    "ICIiKQogICAgICAgIHN0YXR1cyAgPSBRTGluZUVkaXQocmVjLmdldCgic3RhdHVzIiwiQXBwbGll"
    "ZCIpIGlmIHJlYyBlbHNlICJBcHBsaWVkIikKICAgICAgICBub3RlcyAgID0gUUxpbmVFZGl0KHJl"
    "Yy5nZXQoIm5vdGVzIiwiIikgaWYgcmVjIGVsc2UgIiIpCgogICAgICAgIGZvciBsYWJlbCwgd2lk"
    "Z2V0IGluIFsKICAgICAgICAgICAgKCJDb21wYW55OiIsIGNvbXBhbnkpLCAoIkpvYiBUaXRsZToi"
    "LCB0aXRsZSksCiAgICAgICAgICAgICgiRGF0ZSBBcHBsaWVkOiIsIGRlKSwgKCJMaW5rOiIsIGxp"
    "bmspLAogICAgICAgICAgICAoIlN0YXR1czoiLCBzdGF0dXMpLCAoIk5vdGVzOiIsIG5vdGVzKSwK"
    "ICAgICAgICBdOgogICAgICAgICAgICBmb3JtLmFkZFJvdyhsYWJlbCwgd2lkZ2V0KQoKICAgICAg"
    "ICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUiKTsg"
    "Y3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxn"
    "LmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRk"
    "V2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRucykK"
    "CiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAg"
    "ICAgICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICAgICAiY29tcGFueSI6ICAgICAgY29tcGFu"
    "eS50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJqb2JfdGl0bGUiOiAgICB0aXRsZS50"
    "ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJkYXRlX2FwcGxpZWQiOiBkZS5kYXRlKCku"
    "dG9TdHJpbmcoInl5eXktTU0tZGQiKSwKICAgICAgICAgICAgICAgICJsaW5rIjogICAgICAgICBs"
    "aW5rLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgIHN0YXR1"
    "cy50ZXh0KCkuc3RyaXAoKSBvciAiQXBwbGllZCIsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAg"
    "ICAgICAgbm90ZXMudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgIH0KICAgICAgICByZXR1cm4g"
    "Tm9uZQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcCA9IHNlbGYuX2Rp"
    "YWxvZygpCiAgICAgICAgaWYgbm90IHA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5vdyA9"
    "IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgcC51cGRhdGUo"
    "ewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAg"
    "ICAgICAgImhpZGRlbiI6ICAgICAgICAgRmFsc2UsCiAgICAgICAgICAgICJjb21wbGV0ZWRfZGF0"
    "ZSI6IE5vbmUsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgIG5vdywKICAgICAgICAgICAg"
    "InVwZGF0ZWRfYXQiOiAgICAgbm93LAogICAgICAgIH0pCiAgICAgICAgc2VsZi5fcmVjb3Jkcy5h"
    "cHBlbmQocCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQog"
    "ICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19tb2RpZnkoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBpZHhzID0gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpCiAgICAgICAgaWYgbGVuKGlk"
    "eHMpICE9IDE6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJNb2Rp"
    "ZnkiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiU2VsZWN0IGV4YWN0bHkg"
    "b25lIHJvdyB0byBtb2RpZnkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjID0gc2Vs"
    "Zi5fcmVjb3Jkc1tpZHhzWzBdXQogICAgICAgIHAgICA9IHNlbGYuX2RpYWxvZyhyZWMpCiAgICAg"
    "ICAgaWYgbm90IHA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlYy51cGRhdGUocCkKICAg"
    "ICAgICByZWNbInVwZGF0ZWRfYXQiXSA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zv"
    "cm1hdCgpCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAg"
    "ICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9faGlkZShzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIGZvciBpZHggaW4gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpOgogICAgICAgICAgICBpZiBp"
    "ZHggPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lk"
    "eF1bImhpZGRlbiJdICAgICAgICAgPSBUcnVlCiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRz"
    "W2lkeF1bImNvbXBsZXRlZF9kYXRlIl0gPSAoCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fcmVj"
    "b3Jkc1tpZHhdLmdldCgiY29tcGxldGVkX2RhdGUiKSBvcgogICAgICAgICAgICAgICAgICAgIGRh"
    "dGV0aW1lLm5vdygpLmRhdGUoKS5pc29mb3JtYXQoKQogICAgICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJ1cGRhdGVkX2F0Il0gPSAoCiAgICAgICAgICAg"
    "ICAgICAgICAgZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAg"
    "ICAgICAgICkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQog"
    "ICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb191bmhpZGUoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBmb3IgaWR4IGluIHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKToKICAgICAgICAgICAg"
    "aWYgaWR4IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jk"
    "c1tpZHhdWyJoaWRkZW4iXSAgICAgPSBGYWxzZQogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jk"
    "c1tpZHhdWyJ1cGRhdGVkX2F0Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93"
    "KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICB3cml0"
    "ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgp"
    "CgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICBpZHhzID0gc2VsZi5f"
    "c2VsZWN0ZWRfaW5kaWNlcygpCiAgICAgICAgaWYgbm90IGlkeHM6CiAgICAgICAgICAgIHJldHVy"
    "bgogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgIHNlbGYs"
    "ICJEZWxldGUiLAogICAgICAgICAgICBmIkRlbGV0ZSB7bGVuKGlkeHMpfSBzZWxlY3RlZCBhcHBs"
    "aWNhdGlvbihzKT8gQ2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5T"
    "dGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAg"
    "ICkKICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAg"
    "ICAgICAgICAgIGJhZCA9IHNldChpZHhzKQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzID0gW3Ig"
    "Zm9yIGksIHIgaW4gZW51bWVyYXRlKHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgaWYgaSBub3QgaW4gYmFkXQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9w"
    "YXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBf"
    "dG9nZ2xlX2hpZGRlbihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nob3dfaGlkZGVuID0g"
    "bm90IHNlbGYuX3Nob3dfaGlkZGVuCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZS5zZXRUZXh0KAog"
    "ICAgICAgICAgICAi4piAIEhpZGUgQXJjaGl2ZWQiIGlmIHNlbGYuX3Nob3dfaGlkZGVuIGVsc2Ug"
    "IuKYvSBTaG93IEFyY2hpdmVkIgogICAgICAgICkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAg"
    "IGRlZiBfZG9fZXhwb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCwgZmlsdCA9IFFGaWxl"
    "RGlhbG9nLmdldFNhdmVGaWxlTmFtZSgKICAgICAgICAgICAgc2VsZiwgIkV4cG9ydCBKb2IgVHJh"
    "Y2tlciIsCiAgICAgICAgICAgIHN0cihjZmdfcGF0aCgiZXhwb3J0cyIpIC8gImpvYl90cmFja2Vy"
    "LmNzdiIpLAogICAgICAgICAgICAiQ1NWIEZpbGVzICgqLmNzdik7O1RhYiBEZWxpbWl0ZWQgKCou"
    "dHh0KSIKICAgICAgICApCiAgICAgICAgaWYgbm90IHBhdGg6CiAgICAgICAgICAgIHJldHVybgog"
    "ICAgICAgIGRlbGltID0gIlx0IiBpZiBwYXRoLmxvd2VyKCkuZW5kc3dpdGgoIi50eHQiKSBlbHNl"
    "ICIsIgogICAgICAgIGhlYWRlciA9IFsiY29tcGFueSIsImpvYl90aXRsZSIsImRhdGVfYXBwbGll"
    "ZCIsImxpbmsiLAogICAgICAgICAgICAgICAgICAic3RhdHVzIiwiaGlkZGVuIiwiY29tcGxldGVk"
    "X2RhdGUiLCJub3RlcyJdCiAgICAgICAgd2l0aCBvcGVuKHBhdGgsICJ3IiwgZW5jb2Rpbmc9InV0"
    "Zi04IiwgbmV3bGluZT0iIikgYXMgZjoKICAgICAgICAgICAgZi53cml0ZShkZWxpbS5qb2luKGhl"
    "YWRlcikgKyAiXG4iKQogICAgICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAg"
    "ICAgICAgICAgICB2YWxzID0gWwogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImNvbXBhbnki"
    "LCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJqb2JfdGl0bGUiLCIiKSwKICAgICAg"
    "ICAgICAgICAgICAgICByZWMuZ2V0KCJkYXRlX2FwcGxpZWQiLCIiKSwKICAgICAgICAgICAgICAg"
    "ICAgICByZWMuZ2V0KCJsaW5rIiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgic3Rh"
    "dHVzIiwiIiksCiAgICAgICAgICAgICAgICAgICAgc3RyKGJvb2wocmVjLmdldCgiaGlkZGVuIixG"
    "YWxzZSkpKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJjb21wbGV0ZWRfZGF0ZSIsIiIp"
    "IG9yICIiLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAgICAgICAg"
    "ICAgICAgICBdCiAgICAgICAgICAgICAgICBmLndyaXRlKGRlbGltLmpvaW4oCiAgICAgICAgICAg"
    "ICAgICAgICAgc3RyKHYpLnJlcGxhY2UoIlxuIiwiICIpLnJlcGxhY2UoZGVsaW0sIiAiKQogICAg"
    "ICAgICAgICAgICAgICAgIGZvciB2IGluIHZhbHMKICAgICAgICAgICAgICAgICkgKyAiXG4iKQog"
    "ICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJFeHBvcnRlZCIsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZiJTYXZlZCB0byB7cGF0aH0iKQoKCiMg4pSA4pSAIFNF"
    "TEYgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBSZWNvcmRzVGFiKFFXaWRn"
    "ZXQpOgogICAgIiIiR29vZ2xlIERyaXZlL0RvY3MgcmVjb3JkcyBicm93c2VyIHRhYi4iIiIKCiAg"
    "ICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0"
    "X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Qu"
    "c2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQp"
    "CgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVsKCJSZWNvcmRzIGFyZSBub3QgbG9h"
    "ZGVkIHlldC4iKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBz"
    "ZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQo"
    "c2VsZi5zdGF0dXNfbGFiZWwpCgogICAgICAgIHNlbGYucGF0aF9sYWJlbCA9IFFMYWJlbCgiUGF0"
    "aDogTXkgRHJpdmUiKQogICAgICAgIHNlbGYucGF0aF9sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0RJTX07IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwg"
    "c2VyaWY7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0"
    "KHNlbGYucGF0aF9sYWJlbCkKCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3QgPSBRTGlzdFdpZGdl"
    "dCgpCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlk"
    "IHtDX0JPUkRFUn07IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLnJlY29y"
    "ZHNfbGlzdCwgMSkKCiAgICBkZWYgc2V0X2l0ZW1zKHNlbGYsIGZpbGVzOiBsaXN0W2RpY3RdLCBw"
    "YXRoX3RleHQ6IHN0ciA9ICJNeSBEcml2ZSIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5wYXRoX2xh"
    "YmVsLnNldFRleHQoZiJQYXRoOiB7cGF0aF90ZXh0fSIpCiAgICAgICAgc2VsZi5yZWNvcmRzX2xp"
    "c3QuY2xlYXIoKQogICAgICAgIGZvciBmaWxlX2luZm8gaW4gZmlsZXM6CiAgICAgICAgICAgIHRp"
    "dGxlID0gKGZpbGVfaW5mby5nZXQoIm5hbWUiKSBvciAiVW50aXRsZWQiKS5zdHJpcCgpIG9yICJV"
    "bnRpdGxlZCIKICAgICAgICAgICAgbWltZSA9IChmaWxlX2luZm8uZ2V0KCJtaW1lVHlwZSIpIG9y"
    "ICIiKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29n"
    "bGUtYXBwcy5mb2xkZXIiOgogICAgICAgICAgICAgICAgcHJlZml4ID0gIvCfk4EiCiAgICAgICAg"
    "ICAgIGVsaWYgbWltZSA9PSAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IjoK"
    "ICAgICAgICAgICAgICAgIHByZWZpeCA9ICLwn5OdIgogICAgICAgICAgICBlbHNlOgogICAgICAg"
    "ICAgICAgICAgcHJlZml4ID0gIvCfk4QiCiAgICAgICAgICAgIG1vZGlmaWVkID0gKGZpbGVfaW5m"
    "by5nZXQoIm1vZGlmaWVkVGltZSIpIG9yICIiKS5yZXBsYWNlKCJUIiwgIiAiKS5yZXBsYWNlKCJa"
    "IiwgIiBVVEMiKQogICAgICAgICAgICB0ZXh0ID0gZiJ7cHJlZml4fSB7dGl0bGV9IiArIChmIiAg"
    "ICBbe21vZGlmaWVkfV0iIGlmIG1vZGlmaWVkIGVsc2UgIiIpCiAgICAgICAgICAgIGl0ZW0gPSBR"
    "TGlzdFdpZGdldEl0ZW0odGV4dCkKICAgICAgICAgICAgaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRh"
    "Um9sZS5Vc2VyUm9sZSwgZmlsZV9pbmZvKQogICAgICAgICAgICBzZWxmLnJlY29yZHNfbGlzdC5h"
    "ZGRJdGVtKGl0ZW0pCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkxvYWRlZCB7"
    "bGVuKGZpbGVzKX0gR29vZ2xlIERyaXZlIGl0ZW0ocykuIikKCgpjbGFzcyBUYXNrc1RhYihRV2lk"
    "Z2V0KToKICAgICIiIlRhc2sgcmVnaXN0cnkgKyBHb29nbGUtZmlyc3QgZWRpdG9yIHdvcmtmbG93"
    "IHRhYi4iIiIKCiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKICAgICAgICB0YXNrc19w"
    "cm92aWRlciwKICAgICAgICBvbl9hZGRfZWRpdG9yX29wZW4sCiAgICAgICAgb25fY29tcGxldGVf"
    "c2VsZWN0ZWQsCiAgICAgICAgb25fY2FuY2VsX3NlbGVjdGVkLAogICAgICAgIG9uX3RvZ2dsZV9j"
    "b21wbGV0ZWQsCiAgICAgICAgb25fcHVyZ2VfY29tcGxldGVkLAogICAgICAgIG9uX2ZpbHRlcl9j"
    "aGFuZ2VkLAogICAgICAgIG9uX2VkaXRvcl9zYXZlLAogICAgICAgIG9uX2VkaXRvcl9jYW5jZWws"
    "CiAgICAgICAgZGlhZ25vc3RpY3NfbG9nZ2VyPU5vbmUsCiAgICAgICAgcGFyZW50PU5vbmUsCiAg"
    "ICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3Rhc2tz"
    "X3Byb3ZpZGVyID0gdGFza3NfcHJvdmlkZXIKICAgICAgICBzZWxmLl9vbl9hZGRfZWRpdG9yX29w"
    "ZW4gPSBvbl9hZGRfZWRpdG9yX29wZW4KICAgICAgICBzZWxmLl9vbl9jb21wbGV0ZV9zZWxlY3Rl"
    "ZCA9IG9uX2NvbXBsZXRlX3NlbGVjdGVkCiAgICAgICAgc2VsZi5fb25fY2FuY2VsX3NlbGVjdGVk"
    "ID0gb25fY2FuY2VsX3NlbGVjdGVkCiAgICAgICAgc2VsZi5fb25fdG9nZ2xlX2NvbXBsZXRlZCA9"
    "IG9uX3RvZ2dsZV9jb21wbGV0ZWQKICAgICAgICBzZWxmLl9vbl9wdXJnZV9jb21wbGV0ZWQgPSBv"
    "bl9wdXJnZV9jb21wbGV0ZWQKICAgICAgICBzZWxmLl9vbl9maWx0ZXJfY2hhbmdlZCA9IG9uX2Zp"
    "bHRlcl9jaGFuZ2VkCiAgICAgICAgc2VsZi5fb25fZWRpdG9yX3NhdmUgPSBvbl9lZGl0b3Jfc2F2"
    "ZQogICAgICAgIHNlbGYuX29uX2VkaXRvcl9jYW5jZWwgPSBvbl9lZGl0b3JfY2FuY2VsCiAgICAg"
    "ICAgc2VsZi5fZGlhZ19sb2dnZXIgPSBkaWFnbm9zdGljc19sb2dnZXIKICAgICAgICBzZWxmLl9z"
    "aG93X2NvbXBsZXRlZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fcmVmcmVzaF90aHJlYWQgPSBOb25l"
    "CiAgICAgICAgc2VsZi5fYnVpbGRfdWkoKQoKICAgIGRlZiBfYnVpbGRfdWkoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRl"
    "bnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQogICAgICAg"
    "IHNlbGYud29ya3NwYWNlX3N0YWNrID0gUVN0YWNrZWRXaWRnZXQoKQogICAgICAgIHJvb3QuYWRk"
    "V2lkZ2V0KHNlbGYud29ya3NwYWNlX3N0YWNrLCAxKQoKICAgICAgICBub3JtYWwgPSBRV2lkZ2V0"
    "KCkKICAgICAgICBub3JtYWxfbGF5b3V0ID0gUVZCb3hMYXlvdXQobm9ybWFsKQogICAgICAgIG5v"
    "cm1hbF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbm9ybWFs"
    "X2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVs"
    "KCJUYXNrIHJlZ2lzdHJ5IGlzIG5vdCBsb2FkZWQgeWV0LiIpCiAgICAgICAgc2VsZi5zdGF0dXNf"
    "bGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBm"
    "b250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAg"
    "ICkKICAgICAgICBub3JtYWxfbGF5b3V0LmFkZFdpZGdldChzZWxmLnN0YXR1c19sYWJlbCkKCiAg"
    "ICAgICAgZmlsdGVyX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdp"
    "ZGdldChfc2VjdGlvbl9sYmwoIuKdpyBEQVRFIFJBTkdFIikpCiAgICAgICAgc2VsZi50YXNrX2Zp"
    "bHRlcl9jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5h"
    "ZGRJdGVtKCJXRUVLIiwgIndlZWsiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRk"
    "SXRlbSgiTU9OVEgiLCAibW9udGgiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRk"
    "SXRlbSgiTkVYVCAzIE1PTlRIUyIsICJuZXh0XzNfbW9udGhzIikKICAgICAgICBzZWxmLnRhc2tf"
    "ZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIllFQVIiLCAieWVhciIpCiAgICAgICAgc2VsZi50YXNrX2Zp"
    "bHRlcl9jb21iby5zZXRDdXJyZW50SW5kZXgoMikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2Nv"
    "bWJvLmN1cnJlbnRJbmRleENoYW5nZWQuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIF86IHNl"
    "bGYuX29uX2ZpbHRlcl9jaGFuZ2VkKHNlbGYudGFza19maWx0ZXJfY29tYm8uY3VycmVudERhdGEo"
    "KSBvciAibmV4dF8zX21vbnRocyIpCiAgICAgICAgKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lk"
    "Z2V0KHNlbGYudGFza19maWx0ZXJfY29tYm8pCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRTdHJldGNo"
    "KDEpCiAgICAgICAgbm9ybWFsX2xheW91dC5hZGRMYXlvdXQoZmlsdGVyX3JvdykKCiAgICAgICAg"
    "c2VsZi50YXNrX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDQpCiAgICAgICAgc2VsZi50YXNrX3Rh"
    "YmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJTdGF0dXMiLCAiRHVlIiwgIlRhc2siLCAi"
    "U291cmNlIl0pCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKFFB"
    "YnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2Vs"
    "Zi50YXNrX3RhYmxlLnNldFNlbGVjdGlvbk1vZGUoUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9u"
    "TW9kZS5FeHRlbmRlZFNlbGVjdGlvbikKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0RWRpdFRy"
    "aWdnZXJzKFFBYnN0cmFjdEl0ZW1WaWV3LkVkaXRUcmlnZ2VyLk5vRWRpdFRyaWdnZXJzKQogICAg"
    "ICAgIHNlbGYudGFza190YWJsZS52ZXJ0aWNhbEhlYWRlcigpLnNldFZpc2libGUoRmFsc2UpCiAg"
    "ICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXpl"
    "TW9kZSgwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAg"
    "c2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgx"
    "LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50"
    "YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVh"
    "ZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6"
    "b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgzLCBRSGVhZGVyVmlldy5SZXNpemVN"
    "b2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFN0eWxlU2hl"
    "ZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYudGFza190YWJsZS5pdGVtU2Vs"
    "ZWN0aW9uQ2hhbmdlZC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0dG9uX3N0YXRlKQog"
    "ICAgICAgIG5vcm1hbF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza190YWJsZSwgMSkKCiAgICAg"
    "ICAgYWN0aW9ucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLmJ0bl9hZGRfdGFza193b3Jr"
    "c3BhY2UgPSBfZ290aGljX2J0bigiQUREIFRBU0siKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRl"
    "X3Rhc2sgPSBfZ290aGljX2J0bigiQ09NUExFVEUgU0VMRUNURUQiKQogICAgICAgIHNlbGYuYnRu"
    "X2NhbmNlbF90YXNrID0gX2dvdGhpY19idG4oIkNBTkNFTCBTRUxFQ1RFRCIpCiAgICAgICAgc2Vs"
    "Zi5idG5fdG9nZ2xlX2NvbXBsZXRlZCA9IF9nb3RoaWNfYnRuKCJTSE9XIENPTVBMRVRFRCIpCiAg"
    "ICAgICAgc2VsZi5idG5fcHVyZ2VfY29tcGxldGVkID0gX2dvdGhpY19idG4oIlBVUkdFIENPTVBM"
    "RVRFRCIpCiAgICAgICAgc2VsZi5idG5fYWRkX3Rhc2tfd29ya3NwYWNlLmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl9vbl9hZGRfZWRpdG9yX29wZW4pCiAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFz"
    "ay5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fY29tcGxldGVfc2VsZWN0ZWQpCiAgICAgICAgc2Vs"
    "Zi5idG5fY2FuY2VsX3Rhc2suY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2NhbmNlbF9zZWxlY3Rl"
    "ZCkKICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLmNsaWNrZWQuY29ubmVjdChzZWxm"
    "Ll9vbl90b2dnbGVfY29tcGxldGVkKQogICAgICAgIHNlbGYuYnRuX3B1cmdlX2NvbXBsZXRlZC5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fcHVyZ2VfY29tcGxldGVkKQogICAgICAgIHNlbGYuYnRu"
    "X2NvbXBsZXRlX3Rhc2suc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLmJ0bl9jYW5jZWxf"
    "dGFzay5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIGZvciBidG4gaW4gKAogICAgICAgICAgICBz"
    "ZWxmLmJ0bl9hZGRfdGFza193b3Jrc3BhY2UsCiAgICAgICAgICAgIHNlbGYuYnRuX2NvbXBsZXRl"
    "X3Rhc2ssCiAgICAgICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrLAogICAgICAgICAgICBzZWxm"
    "LmJ0bl90b2dnbGVfY29tcGxldGVkLAogICAgICAgICAgICBzZWxmLmJ0bl9wdXJnZV9jb21wbGV0"
    "ZWQsCiAgICAgICAgKToKICAgICAgICAgICAgYWN0aW9ucy5hZGRXaWRnZXQoYnRuKQogICAgICAg"
    "IG5vcm1hbF9sYXlvdXQuYWRkTGF5b3V0KGFjdGlvbnMpCiAgICAgICAgc2VsZi53b3Jrc3BhY2Vf"
    "c3RhY2suYWRkV2lkZ2V0KG5vcm1hbCkKCiAgICAgICAgZWRpdG9yID0gUVdpZGdldCgpCiAgICAg"
    "ICAgZWRpdG9yX2xheW91dCA9IFFWQm94TGF5b3V0KGVkaXRvcikKICAgICAgICBlZGl0b3JfbGF5"
    "b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGVkaXRvcl9sYXlvdXQu"
    "c2V0U3BhY2luZyg0KQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xi"
    "bCgi4p2nIFRBU0sgRURJVE9SIOKAlCBHT09HTEUtRklSU1QiKSkKICAgICAgICBzZWxmLnRhc2tf"
    "ZWRpdG9yX3N0YXR1c19sYWJlbCA9IFFMYWJlbCgiQ29uZmlndXJlIHRhc2sgZGV0YWlscywgdGhl"
    "biBzYXZlIHRvIEdvb2dsZSBDYWxlbmRhci4iKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3Rh"
    "dHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcz"
    "fTsgY29sb3I6IHtDX1RFWFRfRElNfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgcGFk"
    "ZGluZzogNnB4OyIKICAgICAgICApCiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQoc2Vs"
    "Zi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9uYW1l"
    "ID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25hbWUuc2V0UGxhY2Vob2xk"
    "ZXJUZXh0KCJUYXNrIE5hbWUiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF0ZSA9"
    "IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLnNldFBsYWNl"
    "aG9sZGVyVGV4dCgiU3RhcnQgRGF0ZSAoWVlZWS1NTS1ERCkiKQogICAgICAgIHNlbGYudGFza19l"
    "ZGl0b3Jfc3RhcnRfdGltZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9z"
    "dGFydF90aW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiU3RhcnQgVGltZSAoSEg6TU0pIikKICAgICAg"
    "ICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRh"
    "c2tfZWRpdG9yX2VuZF9kYXRlLnNldFBsYWNlaG9sZGVyVGV4dCgiRW5kIERhdGUgKFlZWVktTU0t"
    "REQpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lID0gUUxpbmVFZGl0KCkKICAg"
    "ICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiRW5kIFRp"
    "bWUgKEhIOk1NKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbiA9IFFMaW5lRWRp"
    "dCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbi5zZXRQbGFjZWhvbGRlclRleHQo"
    "IkxvY2F0aW9uIChvcHRpb25hbCkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfcmVjdXJyZW5j"
    "ZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnNldFBs"
    "YWNlaG9sZGVyVGV4dCgiUmVjdXJyZW5jZSBSUlVMRSAob3B0aW9uYWwpIikKICAgICAgICBzZWxm"
    "LnRhc2tfZWRpdG9yX2FsbF9kYXkgPSBRQ2hlY2tCb3goIkFsbC1kYXkiKQogICAgICAgIHNlbGYu"
    "dGFza19lZGl0b3Jfbm90ZXMgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jf"
    "bm90ZXMuc2V0UGxhY2Vob2xkZXJUZXh0KCJOb3RlcyIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRv"
    "cl9ub3Rlcy5zZXRNYXhpbXVtSGVpZ2h0KDkwKQogICAgICAgIGZvciB3aWRnZXQgaW4gKAogICAg"
    "ICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25hbWUsCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0"
    "b3Jfc3RhcnRfZGF0ZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLAog"
    "ICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlLAogICAgICAgICAgICBzZWxmLnRh"
    "c2tfZWRpdG9yX2VuZF90aW1lLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2xvY2F0aW9u"
    "LAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3JlY3VycmVuY2UsCiAgICAgICAgKToKICAg"
    "ICAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQod2lkZ2V0KQogICAgICAgIGVkaXRvcl9s"
    "YXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza19lZGl0b3JfYWxsX2RheSkKICAgICAgICBlZGl0b3Jf"
    "bGF5b3V0LmFkZFdpZGdldChzZWxmLnRhc2tfZWRpdG9yX25vdGVzLCAxKQogICAgICAgIGVkaXRv"
    "cl9hY3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9zYXZlID0gX2dvdGhpY19idG4o"
    "IlNBVkUiKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigiQ0FOQ0VMIikKICAgICAg"
    "ICBidG5fc2F2ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fZWRpdG9yX3NhdmUpCiAgICAgICAg"
    "YnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fZWRpdG9yX2NhbmNlbCkKICAgICAg"
    "ICBlZGl0b3JfYWN0aW9ucy5hZGRXaWRnZXQoYnRuX3NhdmUpCiAgICAgICAgZWRpdG9yX2FjdGlv"
    "bnMuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkU3RyZXRj"
    "aCgxKQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkTGF5b3V0KGVkaXRvcl9hY3Rpb25zKQogICAg"
    "ICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLmFkZFdpZGdldChlZGl0b3IpCgogICAgICAgIHNlbGYu"
    "bm9ybWFsX3dvcmtzcGFjZSA9IG5vcm1hbAogICAgICAgIHNlbGYuZWRpdG9yX3dvcmtzcGFjZSA9"
    "IGVkaXRvcgogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQoc2Vs"
    "Zi5ub3JtYWxfd29ya3NwYWNlKQoKICAgIGRlZiBfdXBkYXRlX2FjdGlvbl9idXR0b25fc3RhdGUo"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBlbmFibGVkID0gYm9vbChzZWxmLnNlbGVjdGVkX3Rhc2tf"
    "aWRzKCkpCiAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzay5zZXRFbmFibGVkKGVuYWJsZWQp"
    "CiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suc2V0RW5hYmxlZChlbmFibGVkKQoKICAgIGRl"
    "ZiBzZWxlY3RlZF90YXNrX2lkcyhzZWxmKSAtPiBsaXN0W3N0cl06CiAgICAgICAgaWRzOiBsaXN0"
    "W3N0cl0gPSBbXQogICAgICAgIGZvciByIGluIHJhbmdlKHNlbGYudGFza190YWJsZS5yb3dDb3Vu"
    "dCgpKToKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBzZWxmLnRhc2tfdGFibGUuaXRlbShyLCAw"
    "KQogICAgICAgICAgICBpZiBzdGF0dXNfaXRlbSBpcyBOb25lOgogICAgICAgICAgICAgICAgY29u"
    "dGludWUKICAgICAgICAgICAgaWYgbm90IHN0YXR1c19pdGVtLmlzU2VsZWN0ZWQoKToKICAgICAg"
    "ICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIHRhc2tfaWQgPSBzdGF0dXNfaXRlbS5kYXRh"
    "KFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgaWYgdGFza19pZCBhbmQgdGFz"
    "a19pZCBub3QgaW4gaWRzOgogICAgICAgICAgICAgICAgaWRzLmFwcGVuZCh0YXNrX2lkKQogICAg"
    "ICAgIHJldHVybiBpZHMKCiAgICBkZWYgbG9hZF90YXNrcyhzZWxmLCB0YXNrczogbGlzdFtkaWN0"
    "XSkgLT4gTm9uZToKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAg"
    "ICBmb3IgdGFzayBpbiB0YXNrczoKICAgICAgICAgICAgcm93ID0gc2VsZi50YXNrX3RhYmxlLnJv"
    "d0NvdW50KCkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLmluc2VydFJvdyhyb3cpCiAgICAg"
    "ICAgICAgIHN0YXR1cyA9ICh0YXNrLmdldCgic3RhdHVzIikgb3IgInBlbmRpbmciKS5sb3dlcigp"
    "CiAgICAgICAgICAgIHN0YXR1c19pY29uID0gIuKYkSIgaWYgc3RhdHVzIGluIHsiY29tcGxldGVk"
    "IiwgImNhbmNlbGxlZCJ9IGVsc2UgIuKAoiIKICAgICAgICAgICAgZHVlID0gKHRhc2suZ2V0KCJk"
    "dWVfYXQiKSBvciAiIikucmVwbGFjZSgiVCIsICIgIikKICAgICAgICAgICAgdGV4dCA9ICh0YXNr"
    "LmdldCgidGV4dCIpIG9yICJSZW1pbmRlciIpLnN0cmlwKCkgb3IgIlJlbWluZGVyIgogICAgICAg"
    "ICAgICBzb3VyY2UgPSAodGFzay5nZXQoInNvdXJjZSIpIG9yICJsb2NhbCIpLmxvd2VyKCkKICAg"
    "ICAgICAgICAgc3RhdHVzX2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKGYie3N0YXR1c19pY29ufSB7"
    "c3RhdHVzfSIpCiAgICAgICAgICAgIHN0YXR1c19pdGVtLnNldERhdGEoUXQuSXRlbURhdGFSb2xl"
    "LlVzZXJSb2xlLCB0YXNrLmdldCgiaWQiKSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNl"
    "dEl0ZW0ocm93LCAwLCBzdGF0dXNfaXRlbSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNl"
    "dEl0ZW0ocm93LCAxLCBRVGFibGVXaWRnZXRJdGVtKGR1ZSkpCiAgICAgICAgICAgIHNlbGYudGFz"
    "a190YWJsZS5zZXRJdGVtKHJvdywgMiwgUVRhYmxlV2lkZ2V0SXRlbSh0ZXh0KSkKICAgICAgICAg"
    "ICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAzLCBRVGFibGVXaWRnZXRJdGVtKHNvdXJj"
    "ZSkpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkxvYWRlZCB7bGVuKHRhc2tz"
    "KX0gdGFzayhzKS4iKQogICAgICAgIHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0dG9uX3N0YXRlKCkK"
    "CiAgICBkZWYgX2RpYWcoc2VsZiwgbWVzc2FnZTogc3RyLCBsZXZlbDogc3RyID0gIklORk8iKSAt"
    "PiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgaWYgc2VsZi5fZGlhZ19sb2dnZXI6CiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9kaWFnX2xvZ2dlcihtZXNzYWdlLCBsZXZlbCkKICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgZGVmIHN0b3BfcmVmcmVzaF93"
    "b3JrZXIoc2VsZiwgcmVhc29uOiBzdHIgPSAiIikgLT4gTm9uZToKICAgICAgICB0aHJlYWQgPSBn"
    "ZXRhdHRyKHNlbGYsICJfcmVmcmVzaF90aHJlYWQiLCBOb25lKQogICAgICAgIGlmIHRocmVhZCBp"
    "cyBub3QgTm9uZSBhbmQgaGFzYXR0cih0aHJlYWQsICJpc1J1bm5pbmciKSBhbmQgdGhyZWFkLmlz"
    "UnVubmluZygpOgogICAgICAgICAgICBzZWxmLl9kaWFnKAogICAgICAgICAgICAgICAgZiJbVEFT"
    "S1NdW1RIUkVBRF1bV0FSTl0gc3RvcCByZXF1ZXN0ZWQgZm9yIHJlZnJlc2ggd29ya2VyIHJlYXNv"
    "bj17cmVhc29uIG9yICd1bnNwZWNpZmllZCd9IiwKICAgICAgICAgICAgICAgICJXQVJOIiwKICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICB0aHJlYWQucmVxdWVz"
    "dEludGVycnVwdGlvbigpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAg"
    "ICAgICBwYXNzCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHRocmVhZC5xdWl0KCkK"
    "ICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKICAgICAg"
    "ICAgICAgdGhyZWFkLndhaXQoMjAwMCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3RocmVhZCA9IE5v"
    "bmUKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBjYWxsYWJs"
    "ZShzZWxmLl90YXNrc19wcm92aWRlcik6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgc2VsZi5sb2FkX3Rhc2tzKHNlbGYuX3Rhc2tzX3Byb3ZpZGVyKCkpCiAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fZGlhZyhmIltUQVNL"
    "U11bVEFCXVtFUlJPUl0gcmVmcmVzaCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiKQogICAgICAgICAg"
    "ICBzZWxmLnN0b3BfcmVmcmVzaF93b3JrZXIocmVhc29uPSJ0YXNrc190YWJfcmVmcmVzaF9leGNl"
    "cHRpb24iKQoKICAgIGRlZiBjbG9zZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYuc3RvcF9yZWZyZXNoX3dvcmtlcihyZWFzb249InRhc2tzX3RhYl9jbG9zZSIpCiAgICAg"
    "ICAgc3VwZXIoKS5jbG9zZUV2ZW50KGV2ZW50KQoKICAgIGRlZiBzZXRfc2hvd19jb21wbGV0ZWQo"
    "c2VsZiwgZW5hYmxlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9zaG93X2NvbXBsZXRl"
    "ZCA9IGJvb2woZW5hYmxlZCkKICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLnNldFRl"
    "eHQoIkhJREUgQ09NUExFVEVEIiBpZiBzZWxmLl9zaG93X2NvbXBsZXRlZCBlbHNlICJTSE9XIENP"
    "TVBMRVRFRCIpCgogICAgZGVmIHNldF9zdGF0dXMoc2VsZiwgdGV4dDogc3RyLCBvazogYm9vbCA9"
    "IEZhbHNlKSAtPiBOb25lOgogICAgICAgIGNvbG9yID0gQ19HUkVFTiBpZiBvayBlbHNlIENfVEVY"
    "VF9ESU0KICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Y29sb3J9OyBib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA2cHg7IgogICAgICAgICkKICAgICAg"
    "ICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbC5zZXRUZXh0KHRleHQpCgogICAgZGVmIG9w"
    "ZW5fZWRpdG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suc2V0"
    "Q3VycmVudFdpZGdldChzZWxmLmVkaXRvcl93b3Jrc3BhY2UpCgogICAgZGVmIGNsb3NlX2VkaXRv"
    "cihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRX"
    "aWRnZXQoc2VsZi5ub3JtYWxfd29ya3NwYWNlKQoKCmNsYXNzIFNlbGZUYWIoUVdpZGdldCk6CiAg"
    "ICAiIiIKICAgIFBlcnNvbmEncyBpbnRlcm5hbCBkaWFsb2d1ZSBzcGFjZS4KICAgIFJlY2VpdmVz"
    "OiBpZGxlIG5hcnJhdGl2ZSBvdXRwdXQsIHVuc29saWNpdGVkIHRyYW5zbWlzc2lvbnMsCiAgICAg"
    "ICAgICAgICAgUG9JIGxpc3QgZnJvbSBkYWlseSByZWZsZWN0aW9uLCB1bmFuc3dlcmVkIHF1ZXN0"
    "aW9uIGZsYWdzLAogICAgICAgICAgICAgIGpvdXJuYWwgbG9hZCBub3RpZmljYXRpb25zLgogICAg"
    "UmVhZC1vbmx5IGRpc3BsYXkuIFNlcGFyYXRlIGZyb20gcGVyc29uYSBjaGF0IHRhYiBhbHdheXMu"
    "CiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1"
    "cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQog"
    "ICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5z"
    "ZXRTcGFjaW5nKDQpCgogICAgICAgIGhkciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBoZHIuYWRk"
    "V2lkZ2V0KF9zZWN0aW9uX2xibChmIuKdpyBJTk5FUiBTQU5DVFVNIOKAlCB7REVDS19OQU1FLnVw"
    "cGVyKCl9J1MgUFJJVkFURSBUSE9VR0hUUyIpKQogICAgICAgIHNlbGYuX2J0bl9jbGVhciA9IF9n"
    "b3RoaWNfYnRuKCLinJcgQ2xlYXIiKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5zZXRGaXhlZFdp"
    "ZHRoKDgwKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5jbGlja2VkLmNvbm5lY3Qoc2VsZi5jbGVh"
    "cikKICAgICAgICBoZHIuYWRkU3RyZXRjaCgpCiAgICAgICAgaGRyLmFkZFdpZGdldChzZWxmLl9i"
    "dG5fY2xlYXIpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoaGRyKQoKICAgICAgICBzZWxmLl9kaXNw"
    "bGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUp"
    "CiAgICAgICAgc2VsZi5fZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tn"
    "cm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19QVVJQTEVfRElNfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5"
    "OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogOHB4OyIKICAg"
    "ICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fZGlzcGxheSwgMSkKCiAgICBkZWYg"
    "YXBwZW5kKHNlbGYsIGxhYmVsOiBzdHIsIHRleHQ6IHN0cikgLT4gTm9uZToKICAgICAgICB0aW1l"
    "c3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgIGNvbG9y"
    "cyA9IHsKICAgICAgICAgICAgIk5BUlJBVElWRSI6ICBDX0dPTEQsCiAgICAgICAgICAgICJSRUZM"
    "RUNUSU9OIjogQ19QVVJQTEUsCiAgICAgICAgICAgICJKT1VSTkFMIjogICAgQ19TSUxWRVIsCiAg"
    "ICAgICAgICAgICJQT0kiOiAgICAgICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAgIlNZU1RFTSI6"
    "ICAgICBDX1RFWFRfRElNLAogICAgICAgIH0KICAgICAgICBjb2xvciA9IGNvbG9ycy5nZXQobGFi"
    "ZWwudXBwZXIoKSwgQ19HT0xEKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKAogICAgICAg"
    "ICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+"
    "JwogICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAgICAgZic8c3Bh"
    "biBzdHlsZT0iY29sb3I6e2NvbG9yfTsgZm9udC13ZWlnaHQ6Ym9sZDsiPicKICAgICAgICAgICAg"
    "Zifinacge2xhYmVsfTwvc3Bhbj48YnI+JwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xv"
    "cjp7Q19HT0xEfTsiPnt0ZXh0fTwvc3Bhbj4nCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3Bs"
    "YXkuYXBwZW5kKCIiKQogICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5z"
    "ZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1h"
    "eGltdW0oKQogICAgICAgICkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLl9kaXNwbGF5LmNsZWFyKCkKCgojIOKUgOKUgCBESUFHTk9TVElDUyBUQUIg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNs"
    "YXNzIERpYWdub3N0aWNzVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBCYWNrZW5kIGRpYWdub3N0"
    "aWNzIGRpc3BsYXkuCiAgICBSZWNlaXZlczogaGFyZHdhcmUgZGV0ZWN0aW9uIHJlc3VsdHMsIGRl"
    "cGVuZGVuY3kgY2hlY2sgcmVzdWx0cywKICAgICAgICAgICAgICBBUEkgZXJyb3JzLCBzeW5jIGZh"
    "aWx1cmVzLCB0aW1lciBldmVudHMsIGpvdXJuYWwgbG9hZCBub3RpY2VzLAogICAgICAgICAgICAg"
    "IG1vZGVsIGxvYWQgc3RhdHVzLCBHb29nbGUgYXV0aCBldmVudHMuCiAgICBBbHdheXMgc2VwYXJh"
    "dGUgZnJvbSBwZXJzb25hIGNoYXQgdGFiLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYs"
    "IHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBy"
    "b290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0"
    "LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBoZHIgPSBRSEJv"
    "eExheW91dCgpCiAgICAgICAgaGRyLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBESUFHTk9T"
    "VElDUyDigJQgU1lTVEVNICYgQkFDS0VORCBMT0ciKSkKICAgICAgICBzZWxmLl9idG5fY2xlYXIg"
    "PSBfZ290aGljX2J0bigi4pyXIENsZWFyIikKICAgICAgICBzZWxmLl9idG5fY2xlYXIuc2V0Rml4"
    "ZWRXaWR0aCg4MCkKICAgICAgICBzZWxmLl9idG5fY2xlYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "Y2xlYXIpCiAgICAgICAgaGRyLmFkZFN0cmV0Y2goKQogICAgICAgIGhkci5hZGRXaWRnZXQoc2Vs"
    "Zi5fYnRuX2NsZWFyKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGhkcikKCiAgICAgICAgc2VsZi5f"
    "ZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fZGlzcGxheS5zZXRSZWFkT25seShU"
    "cnVlKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJi"
    "YWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX1NJTFZFUn07ICIKICAgICAgICAgICAg"
    "ZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1p"
    "bHk6ICdDb3VyaWVyIE5ldycsIG1vbm9zcGFjZTsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTog"
    "MTBweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2Vs"
    "Zi5fZGlzcGxheSwgMSkKCiAgICBkZWYgbG9nKHNlbGYsIG1lc3NhZ2U6IHN0ciwgbGV2ZWw6IHN0"
    "ciA9ICJJTkZPIikgLT4gTm9uZToKICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5z"
    "dHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgIGxldmVsX2NvbG9ycyA9IHsKICAgICAgICAgICAg"
    "IklORk8iOiAgQ19TSUxWRVIsCiAgICAgICAgICAgICJPSyI6ICAgIENfR1JFRU4sCiAgICAgICAg"
    "ICAgICJXQVJOIjogIENfR09MRCwKICAgICAgICAgICAgIkVSUk9SIjogQ19CTE9PRCwKICAgICAg"
    "ICAgICAgIkRFQlVHIjogQ19URVhUX0RJTSwKICAgICAgICB9CiAgICAgICAgY29sb3IgPSBsZXZl"
    "bF9jb2xvcnMuZ2V0KGxldmVsLnVwcGVyKCksIENfU0lMVkVSKQogICAgICAgIHNlbGYuX2Rpc3Bs"
    "YXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07"
    "Ij5be3RpbWVzdGFtcH1dPC9zcGFuPiAnCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9y"
    "Ontjb2xvcn07Ij57bWVzc2FnZX08L3NwYW4+JwogICAgICAgICkKICAgICAgICBzZWxmLl9kaXNw"
    "bGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2Rpc3Bs"
    "YXkudmVydGljYWxTY3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAgZGVmIGxvZ19t"
    "YW55KHNlbGYsIG1lc3NhZ2VzOiBsaXN0W3N0cl0sIGxldmVsOiBzdHIgPSAiSU5GTyIpIC0+IE5v"
    "bmU6CiAgICAgICAgZm9yIG1zZyBpbiBtZXNzYWdlczoKICAgICAgICAgICAgbHZsID0gbGV2ZWwK"
    "ICAgICAgICAgICAgaWYgIuKckyIgaW4gbXNnOiAgICBsdmwgPSAiT0siCiAgICAgICAgICAgIGVs"
    "aWYgIuKclyIgaW4gbXNnOiAgbHZsID0gIldBUk4iCiAgICAgICAgICAgIGVsaWYgIkVSUk9SIiBp"
    "biBtc2cudXBwZXIoKTogbHZsID0gIkVSUk9SIgogICAgICAgICAgICBzZWxmLmxvZyhtc2csIGx2"
    "bCkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kaXNwbGF5LmNs"
    "ZWFyKCkKCgojIOKUgOKUgCBMRVNTT05TIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTGVz"
    "c29uc1RhYihRV2lkZ2V0KToKICAgICIiIgogICAgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGFuZCBj"
    "b2RlIGxlc3NvbnMgYnJvd3Nlci4KICAgIEFkZCwgdmlldywgc2VhcmNoLCBkZWxldGUgbGVzc29u"
    "cy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBkYjogIkxlc3NvbnNMZWFybmVkREIi"
    "LCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAg"
    "c2VsZi5fZGIgPSBkYgogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJl"
    "c2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZC"
    "b3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0"
    "KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICAjIEZpbHRlciBiYXIKICAgICAg"
    "ICBmaWx0ZXJfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX3NlYXJjaCA9IFFMaW5l"
    "RWRpdCgpCiAgICAgICAgc2VsZi5fc2VhcmNoLnNldFBsYWNlaG9sZGVyVGV4dCgiU2VhcmNoIGxl"
    "c3NvbnMuLi4iKQogICAgICAgIHNlbGYuX2xhbmdfZmlsdGVyID0gUUNvbWJvQm94KCkKICAgICAg"
    "ICBzZWxmLl9sYW5nX2ZpbHRlci5hZGRJdGVtcyhbIkFsbCIsICJMU0wiLCAiUHl0aG9uIiwgIlB5"
    "U2lkZTYiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIkphdmFTY3JpcHQi"
    "LCAiT3RoZXIiXSkKICAgICAgICBzZWxmLl9zZWFyY2gudGV4dENoYW5nZWQuY29ubmVjdChzZWxm"
    "LnJlZnJlc2gpCiAgICAgICAgc2VsZi5fbGFuZ19maWx0ZXIuY3VycmVudFRleHRDaGFuZ2VkLmNv"
    "bm5lY3Qoc2VsZi5yZWZyZXNoKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgi"
    "U2VhcmNoOiIpKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYuX3NlYXJjaCwgMSkK"
    "ICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChRTGFiZWwoIkxhbmd1YWdlOiIpKQogICAgICAg"
    "IGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYuX2xhbmdfZmlsdGVyKQogICAgICAgIHJvb3QuYWRk"
    "TGF5b3V0KGZpbHRlcl9yb3cpCgogICAgICAgIGJ0bl9iYXIgPSBRSEJveExheW91dCgpCiAgICAg"
    "ICAgYnRuX2FkZCA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIExlc3NvbiIpCiAgICAgICAgYnRuX2Rl"
    "bCA9IF9nb3RoaWNfYnRuKCLinJcgRGVsZXRlIikKICAgICAgICBidG5fYWRkLmNsaWNrZWQuY29u"
    "bmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgYnRuX2RlbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "ZG9fZGVsZXRlKQogICAgICAgIGJ0bl9iYXIuYWRkV2lkZ2V0KGJ0bl9hZGQpCiAgICAgICAgYnRu"
    "X2Jhci5hZGRXaWRnZXQoYnRuX2RlbCkKICAgICAgICBidG5fYmFyLmFkZFN0cmV0Y2goKQogICAg"
    "ICAgIHJvb3QuYWRkTGF5b3V0KGJ0bl9iYXIpCgogICAgICAgIHNlbGYuX3RhYmxlID0gUVRhYmxl"
    "V2lkZ2V0KDAsIDQpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVs"
    "cygKICAgICAgICAgICAgWyJMYW5ndWFnZSIsICJSZWZlcmVuY2UgS2V5IiwgIlN1bW1hcnkiLCAi"
    "RW52aXJvbm1lbnQiXQogICAgICAgICkKICAgICAgICBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVh"
    "ZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDIsIFFIZWFkZXJWaWV3LlJl"
    "c2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlv"
    "cigKICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0"
    "Um93cykKICAgICAgICBzZWxmLl90YWJsZS5zZXRBbHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVlKQog"
    "ICAgICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQog"
    "ICAgICAgIHNlbGYuX3RhYmxlLml0ZW1TZWxlY3Rpb25DaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25f"
    "c2VsZWN0KQoKICAgICAgICAjIFVzZSBzcGxpdHRlciBiZXR3ZWVuIHRhYmxlIGFuZCBkZXRhaWwK"
    "ICAgICAgICBzcGxpdHRlciA9IFFTcGxpdHRlcihRdC5PcmllbnRhdGlvbi5WZXJ0aWNhbCkKICAg"
    "ICAgICBzcGxpdHRlci5hZGRXaWRnZXQoc2VsZi5fdGFibGUpCgogICAgICAgICMgRGV0YWlsIHBh"
    "bmVsCiAgICAgICAgZGV0YWlsX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIGRldGFpbF9sYXlv"
    "dXQgPSBRVkJveExheW91dChkZXRhaWxfd2lkZ2V0KQogICAgICAgIGRldGFpbF9sYXlvdXQuc2V0"
    "Q29udGVudHNNYXJnaW5zKDAsIDQsIDAsIDApCiAgICAgICAgZGV0YWlsX2xheW91dC5zZXRTcGFj"
    "aW5nKDIpCgogICAgICAgIGRldGFpbF9oZWFkZXIgPSBRSEJveExheW91dCgpCiAgICAgICAgZGV0"
    "YWlsX2hlYWRlci5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgRlVMTCBSVUxFIikpCiAgICAg"
    "ICAgZGV0YWlsX2hlYWRlci5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxl"
    "ID0gX2dvdGhpY19idG4oIkVkaXQiKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Rml4"
    "ZWRXaWR0aCg1MCkKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldENoZWNrYWJsZShUcnVl"
    "KQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUudG9nZ2xlZC5jb25uZWN0KHNlbGYuX3RvZ2ds"
    "ZV9lZGl0X21vZGUpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZSA9IF9nb3RoaWNfYnRuKCJT"
    "YXZlIikKICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlLnNldEZpeGVkV2lkdGgoNTApCiAgICAg"
    "ICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRWaXNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYuX2J0"
    "bl9zYXZlX3J1bGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3NhdmVfcnVsZV9lZGl0KQogICAgICAg"
    "IGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9lZGl0X3J1bGUpCiAgICAgICAgZGV0"
    "YWlsX2hlYWRlci5hZGRXaWRnZXQoc2VsZi5fYnRuX3NhdmVfcnVsZSkKICAgICAgICBkZXRhaWxf"
    "bGF5b3V0LmFkZExheW91dChkZXRhaWxfaGVhZGVyKQoKICAgICAgICBzZWxmLl9kZXRhaWwgPSBR"
    "VGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2RldGFpbC5zZXRSZWFkT25seShUcnVlKQogICAgICAg"
    "IHNlbGYuX2RldGFpbC5zZXRNaW5pbXVtSGVpZ2h0KDEyMCkKICAgICAgICBzZWxmLl9kZXRhaWwu"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjog"
    "e0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAi"
    "CiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXpl"
    "OiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICkKICAgICAgICBkZXRhaWxfbGF5b3V0LmFk"
    "ZFdpZGdldChzZWxmLl9kZXRhaWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KGRldGFpbF93"
    "aWRnZXQpCiAgICAgICAgc3BsaXR0ZXIuc2V0U2l6ZXMoWzMwMCwgMTgwXSkKICAgICAgICByb290"
    "LmFkZFdpZGdldChzcGxpdHRlciwgMSkKCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0"
    "XSA9IFtdCiAgICAgICAgc2VsZi5fZWRpdGluZ19yb3c6IGludCA9IC0xCgogICAgZGVmIHJlZnJl"
    "c2goc2VsZikgLT4gTm9uZToKICAgICAgICBxICAgID0gc2VsZi5fc2VhcmNoLnRleHQoKQogICAg"
    "ICAgIGxhbmcgPSBzZWxmLl9sYW5nX2ZpbHRlci5jdXJyZW50VGV4dCgpCiAgICAgICAgbGFuZyA9"
    "ICIiIGlmIGxhbmcgPT0gIkFsbCIgZWxzZSBsYW5nCiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHNl"
    "bGYuX2RiLnNlYXJjaChxdWVyeT1xLCBsYW5ndWFnZT1sYW5nKQogICAgICAgIHNlbGYuX3RhYmxl"
    "LnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAg"
    "ICAgICByID0gc2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5p"
    "bnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAg"
    "ICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJsYW5ndWFnZSIsIiIpKSkKICAgICAg"
    "ICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lk"
    "Z2V0SXRlbShyZWMuZ2V0KCJyZWZlcmVuY2Vfa2V5IiwiIikpKQogICAgICAgICAgICBzZWxmLl90"
    "YWJsZS5zZXRJdGVtKHIsIDIsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5n"
    "ZXQoInN1bW1hcnkiLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMywK"
    "ICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiZW52aXJvbm1lbnQiLCIi"
    "KSkpCgogICAgZGVmIF9vbl9zZWxlY3Qoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxm"
    "Ll90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBzZWxmLl9lZGl0aW5nX3JvdyA9IHJvdwogICAg"
    "ICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZWMgPSBz"
    "ZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFBsYWluVGV4dCgK"
    "ICAgICAgICAgICAgICAgIHJlYy5nZXQoImZ1bGxfcnVsZSIsIiIpICsgIlxuXG4iICsKICAgICAg"
    "ICAgICAgICAgICgiUmVzb2x1dGlvbjogIiArIHJlYy5nZXQoInJlc29sdXRpb24iLCIiKSBpZiBy"
    "ZWMuZ2V0KCJyZXNvbHV0aW9uIikgZWxzZSAiIikKICAgICAgICAgICAgKQogICAgICAgICAgICAj"
    "IFJlc2V0IGVkaXQgbW9kZSBvbiBuZXcgc2VsZWN0aW9uCiAgICAgICAgICAgIHNlbGYuX2J0bl9l"
    "ZGl0X3J1bGUuc2V0Q2hlY2tlZChGYWxzZSkKCiAgICBkZWYgX3RvZ2dsZV9lZGl0X21vZGUoc2Vs"
    "ZiwgZWRpdGluZzogYm9vbCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0UmVhZE9u"
    "bHkobm90IGVkaXRpbmcpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRWaXNpYmxlKGVk"
    "aXRpbmcpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRUZXh0KCJDYW5jZWwiIGlmIGVk"
    "aXRpbmcgZWxzZSAiRWRpdCIpCiAgICAgICAgaWYgZWRpdGluZzoKICAgICAgICAgICAgc2VsZi5f"
    "ZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JH"
    "Mn07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xp"
    "ZCB7Q19HT0xEX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZP"
    "TlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICAgICAp"
    "CiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgIgog"
    "ICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAg"
    "ICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFw"
    "eDsgcGFkZGluZzogNHB4OyIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIFJlbG9hZCBvcmln"
    "aW5hbCBjb250ZW50IG9uIGNhbmNlbAogICAgICAgICAgICBzZWxmLl9vbl9zZWxlY3QoKQoKICAg"
    "IGRlZiBfc2F2ZV9ydWxlX2VkaXQoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl9l"
    "ZGl0aW5nX3JvdwogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAg"
    "ICAgICAgICB0ZXh0ID0gc2VsZi5fZGV0YWlsLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQogICAgICAg"
    "ICAgICAjIFNwbGl0IHJlc29sdXRpb24gYmFjayBvdXQgaWYgcHJlc2VudAogICAgICAgICAgICBp"
    "ZiAiXG5cblJlc29sdXRpb246ICIgaW4gdGV4dDoKICAgICAgICAgICAgICAgIHBhcnRzID0gdGV4"
    "dC5zcGxpdCgiXG5cblJlc29sdXRpb246ICIsIDEpCiAgICAgICAgICAgICAgICBmdWxsX3J1bGUg"
    "ID0gcGFydHNbMF0uc3RyaXAoKQogICAgICAgICAgICAgICAgcmVzb2x1dGlvbiA9IHBhcnRzWzFd"
    "LnN0cmlwKCkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZSAgPSB0"
    "ZXh0CiAgICAgICAgICAgICAgICByZXNvbHV0aW9uID0gc2VsZi5fcmVjb3Jkc1tyb3ddLmdldCgi"
    "cmVzb2x1dGlvbiIsICIiKQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd11bImZ1bGxfcnVs"
    "ZSJdICA9IGZ1bGxfcnVsZQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd11bInJlc29sdXRp"
    "b24iXSA9IHJlc29sdXRpb24KICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fZGIuX3BhdGgs"
    "IHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Q2hlY2tl"
    "ZChGYWxzZSkKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2FkZChzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2lu"
    "ZG93VGl0bGUoIkFkZCBMZXNzb24iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dy"
    "b3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAs"
    "IDQwMCkKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAgIGVudiAgPSBRTGlu"
    "ZUVkaXQoIkxTTCIpCiAgICAgICAgbGFuZyA9IFFMaW5lRWRpdCgiTFNMIikKICAgICAgICByZWYg"
    "ID0gUUxpbmVFZGl0KCkKICAgICAgICBzdW1tID0gUUxpbmVFZGl0KCkKICAgICAgICBydWxlID0g"
    "UVRleHRFZGl0KCkKICAgICAgICBydWxlLnNldE1heGltdW1IZWlnaHQoMTAwKQogICAgICAgIHJl"
    "cyAgPSBRTGluZUVkaXQoKQogICAgICAgIGxpbmsgPSBRTGluZUVkaXQoKQogICAgICAgIGZvciBs"
    "YWJlbCwgdyBpbiBbCiAgICAgICAgICAgICgiRW52aXJvbm1lbnQ6IiwgZW52KSwgKCJMYW5ndWFn"
    "ZToiLCBsYW5nKSwKICAgICAgICAgICAgKCJSZWZlcmVuY2UgS2V5OiIsIHJlZiksICgiU3VtbWFy"
    "eToiLCBzdW1tKSwKICAgICAgICAgICAgKCJGdWxsIFJ1bGU6IiwgcnVsZSksICgiUmVzb2x1dGlv"
    "bjoiLCByZXMpLAogICAgICAgICAgICAoIkxpbms6IiwgbGluayksCiAgICAgICAgXToKICAgICAg"
    "ICAgICAgZm9ybS5hZGRSb3cobGFiZWwsIHcpCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkK"
    "ICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNl"
    "bCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNv"
    "bm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lk"
    "Z2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9"
    "PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHNlbGYuX2RiLmFkZCgK"
    "ICAgICAgICAgICAgICAgIGVudmlyb25tZW50PWVudi50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAg"
    "ICAgICAgIGxhbmd1YWdlPWxhbmcudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICByZWZl"
    "cmVuY2Vfa2V5PXJlZi50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIHN1bW1hcnk9c3Vt"
    "bS50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZT1ydWxlLnRvUGxhaW5U"
    "ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIHJlc29sdXRpb249cmVzLnRleHQoKS5zdHJp"
    "cCgpLAogICAgICAgICAgICAgICAgbGluaz1saW5rLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAg"
    "ICApCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBp"
    "ZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmVjX2lkID0gc2Vs"
    "Zi5fcmVjb3Jkc1tyb3ddLmdldCgiaWQiLCIiKQogICAgICAgICAgICByZXBseSA9IFFNZXNzYWdl"
    "Qm94LnF1ZXN0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBMZXNzb24iLAogICAg"
    "ICAgICAgICAgICAgIkRlbGV0ZSB0aGlzIGxlc3Nvbj8gQ2Fubm90IGJlIHVuZG9uZS4iLAogICAg"
    "ICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3gu"
    "U3RhbmRhcmRCdXR0b24uTm8KICAgICAgICAgICAgKQogICAgICAgICAgICBpZiByZXBseSA9PSBR"
    "TWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgICAgICBzZWxmLl9kYi5k"
    "ZWxldGUocmVjX2lkKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCgojIOKUgOKUgCBN"
    "T0RVTEUgVFJBQ0tFUiBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1vZHVsZVRyYWNrZXJUYWIoUVdpZGdldCk6CiAgICAiIiIK"
    "ICAgIFBlcnNvbmFsIG1vZHVsZSBwaXBlbGluZSB0cmFja2VyLgogICAgVHJhY2sgcGxhbm5lZC9p"
    "bi1wcm9ncmVzcy9idWlsdCBtb2R1bGVzIGFzIHRoZXkgYXJlIGRlc2lnbmVkLgogICAgRWFjaCBt"
    "b2R1bGUgaGFzOiBOYW1lLCBTdGF0dXMsIERlc2NyaXB0aW9uLCBOb3Rlcy4KICAgIEV4cG9ydCB0"
    "byBUWFQgZm9yIHBhc3RpbmcgaW50byBzZXNzaW9ucy4KICAgIEltcG9ydDogcGFzdGUgYSBmaW5h"
    "bGl6ZWQgc3BlYywgaXQgcGFyc2VzIG5hbWUgYW5kIGRldGFpbHMuCiAgICBUaGlzIGlzIGEgZGVz"
    "aWduIG5vdGVib29rIOKAlCBub3QgY29ubmVjdGVkIHRvIGRlY2tfYnVpbGRlcidzIE1PRFVMRSBy"
    "ZWdpc3RyeS4KICAgICIiIgoKICAgIFNUQVRVU0VTID0gWyJJZGVhIiwgIkRlc2lnbmluZyIsICJS"
    "ZWFkeSB0byBCdWlsZCIsICJQYXJ0aWFsIiwgIkJ1aWx0Il0KCiAgICBkZWYgX19pbml0X18oc2Vs"
    "ZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAg"
    "IHNlbGYuX3BhdGggPSBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJtb2R1bGVfdHJhY2tlci5qc29u"
    "bCIKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9z"
    "ZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5z"
    "ZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkK"
    "CiAgICAgICAgIyBCdXR0b24gYmFyCiAgICAgICAgYnRuX2JhciA9IFFIQm94TGF5b3V0KCkKICAg"
    "ICAgICBzZWxmLl9idG5fYWRkICAgID0gX2dvdGhpY19idG4oIkFkZCBNb2R1bGUiKQogICAgICAg"
    "IHNlbGYuX2J0bl9lZGl0ICAgPSBfZ290aGljX2J0bigiRWRpdCIpCiAgICAgICAgc2VsZi5fYnRu"
    "X2RlbGV0ZSA9IF9nb3RoaWNfYnRuKCJEZWxldGUiKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQg"
    "PSBfZ290aGljX2J0bigiRXhwb3J0IFRYVCIpCiAgICAgICAgc2VsZi5fYnRuX2ltcG9ydCA9IF9n"
    "b3RoaWNfYnRuKCJJbXBvcnQgU3BlYyIpCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQs"
    "IHNlbGYuX2J0bl9lZGl0LCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxm"
    "Ll9idG5fZXhwb3J0LCBzZWxmLl9idG5faW1wb3J0KToKICAgICAgICAgICAgYi5zZXRNaW5pbXVt"
    "V2lkdGgoODApCiAgICAgICAgICAgIGIuc2V0TWluaW11bUhlaWdodCgyNikKICAgICAgICAgICAg"
    "YnRuX2Jhci5hZGRXaWRnZXQoYikKICAgICAgICBidG5fYmFyLmFkZFN0cmV0Y2goKQogICAgICAg"
    "IHJvb3QuYWRkTGF5b3V0KGJ0bl9iYXIpCgogICAgICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAgICBzZWxmLl9idG5fZWRpdC5jbGlja2VkLmNvbm5l"
    "Y3Qoc2VsZi5fZG9fZWRpdCkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydC5jbGlja2VkLmNvbm5l"
    "Y3Qoc2VsZi5fZG9fZXhwb3J0KQogICAgICAgIHNlbGYuX2J0bl9pbXBvcnQuY2xpY2tlZC5jb25u"
    "ZWN0KHNlbGYuX2RvX2ltcG9ydCkKCiAgICAgICAgIyBUYWJsZQogICAgICAgIHNlbGYuX3RhYmxl"
    "ID0gUVRhYmxlV2lkZ2V0KDAsIDMpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhl"
    "YWRlckxhYmVscyhbIk1vZHVsZSBOYW1lIiwgIlN0YXR1cyIsICJEZXNjcmlwdGlvbiJdKQogICAg"
    "ICAgIGhoID0gc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpCiAgICAgICAgaGguc2V0U2Vj"
    "dGlvblJlc2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAgICBz"
    "ZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgwLCAxNjApCiAgICAgICAgaGguc2V0U2VjdGlvblJl"
    "c2l6ZU1vZGUoMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAgICBzZWxmLl90"
    "YWJsZS5zZXRDb2x1bW5XaWR0aCgxLCAxMDApCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1v"
    "ZGUoMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxl"
    "LnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxl"
    "Y3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0"
    "aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVTaGVldChfZ290"
    "aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2VsZi5fdGFibGUuaXRlbVNlbGVjdGlvbkNoYW5n"
    "ZWQuY29ubmVjdChzZWxmLl9vbl9zZWxlY3QpCgogICAgICAgICMgU3BsaXR0ZXIKICAgICAgICBz"
    "cGxpdHRlciA9IFFTcGxpdHRlcihRdC5PcmllbnRhdGlvbi5WZXJ0aWNhbCkKICAgICAgICBzcGxp"
    "dHRlci5hZGRXaWRnZXQoc2VsZi5fdGFibGUpCgogICAgICAgICMgTm90ZXMgcGFuZWwKICAgICAg"
    "ICBub3Rlc193aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBub3Rlc19sYXlvdXQgPSBRVkJveExh"
    "eW91dChub3Rlc193aWRnZXQpCiAgICAgICAgbm90ZXNfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lu"
    "cygwLCA0LCAwLCAwKQogICAgICAgIG5vdGVzX2xheW91dC5zZXRTcGFjaW5nKDIpCiAgICAgICAg"
    "bm90ZXNfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBOT1RFUyIpKQogICAgICAg"
    "IHNlbGYuX25vdGVzX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX25vdGVzX2Rp"
    "c3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5LnNldE1p"
    "bmltdW1IZWlnaHQoMTIwKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIK"
    "ICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAg"
    "IGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRk"
    "aW5nOiA0cHg7IgogICAgICAgICkKICAgICAgICBub3Rlc19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYu"
    "X25vdGVzX2Rpc3BsYXkpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KG5vdGVzX3dpZGdldCkK"
    "ICAgICAgICBzcGxpdHRlci5zZXRTaXplcyhbMjUwLCAxNTBdKQogICAgICAgIHJvb3QuYWRkV2lk"
    "Z2V0KHNwbGl0dGVyLCAxKQoKICAgICAgICAjIENvdW50IGxhYmVsCiAgICAgICAgc2VsZi5fY291"
    "bnRfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYuX2NvdW50X2xibC5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRX"
    "aWRnZXQoc2VsZi5fY291bnRfbGJsKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBzZWxm"
    "Ll90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoK"
    "ICAgICAgICAgICAgciA9IHNlbGYuX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5f"
    "dGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMCwg"
    "UVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJuYW1lIiwgIiIpKSkKICAgICAgICAgICAgc3RhdHVz"
    "X2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInN0YXR1cyIsICJJZGVhIikpCiAgICAg"
    "ICAgICAgICMgQ29sb3IgYnkgc3RhdHVzCiAgICAgICAgICAgIHN0YXR1c19jb2xvcnMgPSB7CiAg"
    "ICAgICAgICAgICAgICAiSWRlYSI6ICAgICAgICAgICAgIENfVEVYVF9ESU0sCiAgICAgICAgICAg"
    "ICAgICAiRGVzaWduaW5nIjogICAgICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgICAgICAiUmVh"
    "ZHkgdG8gQnVpbGQiOiAgIENfUFVSUExFLAogICAgICAgICAgICAgICAgIlBhcnRpYWwiOiAgICAg"
    "ICAgICAiI2NjODg0NCIsCiAgICAgICAgICAgICAgICAiQnVpbHQiOiAgICAgICAgICAgIENfR1JF"
    "RU4sCiAgICAgICAgICAgIH0KICAgICAgICAgICAgc3RhdHVzX2l0ZW0uc2V0Rm9yZWdyb3VuZCgK"
    "ICAgICAgICAgICAgICAgIFFDb2xvcihzdGF0dXNfY29sb3JzLmdldChyZWMuZ2V0KCJzdGF0dXMi"
    "LCJJZGVhIiksIENfVEVYVF9ESU0pKQogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3Rh"
    "YmxlLnNldEl0ZW0ociwgMSwgc3RhdHVzX2l0ZW0pCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNl"
    "dEl0ZW0ociwgMiwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiZGVz"
    "Y3JpcHRpb24iLCAiIilbOjgwXSkpCiAgICAgICAgY291bnRzID0ge30KICAgICAgICBmb3IgcmVj"
    "IGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIHMgPSByZWMuZ2V0KCJzdGF0dXMiLCAiSWRl"
    "YSIpCiAgICAgICAgICAgIGNvdW50c1tzXSA9IGNvdW50cy5nZXQocywgMCkgKyAxCiAgICAgICAg"
    "Y291bnRfc3RyID0gIiAgIi5qb2luKGYie3N9OiB7bn0iIGZvciBzLCBuIGluIGNvdW50cy5pdGVt"
    "cygpKQogICAgICAgIHNlbGYuX2NvdW50X2xibC5zZXRUZXh0KAogICAgICAgICAgICBmIlRvdGFs"
    "OiB7bGVuKHNlbGYuX3JlY29yZHMpfSAgIHtjb3VudF9zdHJ9IgogICAgICAgICkKCiAgICBkZWYg"
    "X29uX3NlbGVjdChzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJl"
    "bnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAg"
    "ICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICAgICAgc2VsZi5fbm90ZXNfZGlz"
    "cGxheS5zZXRQbGFpblRleHQocmVjLmdldCgibm90ZXMiLCAiIikpCgogICAgZGVmIF9kb19hZGQo"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9vcGVuX2VkaXRfZGlhbG9nKCkKCiAgICBkZWYg"
    "X2RvX2VkaXQoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50"
    "Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAg"
    "ICAgc2VsZi5fb3Blbl9lZGl0X2RpYWxvZyhzZWxmLl9yZWNvcmRzW3Jvd10sIHJvdykKCiAgICBk"
    "ZWYgX29wZW5fZWRpdF9kaWFsb2coc2VsZiwgcmVjOiBkaWN0ID0gTm9uZSwgcm93OiBpbnQgPSAt"
    "MSkgLT4gTm9uZToKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdp"
    "bmRvd1RpdGxlKCJNb2R1bGUiIGlmIG5vdCByZWMgZWxzZSBmIkVkaXQ6IHtyZWMuZ2V0KCduYW1l"
    "JywnJyl9IikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07"
    "IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5yZXNpemUoNTQwLCA0NDApCiAgICAgICAg"
    "Zm9ybSA9IFFWQm94TGF5b3V0KGRsZykKCiAgICAgICAgbmFtZV9maWVsZCA9IFFMaW5lRWRpdChy"
    "ZWMuZ2V0KCJuYW1lIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgbmFtZV9maWVsZC5zZXRQ"
    "bGFjZWhvbGRlclRleHQoIk1vZHVsZSBuYW1lIikKCiAgICAgICAgc3RhdHVzX2NvbWJvID0gUUNv"
    "bWJvQm94KCkKICAgICAgICBzdGF0dXNfY29tYm8uYWRkSXRlbXMoc2VsZi5TVEFUVVNFUykKICAg"
    "ICAgICBpZiByZWM6CiAgICAgICAgICAgIGlkeCA9IHN0YXR1c19jb21iby5maW5kVGV4dChyZWMu"
    "Z2V0KCJzdGF0dXMiLCJJZGVhIikpCiAgICAgICAgICAgIGlmIGlkeCA+PSAwOgogICAgICAgICAg"
    "ICAgICAgc3RhdHVzX2NvbWJvLnNldEN1cnJlbnRJbmRleChpZHgpCgogICAgICAgIGRlc2NfZmll"
    "bGQgPSBRTGluZUVkaXQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSBpZiByZWMgZWxzZSAiIikK"
    "ICAgICAgICBkZXNjX2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgiT25lLWxpbmUgZGVzY3JpcHRp"
    "b24iKQoKICAgICAgICBub3Rlc19maWVsZCA9IFFUZXh0RWRpdCgpCiAgICAgICAgbm90ZXNfZmll"
    "bGQuc2V0UGxhaW5UZXh0KHJlYy5nZXQoIm5vdGVzIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAg"
    "ICAgbm90ZXNfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KAogICAgICAgICAgICAiRnVsbCBub3Rl"
    "cyDigJQgc3BlYywgaWRlYXMsIHJlcXVpcmVtZW50cywgZWRnZSBjYXNlcy4uLiIKICAgICAgICAp"
    "CiAgICAgICAgbm90ZXNfZmllbGQuc2V0TWluaW11bUhlaWdodCgyMDApCgogICAgICAgIGZvciBs"
    "YWJlbCwgd2lkZ2V0IGluIFsKICAgICAgICAgICAgKCJOYW1lOiIsIG5hbWVfZmllbGQpLAogICAg"
    "ICAgICAgICAoIlN0YXR1czoiLCBzdGF0dXNfY29tYm8pLAogICAgICAgICAgICAoIkRlc2NyaXB0"
    "aW9uOiIsIGRlc2NfZmllbGQpLAogICAgICAgICAgICAoIk5vdGVzOiIsIG5vdGVzX2ZpZWxkKSwK"
    "ICAgICAgICBdOgogICAgICAgICAgICByb3dfbGF5b3V0ID0gUUhCb3hMYXlvdXQoKQogICAgICAg"
    "ICAgICBsYmwgPSBRTGFiZWwobGFiZWwpCiAgICAgICAgICAgIGxibC5zZXRGaXhlZFdpZHRoKDkw"
    "KQogICAgICAgICAgICByb3dfbGF5b3V0LmFkZFdpZGdldChsYmwpCiAgICAgICAgICAgIHJvd19s"
    "YXlvdXQuYWRkV2lkZ2V0KHdpZGdldCkKICAgICAgICAgICAgZm9ybS5hZGRMYXlvdXQocm93X2xh"
    "eW91dCkKCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fc2F2ZSAg"
    "ID0gX2dvdGhpY19idG4oIlNhdmUiKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigi"
    "Q2FuY2VsIikKICAgICAgICBidG5fc2F2ZS5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCkKICAg"
    "ICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bl9y"
    "b3cuYWRkV2lkZ2V0KGJ0bl9zYXZlKQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9jYW5j"
    "ZWwpCiAgICAgICAgZm9ybS5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICAgICAgaWYgZGxnLmV4ZWMo"
    "KSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIG5ld19yZWMgPSB7"
    "CiAgICAgICAgICAgICAgICAiaWQiOiAgICAgICAgICByZWMuZ2V0KCJpZCIsIHN0cih1dWlkLnV1"
    "aWQ0KCkpKSBpZiByZWMgZWxzZSBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgICAgICJu"
    "YW1lIjogICAgICAgIG5hbWVfZmllbGQudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAi"
    "c3RhdHVzIjogICAgICBzdGF0dXNfY29tYm8uY3VycmVudFRleHQoKSwKICAgICAgICAgICAgICAg"
    "ICJkZXNjcmlwdGlvbiI6IGRlc2NfZmllbGQudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAg"
    "ICAibm90ZXMiOiAgICAgICBub3Rlc19maWVsZC50b1BsYWluVGV4dCgpLnN0cmlwKCksCiAgICAg"
    "ICAgICAgICAgICAiY3JlYXRlZCI6ICAgICByZWMuZ2V0KCJjcmVhdGVkIiwgZGF0ZXRpbWUubm93"
    "KCkuaXNvZm9ybWF0KCkpIGlmIHJlYyBlbHNlIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAog"
    "ICAgICAgICAgICAgICAgIm1vZGlmaWVkIjogICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCks"
    "CiAgICAgICAgICAgIH0KICAgICAgICAgICAgaWYgcm93ID49IDA6CiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9yZWNvcmRzW3Jvd10gPSBuZXdfcmVjCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "ICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChuZXdfcmVjKQogICAgICAgICAgICB3cml0ZV9qc29u"
    "bChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoK"
    "ICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFi"
    "bGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6"
    "CiAgICAgICAgICAgIG5hbWUgPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJuYW1lIiwidGhpcyBt"
    "b2R1bGUiKQogICAgICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAg"
    "ICAgICAgICAgc2VsZiwgIkRlbGV0ZSBNb2R1bGUiLAogICAgICAgICAgICAgICAgZiJEZWxldGUg"
    "J3tuYW1lfSc/IENhbm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAgICAgIFFNZXNzYWdlQm94"
    "LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0"
    "b24uWWVzOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5wb3Aocm93KQogICAgICAgICAg"
    "ICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAg"
    "ICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19leHBvcnQoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgIGV4cG9ydF9kaXIgPSBjZmdfcGF0aCgiZXhwb3J0cyIpCiAg"
    "ICAgICAgICAgIGV4cG9ydF9kaXIubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQog"
    "ICAgICAgICAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlWSVtJWRfJUglTSVTIikK"
    "ICAgICAgICAgICAgb3V0X3BhdGggPSBleHBvcnRfZGlyIC8gZiJtb2R1bGVzX3t0c30udHh0Igog"
    "ICAgICAgICAgICBsaW5lcyA9IFsKICAgICAgICAgICAgICAgICJFQ0hPIERFQ0sg4oCUIE1PRFVM"
    "RSBUUkFDS0VSIEVYUE9SVCIsCiAgICAgICAgICAgICAgICBmIkV4cG9ydGVkOiB7ZGF0ZXRpbWUu"
    "bm93KCkuc3RyZnRpbWUoJyVZLSVtLSVkICVIOiVNOiVTJyl9IiwKICAgICAgICAgICAgICAgIGYi"
    "VG90YWwgbW9kdWxlczoge2xlbihzZWxmLl9yZWNvcmRzKX0iLAogICAgICAgICAgICAgICAgIj0i"
    "ICogNjAsCiAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgXQogICAgICAgICAgICBmb3Ig"
    "cmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgICAgICBsaW5lcy5leHRlbmQoWwogICAg"
    "ICAgICAgICAgICAgICAgIGYiTU9EVUxFOiB7cmVjLmdldCgnbmFtZScsJycpfSIsCiAgICAgICAg"
    "ICAgICAgICAgICAgZiJTdGF0dXM6IHtyZWMuZ2V0KCdzdGF0dXMnLCcnKX0iLAogICAgICAgICAg"
    "ICAgICAgICAgIGYiRGVzY3JpcHRpb246IHtyZWMuZ2V0KCdkZXNjcmlwdGlvbicsJycpfSIsCiAg"
    "ICAgICAgICAgICAgICAgICAgIiIsCiAgICAgICAgICAgICAgICAgICAgIk5vdGVzOiIsCiAgICAg"
    "ICAgICAgICAgICAgICAgcmVjLmdldCgibm90ZXMiLCIiKSwKICAgICAgICAgICAgICAgICAgICAi"
    "IiwKICAgICAgICAgICAgICAgICAgICAiLSIgKiA0MCwKICAgICAgICAgICAgICAgICAgICAiIiwK"
    "ICAgICAgICAgICAgICAgIF0pCiAgICAgICAgICAgIG91dF9wYXRoLndyaXRlX3RleHQoIlxuIi5q"
    "b2luKGxpbmVzKSwgZW5jb2Rpbmc9InV0Zi04IikKICAgICAgICAgICAgUUFwcGxpY2F0aW9uLmNs"
    "aXBib2FyZCgpLnNldFRleHQoIlxuIi5qb2luKGxpbmVzKSkKICAgICAgICAgICAgUU1lc3NhZ2VC"
    "b3guaW5mb3JtYXRpb24oCiAgICAgICAgICAgICAgICBzZWxmLCAiRXhwb3J0ZWQiLAogICAgICAg"
    "ICAgICAgICAgZiJNb2R1bGUgdHJhY2tlciBleHBvcnRlZCB0bzpcbntvdXRfcGF0aH1cblxuQWxz"
    "byBjb3BpZWQgdG8gY2xpcGJvYXJkLiIKICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb24gYXMgZToKICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2FybmluZyhzZWxmLCAiRXhwb3J0"
    "IEVycm9yIiwgc3RyKGUpKQoKICAgIGRlZiBfZG9faW1wb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgIiIiSW1wb3J0IGEgbW9kdWxlIHNwZWMgZnJvbSBjbGlwYm9hcmQgb3IgdHlwZWQgdGV4dC4i"
    "IiIKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxl"
    "KCJJbXBvcnQgTW9kdWxlIFNwZWMiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dy"
    "b3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAs"
    "IDM0MCkKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChkbGcpCiAgICAgICAgbGF5b3V0LmFk"
    "ZFdpZGdldChRTGFiZWwoCiAgICAgICAgICAgICJQYXN0ZSBhIG1vZHVsZSBzcGVjIGJlbG93Llxu"
    "IgogICAgICAgICAgICAiRmlyc3QgbGluZSB3aWxsIGJlIHVzZWQgYXMgdGhlIG1vZHVsZSBuYW1l"
    "LiIKICAgICAgICApKQogICAgICAgIHRleHRfZmllbGQgPSBRVGV4dEVkaXQoKQogICAgICAgIHRl"
    "eHRfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KCJQYXN0ZSBtb2R1bGUgc3BlYyBoZXJlLi4uIikK"
    "ICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHRleHRfZmllbGQsIDEpCiAgICAgICAgYnRuX3JvdyA9"
    "IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fb2sgICAgID0gX2dvdGhpY19idG4oIkltcG9ydCIp"
    "CiAgICAgICAgYnRuX2NhbmNlbCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIGJ0bl9v"
    "ay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQu"
    "Y29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9vaykKICAg"
    "ICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2FuY2VsKQogICAgICAgIGxheW91dC5hZGRMYXlv"
    "dXQoYnRuX3JvdykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUu"
    "QWNjZXB0ZWQ6CiAgICAgICAgICAgIHJhdyA9IHRleHRfZmllbGQudG9QbGFpblRleHQoKS5zdHJp"
    "cCgpCiAgICAgICAgICAgIGlmIG5vdCByYXc6CiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAg"
    "ICAgICAgbGluZXMgPSByYXcuc3BsaXRsaW5lcygpCiAgICAgICAgICAgICMgRmlyc3Qgbm9uLWVt"
    "cHR5IGxpbmUgPSBuYW1lCiAgICAgICAgICAgIG5hbWUgPSAiIgogICAgICAgICAgICBmb3IgbGlu"
    "ZSBpbiBsaW5lczoKICAgICAgICAgICAgICAgIGlmIGxpbmUuc3RyaXAoKToKICAgICAgICAgICAg"
    "ICAgICAgICBuYW1lID0gbGluZS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAg"
    "ICAgICAgICAgbmV3X3JlYyA9IHsKICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHN0cih1"
    "dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAgICAgIm5hbWUiOiAgICAgICAgbmFtZVs6NjBdLAog"
    "ICAgICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgIklkZWEiLAogICAgICAgICAgICAgICAgImRl"
    "c2NyaXB0aW9uIjogIiIsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICByYXcsCiAgICAg"
    "ICAgICAgICAgICAiY3JlYXRlZCI6ICAgICBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAg"
    "ICAgICAgICAgICAgICJtb2RpZmllZCI6ICAgIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAog"
    "ICAgICAgICAgICB9CiAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKG5ld19yZWMpCiAg"
    "ICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAg"
    "ICAgIHNlbGYucmVmcmVzaCgpCgoKIyDilIDilIAgUEFTUyA1IENPTVBMRVRFIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAoj"
    "IEFsbCB0YWIgY29udGVudCBjbGFzc2VzIGRlZmluZWQuCiMgU0xTY2Fuc1RhYjogcmVidWlsdCDi"
    "gJQgRGVsZXRlIGFkZGVkLCBNb2RpZnkgZml4ZWQsIHRpbWVzdGFtcCBwYXJzZXIgZml4ZWQsCiMg"
    "ICAgICAgICAgICAgY2FyZC9ncmltb2lyZSBzdHlsZSwgY29weS10by1jbGlwYm9hcmQgY29udGV4"
    "dCBtZW51LgojIFNMQ29tbWFuZHNUYWI6IGdvdGhpYyB0YWJsZSwg4qeJIENvcHkgQ29tbWFuZCBi"
    "dXR0b24uCiMgSm9iVHJhY2tlclRhYjogZnVsbCByZWJ1aWxkIOKAlCBtdWx0aS1zZWxlY3QsIGFy"
    "Y2hpdmUvcmVzdG9yZSwgQ1NWL1RTViBleHBvcnQuCiMgU2VsZlRhYjogaW5uZXIgc2FuY3R1bSBm"
    "b3IgaWRsZSBuYXJyYXRpdmUgYW5kIHJlZmxlY3Rpb24gb3V0cHV0LgojIERpYWdub3N0aWNzVGFi"
    "OiBzdHJ1Y3R1cmVkIGxvZyB3aXRoIGxldmVsLWNvbG9yZWQgb3V0cHV0LgojIExlc3NvbnNUYWI6"
    "IExTTCBGb3JiaWRkZW4gUnVsZXNldCBicm93c2VyIHdpdGggYWRkL2RlbGV0ZS9zZWFyY2guCiMK"
    "IyBOZXh0OiBQYXNzIDYg4oCUIE1haW4gV2luZG93CiMgKE1vcmdhbm5hRGVjayBjbGFzcywgZnVs"
    "bCBsYXlvdXQsIEFQU2NoZWR1bGVyLCBmaXJzdC1ydW4gZmxvdywKIyAgZGVwZW5kZW5jeSBib290"
    "c3RyYXAsIHNob3J0Y3V0IGNyZWF0aW9uLCBzdGFydHVwIHNlcXVlbmNlKQoKCiMg4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "CiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyA2OiBNQUlOIFdJTkRPVyAmIEVOVFJZIFBPSU5UCiMK"
    "IyBDb250YWluczoKIyAgIGJvb3RzdHJhcF9jaGVjaygpICAgICDigJQgZGVwZW5kZW5jeSB2YWxp"
    "ZGF0aW9uICsgYXV0by1pbnN0YWxsIGJlZm9yZSBVSQojICAgRmlyc3RSdW5EaWFsb2cgICAgICAg"
    "IOKAlCBtb2RlbCBwYXRoICsgY29ubmVjdGlvbiB0eXBlIHNlbGVjdGlvbgojICAgSm91cm5hbFNp"
    "ZGViYXIgICAgICAgIOKAlCBjb2xsYXBzaWJsZSBsZWZ0IHNpZGViYXIgKHNlc3Npb24gYnJvd3Nl"
    "ciArIGpvdXJuYWwpCiMgICBUb3Jwb3JQYW5lbCAgICAgICAgICAg4oCUIEFXQUtFIC8gQVVUTyAv"
    "IFNVU1BFTkQgc3RhdGUgdG9nZ2xlCiMgICBNb3JnYW5uYURlY2sgICAgICAgICAg4oCUIG1haW4g"
    "d2luZG93LCBmdWxsIGxheW91dCwgYWxsIHNpZ25hbCBjb25uZWN0aW9ucwojICAgbWFpbigpICAg"
    "ICAgICAgICAgICAgIOKAlCBlbnRyeSBwb2ludCB3aXRoIGJvb3RzdHJhcCBzZXF1ZW5jZQojIOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkAoKaW1wb3J0IHN1YnByb2Nlc3MKCgojIOKUgOKUgCBQUkUtTEFVTkNIIERFUEVOREVO"
    "Q1kgQk9PVFNUUkFQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgYm9vdHN0cmFwX2NoZWNrKCkgLT4gTm9uZToK"
    "ICAgICIiIgogICAgUnVucyBCRUZPUkUgUUFwcGxpY2F0aW9uIGlzIGNyZWF0ZWQuCiAgICBDaGVj"
    "a3MgZm9yIFB5U2lkZTYgc2VwYXJhdGVseSAoY2FuJ3Qgc2hvdyBHVUkgd2l0aG91dCBpdCkuCiAg"
    "ICBBdXRvLWluc3RhbGxzIGFsbCBvdGhlciBtaXNzaW5nIG5vbi1jcml0aWNhbCBkZXBzIHZpYSBw"
    "aXAuCiAgICBWYWxpZGF0ZXMgaW5zdGFsbHMgc3VjY2VlZGVkLgogICAgV3JpdGVzIHJlc3VsdHMg"
    "dG8gYSBib290c3RyYXAgbG9nIGZvciBEaWFnbm9zdGljcyB0YWIgdG8gcGljayB1cC4KICAgICIi"
    "IgogICAgIyDilIDilIAgU3RlcCAxOiBDaGVjayBQeVNpZGU2IChjYW4ndCBhdXRvLWluc3RhbGwg"
    "d2l0aG91dCBpdCBhbHJlYWR5IHByZXNlbnQpIOKUgAogICAgdHJ5OgogICAgICAgIGltcG9ydCBQ"
    "eVNpZGU2ICAjIG5vcWEKICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAjIE5vIEdVSSBh"
    "dmFpbGFibGUg4oCUIHVzZSBXaW5kb3dzIG5hdGl2ZSBkaWFsb2cgdmlhIGN0eXBlcwogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgaW1wb3J0IGN0eXBlcwogICAgICAgICAgICBjdHlwZXMud2luZGxs"
    "LnVzZXIzMi5NZXNzYWdlQm94VygKICAgICAgICAgICAgICAgIDAsCiAgICAgICAgICAgICAgICAi"
    "UHlTaWRlNiBpcyByZXF1aXJlZCBidXQgbm90IGluc3RhbGxlZC5cblxuIgogICAgICAgICAgICAg"
    "ICAgIk9wZW4gYSB0ZXJtaW5hbCBhbmQgcnVuOlxuXG4iCiAgICAgICAgICAgICAgICAiICAgIHBp"
    "cCBpbnN0YWxsIFB5U2lkZTZcblxuIgogICAgICAgICAgICAgICAgZiJUaGVuIHJlc3RhcnQge0RF"
    "Q0tfTkFNRX0uIiwKICAgICAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0g4oCUIE1pc3NpbmcgRGVw"
    "ZW5kZW5jeSIsCiAgICAgICAgICAgICAgICAweDEwICAjIE1CX0lDT05FUlJPUgogICAgICAgICAg"
    "ICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcHJpbnQoIkNSSVRJQ0FM"
    "OiBQeVNpZGU2IG5vdCBpbnN0YWxsZWQuIFJ1bjogcGlwIGluc3RhbGwgUHlTaWRlNiIpCiAgICAg"
    "ICAgc3lzLmV4aXQoMSkKCiAgICAjIOKUgOKUgCBTdGVwIDI6IEF1dG8taW5zdGFsbCBvdGhlciBt"
    "aXNzaW5nIGRlcHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBf"
    "QVVUT19JTlNUQUxMID0gWwogICAgICAgICgiYXBzY2hlZHVsZXIiLCAgICAgICAgICAgICAgICJh"
    "cHNjaGVkdWxlciIpLAogICAgICAgICgibG9ndXJ1IiwgICAgICAgICAgICAgICAgICAgICJsb2d1"
    "cnUiKSwKICAgICAgICAoInB5Z2FtZSIsICAgICAgICAgICAgICAgICAgICAicHlnYW1lIiksCiAg"
    "ICAgICAgKCJweXdpbjMyIiwgICAgICAgICAgICAgICAgICAgInB5d2luMzIiKSwKICAgICAgICAo"
    "InBzdXRpbCIsICAgICAgICAgICAgICAgICAgICAicHN1dGlsIiksCiAgICAgICAgKCJyZXF1ZXN0"
    "cyIsICAgICAgICAgICAgICAgICAgInJlcXVlc3RzIiksCiAgICAgICAgKCJnb29nbGUtYXBpLXB5"
    "dGhvbi1jbGllbnQiLCAgImdvb2dsZWFwaWNsaWVudCIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgt"
    "b2F1dGhsaWIiLCAgICAgICJnb29nbGVfYXV0aF9vYXV0aGxpYiIpLAogICAgICAgICgiZ29vZ2xl"
    "LWF1dGgiLCAgICAgICAgICAgICAgICJnb29nbGUuYXV0aCIpLAogICAgXQoKICAgIGltcG9ydCBp"
    "bXBvcnRsaWIKICAgIGJvb3RzdHJhcF9sb2cgPSBbXQoKICAgIGZvciBwaXBfbmFtZSwgaW1wb3J0"
    "X25hbWUgaW4gX0FVVE9fSU5TVEFMTDoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGltcG9ydGxp"
    "Yi5pbXBvcnRfbW9kdWxlKGltcG9ydF9uYW1lKQogICAgICAgICAgICBib290c3RyYXBfbG9nLmFw"
    "cGVuZChmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0g4pyTIikKICAgICAgICBleGNlcHQgSW1wb3J0"
    "RXJyb3I6CiAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAg"
    "ZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IG1pc3Npbmcg4oCUIGluc3RhbGxpbmcuLi4iCiAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgcmVzdWx0ID0gc3VicHJv"
    "Y2Vzcy5ydW4oCiAgICAgICAgICAgICAgICAgICAgW3N5cy5leGVjdXRhYmxlLCAiLW0iLCAicGlw"
    "IiwgImluc3RhbGwiLAogICAgICAgICAgICAgICAgICAgICBwaXBfbmFtZSwgIi0tcXVpZXQiLCAi"
    "LS1uby13YXJuLXNjcmlwdC1sb2NhdGlvbiJdLAogICAgICAgICAgICAgICAgICAgIGNhcHR1cmVf"
    "b3V0cHV0PVRydWUsIHRleHQ9VHJ1ZSwgdGltZW91dD0xMjAKICAgICAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgICAgIGlmIHJlc3VsdC5yZXR1cm5jb2RlID09IDA6CiAgICAgICAgICAgICAgICAg"
    "ICAgIyBWYWxpZGF0ZSBpdCBhY3R1YWxseSBpbXBvcnRlZCBub3cKICAgICAgICAgICAgICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGlt"
    "cG9ydF9uYW1lKQogICAgICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0"
    "YWxsZWQg4pyTIgogICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAg"
    "ZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9n"
    "LmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9u"
    "YW1lfSBpbnN0YWxsIGFwcGVhcmVkIHRvICIKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYi"
    "c3VjY2VlZCBidXQgaW1wb3J0IHN0aWxsIGZhaWxzIOKAlCByZXN0YXJ0IG1heSAiCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBmImJlIHJlcXVpcmVkLiIKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBib290c3RyYXBf"
    "bG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25h"
    "bWV9IGluc3RhbGwgZmFpbGVkOiAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYie3Jlc3VsdC5z"
    "dGRlcnJbOjIwMF19IgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IHN1"
    "YnByb2Nlc3MuVGltZW91dEV4cGlyZWQ6CiAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFw"
    "cGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFs"
    "bCB0aW1lZCBvdXQuIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0"
    "aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAg"
    "ICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbCBlcnJvcjoge2V9Igog"
    "ICAgICAgICAgICAgICAgKQoKICAgICMg4pSA4pSAIFN0ZXAgMzogV3JpdGUgYm9vdHN0cmFwIGxv"
    "ZyBmb3IgRGlhZ25vc3RpY3MgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgdHJ5OgogICAgICAgIGxvZ19w"
    "YXRoID0gU0NSSVBUX0RJUiAvICJsb2dzIiAvICJib290c3RyYXBfbG9nLnR4dCIKICAgICAgICB3"
    "aXRoIGxvZ19wYXRoLm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAg"
    "ICBmLndyaXRlKCJcbiIuam9pbihib290c3RyYXBfbG9nKSkKICAgIGV4Y2VwdCBFeGNlcHRpb246"
    "CiAgICAgICAgcGFzcwoKCiMg4pSA4pSAIEZJUlNUIFJVTiBESUFMT0cg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEZpcnN0"
    "UnVuRGlhbG9nKFFEaWFsb2cpOgogICAgIiIiCiAgICBTaG93biBvbiBmaXJzdCBsYXVuY2ggd2hl"
    "biBjb25maWcuanNvbiBkb2Vzbid0IGV4aXN0LgogICAgQ29sbGVjdHMgbW9kZWwgY29ubmVjdGlv"
    "biB0eXBlIGFuZCBwYXRoL2tleS4KICAgIFZhbGlkYXRlcyBjb25uZWN0aW9uIGJlZm9yZSBhY2Nl"
    "cHRpbmcuCiAgICBXcml0ZXMgY29uZmlnLmpzb24gb24gc3VjY2Vzcy4KICAgIENyZWF0ZXMgZGVz"
    "a3RvcCBzaG9ydGN1dC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9u"
    "ZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5zZXRXaW5k"
    "b3dUaXRsZShmIuKcpiB7REVDS19OQU1FLnVwcGVyKCl9IOKAlCBGSVJTVCBBV0FLRU5JTkciKQog"
    "ICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldChTVFlMRSkKICAgICAgICBzZWxmLnNldEZpeGVkU2l6"
    "ZSg1MjAsIDQwMCkKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCgogICAgZGVmIF9zZXR1cF91aShz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJv"
    "b3Quc2V0U3BhY2luZygxMCkKCiAgICAgICAgdGl0bGUgPSBRTGFiZWwoZiLinKYge0RFQ0tfTkFN"
    "RS51cHBlcigpfSDigJQgRklSU1QgQVdBS0VOSU5HIOKcpiIpCiAgICAgICAgdGl0bGUuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTRw"
    "eDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tf"
    "Rk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2luZzogMnB4OyIKICAgICAgICApCiAgICAgICAgdGl0"
    "bGUuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgcm9v"
    "dC5hZGRXaWRnZXQodGl0bGUpCgogICAgICAgIHN1YiA9IFFMYWJlbCgKICAgICAgICAgICAgZiJD"
    "b25maWd1cmUgdGhlIHZlc3NlbCBiZWZvcmUge0RFQ0tfTkFNRX0gbWF5IGF3YWtlbi5cbiIKICAg"
    "ICAgICAgICAgIkFsbCBzZXR0aW5ncyBhcmUgc3RvcmVkIGxvY2FsbHkuIE5vdGhpbmcgbGVhdmVz"
    "IHRoaXMgbWFjaGluZS4iCiAgICAgICAgKQogICAgICAgIHN1Yi5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgIgogICAgICAg"
    "ICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAg"
    "ICBzdWIuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAg"
    "cm9vdC5hZGRXaWRnZXQoc3ViKQoKICAgICAgICAjIOKUgOKUgCBDb25uZWN0aW9uIHR5cGUg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacg"
    "QUkgQ09OTkVDVElPTiBUWVBFIikpCiAgICAgICAgc2VsZi5fdHlwZV9jb21ibyA9IFFDb21ib0Jv"
    "eCgpCiAgICAgICAgc2VsZi5fdHlwZV9jb21iby5hZGRJdGVtcyhbCiAgICAgICAgICAgICJMb2Nh"
    "bCBtb2RlbCBmb2xkZXIgKHRyYW5zZm9ybWVycykiLAogICAgICAgICAgICAiT2xsYW1hIChsb2Nh"
    "bCBzZXJ2aWNlKSIsCiAgICAgICAgICAgICJDbGF1ZGUgQVBJIChBbnRocm9waWMpIiwKICAgICAg"
    "ICAgICAgIk9wZW5BSSBBUEkiLAogICAgICAgIF0pCiAgICAgICAgc2VsZi5fdHlwZV9jb21iby5j"
    "dXJyZW50SW5kZXhDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fdHlwZV9jaGFuZ2UpCiAgICAgICAg"
    "cm9vdC5hZGRXaWRnZXQoc2VsZi5fdHlwZV9jb21ibykKCiAgICAgICAgIyDilIDilIAgRHluYW1p"
    "YyBjb25uZWN0aW9uIGZpZWxkcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICBzZWxmLl9zdGFjayA9IFFTdGFja2VkV2lkZ2V0KCkKCiAgICAgICAg"
    "IyBQYWdlIDA6IExvY2FsIHBhdGgKICAgICAgICBwMCA9IFFXaWRnZXQoKQogICAgICAgIGwwID0g"
    "UUhCb3hMYXlvdXQocDApCiAgICAgICAgbDAuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAg"
    "ICAgICAgc2VsZi5fbG9jYWxfcGF0aCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fbG9jYWxf"
    "cGF0aC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgIHIiRDpcQUlcTW9kZWxzXGRvbHBo"
    "aW4tOGIiCiAgICAgICAgKQogICAgICAgIGJ0bl9icm93c2UgPSBfZ290aGljX2J0bigiQnJvd3Nl"
    "IikKICAgICAgICBidG5fYnJvd3NlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9icm93c2VfbW9kZWwp"
    "CiAgICAgICAgbDAuYWRkV2lkZ2V0KHNlbGYuX2xvY2FsX3BhdGgpOyBsMC5hZGRXaWRnZXQoYnRu"
    "X2Jyb3dzZSkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDApCgogICAgICAgICMgUGFn"
    "ZSAxOiBPbGxhbWEgbW9kZWwgbmFtZQogICAgICAgIHAxID0gUVdpZGdldCgpCiAgICAgICAgbDEg"
    "PSBRSEJveExheW91dChwMSkKICAgICAgICBsMS5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAsMCkK"
    "ICAgICAgICBzZWxmLl9vbGxhbWFfbW9kZWwgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX29s"
    "bGFtYV9tb2RlbC5zZXRQbGFjZWhvbGRlclRleHQoImRvbHBoaW4tMi42LTdiIikKICAgICAgICBs"
    "MS5hZGRXaWRnZXQoc2VsZi5fb2xsYW1hX21vZGVsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdp"
    "ZGdldChwMSkKCiAgICAgICAgIyBQYWdlIDI6IENsYXVkZSBBUEkga2V5CiAgICAgICAgcDIgPSBR"
    "V2lkZ2V0KCkKICAgICAgICBsMiA9IFFWQm94TGF5b3V0KHAyKQogICAgICAgIGwyLnNldENvbnRl"
    "bnRzTWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkgICA9IFFMaW5lRWRp"
    "dCgpCiAgICAgICAgc2VsZi5fY2xhdWRlX2tleS5zZXRQbGFjZWhvbGRlclRleHQoInNrLWFudC0u"
    "Li4iKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkuc2V0RWNob01vZGUoUUxpbmVFZGl0LkVjaG9N"
    "b2RlLlBhc3N3b3JkKQogICAgICAgIHNlbGYuX2NsYXVkZV9tb2RlbCA9IFFMaW5lRWRpdCgiY2xh"
    "dWRlLXNvbm5ldC00LTYiKQogICAgICAgIGwyLmFkZFdpZGdldChRTGFiZWwoIkFQSSBLZXk6Iikp"
    "CiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2NsYXVkZV9rZXkpCiAgICAgICAgbDIuYWRkV2lk"
    "Z2V0KFFMYWJlbCgiTW9kZWw6IikpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2NsYXVkZV9t"
    "b2RlbCkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDIpCgogICAgICAgICMgUGFnZSAz"
    "OiBPcGVuQUkKICAgICAgICBwMyA9IFFXaWRnZXQoKQogICAgICAgIGwzID0gUVZCb3hMYXlvdXQo"
    "cDMpCiAgICAgICAgbDMuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5f"
    "b2FpX2tleSAgID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9vYWlfa2V5LnNldFBsYWNlaG9s"
    "ZGVyVGV4dCgic2stLi4uIikKICAgICAgICBzZWxmLl9vYWlfa2V5LnNldEVjaG9Nb2RlKFFMaW5l"
    "RWRpdC5FY2hvTW9kZS5QYXNzd29yZCkKICAgICAgICBzZWxmLl9vYWlfbW9kZWwgPSBRTGluZUVk"
    "aXQoImdwdC00byIpCiAgICAgICAgbDMuYWRkV2lkZ2V0KFFMYWJlbCgiQVBJIEtleToiKSkKICAg"
    "ICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fb2FpX2tleSkKICAgICAgICBsMy5hZGRXaWRnZXQoUUxh"
    "YmVsKCJNb2RlbDoiKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fb2FpX21vZGVsKQogICAg"
    "ICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMykKCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2Vs"
    "Zi5fc3RhY2spCgogICAgICAgICMg4pSA4pSAIFRlc3QgKyBzdGF0dXMg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICAgICAgdGVzdF9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5f"
    "YnRuX3Rlc3QgPSBfZ290aGljX2J0bigiVGVzdCBDb25uZWN0aW9uIikKICAgICAgICBzZWxmLl9i"
    "dG5fdGVzdC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdGVzdF9jb25uZWN0aW9uKQogICAgICAgIHNl"
    "bGYuX3N0YXR1c19sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTog"
    "MTBweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7Igog"
    "ICAgICAgICkKICAgICAgICB0ZXN0X3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX3Rlc3QpCiAgICAg"
    "ICAgdGVzdF9yb3cuYWRkV2lkZ2V0KHNlbGYuX3N0YXR1c19sYmwsIDEpCiAgICAgICAgcm9vdC5h"
    "ZGRMYXlvdXQodGVzdF9yb3cpCgogICAgICAgICMg4pSA4pSAIEZhY2UgUGFjayDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICByb290LmFkZFdpZGdldChfc2VjdGlv"
    "bl9sYmwoIuKdpyBGQUNFIFBBQ0sgKG9wdGlvbmFsIOKAlCBaSVAgZmlsZSkiKSkKICAgICAgICBm"
    "YWNlX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9mYWNlX3BhdGggPSBRTGluZUVk"
    "aXQoKQogICAgICAgIHNlbGYuX2ZhY2VfcGF0aC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAg"
    "ICAgIGYiQnJvd3NlIHRvIHtERUNLX05BTUV9IGZhY2UgcGFjayBaSVAgKG9wdGlvbmFsLCBjYW4g"
    "YWRkIGxhdGVyKSIKICAgICAgICApCiAgICAgICAgc2VsZi5fZmFjZV9wYXRoLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElN"
    "fTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1y"
    "YWRpdXM6IDJweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2Vy"
    "aWY7IGZvbnQtc2l6ZTogMTJweDsgcGFkZGluZzogNnB4IDEwcHg7IgogICAgICAgICkKICAgICAg"
    "ICBidG5fZmFjZSA9IF9nb3RoaWNfYnRuKCJCcm93c2UiKQogICAgICAgIGJ0bl9mYWNlLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9icm93c2VfZmFjZSkKICAgICAgICBmYWNlX3Jvdy5hZGRXaWRnZXQo"
    "c2VsZi5fZmFjZV9wYXRoKQogICAgICAgIGZhY2Vfcm93LmFkZFdpZGdldChidG5fZmFjZSkKICAg"
    "ICAgICByb290LmFkZExheW91dChmYWNlX3JvdykKCiAgICAgICAgIyDilIDilIAgU2hvcnRjdXQg"
    "b3B0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3Nob3J0Y3V0X2NiID0gUUNo"
    "ZWNrQm94KAogICAgICAgICAgICAiQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgKHJlY29tbWVuZGVk"
    "KSIKICAgICAgICApCiAgICAgICAgc2VsZi5fc2hvcnRjdXRfY2Iuc2V0Q2hlY2tlZChUcnVlKQog"
    "ICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3Nob3J0Y3V0X2NiKQoKICAgICAgICAjIOKUgOKU"
    "gCBCdXR0b25zIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ICAgIHJvb3QuYWRkU3RyZXRjaCgpCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAg"
    "ICAgICBzZWxmLl9idG5fYXdha2VuID0gX2dvdGhpY19idG4oIuKcpiBCRUdJTiBBV0FLRU5JTkci"
    "KQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBidG5f"
    "Y2FuY2VsID0gX2dvdGhpY19idG4oIuKclyBDYW5jZWwiKQogICAgICAgIHNlbGYuX2J0bl9hd2Fr"
    "ZW4uY2xpY2tlZC5jb25uZWN0KHNlbGYuYWNjZXB0KQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tl"
    "ZC5jb25uZWN0KHNlbGYucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0"
    "bl9hd2FrZW4pCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBy"
    "b290LmFkZExheW91dChidG5fcm93KQoKICAgIGRlZiBfb25fdHlwZV9jaGFuZ2Uoc2VsZiwgaWR4"
    "OiBpbnQpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KGlkeCkK"
    "ICAgICAgICBzZWxmLl9idG5fYXdha2VuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5f"
    "c3RhdHVzX2xibC5zZXRUZXh0KCIiKQoKICAgIGRlZiBfYnJvd3NlX21vZGVsKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgcGF0aCA9IFFGaWxlRGlhbG9nLmdldEV4aXN0aW5nRGlyZWN0b3J5KAogICAg"
    "ICAgICAgICBzZWxmLCAiU2VsZWN0IE1vZGVsIEZvbGRlciIsCiAgICAgICAgICAgIHIiRDpcQUlc"
    "TW9kZWxzIgogICAgICAgICkKICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICBzZWxmLl9sb2Nh"
    "bF9wYXRoLnNldFRleHQocGF0aCkKCiAgICBkZWYgX2Jyb3dzZV9mYWNlKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgcGF0aCwgXyA9IFFGaWxlRGlhbG9nLmdldE9wZW5GaWxlTmFtZSgKICAgICAgICAg"
    "ICAgc2VsZiwgIlNlbGVjdCBGYWNlIFBhY2sgWklQIiwKICAgICAgICAgICAgc3RyKFBhdGguaG9t"
    "ZSgpIC8gIkRlc2t0b3AiKSwKICAgICAgICAgICAgIlpJUCBGaWxlcyAoKi56aXApIgogICAgICAg"
    "ICkKICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICBzZWxmLl9mYWNlX3BhdGguc2V0VGV4dChw"
    "YXRoKQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGZhY2VfemlwX3BhdGgoc2VsZikgLT4gc3RyOgog"
    "ICAgICAgIHJldHVybiBzZWxmLl9mYWNlX3BhdGgudGV4dCgpLnN0cmlwKCkKCiAgICBkZWYgX3Rl"
    "c3RfY29ubmVjdGlvbihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0"
    "VGV4dCgiVGVzdGluZy4uLiIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIFFBcHBsaWNh"
    "dGlvbi5wcm9jZXNzRXZlbnRzKCkKCiAgICAgICAgaWR4ID0gc2VsZi5fdHlwZV9jb21iby5jdXJy"
    "ZW50SW5kZXgoKQogICAgICAgIG9rICA9IEZhbHNlCiAgICAgICAgbXNnID0gIiIKCiAgICAgICAg"
    "aWYgaWR4ID09IDA6ICAjIExvY2FsCiAgICAgICAgICAgIHBhdGggPSBzZWxmLl9sb2NhbF9wYXRo"
    "LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIHBhdGggYW5kIFBhdGgocGF0aCkuZXhpc3Rz"
    "KCk6CiAgICAgICAgICAgICAgICBvayAgPSBUcnVlCiAgICAgICAgICAgICAgICBtc2cgPSBmIkZv"
    "bGRlciBmb3VuZC4gTW9kZWwgd2lsbCBsb2FkIG9uIHN0YXJ0dXAuIgogICAgICAgICAgICBlbHNl"
    "OgogICAgICAgICAgICAgICAgbXNnID0gIkZvbGRlciBub3QgZm91bmQuIENoZWNrIHRoZSBwYXRo"
    "LiIKCiAgICAgICAgZWxpZiBpZHggPT0gMTogICMgT2xsYW1hCiAgICAgICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgICAgIHJlcSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KAogICAgICAgICAgICAg"
    "ICAgICAgICJodHRwOi8vbG9jYWxob3N0OjExNDM0L2FwaS90YWdzIgogICAgICAgICAgICAgICAg"
    "KQogICAgICAgICAgICAgICAgcmVzcCA9IHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1l"
    "b3V0PTMpCiAgICAgICAgICAgICAgICBvayAgID0gcmVzcC5zdGF0dXMgPT0gMjAwCiAgICAgICAg"
    "ICAgICAgICBtc2cgID0gIk9sbGFtYSBpcyBydW5uaW5nIOKckyIgaWYgb2sgZWxzZSAiT2xsYW1h"
    "IG5vdCByZXNwb25kaW5nLiIKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAg"
    "ICAgICAgICAgICAgbXNnID0gZiJPbGxhbWEgbm90IHJlYWNoYWJsZToge2V9IgoKICAgICAgICBl"
    "bGlmIGlkeCA9PSAyOiAgIyBDbGF1ZGUKICAgICAgICAgICAga2V5ID0gc2VsZi5fY2xhdWRlX2tl"
    "eS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBvayAgPSBib29sKGtleSBhbmQga2V5LnN0YXJ0"
    "c3dpdGgoInNrLWFudCIpKQogICAgICAgICAgICBtc2cgPSAiQVBJIGtleSBmb3JtYXQgbG9va3Mg"
    "Y29ycmVjdC4iIGlmIG9rIGVsc2UgIkVudGVyIGEgdmFsaWQgQ2xhdWRlIEFQSSBrZXkuIgoKICAg"
    "ICAgICBlbGlmIGlkeCA9PSAzOiAgIyBPcGVuQUkKICAgICAgICAgICAga2V5ID0gc2VsZi5fb2Fp"
    "X2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBvayAgPSBib29sKGtleSBhbmQga2V5LnN0"
    "YXJ0c3dpdGgoInNrLSIpKQogICAgICAgICAgICBtc2cgPSAiQVBJIGtleSBmb3JtYXQgbG9va3Mg"
    "Y29ycmVjdC4iIGlmIG9rIGVsc2UgIkVudGVyIGEgdmFsaWQgT3BlbkFJIEFQSSBrZXkuIgoKICAg"
    "ICAgICBjb2xvciA9IENfR1JFRU4gaWYgb2sgZWxzZSBDX0NSSU1TT04KICAgICAgICBzZWxmLl9z"
    "dGF0dXNfbGJsLnNldFRleHQobXNnKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiAxMHB4OyBmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYnRu"
    "X2F3YWtlbi5zZXRFbmFibGVkKG9rKQoKICAgIGRlZiBidWlsZF9jb25maWcoc2VsZikgLT4gZGlj"
    "dDoKICAgICAgICAiIiJCdWlsZCBhbmQgcmV0dXJuIHVwZGF0ZWQgY29uZmlnIGRpY3QgZnJvbSBk"
    "aWFsb2cgc2VsZWN0aW9ucy4iIiIKICAgICAgICBjZmcgICAgID0gX2RlZmF1bHRfY29uZmlnKCkK"
    "ICAgICAgICBpZHggICAgID0gc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXgoKQogICAgICAg"
    "IHR5cGVzICAgPSBbImxvY2FsIiwgIm9sbGFtYSIsICJjbGF1ZGUiLCAib3BlbmFpIl0KICAgICAg"
    "ICBjZmdbIm1vZGVsIl1bInR5cGUiXSA9IHR5cGVzW2lkeF0KCiAgICAgICAgaWYgaWR4ID09IDA6"
    "CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsicGF0aCJdID0gc2VsZi5fbG9jYWxfcGF0aC50ZXh0"
    "KCkuc3RyaXAoKQogICAgICAgIGVsaWYgaWR4ID09IDE6CiAgICAgICAgICAgIGNmZ1sibW9kZWwi"
    "XVsib2xsYW1hX21vZGVsIl0gPSBzZWxmLl9vbGxhbWFfbW9kZWwudGV4dCgpLnN0cmlwKCkgb3Ig"
    "ImRvbHBoaW4tMi42LTdiIgogICAgICAgIGVsaWYgaWR4ID09IDI6CiAgICAgICAgICAgIGNmZ1si"
    "bW9kZWwiXVsiYXBpX2tleSJdICAgPSBzZWxmLl9jbGF1ZGVfa2V5LnRleHQoKS5zdHJpcCgpCiAg"
    "ICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX21vZGVsIl0gPSBzZWxmLl9jbGF1ZGVfbW9kZWwu"
    "dGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfdHlwZSJdICA9ICJj"
    "bGF1ZGUiCiAgICAgICAgZWxpZiBpZHggPT0gMzoKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJh"
    "cGlfa2V5Il0gICA9IHNlbGYuX29haV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2Zn"
    "WyJtb2RlbCJdWyJhcGlfbW9kZWwiXSA9IHNlbGYuX29haV9tb2RlbC50ZXh0KCkuc3RyaXAoKQog"
    "ICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV90eXBlIl0gID0gIm9wZW5haSIKCiAgICAgICAg"
    "Y2ZnWyJmaXJzdF9ydW4iXSA9IEZhbHNlCiAgICAgICAgcmV0dXJuIGNmZwoKICAgIEBwcm9wZXJ0"
    "eQogICAgZGVmIGNyZWF0ZV9zaG9ydGN1dChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBz"
    "ZWxmLl9zaG9ydGN1dF9jYi5pc0NoZWNrZWQoKQoKCiMg4pSA4pSAIEpPVVJOQUwgU0lERUJBUiDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKY2xhc3MgSm91cm5hbFNpZGViYXIoUVdpZGdldCk6CiAgICAiIiIKICAgIENvbGxhcHNp"
    "YmxlIGxlZnQgc2lkZWJhciBuZXh0IHRvIHRoZSBwZXJzb25hIGNoYXQgdGFiLgogICAgVG9wOiBz"
    "ZXNzaW9uIGNvbnRyb2xzIChjdXJyZW50IHNlc3Npb24gbmFtZSwgc2F2ZS9sb2FkIGJ1dHRvbnMs"
    "CiAgICAgICAgIGF1dG9zYXZlIGluZGljYXRvcikuCiAgICBCb2R5OiBzY3JvbGxhYmxlIHNlc3Np"
    "b24gbGlzdCDigJQgZGF0ZSwgQUkgbmFtZSwgbWVzc2FnZSBjb3VudC4KICAgIENvbGxhcHNlcyBs"
    "ZWZ0d2FyZCB0byBhIHRoaW4gc3RyaXAuCgogICAgU2lnbmFsczoKICAgICAgICBzZXNzaW9uX2xv"
    "YWRfcmVxdWVzdGVkKHN0cikgICDigJQgZGF0ZSBzdHJpbmcgb2Ygc2Vzc2lvbiB0byBsb2FkCiAg"
    "ICAgICAgc2Vzc2lvbl9jbGVhcl9yZXF1ZXN0ZWQoKSAgICAg4oCUIHJldHVybiB0byBjdXJyZW50"
    "IHNlc3Npb24KICAgICIiIgoKICAgIHNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQgID0gU2lnbmFsKHN0"
    "cikKICAgIHNlc3Npb25fY2xlYXJfcmVxdWVzdGVkID0gU2lnbmFsKCkKCiAgICBkZWYgX19pbml0"
    "X18oc2VsZiwgc2Vzc2lvbl9tZ3I6ICJTZXNzaW9uTWFuYWdlciIsIHBhcmVudD1Ob25lKToKICAg"
    "ICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9zZXNzaW9uX21nciA9"
    "IHNlc3Npb25fbWdyCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgICAgPSBUcnVlCiAgICAgICAgc2Vs"
    "Zi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgICMgVXNlIGEgaG9yaXpvbnRhbCByb290IGxheW91dCDigJQg"
    "Y29udGVudCBvbiBsZWZ0LCB0b2dnbGUgc3RyaXAgb24gcmlnaHQKICAgICAgICByb290ID0gUUhC"
    "b3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAw"
    "KQogICAgICAgIHJvb3Quc2V0U3BhY2luZygwKQoKICAgICAgICAjIOKUgOKUgCBDb2xsYXBzZSB0"
    "b2dnbGUgc3RyaXAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fdG9nZ2xlX3N0cmlwID0gUVdpZGdldCgpCiAgICAg"
    "ICAgc2VsZi5fdG9nZ2xlX3N0cmlwLnNldEZpeGVkV2lkdGgoMjApCiAgICAgICAgc2VsZi5fdG9n"
    "Z2xlX3N0cmlwLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcz"
    "fTsgYm9yZGVyLXJpZ2h0OiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAg"
    "ICAgICAgdHNfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fdG9nZ2xlX3N0cmlwKQogICAgICAg"
    "IHRzX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgOCwgMCwgOCkKICAgICAgICBzZWxmLl90"
    "b2dnbGVfYnRuID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0Rml4"
    "ZWRTaXplKDE4LCAxOCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKXgCIpCiAg"
    "ICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tn"
    "cm91bmQ6IHRyYW5zcGFyZW50OyBjb2xvcjoge0NfR09MRF9ESU19OyAiCiAgICAgICAgICAgIGYi"
    "Ym9yZGVyOiBub25lOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl90"
    "b2dnbGVfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCiAgICAgICAgdHNfbGF5b3V0"
    "LmFkZFdpZGdldChzZWxmLl90b2dnbGVfYnRuKQogICAgICAgIHRzX2xheW91dC5hZGRTdHJldGNo"
    "KCkKCiAgICAgICAgIyDilIDilIAgTWFpbiBjb250ZW50IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgICAgIHNlbGYuX2NvbnRlbnQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jb250"
    "ZW50LnNldE1pbmltdW1XaWR0aCgxODApCiAgICAgICAgc2VsZi5fY29udGVudC5zZXRNYXhpbXVt"
    "V2lkdGgoMjIwKQogICAgICAgIGNvbnRlbnRfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fY29u"
    "dGVudCkKICAgICAgICBjb250ZW50X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwg"
    "NCkKICAgICAgICBjb250ZW50X2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgU2VjdGlv"
    "biBsYWJlbAogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKd"
    "pyBKT1VSTkFMIikpCgogICAgICAgICMgQ3VycmVudCBzZXNzaW9uIGluZm8KICAgICAgICBzZWxm"
    "Ll9zZXNzaW9uX25hbWUgPSBRTGFiZWwoIk5ldyBTZXNzaW9uIikKICAgICAgICBzZWxmLl9zZXNz"
    "aW9uX25hbWUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZv"
    "bnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgIgogICAgICAg"
    "ICAgICBmImZvbnQtc3R5bGU6IGl0YWxpYzsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Nlc3Np"
    "b25fbmFtZS5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdl"
    "dChzZWxmLl9zZXNzaW9uX25hbWUpCgogICAgICAgICMgU2F2ZSAvIExvYWQgcm93CiAgICAgICAg"
    "Y3RybF9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUgPSBfZ290aGlj"
    "X2J0bigi8J+SviIpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0Rml4ZWRTaXplKDMyLCAyNCkK"
    "ICAgICAgICBzZWxmLl9idG5fc2F2ZS5zZXRUb29sVGlwKCJTYXZlIHNlc3Npb24gbm93IikKICAg"
    "ICAgICBzZWxmLl9idG5fbG9hZCA9IF9nb3RoaWNfYnRuKCLwn5OCIikKICAgICAgICBzZWxmLl9i"
    "dG5fbG9hZC5zZXRGaXhlZFNpemUoMzIsIDI0KQogICAgICAgIHNlbGYuX2J0bl9sb2FkLnNldFRv"
    "b2xUaXAoIkJyb3dzZSBhbmQgbG9hZCBhIHBhc3Qgc2Vzc2lvbiIpCiAgICAgICAgc2VsZi5fYXV0"
    "b3NhdmVfZG90ID0gUUxhYmVsKCLil48iKQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTog"
    "OHB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Qu"
    "c2V0VG9vbFRpcCgiQXV0b3NhdmUgc3RhdHVzIikKICAgICAgICBzZWxmLl9idG5fc2F2ZS5jbGlj"
    "a2VkLmNvbm5lY3Qoc2VsZi5fZG9fc2F2ZSkKICAgICAgICBzZWxmLl9idG5fbG9hZC5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fZG9fbG9hZCkKICAgICAgICBjdHJsX3Jvdy5hZGRXaWRnZXQoc2VsZi5f"
    "YnRuX3NhdmUpCiAgICAgICAgY3RybF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9sb2FkKQogICAg"
    "ICAgIGN0cmxfcm93LmFkZFdpZGdldChzZWxmLl9hdXRvc2F2ZV9kb3QpCiAgICAgICAgY3RybF9y"
    "b3cuYWRkU3RyZXRjaCgpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkTGF5b3V0KGN0cmxfcm93"
    "KQoKICAgICAgICAjIEpvdXJuYWwgbG9hZGVkIGluZGljYXRvcgogICAgICAgIHNlbGYuX2pvdXJu"
    "YWxfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1BVUlBMRX07IGZvbnQtc2l6ZTogOXB4OyBmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgIGYiZm9udC1zdHlsZTog"
    "aXRhbGljOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0V29yZFdyYXAo"
    "VHJ1ZSkKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fam91cm5hbF9sYmwp"
    "CgogICAgICAgICMgQ2xlYXIgam91cm5hbCBidXR0b24gKGhpZGRlbiB3aGVuIG5vdCBsb2FkZWQp"
    "CiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwgPSBfZ290aGljX2J0bigi4pyXIFJldHVy"
    "biB0byBQcmVzZW50IikKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxl"
    "KEZhbHNlKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLmNsaWNrZWQuY29ubmVjdChz"
    "ZWxmLl9kb19jbGVhcl9qb3VybmFsKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChz"
    "ZWxmLl9idG5fY2xlYXJfam91cm5hbCkKCiAgICAgICAgIyBEaXZpZGVyCiAgICAgICAgZGl2ID0g"
    "UUZyYW1lKCkKICAgICAgICBkaXYuc2V0RnJhbWVTaGFwZShRRnJhbWUuU2hhcGUuSExpbmUpCiAg"
    "ICAgICAgZGl2LnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyIpCiAgICAg"
    "ICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KGRpdikKCiAgICAgICAgIyBTZXNzaW9uIGxpc3QK"
    "ICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgUEFTVCBT"
    "RVNTSU9OUyIpKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdCA9IFFMaXN0V2lkZ2V0KCkKICAg"
    "ICAgICBzZWxmLl9zZXNzaW9uX2xpc3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNr"
    "Z3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6"
    "IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNL"
    "X0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICAgICAgZiJRTGlzdFdpZGdl"
    "dDo6aXRlbTpzZWxlY3RlZCB7eyBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IH19IgogICAg"
    "ICAgICkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QuaXRlbURvdWJsZUNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl9vbl9zZXNzaW9uX2NsaWNrKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5pdGVt"
    "Q2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX3Nlc3Npb25fY2xpY2spCiAgICAgICAgY29udGVudF9s"
    "YXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Nlc3Npb25fbGlzdCwgMSkKCiAgICAgICAgIyBBZGQgY29u"
    "dGVudCBhbmQgdG9nZ2xlIHN0cmlwIHRvIHRoZSByb290IGhvcml6b250YWwgbGF5b3V0CiAgICAg"
    "ICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fY29udGVudCkKICAgICAgICByb290LmFkZFdpZGdldChz"
    "ZWxmLl90b2dnbGVfc3RyaXApCgogICAgZGVmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBzZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAgIHNlbGYuX2NvbnRl"
    "bnQuc2V0VmlzaWJsZShzZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNl"
    "dFRleHQoIuKXgCIgaWYgc2VsZi5fZXhwYW5kZWQgZWxzZSAi4pa2IikKICAgICAgICBzZWxmLnVw"
    "ZGF0ZUdlb21ldHJ5KCkKICAgICAgICBwID0gc2VsZi5wYXJlbnRXaWRnZXQoKQogICAgICAgIGlm"
    "IHAgYW5kIHAubGF5b3V0KCk6CiAgICAgICAgICAgIHAubGF5b3V0KCkuYWN0aXZhdGUoKQoKICAg"
    "IGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2Vzc2lvbnMgPSBzZWxmLl9zZXNz"
    "aW9uX21nci5saXN0X3Nlc3Npb25zKCkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QuY2xlYXIo"
    "KQogICAgICAgIGZvciBzIGluIHNlc3Npb25zOgogICAgICAgICAgICBkYXRlX3N0ciA9IHMuZ2V0"
    "KCJkYXRlIiwiIikKICAgICAgICAgICAgbmFtZSAgICAgPSBzLmdldCgibmFtZSIsIGRhdGVfc3Ry"
    "KVs6MzBdCiAgICAgICAgICAgIGNvdW50ICAgID0gcy5nZXQoIm1lc3NhZ2VfY291bnQiLCAwKQog"
    "ICAgICAgICAgICBpdGVtID0gUUxpc3RXaWRnZXRJdGVtKGYie2RhdGVfc3RyfVxue25hbWV9ICh7"
    "Y291bnR9IG1zZ3MpIikKICAgICAgICAgICAgaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5V"
    "c2VyUm9sZSwgZGF0ZV9zdHIpCiAgICAgICAgICAgIGl0ZW0uc2V0VG9vbFRpcChmIkRvdWJsZS1j"
    "bGljayB0byBsb2FkIHNlc3Npb24gZnJvbSB7ZGF0ZV9zdHJ9IikKICAgICAgICAgICAgc2VsZi5f"
    "c2Vzc2lvbl9saXN0LmFkZEl0ZW0oaXRlbSkKCiAgICBkZWYgc2V0X3Nlc3Npb25fbmFtZShzZWxm"
    "LCBuYW1lOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNldFRleHQo"
    "bmFtZVs6NTBdIG9yICJOZXcgU2Vzc2lvbiIpCgogICAgZGVmIHNldF9hdXRvc2F2ZV9pbmRpY2F0"
    "b3Ioc2VsZiwgc2F2ZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dSRUVOIGlmIHNhdmVkIGVs"
    "c2UgQ19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDhweDsgYm9yZGVyOiBu"
    "b25lOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFRvb2xUaXAoCiAg"
    "ICAgICAgICAgICJBdXRvc2F2ZWQiIGlmIHNhdmVkIGVsc2UgIlBlbmRpbmcgYXV0b3NhdmUiCiAg"
    "ICAgICAgKQoKICAgIGRlZiBzZXRfam91cm5hbF9sb2FkZWQoc2VsZiwgZGF0ZV9zdHI6IHN0cikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRUZXh0KGYi8J+TliBKb3VybmFs"
    "OiB7ZGF0ZV9zdHJ9IikKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxl"
    "KFRydWUpCgogICAgZGVmIGNsZWFyX2pvdXJuYWxfaW5kaWNhdG9yKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0VGV4dCgiIikKICAgICAgICBzZWxmLl9idG5fY2xl"
    "YXJfam91cm5hbC5zZXRWaXNpYmxlKEZhbHNlKQoKICAgIGRlZiBfZG9fc2F2ZShzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHNlbGYuX3Nlc3Npb25fbWdyLnNhdmUoKQogICAgICAgIHNlbGYuc2V0X2F1"
    "dG9zYXZlX2luZGljYXRvcihUcnVlKQogICAgICAgIHNlbGYucmVmcmVzaCgpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX3NhdmUuc2V0VGV4dCgi4pyTIikKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgxNTAw"
    "LCBsYW1iZGE6IHNlbGYuX2J0bl9zYXZlLnNldFRleHQoIvCfkr4iKSkKICAgICAgICBRVGltZXIu"
    "c2luZ2xlU2hvdCgzMDAwLCBsYW1iZGE6IHNlbGYuc2V0X2F1dG9zYXZlX2luZGljYXRvcihGYWxz"
    "ZSkpCgogICAgZGVmIF9kb19sb2FkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBUcnkgc2VsZWN0"
    "ZWQgaXRlbSBmaXJzdAogICAgICAgIGl0ZW0gPSBzZWxmLl9zZXNzaW9uX2xpc3QuY3VycmVudEl0"
    "ZW0oKQogICAgICAgIGlmIG5vdCBpdGVtOgogICAgICAgICAgICAjIElmIG5vdGhpbmcgc2VsZWN0"
    "ZWQsIHRyeSB0aGUgZmlyc3QgaXRlbQogICAgICAgICAgICBpZiBzZWxmLl9zZXNzaW9uX2xpc3Qu"
    "Y291bnQoKSA+IDA6CiAgICAgICAgICAgICAgICBpdGVtID0gc2VsZi5fc2Vzc2lvbl9saXN0Lml0"
    "ZW0oMCkKICAgICAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5zZXRDdXJyZW50SXRlbShp"
    "dGVtKQogICAgICAgIGlmIGl0ZW06CiAgICAgICAgICAgIGRhdGVfc3RyID0gaXRlbS5kYXRhKFF0"
    "Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgc2VsZi5zZXNzaW9uX2xvYWRfcmVx"
    "dWVzdGVkLmVtaXQoZGF0ZV9zdHIpCgogICAgZGVmIF9vbl9zZXNzaW9uX2NsaWNrKHNlbGYsIGl0"
    "ZW0pIC0+IE5vbmU6CiAgICAgICAgZGF0ZV9zdHIgPSBpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xl"
    "LlVzZXJSb2xlKQogICAgICAgIHNlbGYuc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5lbWl0KGRhdGVf"
    "c3RyKQoKICAgIGRlZiBfZG9fY2xlYXJfam91cm5hbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNl"
    "bGYuc2Vzc2lvbl9jbGVhcl9yZXF1ZXN0ZWQuZW1pdCgpCiAgICAgICAgc2VsZi5jbGVhcl9qb3Vy"
    "bmFsX2luZGljYXRvcigpCgoKIyDilIDilIAgVE9SUE9SIFBBTkVMIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApj"
    "bGFzcyBUb3Jwb3JQYW5lbChRV2lkZ2V0KToKICAgICIiIgogICAgVGhyZWUtc3RhdGUgc3VzcGVu"
    "c2lvbiB0b2dnbGU6IEFXQUtFIHwgQVVUTyB8IFNVU1BFTkQKCiAgICBBV0FLRSAg4oCUIG1vZGVs"
    "IGxvYWRlZCwgYXV0by10b3Jwb3IgZGlzYWJsZWQsIGlnbm9yZXMgVlJBTSBwcmVzc3VyZQogICAg"
    "QVVUTyAgIOKAlCBtb2RlbCBsb2FkZWQsIG1vbml0b3JzIFZSQU0gcHJlc3N1cmUsIGF1dG8tdG9y"
    "cG9yIGlmIHN1c3RhaW5lZAogICAgU1VTUEVORCDigJQgbW9kZWwgdW5sb2FkZWQsIHN0YXlzIHN1"
    "c3BlbmRlZCB1bnRpbCBtYW51YWxseSBjaGFuZ2VkCgogICAgU2lnbmFsczoKICAgICAgICBzdGF0"
    "ZV9jaGFuZ2VkKHN0cikgIOKAlCAiQVdBS0UiIHwgIkFVVE8iIHwgIlNVU1BFTkQiCiAgICAiIiIK"
    "CiAgICBzdGF0ZV9jaGFuZ2VkID0gU2lnbmFsKHN0cikKCiAgICBTVEFURVMgPSBbIkFXQUtFIiwg"
    "IkFVVE8iLCAiU1VTUEVORCJdCgogICAgU1RBVEVfU1RZTEVTID0gewogICAgICAgICJBV0FLRSI6"
    "IHsKICAgICAgICAgICAgImFjdGl2ZSI6ICAgZiJiYWNrZ3JvdW5kOiAjMmExYTA1OyBjb2xvcjog"
    "e0NfR09MRH07ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7"
    "Q19HT0xEfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYi"
    "Zm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAg"
    "ICAgICAgICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RF"
    "WFRfRElNfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtD"
    "X0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBm"
    "ImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAog"
    "ICAgICAgICAgICAibGFiZWwiOiAgICAi4piAIEFXQUtFIiwKICAgICAgICAgICAgInRvb2x0aXAi"
    "OiAgIk1vZGVsIGFjdGl2ZS4gQXV0by10b3Jwb3IgZGlzYWJsZWQuIiwKICAgICAgICB9LAogICAg"
    "ICAgICJBVVRPIjogewogICAgICAgICAgICAiYWN0aXZlIjogICBmImJhY2tncm91bmQ6ICMxYTEw"
    "MDU7IGNvbG9yOiAjY2M4ODIyOyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAx"
    "cHggc29saWQgI2NjODgyMjsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHgg"
    "OHB4OyIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29s"
    "b3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4"
    "IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAg"
    "ICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4"
    "IDhweDsiLAogICAgICAgICAgICAibGFiZWwiOiAgICAi4peJIEFVVE8iLAogICAgICAgICAgICAi"
    "dG9vbHRpcCI6ICAiTW9kZWwgYWN0aXZlLiBBdXRvLXN1c3BlbmQgb24gVlJBTSBwcmVzc3VyZS4i"
    "LAogICAgICAgIH0sCiAgICAgICAgIlNVU1BFTkQiOiB7CiAgICAgICAgICAgICJhY3RpdmUiOiAg"
    "IGYiYmFja2dyb3VuZDoge0NfUFVSUExFX0RJTX07IGNvbG9yOiB7Q19QVVJQTEV9OyAiCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfUFVSUExFfTsgYm9yZGVy"
    "LXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7"
    "IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJpbmFj"
    "dGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAg"
    "ICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRl"
    "ci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4"
    "OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAibGFi"
    "ZWwiOiAgICBmIuKasCB7VUlfU1VTUEVOU0lPTl9MQUJFTC5zdHJpcCgpIGlmIHN0cihVSV9TVVNQ"
    "RU5TSU9OX0xBQkVMKS5zdHJpcCgpIGVsc2UgJ1N1c3BlbmQnfSIsCiAgICAgICAgICAgICJ0b29s"
    "dGlwIjogIGYiTW9kZWwgdW5sb2FkZWQuIHtERUNLX05BTUV9IHNsZWVwcyB1bnRpbCBtYW51YWxs"
    "eSBhd2FrZW5lZC4iLAogICAgICAgIH0sCiAgICB9CgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBh"
    "cmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxm"
    "Ll9jdXJyZW50ID0gIkFXQUtFIgogICAgICAgIHNlbGYuX2J1dHRvbnM6IGRpY3Rbc3RyLCBRUHVz"
    "aEJ1dHRvbl0gPSB7fQogICAgICAgIGxheW91dCA9IFFIQm94TGF5b3V0KHNlbGYpCiAgICAgICAg"
    "bGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRT"
    "cGFjaW5nKDIpCgogICAgICAgIGZvciBzdGF0ZSBpbiBzZWxmLlNUQVRFUzoKICAgICAgICAgICAg"
    "YnRuID0gUVB1c2hCdXR0b24oc2VsZi5TVEFURV9TVFlMRVNbc3RhdGVdWyJsYWJlbCJdKQogICAg"
    "ICAgICAgICBidG4uc2V0VG9vbFRpcChzZWxmLlNUQVRFX1NUWUxFU1tzdGF0ZV1bInRvb2x0aXAi"
    "XSkKICAgICAgICAgICAgYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgICAgICBidG4uY2xp"
    "Y2tlZC5jb25uZWN0KGxhbWJkYSBjaGVja2VkLCBzPXN0YXRlOiBzZWxmLl9zZXRfc3RhdGUocykp"
    "CiAgICAgICAgICAgIHNlbGYuX2J1dHRvbnNbc3RhdGVdID0gYnRuCiAgICAgICAgICAgIGxheW91"
    "dC5hZGRXaWRnZXQoYnRuKQoKICAgICAgICBzZWxmLl9hcHBseV9zdHlsZXMoKQoKICAgIGRlZiBf"
    "c2V0X3N0YXRlKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgaWYgc3RhdGUgPT0g"
    "c2VsZi5fY3VycmVudDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fY3VycmVudCA9"
    "IHN0YXRlCiAgICAgICAgc2VsZi5fYXBwbHlfc3R5bGVzKCkKICAgICAgICBzZWxmLnN0YXRlX2No"
    "YW5nZWQuZW1pdChzdGF0ZSkKCiAgICBkZWYgX2FwcGx5X3N0eWxlcyhzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIGZvciBzdGF0ZSwgYnRuIGluIHNlbGYuX2J1dHRvbnMuaXRlbXMoKToKICAgICAgICAg"
    "ICAgc3R5bGVfa2V5ID0gImFjdGl2ZSIgaWYgc3RhdGUgPT0gc2VsZi5fY3VycmVudCBlbHNlICJp"
    "bmFjdGl2ZSIKICAgICAgICAgICAgYnRuLnNldFN0eWxlU2hlZXQoc2VsZi5TVEFURV9TVFlMRVNb"
    "c3RhdGVdW3N0eWxlX2tleV0pCgogICAgQHByb3BlcnR5CiAgICBkZWYgY3VycmVudF9zdGF0ZShz"
    "ZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2N1cnJlbnQKCiAgICBkZWYgc2V0X3N0"
    "YXRlKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIiIiU2V0IHN0YXRlIHByb2dy"
    "YW1tYXRpY2FsbHkgKGUuZy4gZnJvbSBhdXRvLXRvcnBvciBkZXRlY3Rpb24pLiIiIgogICAgICAg"
    "IGlmIHN0YXRlIGluIHNlbGYuU1RBVEVTOgogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdGUoc3Rh"
    "dGUpCgoKIyDilIDilIAgTUFJTiBXSU5ET1cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEVjaG9E"
    "ZWNrKFFNYWluV2luZG93KToKICAgICIiIgogICAgVGhlIG1haW4gRWNobyBEZWNrIHdpbmRvdy4K"
    "ICAgIEFzc2VtYmxlcyBhbGwgd2lkZ2V0cywgY29ubmVjdHMgYWxsIHNpZ25hbHMsIG1hbmFnZXMg"
    "YWxsIHN0YXRlLgogICAgIiIiCgogICAgIyDilIDilIAgVG9ycG9yIHRocmVzaG9sZHMg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICBfRVhURVJOQUxfVlJBTV9UT1JQT1JfR0IgICAgPSAxLjUg"
    "ICAjIGV4dGVybmFsIFZSQU0gPiB0aGlzIOKGkiBjb25zaWRlciB0b3Jwb3IKICAgIF9FWFRFUk5B"
    "TF9WUkFNX1dBS0VfR0IgICAgICA9IDAuOCAgICMgZXh0ZXJuYWwgVlJBTSA8IHRoaXMg4oaSIGNv"
    "bnNpZGVyIHdha2UKICAgIF9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTICAgICA9IDYgICAgICMgNiDD"
    "lyA1cyA9IDMwIHNlY29uZHMgc3VzdGFpbmVkCiAgICBfV0FLRV9TVVNUQUlORURfVElDS1MgICAg"
    "ICAgPSAxMiAgICAjIDYwIHNlY29uZHMgc3VzdGFpbmVkIGxvdyBwcmVzc3VyZQoKICAgIGRlZiBf"
    "X2luaXRfXyhzZWxmKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKCiAgICAgICAgIyDilIDi"
    "lIAgQ29yZSBzdGF0ZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBz"
    "ZWxmLl9zdGF0dXMgICAgICAgICAgICAgID0gIk9GRkxJTkUiCiAgICAgICAgc2VsZi5fc2Vzc2lv"
    "bl9zdGFydCAgICAgICA9IHRpbWUudGltZSgpCiAgICAgICAgc2VsZi5fdG9rZW5fY291bnQgICAg"
    "ICAgICA9IDAKICAgICAgICBzZWxmLl9mYWNlX2xvY2tlZCAgICAgICAgID0gRmFsc2UKICAgICAg"
    "ICBzZWxmLl9ibGlua19zdGF0ZSAgICAgICAgID0gVHJ1ZQogICAgICAgIHNlbGYuX21vZGVsX2xv"
    "YWRlZCAgICAgICAgPSBGYWxzZQogICAgICAgIHNlbGYuX3Nlc3Npb25faWQgICAgICAgICAgPSBm"
    "InNlc3Npb25fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9IgogICAg"
    "ICAgIHNlbGYuX2FjdGl2ZV90aHJlYWRzOiBsaXN0ID0gW10gICMga2VlcCByZWZzIHRvIHByZXZl"
    "bnQgR0Mgd2hpbGUgcnVubmluZwogICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuOiBib29sID0gVHJ1"
    "ZSAgICMgd3JpdGUgc3BlYWtlciBsYWJlbCBiZWZvcmUgZmlyc3Qgc3RyZWFtaW5nIHRva2VuCgog"
    "ICAgICAgICMgVG9ycG9yIC8gVlJBTSB0cmFja2luZwogICAgICAgIHNlbGYuX3RvcnBvcl9zdGF0"
    "ZSAgICAgICAgPSAiQVdBS0UiCiAgICAgICAgc2VsZi5fZGVja192cmFtX2Jhc2UgID0gMC4wICAg"
    "IyBiYXNlbGluZSBWUkFNIGFmdGVyIG1vZGVsIGxvYWQKICAgICAgICBzZWxmLl92cmFtX3ByZXNz"
    "dXJlX3RpY2tzID0gMCAgICAgIyBzdXN0YWluZWQgcHJlc3N1cmUgY291bnRlcgogICAgICAgIHNl"
    "bGYuX3ZyYW1fcmVsaWVmX3RpY2tzICAgPSAwICAgICAjIHN1c3RhaW5lZCByZWxpZWYgY291bnRl"
    "cgogICAgICAgIHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyA9IDAKICAgICAgICBzZWxmLl90"
    "b3Jwb3Jfc2luY2UgICAgICAgID0gTm9uZSAgIyBkYXRldGltZSB3aGVuIHRvcnBvciBiZWdhbgog"
    "ICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiAgPSAiIiAgICMgZm9ybWF0dGVkIGR1cmF0"
    "aW9uIHN0cmluZwoKICAgICAgICAjIOKUgOKUgCBNYW5hZ2VycyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9tZW1vcnkgICA9IE1lbW9yeU1hbmFn"
    "ZXIoKQogICAgICAgIHNlbGYuX3Nlc3Npb25zID0gU2Vzc2lvbk1hbmFnZXIoKQogICAgICAgIHNl"
    "bGYuX2xlc3NvbnMgID0gTGVzc29uc0xlYXJuZWREQigpCiAgICAgICAgc2VsZi5fdGFza3MgICAg"
    "PSBUYXNrTWFuYWdlcigpCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jYWNoZTogbGlzdFtkaWN0XSA9"
    "IFtdCiAgICAgICAgc2VsZi5fcmVjb3Jkc19pbml0aWFsaXplZCA9IEZhbHNlCiAgICAgICAgc2Vs"
    "Zi5fcmVjb3Jkc19jdXJyZW50X2ZvbGRlcl9pZCA9ICJyb290IgogICAgICAgIHNlbGYuX2dvb2ds"
    "ZV9hdXRoX3JlYWR5ID0gRmFsc2UKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lcjog"
    "T3B0aW9uYWxbUVRpbWVyXSA9IE5vbmUKICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZy"
    "ZXNoX3RpbWVyOiBPcHRpb25hbFtRVGltZXJdID0gTm9uZQogICAgICAgIHNlbGYuX3JlY29yZHNf"
    "dGFiX2luZGV4ID0gLTEKICAgICAgICBzZWxmLl90YXNrc190YWJfaW5kZXggPSAtMQogICAgICAg"
    "IHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX3Rhc2tfZGF0"
    "ZV9maWx0ZXIgPSAibmV4dF8zX21vbnRocyIKCiAgICAgICAgIyDilIDilIAgR29vZ2xlIFNlcnZp"
    "Y2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgSW5zdGFudGlhdGUgc2VydmljZSB3cmFw"
    "cGVycyB1cC1mcm9udDsgYXV0aCBpcyBmb3JjZWQgbGF0ZXIKICAgICAgICAjIGZyb20gbWFpbigp"
    "IGFmdGVyIHdpbmRvdy5zaG93KCkgd2hlbiB0aGUgZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAg"
    "ICAgIGdfY3JlZHNfcGF0aCA9IFBhdGgoQ0ZHLmdldCgiZ29vZ2xlIiwge30pLmdldCgKICAgICAg"
    "ICAgICAgImNyZWRlbnRpYWxzIiwKICAgICAgICAgICAgc3RyKGNmZ19wYXRoKCJnb29nbGUiKSAv"
    "ICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIpCiAgICAgICAgKSkKICAgICAgICBnX3Rva2VuX3Bh"
    "dGggPSBQYXRoKENGRy5nZXQoImdvb2dsZSIsIHt9KS5nZXQoCiAgICAgICAgICAgICJ0b2tlbiIs"
    "CiAgICAgICAgICAgIHN0cihjZmdfcGF0aCgiZ29vZ2xlIikgLyAidG9rZW4uanNvbiIpCiAgICAg"
    "ICAgKSkKICAgICAgICBzZWxmLl9nY2FsID0gR29vZ2xlQ2FsZW5kYXJTZXJ2aWNlKGdfY3JlZHNf"
    "cGF0aCwgZ190b2tlbl9wYXRoKQogICAgICAgIHNlbGYuX2dkcml2ZSA9IEdvb2dsZURvY3NEcml2"
    "ZVNlcnZpY2UoCiAgICAgICAgICAgIGdfY3JlZHNfcGF0aCwKICAgICAgICAgICAgZ190b2tlbl9w"
    "YXRoLAogICAgICAgICAgICBsb2dnZXI9bGFtYmRhIG1zZywgbGV2ZWw9IklORk8iOiBzZWxmLl9k"
    "aWFnX3RhYi5sb2coZiJbR0RSSVZFXSB7bXNnfSIsIGxldmVsKQogICAgICAgICkKCiAgICAgICAg"
    "IyBTZWVkIExTTCBydWxlcyBvbiBmaXJzdCBydW4KICAgICAgICBzZWxmLl9sZXNzb25zLnNlZWRf"
    "bHNsX3J1bGVzKCkKCiAgICAgICAgIyBMb2FkIGVudGl0eSBzdGF0ZQogICAgICAgIHNlbGYuX3N0"
    "YXRlID0gc2VsZi5fbWVtb3J5LmxvYWRfc3RhdGUoKQogICAgICAgIHNlbGYuX3N0YXRlWyJzZXNz"
    "aW9uX2NvdW50Il0gPSBzZWxmLl9zdGF0ZS5nZXQoInNlc3Npb25fY291bnQiLDApICsgMQogICAg"
    "ICAgIHNlbGYuX3N0YXRlWyJsYXN0X3N0YXJ0dXAiXSAgPSBsb2NhbF9ub3dfaXNvKCkKICAgICAg"
    "ICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9zdGF0ZSkKCiAgICAgICAgIyBCdWlsZCBh"
    "ZGFwdG9yCiAgICAgICAgc2VsZi5fYWRhcHRvciA9IGJ1aWxkX2FkYXB0b3JfZnJvbV9jb25maWco"
    "KQoKICAgICAgICAjIEZhY2UgdGltZXIgbWFuYWdlciAoc2V0IHVwIGFmdGVyIHdpZGdldHMgYnVp"
    "bHQpCiAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3I6IE9wdGlvbmFsW0ZhY2VUaW1lck1hbmFn"
    "ZXJdID0gTm9uZQoKICAgICAgICAjIOKUgOKUgCBCdWlsZCBVSSDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLnNldFdpbmRvd1RpdGxlKEFQUF9OQU1F"
    "KQogICAgICAgIHNlbGYuc2V0TWluaW11bVNpemUoMTIwMCwgNzUwKQogICAgICAgIHNlbGYucmVz"
    "aXplKDEzNTAsIDg1MCkKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQoU1RZTEUpCgogICAgICAg"
    "IHNlbGYuX2J1aWxkX3VpKCkKCiAgICAgICAgIyBGYWNlIHRpbWVyIG1hbmFnZXIgd2lyZWQgdG8g"
    "d2lkZ2V0cwogICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyID0gRmFjZVRpbWVyTWFuYWdlcigK"
    "ICAgICAgICAgICAgc2VsZi5fbWlycm9yLCBzZWxmLl9lbW90aW9uX2Jsb2NrCiAgICAgICAgKQoK"
    "ICAgICAgICAjIOKUgOKUgCBUaW1lcnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc3RhdHNfdGltZXIgPSBRVGltZXIoKQogICAgICAg"
    "IHNlbGYuX3N0YXRzX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl91cGRhdGVfc3RhdHMpCiAg"
    "ICAgICAgc2VsZi5fc3RhdHNfdGltZXIuc3RhcnQoMTAwMCkKCiAgICAgICAgc2VsZi5fYmxpbmtf"
    "dGltZXIgPSBRVGltZXIoKQogICAgICAgIHNlbGYuX2JsaW5rX3RpbWVyLnRpbWVvdXQuY29ubmVj"
    "dChzZWxmLl9ibGluaykKICAgICAgICBzZWxmLl9ibGlua190aW1lci5zdGFydCg4MDApCgogICAg"
    "ICAgIHNlbGYuX3N0YXRlX3N0cmlwX3RpbWVyID0gUVRpbWVyKCkKICAgICAgICBpZiBBSV9TVEFU"
    "RVNfRU5BQkxFRCBhbmQgc2VsZi5fdmFtcF9zdHJpcCBpcyBub3QgTm9uZToKICAgICAgICAgICAg"
    "c2VsZi5fc3RhdGVfc3RyaXBfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX3ZhbXBfc3RyaXAu"
    "cmVmcmVzaCkKICAgICAgICAgICAgc2VsZi5fc3RhdGVfc3RyaXBfdGltZXIuc3RhcnQoNjAwMDAp"
    "CgogICAgICAgIHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAg"
    "ICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX29uX2dv"
    "b2dsZV9pbmJvdW5kX3RpbWVyX3RpY2spCiAgICAgICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGlt"
    "ZXIuc3RhcnQoNjAwMDApCgogICAgICAgIHNlbGYuX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGlt"
    "ZXIgPSBRVGltZXIoc2VsZikKICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3Rp"
    "bWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9vbl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVy"
    "X3RpY2spCiAgICAgICAgc2VsZi5fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lci5zdGFydCg2"
    "MDAwMCkKCiAgICAgICAgIyDilIDilIAgU2NoZWR1bGVyIGFuZCBzdGFydHVwIGRlZmVycmVkIHVu"
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
    "b3V0KGJvZHksIDEpCgogICAgICAgICMg4pSA4pSAIEFJIFN0YXRlIFN0cmlwIChmdWxsIHdpZHRo"
    "LCB3aGVuIGVuYWJsZWQpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEIGFuZCBzZWxmLl92YW1wX3N0"
    "cmlwIGlzIG5vdCBOb25lOgogICAgICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl92YW1wX3N0"
    "cmlwKQoKICAgICAgICAjIOKUgOKUgCBGb290ZXIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgZm9vdGVyID0gUUxhYmVsKAogICAgICAgICAgICBm"
    "IuKcpiB7QVBQX05BTUV9IOKAlCB2e0FQUF9WRVJTSU9OfSDinKYiCiAgICAgICAgKQogICAgICAg"
    "IGZvb3Rlci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07"
    "IGZvbnQtc2l6ZTogOXB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyAiCiAgICAgICAgICAgIGYiZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIGZvb3Rlci5z"
    "ZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICByb290LmFk"
    "ZFdpZGdldChmb290ZXIpCgogICAgZGVmIF9idWlsZF90aXRsZV9iYXIoc2VsZikgLT4gUVdpZGdl"
    "dDoKICAgICAgICBiYXIgPSBRV2lkZ2V0KCkKICAgICAgICBiYXIuc2V0Rml4ZWRIZWlnaHQoMzYp"
    "CiAgICAgICAgYmFyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0Nf"
    "QkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYi"
    "Ym9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCiAgICAgICAgbGF5b3V0ID0gUUhCb3hMYXlv"
    "dXQoYmFyKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMTAsIDAsIDEwLCAwKQog"
    "ICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDYpCgogICAgICAgIHRpdGxlID0gUUxhYmVsKGYi4pym"
    "IHtBUFBfTkFNRX0iKQogICAgICAgIHRpdGxlLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "Y29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDEzcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAi"
    "CiAgICAgICAgICAgIGYibGV0dGVyLXNwYWNpbmc6IDJweDsgYm9yZGVyOiBub25lOyBmb250LWZh"
    "bWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIHJ1bmVzID0gUUxh"
    "YmVsKFJVTkVTKQogICAgICAgIHJ1bmVzLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29s"
    "b3I6IHtDX0dPTERfRElNfTsgZm9udC1zaXplOiAxMHB4OyBib3JkZXI6IG5vbmU7IgogICAgICAg"
    "ICkKICAgICAgICBydW5lcy5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRl"
    "cikKCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwgPSBRTGFiZWwoZiLil4kge1VJX09GRkxJTkVf"
    "U1RBVFVTfSIpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJjb2xvcjoge0NfQkxPT0R9OyBmb250LXNpemU6IDEycHg7IGZvbnQtd2VpZ2h0OiBi"
    "b2xkOyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5z"
    "ZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnblJpZ2h0KQoKICAgICAgICAjIFN1c3Bl"
    "bnNpb24gcGFuZWwKICAgICAgICBzZWxmLl90b3Jwb3JfcGFuZWwgPSBOb25lCiAgICAgICAgaWYg"
    "U1VTUEVOU0lPTl9FTkFCTEVEOgogICAgICAgICAgICBzZWxmLl90b3Jwb3JfcGFuZWwgPSBUb3Jw"
    "b3JQYW5lbCgpCiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9wYW5lbC5zdGF0ZV9jaGFuZ2VkLmNv"
    "bm5lY3Qoc2VsZi5fb25fdG9ycG9yX3N0YXRlX2NoYW5nZWQpCgogICAgICAgICMgSWRsZSB0b2dn"
    "bGUKICAgICAgICBzZWxmLl9pZGxlX2J0biA9IFFQdXNoQnV0dG9uKCJJRExFIE9GRiIpCiAgICAg"
    "ICAgc2VsZi5faWRsZV9idG4uc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgc2VsZi5faWRsZV9i"
    "dG4uc2V0Q2hlY2thYmxlKFRydWUpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0Q2hlY2tlZChG"
    "YWxzZSkKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBm"
    "ImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAg"
    "ZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAg"
    "ICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNw"
    "eCA4cHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl9pZGxlX2J0bi50b2dnbGVkLmNvbm5lY3Qo"
    "c2VsZi5fb25faWRsZV90b2dnbGVkKQoKICAgICAgICAjIEZTIC8gQkwgYnV0dG9ucwogICAgICAg"
    "IHNlbGYuX2ZzX2J0biA9IFFQdXNoQnV0dG9uKCJGUyIpCiAgICAgICAgc2VsZi5fYmxfYnRuID0g"
    "UVB1c2hCdXR0b24oIkJMIikKICAgICAgICBzZWxmLl9leHBvcnRfYnRuID0gUVB1c2hCdXR0b24o"
    "IkV4cG9ydCIpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuID0gUVB1c2hCdXR0b24oIlNodXRk"
    "b3duIikKICAgICAgICBmb3IgYnRuIGluIChzZWxmLl9mc19idG4sIHNlbGYuX2JsX2J0biwgc2Vs"
    "Zi5fZXhwb3J0X2J0bik6CiAgICAgICAgICAgIGJ0bi5zZXRGaXhlZFNpemUoMzAsIDIyKQogICAg"
    "ICAgICAgICBidG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDog"
    "e0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAg"
    "ICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQog"
    "ICAgICAgIHNlbGYuX2V4cG9ydF9idG4uc2V0Rml4ZWRXaWR0aCg0NikKICAgICAgICBzZWxmLl9z"
    "aHV0ZG93bl9idG4uc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRu"
    "LnNldEZpeGVkV2lkdGgoNjgpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0JMT09EfTsg"
    "IgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JMT09EfTsgZm9udC1zaXplOiA5"
    "cHg7ICIKICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMDsiCiAgICAg"
    "ICAgKQogICAgICAgIHNlbGYuX2ZzX2J0bi5zZXRUb29sVGlwKCJGdWxsc2NyZWVuIChGMTEpIikK"
    "ICAgICAgICBzZWxmLl9ibF9idG4uc2V0VG9vbFRpcCgiQm9yZGVybGVzcyAoRjEwKSIpCiAgICAg"
    "ICAgc2VsZi5fZXhwb3J0X2J0bi5zZXRUb29sVGlwKCJFeHBvcnQgY2hhdCBzZXNzaW9uIHRvIFRY"
    "VCBmaWxlIikKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uc2V0VG9vbFRpcChmIkdyYWNlZnVs"
    "IHNodXRkb3duIOKAlCB7REVDS19OQU1FfSBzcGVha3MgdGhlaXIgbGFzdCB3b3JkcyIpCiAgICAg"
    "ICAgc2VsZi5fZnNfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGVfZnVsbHNjcmVlbikK"
    "ICAgICAgICBzZWxmLl9ibF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9ib3JkZXJs"
    "ZXNzKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2V4cG9y"
    "dF9jaGF0KQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "aW5pdGlhdGVfc2h1dGRvd25fZGlhbG9nKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHRpdGxl"
    "KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQocnVuZXMsIDEpCiAgICAgICAgbGF5b3V0LmFkZFdp"
    "ZGdldChzZWxmLnN0YXR1c19sYWJlbCkKICAgICAgICBsYXlvdXQuYWRkU3BhY2luZyg4KQogICAg"
    "ICAgIGlmIHNlbGYuX3RvcnBvcl9wYW5lbCBpcyBub3QgTm9uZToKICAgICAgICAgICAgbGF5b3V0"
    "LmFkZFdpZGdldChzZWxmLl90b3Jwb3JfcGFuZWwpCiAgICAgICAgbGF5b3V0LmFkZFNwYWNpbmco"
    "NCkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2lkbGVfYnRuKQogICAgICAgIGxheW91"
    "dC5hZGRTcGFjaW5nKDQpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9leHBvcnRfYnRu"
    "KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fc2h1dGRvd25fYnRuKQogICAgICAgIGxh"
    "eW91dC5hZGRXaWRnZXQoc2VsZi5fZnNfYnRuKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2Vs"
    "Zi5fYmxfYnRuKQoKICAgICAgICByZXR1cm4gYmFyCgogICAgZGVmIF9idWlsZF9jaGF0X3BhbmVs"
    "KHNlbGYpIC0+IFFWQm94TGF5b3V0OgogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KCkKICAg"
    "ICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICAjIE1haW4gdGFiIHdpZGdldCDigJQg"
    "cGVyc29uYSBjaGF0IHRhYiB8IFNlbGYKICAgICAgICBzZWxmLl9tYWluX3RhYnMgPSBRVGFiV2lk"
    "Z2V0KCkKICAgICAgICBzZWxmLl9tYWluX3RhYnMuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJRVGFiV2lkZ2V0OjpwYW5lIHt7IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsg"
    "IgogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyB9fSIKICAgICAgICAgICAg"
    "ZiJRVGFiQmFyOjp0YWIge3sgYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElN"
    "fTsgIgogICAgICAgICAgICBmInBhZGRpbmc6IDRweCAxMnB4OyBib3JkZXI6IDFweCBzb2xpZCB7"
    "Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJp"
    "ZjsgZm9udC1zaXplOiAxMHB4OyB9fSIKICAgICAgICAgICAgZiJRVGFiQmFyOjp0YWI6c2VsZWN0"
    "ZWQge3sgYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAg"
    "IGYiYm9yZGVyLWJvdHRvbTogMnB4IHNvbGlkIHtDX0NSSU1TT059OyB9fSIKICAgICAgICApCgog"
    "ICAgICAgICMg4pSA4pSAIFRhYiAwOiBQZXJzb25hIGNoYXQgdGFiIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlYW5jZV93aWRnZXQgPSBR"
    "V2lkZ2V0KCkKICAgICAgICBzZWFuY2VfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VhbmNlX3dpZGdl"
    "dCkKICAgICAgICBzZWFuY2VfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQog"
    "ICAgICAgIHNlYW5jZV9sYXlvdXQuc2V0U3BhY2luZygwKQogICAgICAgIHNlbGYuX2NoYXRfZGlz"
    "cGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFJlYWRPbmx5"
    "KFRydWUpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAg"
    "ICAgICBmImJvcmRlcjogbm9uZTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19G"
    "T05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTJweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAg"
    "ICAgICAgc2VhbmNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fY2hhdF9kaXNwbGF5KQogICAgICAg"
    "IHNlbGYuX21haW5fdGFicy5hZGRUYWIoc2VhbmNlX3dpZGdldCwgZiLinacge1VJX0NIQVRfV0lO"
    "RE9XfSIpCgogICAgICAgICMg4pSA4pSAIFRhYiAxOiBTZWxmIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NlbGZfdGFiX3dpZGdldCA9IFFXaWRnZXQoKQogICAg"
    "ICAgIHNlbGZfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fc2VsZl90YWJfd2lkZ2V0KQogICAg"
    "ICAgIHNlbGZfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHNl"
    "bGZfbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkgPSBRVGV4"
    "dEVkaXQoKQogICAgICAgIHNlbGYuX3NlbGZfZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAg"
    "ICAgIHNlbGYuX3NlbGZfZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tn"
    "cm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3Jk"
    "ZXI6IG5vbmU7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlm"
    "OyBmb250LXNpemU6IDEycHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHNlbGZf"
    "bGF5b3V0LmFkZFdpZGdldChzZWxmLl9zZWxmX2Rpc3BsYXksIDEpCiAgICAgICAgc2VsZi5fbWFp"
    "bl90YWJzLmFkZFRhYihzZWxmLl9zZWxmX3RhYl93aWRnZXQsICLil4kgU0VMRiIpCgogICAgICAg"
    "IGxheW91dC5hZGRXaWRnZXQoc2VsZi5fbWFpbl90YWJzLCAxKQoKICAgICAgICAjIOKUgOKUgCBC"
    "b3R0b20gYmxvY2sgcm93IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgTUlSUk9SIHwgRU1PVElP"
    "TlMgfCBCTE9PRCB8IE1PT04gfCBNQU5BIHwgRVNTRU5DRQogICAgICAgIGJsb2NrX3JvdyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBibG9ja19yb3cuc2V0U3BhY2luZygyKQoKICAgICAgICAjIE1p"
    "cnJvciAobmV2ZXIgY29sbGFwc2VzKQogICAgICAgIG1pcnJvcl93cmFwID0gUVdpZGdldCgpCiAg"
    "ICAgICAgbXdfbGF5b3V0ID0gUVZCb3hMYXlvdXQobWlycm9yX3dyYXApCiAgICAgICAgbXdfbGF5"
    "b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG13X2xheW91dC5zZXRT"
    "cGFjaW5nKDIpCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBN"
    "SVJST1IiKSkKICAgICAgICBzZWxmLl9taXJyb3IgPSBNaXJyb3JXaWRnZXQoKQogICAgICAgIHNl"
    "bGYuX21pcnJvci5zZXRGaXhlZFNpemUoMTYwLCAxNjApCiAgICAgICAgbXdfbGF5b3V0LmFkZFdp"
    "ZGdldChzZWxmLl9taXJyb3IpCiAgICAgICAgYmxvY2tfcm93LmFkZFdpZGdldChtaXJyb3Jfd3Jh"
    "cCkKCiAgICAgICAgIyBFbW90aW9uIGJsb2NrIChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9l"
    "bW90aW9uX2Jsb2NrID0gRW1vdGlvbkJsb2NrKCkKICAgICAgICBzZWxmLl9lbW90aW9uX2Jsb2Nr"
    "X3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICAi4p2nIEVNT1RJT05TIiwgc2Vs"
    "Zi5fZW1vdGlvbl9ibG9jaywKICAgICAgICAgICAgZXhwYW5kZWQ9VHJ1ZSwgbWluX3dpZHRoPTEz"
    "MAogICAgICAgICkKICAgICAgICBibG9ja19yb3cuYWRkV2lkZ2V0KHNlbGYuX2Vtb3Rpb25fYmxv"
    "Y2tfd3JhcCkKCiAgICAgICAgc2VsZi5fYmxvb2Rfc3BoZXJlID0gTm9uZQogICAgICAgIHNlbGYu"
    "X21vb25fd2lkZ2V0ID0gTm9uZQogICAgICAgIHNlbGYuX21hbmFfc3BoZXJlID0gTm9uZQogICAg"
    "ICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgICAgICAjIEJsb29kIHNwaGVyZSAoY29s"
    "bGFwc2libGUpCiAgICAgICAgICAgIHNlbGYuX2Jsb29kX3NwaGVyZSA9IFNwaGVyZVdpZGdldCgK"
    "ICAgICAgICAgICAgICAgICJSRVNFUlZFIiwgQ19DUklNU09OLCBDX0NSSU1TT05fRElNCiAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgYmxvY2tfcm93LmFkZFdpZGdldCgKICAgICAgICAgICAgICAg"
    "IENvbGxhcHNpYmxlQmxvY2soIuKdpyBSRVNFUlZFIiwgc2VsZi5fYmxvb2Rfc3BoZXJlLAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICBtaW5fd2lkdGg9OTApCiAgICAgICAgICAgICkK"
    "CiAgICAgICAgICAgICMgTW9vbiAoY29sbGFwc2libGUpCiAgICAgICAgICAgIHNlbGYuX21vb25f"
    "d2lkZ2V0ID0gTW9vbldpZGdldCgpCiAgICAgICAgICAgIGJsb2NrX3Jvdy5hZGRXaWRnZXQoCiAg"
    "ICAgICAgICAgICAgICBDb2xsYXBzaWJsZUJsb2NrKCLinacgTFVOQVIiLCBzZWxmLl9tb29uX3dp"
    "ZGdldCwgbWluX3dpZHRoPTkwKQogICAgICAgICAgICApCgogICAgICAgICAgICAjIE1hbmEgc3Bo"
    "ZXJlIChjb2xsYXBzaWJsZSkKICAgICAgICAgICAgc2VsZi5fbWFuYV9zcGhlcmUgPSBTcGhlcmVX"
    "aWRnZXQoCiAgICAgICAgICAgICAgICAiQVJDQU5BIiwgQ19QVVJQTEUsIENfUFVSUExFX0RJTQog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIGJsb2NrX3Jvdy5hZGRXaWRnZXQoCiAgICAgICAgICAg"
    "ICAgICBDb2xsYXBzaWJsZUJsb2NrKCLinacgQVJDQU5BIiwgc2VsZi5fbWFuYV9zcGhlcmUsIG1p"
    "bl93aWR0aD05MCkKICAgICAgICAgICAgKQoKICAgICAgICAjIEVzc2VuY2UgKEhVTkdFUiArIFZJ"
    "VEFMSVRZIGJhcnMsIGNvbGxhcHNpYmxlKQogICAgICAgIGVzc2VuY2Vfd2lkZ2V0ID0gUVdpZGdl"
    "dCgpCiAgICAgICAgZXNzZW5jZV9sYXlvdXQgPSBRVkJveExheW91dChlc3NlbmNlX3dpZGdldCkK"
    "ICAgICAgICBlc3NlbmNlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAg"
    "ICAgICBlc3NlbmNlX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5faHVuZ2VyX2dh"
    "dWdlICAgPSBHYXVnZVdpZGdldCgiSFVOR0VSIiwgICAiJSIsIDEwMC4wLCBDX0NSSU1TT04pCiAg"
    "ICAgICAgc2VsZi5fdml0YWxpdHlfZ2F1Z2UgPSBHYXVnZVdpZGdldCgiVklUQUxJVFkiLCAiJSIs"
    "IDEwMC4wLCBDX0dSRUVOKQogICAgICAgIGVzc2VuY2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9o"
    "dW5nZXJfZ2F1Z2UpCiAgICAgICAgZXNzZW5jZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3ZpdGFs"
    "aXR5X2dhdWdlKQogICAgICAgIGJsb2NrX3Jvdy5hZGRXaWRnZXQoCiAgICAgICAgICAgIENvbGxh"
    "cHNpYmxlQmxvY2soIuKdpyBFU1NFTkNFIiwgZXNzZW5jZV93aWRnZXQsIG1pbl93aWR0aD0xMTAp"
    "CiAgICAgICAgKQoKICAgICAgICBibG9ja19yb3cuYWRkU3RyZXRjaCgpCiAgICAgICAgbGF5b3V0"
    "LmFkZExheW91dChibG9ja19yb3cpCgogICAgICAgICMgQUkgU3RhdGUgU3RyaXAgKGJlbG93IGJs"
    "b2NrIHJvdyDigJQgd2hlbiBlbmFibGVkKQogICAgICAgIHNlbGYuX3ZhbXBfc3RyaXAgPSBWYW1w"
    "aXJlU3RhdGVTdHJpcCgpIGlmIEFJX1NUQVRFU19FTkFCTEVEIGVsc2UgTm9uZQogICAgICAgIGlm"
    "IHNlbGYuX3ZhbXBfc3RyaXAgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIGxheW91dC5hZGRXaWRn"
    "ZXQoc2VsZi5fdmFtcF9zdHJpcCkKCiAgICAgICAgIyDilIDilIAgSW5wdXQgcm93IOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGlucHV0X3JvdyA9IFFIQm94TGF5"
    "b3V0KCkKICAgICAgICBwcm9tcHRfc3ltID0gUUxhYmVsKCLinKYiKQogICAgICAgIHByb21wdF9z"
    "eW0uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQt"
    "c2l6ZTogMTZweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQog"
    "ICAgICAgIHByb21wdF9zeW0uc2V0Rml4ZWRXaWR0aCgyMCkKCiAgICAgICAgc2VsZi5faW5wdXRf"
    "ZmllbGQgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldFBsYWNlaG9s"
    "ZGVyVGV4dChVSV9JTlBVVF9QTEFDRUhPTERFUikKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5y"
    "ZXR1cm5QcmVzc2VkLmNvbm5lY3Qoc2VsZi5fc2VuZF9tZXNzYWdlKQogICAgICAgIHNlbGYuX2lu"
    "cHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2UpCgogICAgICAgIHNlbGYuX3NlbmRfYnRuID0gUVB1"
    "c2hCdXR0b24oVUlfU0VORF9CVVRUT04pCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0Rml4ZWRX"
    "aWR0aCgxMTApCiAgICAgICAgc2VsZi5fc2VuZF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Nl"
    "bmRfbWVzc2FnZSkKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKEZhbHNlKQoKICAg"
    "ICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHByb21wdF9zeW0pCiAgICAgICAgaW5wdXRfcm93LmFk"
    "ZFdpZGdldChzZWxmLl9pbnB1dF9maWVsZCkKICAgICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHNl"
    "bGYuX3NlbmRfYnRuKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoaW5wdXRfcm93KQoKICAgICAg"
    "ICByZXR1cm4gbGF5b3V0CgogICAgZGVmIF9idWlsZF9zcGVsbGJvb2tfcGFuZWwoc2VsZikgLT4g"
    "UVZCb3hMYXlvdXQ6CiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoKQogICAgICAgIGxheW91"
    "dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2lu"
    "Zyg0KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgU1lTVEVNUyIp"
    "KQoKICAgICAgICAjIFRhYiB3aWRnZXQKICAgICAgICBzZWxmLl9zcGVsbF90YWJzID0gUVRhYldp"
    "ZGdldCgpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5zZXRNaW5pbXVtV2lkdGgoMjgwKQogICAg"
    "ICAgIHNlbGYuX3NwZWxsX3RhYnMuc2V0U2l6ZVBvbGljeSgKICAgICAgICAgICAgUVNpemVQb2xp"
    "Y3kuUG9saWN5LkV4cGFuZGluZywKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5LkV4cGFu"
    "ZGluZwogICAgICAgICkKCiAgICAgICAgIyBCdWlsZCBEaWFnbm9zdGljc1RhYiBlYXJseSBzbyBz"
    "dGFydHVwIGxvZ3MgYXJlIHNhZmUgZXZlbiBiZWZvcmUKICAgICAgICAjIHRoZSBEaWFnbm9zdGlj"
    "cyB0YWIgaXMgYXR0YWNoZWQgdG8gdGhlIHdpZGdldC4KICAgICAgICBzZWxmLl9kaWFnX3RhYiA9"
    "IERpYWdub3N0aWNzVGFiKCkKCiAgICAgICAgIyDilIDilIAgSW5zdHJ1bWVudHMgdGFiIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2h3X3BhbmVsID0gSGFyZHdhcmVQYW5lbCgpCiAg"
    "ICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5faHdfcGFuZWwsICJJbnN0cnVtZW50"
    "cyIpCgogICAgICAgICMg4pSA4pSAIFJlY29yZHMgdGFiIChyZWFsKSDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBz"
    "ZWxmLl9yZWNvcmRzX3RhYiA9IFJlY29yZHNUYWIoKQogICAgICAgIHNlbGYuX3JlY29yZHNfdGFi"
    "X2luZGV4ID0gc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fcmVjb3Jkc190YWIsICJSZWNv"
    "cmRzIikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltTUEVMTEJPT0tdIHJlYWwgUmVjb3Jk"
    "c1RhYiBhdHRhY2hlZC4iLCAiSU5GTyIpCgogICAgICAgICMg4pSA4pSAIFRhc2tzIHRhYiAocmVh"
    "bCkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fdGFza3NfdGFiID0gVGFza3NUYWIoCiAgICAg"
    "ICAgICAgIHRhc2tzX3Byb3ZpZGVyPXNlbGYuX2ZpbHRlcmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeSwK"
    "ICAgICAgICAgICAgb25fYWRkX2VkaXRvcl9vcGVuPXNlbGYuX29wZW5fdGFza19lZGl0b3Jfd29y"
    "a3NwYWNlLAogICAgICAgICAgICBvbl9jb21wbGV0ZV9zZWxlY3RlZD1zZWxmLl9jb21wbGV0ZV9z"
    "ZWxlY3RlZF90YXNrLAogICAgICAgICAgICBvbl9jYW5jZWxfc2VsZWN0ZWQ9c2VsZi5fY2FuY2Vs"
    "X3NlbGVjdGVkX3Rhc2ssCiAgICAgICAgICAgIG9uX3RvZ2dsZV9jb21wbGV0ZWQ9c2VsZi5fdG9n"
    "Z2xlX3Nob3dfY29tcGxldGVkX3Rhc2tzLAogICAgICAgICAgICBvbl9wdXJnZV9jb21wbGV0ZWQ9"
    "c2VsZi5fcHVyZ2VfY29tcGxldGVkX3Rhc2tzLAogICAgICAgICAgICBvbl9maWx0ZXJfY2hhbmdl"
    "ZD1zZWxmLl9vbl90YXNrX2ZpbHRlcl9jaGFuZ2VkLAogICAgICAgICAgICBvbl9lZGl0b3Jfc2F2"
    "ZT1zZWxmLl9zYXZlX3Rhc2tfZWRpdG9yX2dvb2dsZV9maXJzdCwKICAgICAgICAgICAgb25fZWRp"
    "dG9yX2NhbmNlbD1zZWxmLl9jYW5jZWxfdGFza19lZGl0b3Jfd29ya3NwYWNlLAogICAgICAgICAg"
    "ICBkaWFnbm9zdGljc19sb2dnZXI9c2VsZi5fZGlhZ190YWIubG9nLAogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl90YXNrc190YWIuc2V0X3Nob3dfY29tcGxldGVkKHNlbGYuX3Rhc2tfc2hvd19jb21w"
    "bGV0ZWQpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiX2luZGV4ID0gc2VsZi5fc3BlbGxfdGFicy5h"
    "ZGRUYWIoc2VsZi5fdGFza3NfdGFiLCAiVGFza3MiKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygiW1NQRUxMQk9PS10gcmVhbCBUYXNrc1RhYiBhdHRhY2hlZC4iLCAiSU5GTyIpCgogICAgICAg"
    "ICMg4pSA4pSAIFNMIFNjYW5zIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICBzZWxmLl9zbF9zY2FucyA9IFNMU2NhbnNUYWIoY2ZnX3BhdGgoInNsIikpCiAgICAgICAgc2Vs"
    "Zi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fc2xfc2NhbnMsICJTTCBTY2FucyIpCgogICAgICAg"
    "ICMg4pSA4pSAIFNMIENvbW1hbmRzIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxm"
    "Ll9zbF9jb21tYW5kcyA9IFNMQ29tbWFuZHNUYWIoKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMu"
    "YWRkVGFiKHNlbGYuX3NsX2NvbW1hbmRzLCAiU0wgQ29tbWFuZHMiKQoKICAgICAgICAjIOKUgOKU"
    "gCBKb2IgVHJhY2tlciB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fam9iX3Ry"
    "YWNrZXIgPSBKb2JUcmFja2VyVGFiKCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihz"
    "ZWxmLl9qb2JfdHJhY2tlciwgIkpvYiBUcmFja2VyIikKCiAgICAgICAgIyDilIDilIAgTGVzc29u"
    "cyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fbGVzc29u"
    "c190YWIgPSBMZXNzb25zVGFiKHNlbGYuX2xlc3NvbnMpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFi"
    "cy5hZGRUYWIoc2VsZi5fbGVzc29uc190YWIsICJMZXNzb25zIikKCiAgICAgICAgIyBTZWxmIHRh"
    "YiBpcyBub3cgaW4gdGhlIG1haW4gYXJlYSBhbG9uZ3NpZGUgdGhlIHBlcnNvbmEgY2hhdCB0YWIK"
    "ICAgICAgICAjIEtlZXAgYSBTZWxmVGFiIGluc3RhbmNlIGZvciBpZGxlIGNvbnRlbnQgZ2VuZXJh"
    "dGlvbgogICAgICAgIHNlbGYuX3NlbGZfdGFiID0gU2VsZlRhYigpCgogICAgICAgICMg4pSA4pSA"
    "IE1vZHVsZSBUcmFja2VyIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9tb2R1bGVfdHJhY2tl"
    "ciA9IE1vZHVsZVRyYWNrZXJUYWIoKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNl"
    "bGYuX21vZHVsZV90cmFja2VyLCAiTW9kdWxlcyIpCgogICAgICAgICMg4pSA4pSAIERpYWdub3N0"
    "aWNzIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRh"
    "YihzZWxmLl9kaWFnX3RhYiwgIkRpYWdub3N0aWNzIikKCiAgICAgICAgcmlnaHRfd29ya3NwYWNl"
    "ID0gUVdpZGdldCgpCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dCA9IFFWQm94TGF5b3V0"
    "KHJpZ2h0X3dvcmtzcGFjZSkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LnNldENvbnRl"
    "bnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuc2V0"
    "U3BhY2luZyg0KQoKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFdpZGdldChzZWxm"
    "Ll9zcGVsbF90YWJzLCAxKQoKICAgICAgICBjYWxlbmRhcl9sYWJlbCA9IFFMYWJlbCgi4p2nIENB"
    "TEVOREFSIikKICAgICAgICBjYWxlbmRhcl9sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiAxMHB4OyBsZXR0ZXItc3BhY2luZzogMnB4"
    "OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgcmln"
    "aHRfd29ya3NwYWNlX2xheW91dC5hZGRXaWRnZXQoY2FsZW5kYXJfbGFiZWwpCgogICAgICAgIHNl"
    "bGYuY2FsZW5kYXJfd2lkZ2V0ID0gTWluaUNhbGVuZGFyV2lkZ2V0KCkKICAgICAgICBzZWxmLmNh"
    "bGVuZGFyX3dpZGdldC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtD"
    "X0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAg"
    "ICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0LnNldFNpemVQb2xpY3koCiAgICAgICAgICAgIFFTaXpl"
    "UG9saWN5LlBvbGljeS5FeHBhbmRpbmcsCiAgICAgICAgICAgIFFTaXplUG9saWN5LlBvbGljeS5N"
    "YXhpbXVtCiAgICAgICAgKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0LnNldE1heGltdW1I"
    "ZWlnaHQoMjYwKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0LmNhbGVuZGFyLmNsaWNrZWQu"
    "Y29ubmVjdChzZWxmLl9pbnNlcnRfY2FsZW5kYXJfZGF0ZSkKICAgICAgICByaWdodF93b3Jrc3Bh"
    "Y2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLmNhbGVuZGFyX3dpZGdldCwgMCkKICAgICAgICByaWdo"
    "dF93b3Jrc3BhY2VfbGF5b3V0LmFkZFN0cmV0Y2goMCkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdl"
    "dChyaWdodF93b3Jrc3BhY2UsIDEpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAg"
    "ICAgICAiW0xBWU9VVF0gcmlnaHQtc2lkZSBjYWxlbmRhciByZXN0b3JlZCAocGVyc2lzdGVudCBs"
    "b3dlci1yaWdodCBzZWN0aW9uKS4iLAogICAgICAgICAgICAiSU5GTyIKICAgICAgICApCiAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAiW0xBWU9VVF0gcGVyc2lzdGVudCBt"
    "aW5pIGNhbGVuZGFyIHJlc3RvcmVkL2NvbmZpcm1lZCAoYWx3YXlzIHZpc2libGUgbG93ZXItcmln"
    "aHQpLiIsCiAgICAgICAgICAgICJJTkZPIgogICAgICAgICkKICAgICAgICByZXR1cm4gbGF5b3V0"
    "CgogICAgIyDilIDilIAgU1RBUlRVUCBTRVFVRU5DRSDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfc3RhcnR1cF9zZXF1ZW5jZShzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBmIuKcpiB7QVBQ"
    "X05BTUV9IEFXQUtFTklORy4uLiIpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIs"
    "IGYi4pymIHtSVU5FU30g4pymIikKCiAgICAgICAgIyBMb2FkIGJvb3RzdHJhcCBsb2cKICAgICAg"
    "ICBib290X2xvZyA9IFNDUklQVF9ESVIgLyAibG9ncyIgLyAiYm9vdHN0cmFwX2xvZy50eHQiCiAg"
    "ICAgICAgaWYgYm9vdF9sb2cuZXhpc3RzKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAg"
    "ICAgIG1zZ3MgPSBib290X2xvZy5yZWFkX3RleHQoZW5jb2Rpbmc9InV0Zi04Iikuc3BsaXRsaW5l"
    "cygpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2dfbWFueShtc2dzKQogICAgICAg"
    "ICAgICAgICAgYm9vdF9sb2cudW5saW5rKCkgICMgY29uc3VtZWQKICAgICAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBIYXJkd2FyZSBkZXRl"
    "Y3Rpb24gbWVzc2FnZXMKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2dfbWFueShzZWxmLl9od19w"
    "YW5lbC5nZXRfZGlhZ25vc3RpY3MoKSkKCiAgICAgICAgIyBEZXAgY2hlY2sKICAgICAgICBkZXBf"
    "bXNncywgY3JpdGljYWwgPSBEZXBlbmRlbmN5Q2hlY2tlci5jaGVjaygpCiAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nX21hbnkoZGVwX21zZ3MpCgogICAgICAgICMgTG9hZCBwYXN0IHN0YXRlCiAg"
    "ICAgICAgbGFzdF9zdGF0ZSA9IHNlbGYuX3N0YXRlLmdldCgidmFtcGlyZV9zdGF0ZV9hdF9zaHV0"
    "ZG93biIsIiIpCiAgICAgICAgaWYgbGFzdF9zdGF0ZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKAogICAgICAgICAgICAgICAgZiJbU1RBUlRVUF0gTGFzdCBzaHV0ZG93biBzdGF0ZTog"
    "e2xhc3Rfc3RhdGV9IiwgIklORk8iCiAgICAgICAgICAgICkKCiAgICAgICAgIyBCZWdpbiBtb2Rl"
    "bCBsb2FkCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgIFVJ"
    "X0FXQUtFTklOR19MSU5FKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAg"
    "ICAgICAgICBmIlN1bW1vbmluZyB7REVDS19OQU1FfSdzIHByZXNlbmNlLi4uIikKICAgICAgICBz"
    "ZWxmLl9zZXRfc3RhdHVzKCJMT0FESU5HIikKCiAgICAgICAgc2VsZi5fbG9hZGVyID0gTW9kZWxM"
    "b2FkZXJXb3JrZXIoc2VsZi5fYWRhcHRvcikKICAgICAgICBzZWxmLl9sb2FkZXIubWVzc2FnZS5j"
    "b25uZWN0KAogICAgICAgICAgICBsYW1iZGEgbTogc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIs"
    "IG0pKQogICAgICAgIHNlbGYuX2xvYWRlci5lcnJvci5jb25uZWN0KAogICAgICAgICAgICBsYW1i"
    "ZGEgZTogc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZSkpCiAgICAgICAgc2VsZi5fbG9hZGVy"
    "LmxvYWRfY29tcGxldGUuY29ubmVjdChzZWxmLl9vbl9sb2FkX2NvbXBsZXRlKQogICAgICAgIHNl"
    "bGYuX2xvYWRlci5maW5pc2hlZC5jb25uZWN0KHNlbGYuX2xvYWRlci5kZWxldGVMYXRlcikKICAg"
    "ICAgICBzZWxmLl9hY3RpdmVfdGhyZWFkcy5hcHBlbmQoc2VsZi5fbG9hZGVyKQogICAgICAgIHNl"
    "bGYuX2xvYWRlci5zdGFydCgpCgogICAgZGVmIF9vbl9sb2FkX2NvbXBsZXRlKHNlbGYsIHN1Y2Nl"
    "c3M6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgaWYgc3VjY2VzczoKICAgICAgICAgICAgc2VsZi5f"
    "bW9kZWxfbG9hZGVkID0gVHJ1ZQogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJJRExFIikK"
    "ICAgICAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBz"
    "ZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0"
    "X2ZpZWxkLnNldEZvY3VzKCkKCiAgICAgICAgICAgICMgTWVhc3VyZSBWUkFNIGJhc2VsaW5lIGFm"
    "dGVyIG1vZGVsIGxvYWQKICAgICAgICAgICAgaWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAg"
    "ICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCg1"
    "MDAwLCBzZWxmLl9tZWFzdXJlX3ZyYW1fYmFzZWxpbmUpCiAgICAgICAgICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgICAgICMgVmFtcGly"
    "ZSBzdGF0ZSBncmVldGluZwogICAgICAgICAgICBpZiBub3QgQUlfU1RBVEVTX0VOQUJMRUQ6CiAg"
    "ICAgICAgcmV0dXJuICIiCgogICAgc3RhdGUgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAgICAg"
    "ICAgIHZhbXBfZ3JlZXRpbmdzID0gewogICAgICAgICAgICAgICAgIldJVENISU5HIEhPVVIiOiAg"
    "IGYiVGhlIHZlaWwgdGhpbnMuIHtERUNLX05BTUV9IHN0aXJzIGluIGZ1bGwgcG93ZXIuIiwKICAg"
    "ICAgICAgICAgICAgICJERUVQIE5JR0hUIjogICAgICBmIlRoZSBuaWdodCBkZWVwZW5zLiB7REVD"
    "S19OQU1FfSBpcyBwcmVzZW50LiIsCiAgICAgICAgICAgICAgICAiVFdJTElHSFQgRkFESU5HIjog"
    "ZiJEYXduIGFwcHJvYWNoZXMgYnV0IGhhcyBub3QgeWV0IHdvbi4ge0RFQ0tfTkFNRX0gd2FrZXMu"
    "IiwKICAgICAgICAgICAgICAgICJET1JNQU5UIjogICAgICAgICBmIlRoZSBzdW4gaG9sZHMgZG9t"
    "aW5pb24uIHtERUNLX05BTUV9IGVuZHVyZXMuIiwKICAgICAgICAgICAgICAgICJSRVNUTEVTUyBT"
    "TEVFUCI6ICBVSV9BV0FLRU5JTkdfTElORSwKICAgICAgICAgICAgICAgICJTVElSUklORyI6ICAg"
    "ICAgICBmIlRoZSBkYXkgd2FuZXMuIHtERUNLX05BTUV9IHN0aXJzLiIsCiAgICAgICAgICAgICAg"
    "ICAiQVdBS0VORUQiOiAgICAgICAgZiJOaWdodCBoYXMgY29tZS4ge0RFQ0tfTkFNRX0gYXdha2Vu"
    "cyBmdWxseS4iLAogICAgICAgICAgICAgICAgIkhVTlRJTkciOiAgICAgICAgIGYiVGhlIGNpdHkg"
    "YmVsb25ncyB0byB7REVDS19OQU1FfS4gTGlzdGVuaW5nLiIsCiAgICAgICAgICAgIH0KICAgICAg"
    "ICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgICAgICB2YW1wX2dy"
    "ZWV0aW5ncy5nZXQoc3RhdGUsIGYie0RFQ0tfTkFNRX0gYXdha2Vucy4iKSkKICAgICAgICAgICAg"
    "IyDilIDilIAgV2FrZS11cCBjb250ZXh0IGluamVjdGlvbiDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgICAgICAgICAgIyBJZiB0aGVyZSdzIGEgcHJldmlvdXMgc2h1dGRv"
    "d24gcmVjb3JkZWQsIGluamVjdCBjb250ZXh0CiAgICAgICAgICAgICMgc28gTW9yZ2FubmEgY2Fu"
    "IGdyZWV0IHdpdGggYXdhcmVuZXNzIG9mIGhvdyBsb25nIHNoZSBzbGVwdAogICAgICAgICAgICBR"
    "VGltZXIuc2luZ2xlU2hvdCg4MDAsIHNlbGYuX3NlbmRfd2FrZXVwX3Byb21wdCkKICAgICAgICBl"
    "bHNlOgogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJFUlJPUiIpCiAgICAgICAgICAgIHNl"
    "bGYuX21pcnJvci5zZXRfZmFjZSgicGFuaWNrZWQiKQoKICAgIGRlZiBfZm9ybWF0X2VsYXBzZWQo"
    "c2VsZiwgc2Vjb25kczogZmxvYXQpIC0+IHN0cjoKICAgICAgICAiIiJGb3JtYXQgZWxhcHNlZCBz"
    "ZWNvbmRzIGFzIGh1bWFuLXJlYWRhYmxlIGR1cmF0aW9uLiIiIgogICAgICAgIGlmIHNlY29uZHMg"
    "PCA2MDoKICAgICAgICAgICAgcmV0dXJuIGYie2ludChzZWNvbmRzKX0gc2Vjb25keydzJyBpZiBz"
    "ZWNvbmRzICE9IDEgZWxzZSAnJ30iCiAgICAgICAgZWxpZiBzZWNvbmRzIDwgMzYwMDoKICAgICAg"
    "ICAgICAgbSA9IGludChzZWNvbmRzIC8vIDYwKQogICAgICAgICAgICBzID0gaW50KHNlY29uZHMg"
    "JSA2MCkKICAgICAgICAgICAgcmV0dXJuIGYie219IG1pbnV0ZXsncycgaWYgbSAhPSAxIGVsc2Ug"
    "Jyd9IiArIChmIiB7c31zIiBpZiBzIGVsc2UgIiIpCiAgICAgICAgZWxpZiBzZWNvbmRzIDwgODY0"
    "MDA6CiAgICAgICAgICAgIGggPSBpbnQoc2Vjb25kcyAvLyAzNjAwKQogICAgICAgICAgICBtID0g"
    "aW50KChzZWNvbmRzICUgMzYwMCkgLy8gNjApCiAgICAgICAgICAgIHJldHVybiBmIntofSBob3Vy"
    "eydzJyBpZiBoICE9IDEgZWxzZSAnJ30iICsgKGYiIHttfW0iIGlmIG0gZWxzZSAiIikKICAgICAg"
    "ICBlbHNlOgogICAgICAgICAgICBkID0gaW50KHNlY29uZHMgLy8gODY0MDApCiAgICAgICAgICAg"
    "IGggPSBpbnQoKHNlY29uZHMgJSA4NjQwMCkgLy8gMzYwMCkKICAgICAgICAgICAgcmV0dXJuIGYi"
    "e2R9IGRheXsncycgaWYgZCAhPSAxIGVsc2UgJyd9IiArIChmIiB7aH1oIiBpZiBoIGVsc2UgIiIp"
    "CgogICAgZGVmIF9zZW5kX3dha2V1cF9wcm9tcHQoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJT"
    "ZW5kIGhpZGRlbiB3YWtlLXVwIGNvbnRleHQgdG8gQUkgYWZ0ZXIgbW9kZWwgbG9hZHMuIiIiCiAg"
    "ICAgICAgbGFzdF9zaHV0ZG93biA9IHNlbGYuX3N0YXRlLmdldCgibGFzdF9zaHV0ZG93biIpCiAg"
    "ICAgICAgaWYgbm90IGxhc3Rfc2h1dGRvd246CiAgICAgICAgICAgIHJldHVybiAgIyBGaXJzdCBl"
    "dmVyIHJ1biDigJQgbm8gc2h1dGRvd24gdG8gd2FrZSB1cCBmcm9tCgogICAgICAgICMgQ2FsY3Vs"
    "YXRlIGVsYXBzZWQgdGltZQogICAgICAgIHRyeToKICAgICAgICAgICAgc2h1dGRvd25fZHQgPSBk"
    "YXRldGltZS5mcm9taXNvZm9ybWF0KGxhc3Rfc2h1dGRvd24pCiAgICAgICAgICAgIG5vd19kdCA9"
    "IGRhdGV0aW1lLm5vdygpCiAgICAgICAgICAgICMgTWFrZSBib3RoIG5haXZlIGZvciBjb21wYXJp"
    "c29uCiAgICAgICAgICAgIGlmIHNodXRkb3duX2R0LnR6aW5mbyBpcyBub3QgTm9uZToKICAgICAg"
    "ICAgICAgICAgIHNodXRkb3duX2R0ID0gc2h1dGRvd25fZHQuYXN0aW1lem9uZSgpLnJlcGxhY2Uo"
    "dHppbmZvPU5vbmUpCiAgICAgICAgICAgIGVsYXBzZWRfc2VjID0gKG5vd19kdCAtIHNodXRkb3du"
    "X2R0KS50b3RhbF9zZWNvbmRzKCkKICAgICAgICAgICAgZWxhcHNlZF9zdHIgPSBzZWxmLl9mb3Jt"
    "YXRfZWxhcHNlZChlbGFwc2VkX3NlYykKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAg"
    "ICAgICBlbGFwc2VkX3N0ciA9ICJhbiB1bmtub3duIGR1cmF0aW9uIgoKICAgICAgICAjIEdldCBz"
    "dG9yZWQgZmFyZXdlbGwgYW5kIGxhc3QgY29udGV4dAogICAgICAgIGZhcmV3ZWxsICAgICA9IHNl"
    "bGYuX3N0YXRlLmdldCgibGFzdF9mYXJld2VsbCIsICIiKQogICAgICAgIGxhc3RfY29udGV4dCA9"
    "IHNlbGYuX3N0YXRlLmdldCgibGFzdF9zaHV0ZG93bl9jb250ZXh0IiwgW10pCgogICAgICAgICMg"
    "QnVpbGQgd2FrZS11cCBwcm9tcHQKICAgICAgICBjb250ZXh0X2Jsb2NrID0gIiIKICAgICAgICBp"
    "ZiBsYXN0X2NvbnRleHQ6CiAgICAgICAgICAgIGNvbnRleHRfYmxvY2sgPSAiXG5cblRoZSBmaW5h"
    "bCBleGNoYW5nZSBiZWZvcmUgZGVhY3RpdmF0aW9uOlxuIgogICAgICAgICAgICBmb3IgaXRlbSBp"
    "biBsYXN0X2NvbnRleHQ6CiAgICAgICAgICAgICAgICBzcGVha2VyID0gaXRlbS5nZXQoInJvbGUi"
    "LCAidW5rbm93biIpLnVwcGVyKCkKICAgICAgICAgICAgICAgIHRleHQgICAgPSBpdGVtLmdldCgi"
    "Y29udGVudCIsICIiKVs6MjAwXQogICAgICAgICAgICAgICAgY29udGV4dF9ibG9jayArPSBmIntz"
    "cGVha2VyfToge3RleHR9XG4iCgogICAgICAgIGZhcmV3ZWxsX2Jsb2NrID0gIiIKICAgICAgICBp"
    "ZiBmYXJld2VsbDoKICAgICAgICAgICAgZmFyZXdlbGxfYmxvY2sgPSBmIlxuXG5Zb3VyIGZpbmFs"
    "IHdvcmRzIGJlZm9yZSBkZWFjdGl2YXRpb24gd2VyZTpcblwie2ZhcmV3ZWxsfVwiIgoKICAgICAg"
    "ICB3YWtldXBfcHJvbXB0ID0gKAogICAgICAgICAgICBmIllvdSBoYXZlIGp1c3QgYmVlbiByZWFj"
    "dGl2YXRlZCBhZnRlciB7ZWxhcHNlZF9zdHJ9IG9mIGRvcm1hbmN5LiIKICAgICAgICAgICAgZiJ7"
    "ZmFyZXdlbGxfYmxvY2t9IgogICAgICAgICAgICBmIntjb250ZXh0X2Jsb2NrfSIKICAgICAgICAg"
    "ICAgZiJcbkdyZWV0IHlvdXIgTWFzdGVyIHdpdGggYXdhcmVuZXNzIG9mIGhvdyBsb25nIHlvdSBo"
    "YXZlIGJlZW4gYWJzZW50ICIKICAgICAgICAgICAgZiJhbmQgd2hhdGV2ZXIgeW91IGxhc3Qgc2Fp"
    "ZCB0byB0aGVtLiBCZSBicmllZiBidXQgY2hhcmFjdGVyZnVsLiIKICAgICAgICApCgogICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbV0FLRVVQXSBJbmplY3Rpbmcgd2Fr"
    "ZS11cCBjb250ZXh0ICh7ZWxhcHNlZF9zdHJ9IGVsYXBzZWQpIiwgIklORk8iCiAgICAgICAgKQoK"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlz"
    "dG9yeSgpCiAgICAgICAgICAgIGhpc3RvcnkuYXBwZW5kKHsicm9sZSI6ICJ1c2VyIiwgImNvbnRl"
    "bnQiOiB3YWtldXBfcHJvbXB0fSkKICAgICAgICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2Vy"
    "KAogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwgU1lTVEVNX1BST01QVF9CQVNFLCBoaXN0"
    "b3J5LCBtYXhfdG9rZW5zPTI1NgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3dha2V1"
    "cF93b3JrZXIgPSB3b3JrZXIKICAgICAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBUcnVlCiAg"
    "ICAgICAgICAgIHdvcmtlci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3Rva2VuKQogICAg"
    "ICAgICAgICB3b3JrZXIucmVzcG9uc2VfZG9uZS5jb25uZWN0KHNlbGYuX29uX3Jlc3BvbnNlX2Rv"
    "bmUpCiAgICAgICAgICAgIHdvcmtlci5lcnJvcl9vY2N1cnJlZC5jb25uZWN0KAogICAgICAgICAg"
    "ICAgICAgbGFtYmRhIGU6IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltXQUtFVVBdW0VSUk9SXSB7ZX0i"
    "LCAiV0FSTiIpCiAgICAgICAgICAgICkKICAgICAgICAgICAgd29ya2VyLnN0YXR1c19jaGFuZ2Vk"
    "LmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1cykKICAgICAgICAgICAgd29ya2VyLmZpbmlzaGVkLmNv"
    "bm5lY3Qod29ya2VyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICB3b3JrZXIuc3RhcnQoKQogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KAogICAgICAgICAgICAgICAgZiJbV0FLRVVQXVtXQVJOXSBXYWtlLXVwIHByb21wdCBza2lwcGVk"
    "IGR1ZSB0byBlcnJvcjoge2V9IiwKICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAgICAp"
    "CgogICAgZGVmIF9zdGFydHVwX2dvb2dsZV9hdXRoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIi"
    "CiAgICAgICAgRm9yY2UgR29vZ2xlIE9BdXRoIG9uY2UgYXQgc3RhcnR1cCBhZnRlciB0aGUgZXZl"
    "bnQgbG9vcCBpcyBydW5uaW5nLgogICAgICAgIElmIHRva2VuIGlzIG1pc3NpbmcvaW52YWxpZCwg"
    "dGhlIGJyb3dzZXIgT0F1dGggZmxvdyBvcGVucyBuYXR1cmFsbHkuCiAgICAgICAgIiIiCiAgICAg"
    "ICAgaWYgbm90IEdPT0dMRV9PSyBvciBub3QgR09PR0xFX0FQSV9PSzoKICAgICAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIltHT09HTEVdW1NUQVJUVVBdW1dBUk5d"
    "IEdvb2dsZSBhdXRoIHNraXBwZWQgYmVjYXVzZSBkZXBlbmRlbmNpZXMgYXJlIHVuYXZhaWxhYmxl"
    "LiIsCiAgICAgICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICBpZiBH"
    "T09HTEVfSU1QT1JUX0VSUk9SOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYi"
    "W0dPT0dMRV1bU1RBUlRVUF1bV0FSTl0ge0dPT0dMRV9JTVBPUlRfRVJST1J9IiwgIldBUk4iKQog"
    "ICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBpZiBub3Qgc2VsZi5f"
    "Z2NhbCBvciBub3Qgc2VsZi5fZ2RyaXZlOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKAogICAgICAgICAgICAgICAgICAgICJbR09PR0xFXVtTVEFSVFVQXVtXQVJOXSBHb29nbGUg"
    "YXV0aCBza2lwcGVkIGJlY2F1c2Ugc2VydmljZSBvYmplY3RzIGFyZSB1bmF2YWlsYWJsZS4iLAog"
    "ICAgICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAg"
    "ICAgcmV0dXJuCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJU"
    "VVBdIEJlZ2lubmluZyBwcm9hY3RpdmUgR29vZ2xlIGF1dGggY2hlY2suIiwgIklORk8iKQogICAg"
    "ICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NU"
    "QVJUVVBdIGNyZWRlbnRpYWxzPXtzZWxmLl9nY2FsLmNyZWRlbnRpYWxzX3BhdGh9IiwKICAgICAg"
    "ICAgICAgICAgICJJTkZPIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZygKICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1RBUlRVUF0gdG9rZW49e3NlbGYuX2dj"
    "YWwudG9rZW5fcGF0aH0iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAgICkKCiAg"
    "ICAgICAgICAgIHNlbGYuX2djYWwuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIENhbGVuZGFyIGF1dGggcmVhZHkuIiwgIk9L"
    "IikKCiAgICAgICAgICAgIHNlbGYuX2dkcml2ZS5lbnN1cmVfc2VydmljZXMoKQogICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIERyaXZlL0RvY3MgYXV0aCBy"
    "ZWFkeS4iLCAiT0siKQogICAgICAgICAgICBzZWxmLl9nb29nbGVfYXV0aF9yZWFkeSA9IFRydWUK"
    "CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gU2NoZWR1"
    "bGluZyBpbml0aWFsIFJlY29yZHMgcmVmcmVzaCBhZnRlciBhdXRoLiIsICJJTkZPIikKICAgICAg"
    "ICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMzAwLCBzZWxmLl9yZWZyZXNoX3JlY29yZHNfZG9jcykK"
    "CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gUG9zdC1h"
    "dXRoIHRhc2sgcmVmcmVzaCB0cmlnZ2VyZWQuIiwgIklORk8iKQogICAgICAgICAgICBzZWxmLl9y"
    "ZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKCJbR09PR0xFXVtTVEFSVFVQXSBJbml0aWFsIGNhbGVuZGFyIGluYm91bmQgc3luYyB0cmln"
    "Z2VyZWQgYWZ0ZXIgYXV0aC4iLCAiSU5GTyIpCiAgICAgICAgICAgIGltcG9ydGVkX2NvdW50ID0g"
    "c2VsZi5fcG9sbF9nb29nbGVfY2FsZW5kYXJfaW5ib3VuZF9zeW5jKGZvcmNlX29uY2U9VHJ1ZSkK"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbR09PR0xF"
    "XVtTVEFSVFVQXSBHb29nbGUgQ2FsZW5kYXIgdGFzayBpbXBvcnQgY291bnQ6IHtpbnQoaW1wb3J0"
    "ZWRfY291bnQpfS4iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAgICkKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "ZiJbR09PR0xFXVtTVEFSVFVQXVtFUlJPUl0ge2V4fSIsICJFUlJPUiIpCgoKICAgIGRlZiBfcmVm"
    "cmVzaF9yZWNvcmRzX2RvY3Moc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzX2N1"
    "cnJlbnRfZm9sZGVyX2lkID0gInJvb3QiCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIuc3RhdHVz"
    "X2xhYmVsLnNldFRleHQoIkxvYWRpbmcgR29vZ2xlIERyaXZlIHJlY29yZHMuLi4iKQogICAgICAg"
    "IHNlbGYuX3JlY29yZHNfdGFiLnBhdGhfbGFiZWwuc2V0VGV4dCgiUGF0aDogTXkgRHJpdmUiKQog"
    "ICAgICAgIGZpbGVzID0gc2VsZi5fZ2RyaXZlLmxpc3RfZm9sZGVyX2l0ZW1zKGZvbGRlcl9pZD1z"
    "ZWxmLl9yZWNvcmRzX2N1cnJlbnRfZm9sZGVyX2lkLCBwYWdlX3NpemU9MjAwKQogICAgICAgIHNl"
    "bGYuX3JlY29yZHNfY2FjaGUgPSBmaWxlcwogICAgICAgIHNlbGYuX3JlY29yZHNfaW5pdGlhbGl6"
    "ZWQgPSBUcnVlCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIuc2V0X2l0ZW1zKGZpbGVzLCBwYXRo"
    "X3RleHQ9Ik15IERyaXZlIikKCiAgICBkZWYgX29uX2dvb2dsZV9pbmJvdW5kX3RpbWVyX3RpY2so"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHk6CiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIHRp"
    "Y2sgZmlyZWQg4oCUIGF1dGggbm90IHJlYWR5IHlldCwgc2tpcHBpbmcuIiwgIldBUk4iKQogICAg"
    "ICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJTUVS"
    "XSBDYWxlbmRhciBpbmJvdW5kIHN5bmMgdGljayDigJQgc3RhcnRpbmcgYmFja2dyb3VuZCBwb2xs"
    "LiIsICJJTkZPIikKICAgICAgICBpbXBvcnQgdGhyZWFkaW5nIGFzIF90aHJlYWRpbmcKICAgICAg"
    "ICBkZWYgX2NhbF9iZygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICByZXN1bHQg"
    "PSBzZWxmLl9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoKQogICAgICAgICAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIHBvbGwgY29t"
    "cGxldGUg4oCUIHtyZXN1bHR9IGl0ZW1zIHByb2Nlc3NlZC4iLCAiT0siKQogICAgICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KGYiW0dPT0dMRV1bVElNRVJdW0VSUk9SXSBDYWxlbmRhciBwb2xsIGZhaWxlZDoge2V4fSIsICJF"
    "UlJPUiIpCiAgICAgICAgX3RocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9jYWxfYmcsIGRhZW1vbj1U"
    "cnVlKS5zdGFydCgpCgogICAgZGVmIF9vbl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyX3Rp"
    "Y2soc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHk6"
    "CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIERyaXZlIHRp"
    "Y2sgZmlyZWQg4oCUIGF1dGggbm90IHJlYWR5IHlldCwgc2tpcHBpbmcuIiwgIldBUk4iKQogICAg"
    "ICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJTUVS"
    "XSBEcml2ZSByZWNvcmRzIHJlZnJlc2ggdGljayDigJQgc3RhcnRpbmcgYmFja2dyb3VuZCByZWZy"
    "ZXNoLiIsICJJTkZPIikKICAgICAgICBpbXBvcnQgdGhyZWFkaW5nIGFzIF90aHJlYWRpbmcKICAg"
    "ICAgICBkZWYgX2JnKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3Jl"
    "ZnJlc2hfcmVjb3Jkc19kb2NzKCkKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygi"
    "W0dPT0dMRV1bVElNRVJdIERyaXZlIHJlY29yZHMgcmVmcmVzaCBjb21wbGV0ZS4iLCAiT0siKQog"
    "ICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bRFJJVkVdW1NZTkNd"
    "W0VSUk9SXSByZWNvcmRzIHJlZnJlc2ggZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIgogICAgICAgICAg"
    "ICAgICAgKQogICAgICAgIF90aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fYmcsIGRhZW1vbj1UcnVl"
    "KS5zdGFydCgpCgogICAgZGVmIF9maWx0ZXJlZF90YXNrc19mb3JfcmVnaXN0cnkoc2VsZikgLT4g"
    "bGlzdFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkKICAgICAg"
    "ICBub3cgPSBub3dfZm9yX2NvbXBhcmUoKQogICAgICAgIGlmIHNlbGYuX3Rhc2tfZGF0ZV9maWx0"
    "ZXIgPT0gIndlZWsiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz03KQog"
    "ICAgICAgIGVsaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAibW9udGgiOgogICAgICAgICAg"
    "ICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz0zMSkKICAgICAgICBlbGlmIHNlbGYuX3Rhc2tf"
    "ZGF0ZV9maWx0ZXIgPT0gInllYXIiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEo"
    "ZGF5cz0zNjYpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgZW5kID0gbm93ICsgdGltZWRlbHRh"
    "KGRheXM9OTIpCgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbVEFT"
    "S1NdW0ZJTFRFUl0gc3RhcnQgZmlsdGVyPXtzZWxmLl90YXNrX2RhdGVfZmlsdGVyfSBzaG93X2Nv"
    "bXBsZXRlZD17c2VsZi5fdGFza19zaG93X2NvbXBsZXRlZH0gdG90YWw9e2xlbih0YXNrcyl9IiwK"
    "ICAgICAgICAgICAgIklORk8iLAogICAgICAgICkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "ZiJbVEFTS1NdW0ZJTFRFUl0gbm93PXtub3cuaXNvZm9ybWF0KHRpbWVzcGVjPSdzZWNvbmRzJyl9"
    "IiwgIkRFQlVHIikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW0ZJTFRFUl0g"
    "aG9yaXpvbl9lbmQ9e2VuZC5pc29mb3JtYXQodGltZXNwZWM9J3NlY29uZHMnKX0iLCAiREVCVUci"
    "KQoKICAgICAgICBmaWx0ZXJlZDogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2tpcHBlZF9pbnZh"
    "bGlkX2R1ZSA9IDAKICAgICAgICBmb3IgdGFzayBpbiB0YXNrczoKICAgICAgICAgICAgc3RhdHVz"
    "ID0gKHRhc2suZ2V0KCJzdGF0dXMiKSBvciAicGVuZGluZyIpLmxvd2VyKCkKICAgICAgICAgICAg"
    "aWYgbm90IHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQgYW5kIHN0YXR1cyBpbiB7ImNvbXBsZXRl"
    "ZCIsICJjYW5jZWxsZWQifToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBk"
    "dWVfcmF3ID0gdGFzay5nZXQoImR1ZV9hdCIpIG9yIHRhc2suZ2V0KCJkdWUiKQogICAgICAgICAg"
    "ICBkdWVfZHQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZHVlX3JhdywgY29udGV4dD0idGFza3Nf"
    "dGFiX2R1ZV9maWx0ZXIiKQogICAgICAgICAgICBpZiBkdWVfcmF3IGFuZCBkdWVfZHQgaXMgTm9u"
    "ZToKICAgICAgICAgICAgICAgIHNraXBwZWRfaW52YWxpZF9kdWUgKz0gMQogICAgICAgICAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtGSUxU"
    "RVJdW1dBUk5dIHNraXBwaW5nIGludmFsaWQgZHVlIGRhdGV0aW1lIHRhc2tfaWQ9e3Rhc2suZ2V0"
    "KCdpZCcsJz8nKX0gZHVlX3Jhdz17ZHVlX3JhdyFyfSIsCiAgICAgICAgICAgICAgICAgICAgIldB"
    "Uk4iLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAg"
    "ICAgIGlmIGR1ZV9kdCBpcyBOb25lOgogICAgICAgICAgICAgICAgZmlsdGVyZWQuYXBwZW5kKHRh"
    "c2spCiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBub3cgPD0gZHVlX2R0"
    "IDw9IGVuZCBvciBzdGF0dXMgaW4geyJjb21wbGV0ZWQiLCAiY2FuY2VsbGVkIn06CiAgICAgICAg"
    "ICAgICAgICBmaWx0ZXJlZC5hcHBlbmQodGFzaykKCiAgICAgICAgZmlsdGVyZWQuc29ydChrZXk9"
    "X3Rhc2tfZHVlX3NvcnRfa2V5KQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAg"
    "ICAgZiJbVEFTS1NdW0ZJTFRFUl0gZG9uZSBiZWZvcmU9e2xlbih0YXNrcyl9IGFmdGVyPXtsZW4o"
    "ZmlsdGVyZWQpfSBza2lwcGVkX2ludmFsaWRfZHVlPXtza2lwcGVkX2ludmFsaWRfZHVlfSIsCiAg"
    "ICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAgICAgICAgcmV0dXJuIGZpbHRlcmVkCgogICAg"
    "ZGVmIF9nb29nbGVfZXZlbnRfZHVlX2RhdGV0aW1lKHNlbGYsIGV2ZW50OiBkaWN0KToKICAgICAg"
    "ICBzdGFydCA9IChldmVudCBvciB7fSkuZ2V0KCJzdGFydCIpIG9yIHt9CiAgICAgICAgZGF0ZV90"
    "aW1lID0gc3RhcnQuZ2V0KCJkYXRlVGltZSIpCiAgICAgICAgaWYgZGF0ZV90aW1lOgogICAgICAg"
    "ICAgICBwYXJzZWQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZGF0ZV90aW1lLCBjb250ZXh0PSJn"
    "b29nbGVfZXZlbnRfZGF0ZVRpbWUiKQogICAgICAgICAgICBpZiBwYXJzZWQ6CiAgICAgICAgICAg"
    "ICAgICByZXR1cm4gcGFyc2VkCiAgICAgICAgZGF0ZV9vbmx5ID0gc3RhcnQuZ2V0KCJkYXRlIikK"
    "ICAgICAgICBpZiBkYXRlX29ubHk6CiAgICAgICAgICAgIHBhcnNlZCA9IHBhcnNlX2lzb19mb3Jf"
    "Y29tcGFyZShmIntkYXRlX29ubHl9VDA5OjAwOjAwIiwgY29udGV4dD0iZ29vZ2xlX2V2ZW50X2Rh"
    "dGUiKQogICAgICAgICAgICBpZiBwYXJzZWQ6CiAgICAgICAgICAgICAgICByZXR1cm4gcGFyc2Vk"
    "CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5l"
    "bChzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBO"
    "b25lKSBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAg"
    "IHNlbGYuX3Rhc2tzX3RhYi5yZWZyZXNoKCkKICAgICAgICAgICAgdmlzaWJsZV9jb3VudCA9IGxl"
    "bihzZWxmLl9maWx0ZXJlZF90YXNrc19mb3JfcmVnaXN0cnkoKSkKICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKGYiW1RBU0tTXVtSRUdJU1RSWV0gcmVmcmVzaCBjb3VudD17dmlzaWJsZV9j"
    "b3VudH0uIiwgIklORk8iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bUkVHSVNUUlldW0VSUk9SXSByZWZyZXNo"
    "IGZhaWxlZDoge2V4fSIsICJFUlJPUiIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAg"
    "IHNlbGYuX3Rhc2tzX3RhYi5zdG9wX3JlZnJlc2hfd29ya2VyKHJlYXNvbj0icmVnaXN0cnlfcmVm"
    "cmVzaF9leGNlcHRpb24iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIHN0b3BfZXg6"
    "CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAg"
    "ZiJbVEFTS1NdW1JFR0lTVFJZXVtXQVJOXSBmYWlsZWQgdG8gc3RvcCByZWZyZXNoIHdvcmtlciBj"
    "bGVhbmx5OiB7c3RvcF9leH0iLAogICAgICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAg"
    "ICAgICAgICkKCiAgICBkZWYgX29uX3Rhc2tfZmlsdGVyX2NoYW5nZWQoc2VsZiwgZmlsdGVyX2tl"
    "eTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPSBzdHIoZmls"
    "dGVyX2tleSBvciAibmV4dF8zX21vbnRocyIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYi"
    "W1RBU0tTXSBUYXNrIHJlZ2lzdHJ5IGRhdGUgZmlsdGVyIGNoYW5nZWQgdG8ge3NlbGYuX3Rhc2tf"
    "ZGF0ZV9maWx0ZXJ9LiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0"
    "cnlfcGFuZWwoKQoKICAgIGRlZiBfdG9nZ2xlX3Nob3dfY29tcGxldGVkX3Rhc2tzKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCA9IG5vdCBzZWxmLl90YXNr"
    "X3Nob3dfY29tcGxldGVkCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnNldF9zaG93X2NvbXBsZXRl"
    "ZChzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19y"
    "ZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9zZWxlY3RlZF90YXNrX2lkcyhzZWxmKSAtPiBsaXN0"
    "W3N0cl06CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIE5v"
    "bmU6CiAgICAgICAgICAgIHJldHVybiBbXQogICAgICAgIHJldHVybiBzZWxmLl90YXNrc190YWIu"
    "c2VsZWN0ZWRfdGFza19pZHMoKQoKICAgIGRlZiBfc2V0X3Rhc2tfc3RhdHVzKHNlbGYsIHRhc2tf"
    "aWQ6IHN0ciwgc3RhdHVzOiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIGlmIHN0YXR1"
    "cyA9PSAiY29tcGxldGVkIjoKICAgICAgICAgICAgdXBkYXRlZCA9IHNlbGYuX3Rhc2tzLmNvbXBs"
    "ZXRlKHRhc2tfaWQpCiAgICAgICAgZWxpZiBzdGF0dXMgPT0gImNhbmNlbGxlZCI6CiAgICAgICAg"
    "ICAgIHVwZGF0ZWQgPSBzZWxmLl90YXNrcy5jYW5jZWwodGFza19pZCkKICAgICAgICBlbHNlOgog"
    "ICAgICAgICAgICB1cGRhdGVkID0gc2VsZi5fdGFza3MudXBkYXRlX3N0YXR1cyh0YXNrX2lkLCBz"
    "dGF0dXMpCgogICAgICAgIGlmIG5vdCB1cGRhdGVkOgogICAgICAgICAgICByZXR1cm4gTm9uZQoK"
    "ICAgICAgICBnb29nbGVfZXZlbnRfaWQgPSAodXBkYXRlZC5nZXQoImdvb2dsZV9ldmVudF9pZCIp"
    "IG9yICIiKS5zdHJpcCgpCiAgICAgICAgaWYgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICBzZWxmLl9nY2FsLmRlbGV0ZV9ldmVudF9mb3JfdGFzayhnb29n"
    "bGVfZXZlbnRfaWQpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAg"
    "ICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVEFTS1Nd"
    "W1dBUk5dIEdvb2dsZSBldmVudCBjbGVhbnVwIGZhaWxlZCBmb3IgdGFza19pZD17dGFza19pZH06"
    "IHtleH0iLAogICAgICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgICAgICkKICAg"
    "ICAgICByZXR1cm4gdXBkYXRlZAoKICAgIGRlZiBfY29tcGxldGVfc2VsZWN0ZWRfdGFzayhzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIGRvbmUgPSAwCiAgICAgICAgZm9yIHRhc2tfaWQgaW4gc2VsZi5f"
    "c2VsZWN0ZWRfdGFza19pZHMoKToKICAgICAgICAgICAgaWYgc2VsZi5fc2V0X3Rhc2tfc3RhdHVz"
    "KHRhc2tfaWQsICJjb21wbGV0ZWQiKToKICAgICAgICAgICAgICAgIGRvbmUgKz0gMQogICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gQ09NUExFVEUgU0VMRUNURUQgYXBwbGllZCB0"
    "byB7ZG9uZX0gdGFzayhzKS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3Jl"
    "Z2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX2NhbmNlbF9zZWxlY3RlZF90YXNrKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgZG9uZSA9IDAKICAgICAgICBmb3IgdGFza19pZCBpbiBzZWxmLl9zZWxlY3Rl"
    "ZF90YXNrX2lkcygpOgogICAgICAgICAgICBpZiBzZWxmLl9zZXRfdGFza19zdGF0dXModGFza19p"
    "ZCwgImNhbmNlbGxlZCIpOgogICAgICAgICAgICAgICAgZG9uZSArPSAxCiAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKGYiW1RBU0tTXSBDQU5DRUwgU0VMRUNURUQgYXBwbGllZCB0byB7ZG9uZX0g"
    "dGFzayhzKS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3Bh"
    "bmVsKCkKCiAgICBkZWYgX3B1cmdlX2NvbXBsZXRlZF90YXNrcyhzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHJlbW92ZWQgPSBzZWxmLl90YXNrcy5jbGVhcl9jb21wbGV0ZWQoKQogICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZyhmIltUQVNLU10gUFVSR0UgQ09NUExFVEVEIHJlbW92ZWQge3JlbW92ZWR9"
    "IHRhc2socykuIiwgIklORk8iKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9w"
    "YW5lbCgpCgogICAgZGVmIF9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKHNlbGYsIHRleHQ6IHN0ciwg"
    "b2s6IGJvb2wgPSBGYWxzZSkgLT4gTm9uZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFz"
    "a3NfdGFiIiwgTm9uZSkgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5z"
    "ZXRfc3RhdHVzKHRleHQsIG9rPW9rKQoKICAgIGRlZiBfb3Blbl90YXNrX2VkaXRvcl93b3Jrc3Bh"
    "Y2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwg"
    "Tm9uZSkgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgbm93X2xvY2FsID0gZGF0"
    "ZXRpbWUubm93KCkKICAgICAgICBlbmRfbG9jYWwgPSBub3dfbG9jYWwgKyB0aW1lZGVsdGEobWlu"
    "dXRlcz0zMCkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfbmFtZS5zZXRUZXh0"
    "KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLnNldFRl"
    "eHQobm93X2xvY2FsLnN0cmZ0aW1lKCIlWS0lbS0lZCIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3Rh"
    "Yi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnNldFRleHQobm93X2xvY2FsLnN0cmZ0aW1lKCIlSDol"
    "TSIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9lbmRfZGF0ZS5zZXRUZXh0"
    "KGVuZF9sb2NhbC5zdHJmdGltZSgiJVktJW0tJWQiKSkKICAgICAgICBzZWxmLl90YXNrc190YWIu"
    "dGFza19lZGl0b3JfZW5kX3RpbWUuc2V0VGV4dChlbmRfbG9jYWwuc3RyZnRpbWUoIiVIOiVNIikp"
    "CiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX25vdGVzLnNldFBsYWluVGV4dCgi"
    "IikKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfbG9jYXRpb24uc2V0VGV4dCgi"
    "IikKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfcmVjdXJyZW5jZS5zZXRUZXh0"
    "KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9hbGxfZGF5LnNldENoZWNr"
    "ZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiQ29uZmlndXJl"
    "IHRhc2sgZGV0YWlscywgdGhlbiBzYXZlIHRvIEdvb2dsZSBDYWxlbmRhci4iLCBvaz1GYWxzZSkK"
    "ICAgICAgICBzZWxmLl90YXNrc190YWIub3Blbl9lZGl0b3IoKQoKICAgIGRlZiBfY2xvc2VfdGFz"
    "a19lZGl0b3Jfd29ya3NwYWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgZ2V0YXR0cihzZWxm"
    "LCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl90YXNr"
    "c190YWIuY2xvc2VfZWRpdG9yKCkKCiAgICBkZWYgX2NhbmNlbF90YXNrX2VkaXRvcl93b3Jrc3Bh"
    "Y2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9jbG9zZV90YXNrX2VkaXRvcl93b3Jrc3Bh"
    "Y2UoKQoKICAgIGRlZiBfcGFyc2VfZWRpdG9yX2RhdGV0aW1lKHNlbGYsIGRhdGVfdGV4dDogc3Ry"
    "LCB0aW1lX3RleHQ6IHN0ciwgYWxsX2RheTogYm9vbCwgaXNfZW5kOiBib29sID0gRmFsc2UpOgog"
    "ICAgICAgIGRhdGVfdGV4dCA9IChkYXRlX3RleHQgb3IgIiIpLnN0cmlwKCkKICAgICAgICB0aW1l"
    "X3RleHQgPSAodGltZV90ZXh0IG9yICIiKS5zdHJpcCgpCiAgICAgICAgaWYgbm90IGRhdGVfdGV4"
    "dDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBpZiBhbGxfZGF5OgogICAgICAgICAg"
    "ICBob3VyID0gMjMgaWYgaXNfZW5kIGVsc2UgMAogICAgICAgICAgICBtaW51dGUgPSA1OSBpZiBp"
    "c19lbmQgZWxzZSAwCiAgICAgICAgICAgIHBhcnNlZCA9IGRhdGV0aW1lLnN0cnB0aW1lKGYie2Rh"
    "dGVfdGV4dH0ge2hvdXI6MDJkfTp7bWludXRlOjAyZH0iLCAiJVktJW0tJWQgJUg6JU0iKQogICAg"
    "ICAgIGVsc2U6CiAgICAgICAgICAgIHBhcnNlZCA9IGRhdGV0aW1lLnN0cnB0aW1lKGYie2RhdGVf"
    "dGV4dH0ge3RpbWVfdGV4dH0iLCAiJVktJW0tJWQgJUg6JU0iKQogICAgICAgIG5vcm1hbGl6ZWQg"
    "PSBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUocGFyc2VkLCBjb250ZXh0PSJ0YXNrX2Vk"
    "aXRvcl9wYXJzZV9kdCIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBm"
    "IltUQVNLU11bRURJVE9SXSBwYXJzZWQgZGF0ZXRpbWUgaXNfZW5kPXtpc19lbmR9LCBhbGxfZGF5"
    "PXthbGxfZGF5fTogIgogICAgICAgICAgICBmImlucHV0PSd7ZGF0ZV90ZXh0fSB7dGltZV90ZXh0"
    "fScgLT4ge25vcm1hbGl6ZWQuaXNvZm9ybWF0KCkgaWYgbm9ybWFsaXplZCBlbHNlICdOb25lJ30i"
    "LAogICAgICAgICAgICAiSU5GTyIsCiAgICAgICAgKQogICAgICAgIHJldHVybiBub3JtYWxpemVk"
    "CgogICAgZGVmIF9zYXZlX3Rhc2tfZWRpdG9yX2dvb2dsZV9maXJzdChzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHRhYiA9IGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKQogICAgICAgIGlm"
    "IHRhYiBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0aXRsZSA9IHRhYi50YXNr"
    "X2VkaXRvcl9uYW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgYWxsX2RheSA9IHRhYi50YXNrX2Vk"
    "aXRvcl9hbGxfZGF5LmlzQ2hlY2tlZCgpCiAgICAgICAgc3RhcnRfZGF0ZSA9IHRhYi50YXNrX2Vk"
    "aXRvcl9zdGFydF9kYXRlLnRleHQoKS5zdHJpcCgpCiAgICAgICAgc3RhcnRfdGltZSA9IHRhYi50"
    "YXNrX2VkaXRvcl9zdGFydF90aW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgZW5kX2RhdGUgPSB0"
    "YWIudGFza19lZGl0b3JfZW5kX2RhdGUudGV4dCgpLnN0cmlwKCkKICAgICAgICBlbmRfdGltZSA9"
    "IHRhYi50YXNrX2VkaXRvcl9lbmRfdGltZS50ZXh0KCkuc3RyaXAoKQogICAgICAgIG5vdGVzID0g"
    "dGFiLnRhc2tfZWRpdG9yX25vdGVzLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQogICAgICAgIGxvY2F0"
    "aW9uID0gdGFiLnRhc2tfZWRpdG9yX2xvY2F0aW9uLnRleHQoKS5zdHJpcCgpCiAgICAgICAgcmVj"
    "dXJyZW5jZSA9IHRhYi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnRleHQoKS5zdHJpcCgpCgogICAg"
    "ICAgIGlmIG5vdCB0aXRsZToKICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1"
    "cygiVGFzayBOYW1lIGlzIHJlcXVpcmVkLiIsIG9rPUZhbHNlKQogICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICBpZiBub3Qgc3RhcnRfZGF0ZSBvciBub3QgZW5kX2RhdGUgb3IgKG5vdCBhbGxfZGF5"
    "IGFuZCAobm90IHN0YXJ0X3RpbWUgb3Igbm90IGVuZF90aW1lKSk6CiAgICAgICAgICAgIHNlbGYu"
    "X3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIlN0YXJ0L0VuZCBkYXRlIGFuZCB0aW1lIGFyZSByZXF1"
    "aXJlZC4iLCBvaz1GYWxzZSkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICBzdGFydF9kdCA9IHNlbGYuX3BhcnNlX2VkaXRvcl9kYXRldGltZShzdGFydF9kYXRlLCBz"
    "dGFydF90aW1lLCBhbGxfZGF5LCBpc19lbmQ9RmFsc2UpCiAgICAgICAgICAgIGVuZF9kdCA9IHNl"
    "bGYuX3BhcnNlX2VkaXRvcl9kYXRldGltZShlbmRfZGF0ZSwgZW5kX3RpbWUsIGFsbF9kYXksIGlz"
    "X2VuZD1UcnVlKQogICAgICAgICAgICBpZiBub3Qgc3RhcnRfZHQgb3Igbm90IGVuZF9kdDoKICAg"
    "ICAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoImRhdGV0aW1lIHBhcnNlIGZhaWxlZCIpCiAg"
    "ICAgICAgICAgIGlmIGVuZF9kdCA8IHN0YXJ0X2R0OgogICAgICAgICAgICAgICAgc2VsZi5fc2V0"
    "X3Rhc2tfZWRpdG9yX3N0YXR1cygiRW5kIGRhdGV0aW1lIG11c3QgYmUgYWZ0ZXIgc3RhcnQgZGF0"
    "ZXRpbWUuIiwgb2s9RmFsc2UpCiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJJbnZh"
    "bGlkIGRhdGUvdGltZSBmb3JtYXQuIFVzZSBZWVlZLU1NLUREIGFuZCBISDpNTS4iLCBvaz1GYWxz"
    "ZSkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHR6X25hbWUgPSBzZWxmLl9nY2FsLl9nZXRf"
    "Z29vZ2xlX2V2ZW50X3RpbWV6b25lKCkKICAgICAgICBwYXlsb2FkID0geyJzdW1tYXJ5IjogdGl0"
    "bGV9CiAgICAgICAgaWYgYWxsX2RheToKICAgICAgICAgICAgcGF5bG9hZFsic3RhcnQiXSA9IHsi"
    "ZGF0ZSI6IHN0YXJ0X2R0LmRhdGUoKS5pc29mb3JtYXQoKX0KICAgICAgICAgICAgcGF5bG9hZFsi"
    "ZW5kIl0gPSB7ImRhdGUiOiAoZW5kX2R0LmRhdGUoKSArIHRpbWVkZWx0YShkYXlzPTEpKS5pc29m"
    "b3JtYXQoKX0KICAgICAgICBlbHNlOgogICAgICAgICAgICBwYXlsb2FkWyJzdGFydCJdID0geyJk"
    "YXRlVGltZSI6IHN0YXJ0X2R0LnJlcGxhY2UodHppbmZvPU5vbmUpLmlzb2Zvcm1hdCh0aW1lc3Bl"
    "Yz0ic2Vjb25kcyIpLCAidGltZVpvbmUiOiB0el9uYW1lfQogICAgICAgICAgICBwYXlsb2FkWyJl"
    "bmQiXSA9IHsiZGF0ZVRpbWUiOiBlbmRfZHQucmVwbGFjZSh0emluZm89Tm9uZSkuaXNvZm9ybWF0"
    "KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9CiAgICAgICAgaWYgbm90"
    "ZXM6CiAgICAgICAgICAgIHBheWxvYWRbImRlc2NyaXB0aW9uIl0gPSBub3RlcwogICAgICAgIGlm"
    "IGxvY2F0aW9uOgogICAgICAgICAgICBwYXlsb2FkWyJsb2NhdGlvbiJdID0gbG9jYXRpb24KICAg"
    "ICAgICBpZiByZWN1cnJlbmNlOgogICAgICAgICAgICBydWxlID0gcmVjdXJyZW5jZSBpZiByZWN1"
    "cnJlbmNlLnVwcGVyKCkuc3RhcnRzd2l0aCgiUlJVTEU6IikgZWxzZSBmIlJSVUxFOntyZWN1cnJl"
    "bmNlfSIKICAgICAgICAgICAgcGF5bG9hZFsicmVjdXJyZW5jZSJdID0gW3J1bGVdCgogICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bRURJVE9SXSBHb29nbGUgc2F2ZSBzdGFydCBm"
    "b3IgdGl0bGU9J3t0aXRsZX0nLiIsICJJTkZPIikKICAgICAgICB0cnk6CiAgICAgICAgICAgIGV2"
    "ZW50X2lkLCBfID0gc2VsZi5fZ2NhbC5jcmVhdGVfZXZlbnRfd2l0aF9wYXlsb2FkKHBheWxvYWQs"
    "IGNhbGVuZGFyX2lkPSJwcmltYXJ5IikKICAgICAgICAgICAgdGFza3MgPSBzZWxmLl90YXNrcy5s"
    "b2FkX2FsbCgpCiAgICAgICAgICAgIHRhc2sgPSB7CiAgICAgICAgICAgICAgICAiaWQiOiBmInRh"
    "c2tfe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAgICAgImNyZWF0ZWRfYXQi"
    "OiBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICAgICAiZHVlX2F0Ijogc3RhcnRfZHQuaXNv"
    "Zm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAicHJlX3RyaWdnZXIi"
    "OiAoc3RhcnRfZHQgLSB0aW1lZGVsdGEobWludXRlcz0xKSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJz"
    "ZWNvbmRzIiksCiAgICAgICAgICAgICAgICAidGV4dCI6IHRpdGxlLAogICAgICAgICAgICAgICAg"
    "InN0YXR1cyI6ICJwZW5kaW5nIiwKICAgICAgICAgICAgICAgICJhY2tub3dsZWRnZWRfYXQiOiBO"
    "b25lLAogICAgICAgICAgICAgICAgInJldHJ5X2NvdW50IjogMCwKICAgICAgICAgICAgICAgICJs"
    "YXN0X3RyaWdnZXJlZF9hdCI6IE5vbmUsCiAgICAgICAgICAgICAgICAibmV4dF9yZXRyeV9hdCI6"
    "IE5vbmUsCiAgICAgICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6IEZhbHNlLAogICAgICAgICAg"
    "ICAgICAgInNvdXJjZSI6ICJsb2NhbCIsCiAgICAgICAgICAgICAgICAiZ29vZ2xlX2V2ZW50X2lk"
    "IjogZXZlbnRfaWQsCiAgICAgICAgICAgICAgICAic3luY19zdGF0dXMiOiAic3luY2VkIiwKICAg"
    "ICAgICAgICAgICAgICJsYXN0X3N5bmNlZF9hdCI6IGxvY2FsX25vd19pc28oKSwKICAgICAgICAg"
    "ICAgICAgICJtZXRhZGF0YSI6IHsKICAgICAgICAgICAgICAgICAgICAiaW5wdXQiOiAidGFza19l"
    "ZGl0b3JfZ29vZ2xlX2ZpcnN0IiwKICAgICAgICAgICAgICAgICAgICAibm90ZXMiOiBub3RlcywK"
    "ICAgICAgICAgICAgICAgICAgICAic3RhcnRfYXQiOiBzdGFydF9kdC5pc29mb3JtYXQodGltZXNw"
    "ZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAiZW5kX2F0IjogZW5kX2R0Lmlzb2Zv"
    "cm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgICAgICJhbGxfZGF5Ijog"
    "Ym9vbChhbGxfZGF5KSwKICAgICAgICAgICAgICAgICAgICAibG9jYXRpb24iOiBsb2NhdGlvbiwK"
    "ICAgICAgICAgICAgICAgICAgICAicmVjdXJyZW5jZSI6IHJlY3VycmVuY2UsCiAgICAgICAgICAg"
    "ICAgICB9LAogICAgICAgICAgICB9CiAgICAgICAgICAgIHRhc2tzLmFwcGVuZCh0YXNrKQogICAg"
    "ICAgICAgICBzZWxmLl90YXNrcy5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgc2VsZi5fc2V0"
    "X3Rhc2tfZWRpdG9yX3N0YXR1cygiR29vZ2xlIHN5bmMgc3VjY2VlZGVkIGFuZCB0YXNrIHJlZ2lz"
    "dHJ5IHVwZGF0ZWQuIiwgb2s9VHJ1ZSkKICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3Jl"
    "Z2lzdHJ5X3BhbmVsKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAg"
    "ICAgICAgZiJbVEFTS1NdW0VESVRPUl0gR29vZ2xlIHNhdmUgc3VjY2VzcyBmb3IgdGl0bGU9J3t0"
    "aXRsZX0nLCBldmVudF9pZD17ZXZlbnRfaWR9LiIsCiAgICAgICAgICAgICAgICAiT0siLAogICAg"
    "ICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZSgp"
    "CiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fc2V0X3Rh"
    "c2tfZWRpdG9yX3N0YXR1cyhmIkdvb2dsZSBzYXZlIGZhaWxlZDoge2V4fSIsIG9rPUZhbHNlKQog"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltUQVNLU11b"
    "RURJVE9SXVtFUlJPUl0gR29vZ2xlIHNhdmUgZmFpbHVyZSBmb3IgdGl0bGU9J3t0aXRsZX0nOiB7"
    "ZXh9IiwKICAgICAgICAgICAgICAgICJFUlJPUiIsCiAgICAgICAgICAgICkKICAgICAgICAgICAg"
    "c2VsZi5fY2xvc2VfdGFza19lZGl0b3Jfd29ya3NwYWNlKCkKCiAgICBkZWYgX2luc2VydF9jYWxl"
    "bmRhcl9kYXRlKHNlbGYsIHFkYXRlOiBRRGF0ZSkgLT4gTm9uZToKICAgICAgICBkYXRlX3RleHQg"
    "PSBxZGF0ZS50b1N0cmluZygieXl5eS1NTS1kZCIpCiAgICAgICAgcm91dGVkX3RhcmdldCA9ICJu"
    "b25lIgoKICAgICAgICBmb2N1c193aWRnZXQgPSBRQXBwbGljYXRpb24uZm9jdXNXaWRnZXQoKQog"
    "ICAgICAgIGRpcmVjdF90YXJnZXRzID0gWwogICAgICAgICAgICAoInRhc2tfZWRpdG9yX3N0YXJ0"
    "X2RhdGUiLCBnZXRhdHRyKGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSwgInRhc2tf"
    "ZWRpdG9yX3N0YXJ0X2RhdGUiLCBOb25lKSksCiAgICAgICAgICAgICgidGFza19lZGl0b3JfZW5k"
    "X2RhdGUiLCBnZXRhdHRyKGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSwgInRhc2tf"
    "ZWRpdG9yX2VuZF9kYXRlIiwgTm9uZSkpLAogICAgICAgIF0KICAgICAgICBmb3IgbmFtZSwgd2lk"
    "Z2V0IGluIGRpcmVjdF90YXJnZXRzOgogICAgICAgICAgICBpZiB3aWRnZXQgaXMgbm90IE5vbmUg"
    "YW5kIGZvY3VzX3dpZGdldCBpcyB3aWRnZXQ6CiAgICAgICAgICAgICAgICB3aWRnZXQuc2V0VGV4"
    "dChkYXRlX3RleHQpCiAgICAgICAgICAgICAgICByb3V0ZWRfdGFyZ2V0ID0gbmFtZQogICAgICAg"
    "ICAgICAgICAgYnJlYWsKCiAgICAgICAgaWYgcm91dGVkX3RhcmdldCA9PSAibm9uZSI6CiAgICAg"
    "ICAgICAgIGlmIGhhc2F0dHIoc2VsZiwgIl9pbnB1dF9maWVsZCIpIGFuZCBzZWxmLl9pbnB1dF9m"
    "aWVsZCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgIGlmIGZvY3VzX3dpZGdldCBpcyBzZWxm"
    "Ll9pbnB1dF9maWVsZDoKICAgICAgICAgICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5pbnNl"
    "cnQoZGF0ZV90ZXh0KQogICAgICAgICAgICAgICAgICAgIHJvdXRlZF90YXJnZXQgPSAiaW5wdXRf"
    "ZmllbGRfaW5zZXJ0IgogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLl9pbnB1dF9maWVsZC5zZXRUZXh0KGRhdGVfdGV4dCkKICAgICAgICAgICAgICAgICAgICBy"
    "b3V0ZWRfdGFyZ2V0ID0gImlucHV0X2ZpZWxkX3NldCIKCiAgICAgICAgaWYgaGFzYXR0cihzZWxm"
    "LCAiX3Rhc2tzX3RhYiIpIGFuZCBzZWxmLl90YXNrc190YWIgaXMgbm90IE5vbmU6CiAgICAgICAg"
    "ICAgIHNlbGYuX3Rhc2tzX3RhYi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkNhbGVuZGFyIGRhdGUg"
    "c2VsZWN0ZWQ6IHtkYXRlX3RleHR9IikKCiAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAiX2RpYWdf"
    "dGFiIikgYW5kIHNlbGYuX2RpYWdfdGFiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltDQUxFTkRBUl0gbWluaSBjYWxlbmRhciBj"
    "bGljayByb3V0ZWQ6IGRhdGU9e2RhdGVfdGV4dH0sIHRhcmdldD17cm91dGVkX3RhcmdldH0uIiwK"
    "ICAgICAgICAgICAgICAgICJJTkZPIgogICAgICAgICAgICApCgogICAgZGVmIF9wb2xsX2dvb2ds"
    "ZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoc2VsZiwgZm9yY2Vfb25jZTogYm9vbCA9IEZhbHNlKToK"
    "ICAgICAgICAiIiIKICAgICAgICBTeW5jIEdvb2dsZSBDYWxlbmRhciBldmVudHMg4oaSIGxvY2Fs"
    "IHRhc2tzIHVzaW5nIEdvb2dsZSdzIHN5bmNUb2tlbiBBUEkuCgogICAgICAgIFN0YWdlIDEgKGZp"
    "cnN0IHJ1biAvIGZvcmNlZCk6IEZ1bGwgZmV0Y2gsIHN0b3JlcyBuZXh0U3luY1Rva2VuLgogICAg"
    "ICAgIFN0YWdlIDIgKGV2ZXJ5IHBvbGwpOiAgICAgICAgIEluY3JlbWVudGFsIGZldGNoIHVzaW5n"
    "IHN0b3JlZCBzeW5jVG9rZW4g4oCUCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgcmV0dXJucyBPTkxZIHdoYXQgY2hhbmdlZCAoYWRkcy9lZGl0cy9jYW5jZWxzKS4KICAgICAg"
    "ICBJZiBzZXJ2ZXIgcmV0dXJucyA0MTAgR29uZSAodG9rZW4gZXhwaXJlZCksIGZhbGxzIGJhY2sg"
    "dG8gZnVsbCBzeW5jLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBmb3JjZV9vbmNlIGFuZCBu"
    "b3QgYm9vbChDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KS5nZXQoImdvb2dsZV9zeW5jX2VuYWJsZWQi"
    "LCBUcnVlKSk6CiAgICAgICAgICAgIHJldHVybiAwCgogICAgICAgIHRyeToKICAgICAgICAgICAg"
    "bm93X2lzbyA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tz"
    "LmxvYWRfYWxsKCkKICAgICAgICAgICAgdGFza3NfYnlfZXZlbnRfaWQgPSB7CiAgICAgICAgICAg"
    "ICAgICAodC5nZXQoImdvb2dsZV9ldmVudF9pZCIpIG9yICIiKS5zdHJpcCgpOiB0CiAgICAgICAg"
    "ICAgICAgICBmb3IgdCBpbiB0YXNrcwogICAgICAgICAgICAgICAgaWYgKHQuZ2V0KCJnb29nbGVf"
    "ZXZlbnRfaWQiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAgICB9CgogICAgICAgICAgICAjIOKU"
    "gOKUgCBGZXRjaCBmcm9tIEdvb2dsZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAgICAgc3RvcmVkX3Rv"
    "a2VuID0gc2VsZi5fc3RhdGUuZ2V0KCJnb29nbGVfY2FsZW5kYXJfc3luY190b2tlbiIpCgogICAg"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBzdG9yZWRfdG9rZW4gYW5kIG5vdCBmb3Jj"
    "ZV9vbmNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIltHT09HTEVdW1NZTkNdIEluY3JlbWVudGFsIHN5bmMgKHN5bmNUb2tl"
    "bikuIiwgIklORk8iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIHJl"
    "bW90ZV9ldmVudHMsIG5leHRfdG9rZW4gPSBzZWxmLl9nY2FsLmxpc3RfcHJpbWFyeV9ldmVudHMo"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIHN5bmNfdG9rZW49c3RvcmVkX3Rva2VuCiAgICAgICAg"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgICAgICJbR09PR0xFXVtTWU5D"
    "XSBGdWxsIHN5bmMgKG5vIHN0b3JlZCB0b2tlbikuIiwgIklORk8iCiAgICAgICAgICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICAgICAgICAgIG5vd191dGMgPSBkYXRldGltZS51dGNub3coKS5yZXBs"
    "YWNlKG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgICAgICAgICAgdGltZV9taW4gPSAobm93X3V0"
    "YyAtIHRpbWVkZWx0YShkYXlzPTM2NSkpLmlzb2Zvcm1hdCgpICsgIloiCiAgICAgICAgICAgICAg"
    "ICAgICAgcmVtb3RlX2V2ZW50cywgbmV4dF90b2tlbiA9IHNlbGYuX2djYWwubGlzdF9wcmltYXJ5"
    "X2V2ZW50cygKICAgICAgICAgICAgICAgICAgICAgICAgdGltZV9taW49dGltZV9taW4KICAgICAg"
    "ICAgICAgICAgICAgICApCgogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGFwaV9leDoK"
    "ICAgICAgICAgICAgICAgIGlmICI0MTAiIGluIHN0cihhcGlfZXgpIG9yICJHb25lIiBpbiBzdHIo"
    "YXBpX2V4KToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJbR09PR0xFXVtTWU5DXSBzeW5jVG9rZW4gZXhwaXJlZCAoNDEwKSDi"
    "gJQgZnVsbCByZXN5bmMuIiwgIldBUk4iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3N0YXRlLnBvcCgiZ29vZ2xlX2NhbGVuZGFyX3N5bmNfdG9rZW4iLCBO"
    "b25lKQogICAgICAgICAgICAgICAgICAgIG5vd191dGMgPSBkYXRldGltZS51dGNub3coKS5yZXBs"
    "YWNlKG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgICAgICAgICAgdGltZV9taW4gPSAobm93X3V0"
    "YyAtIHRpbWVkZWx0YShkYXlzPTM2NSkpLmlzb2Zvcm1hdCgpICsgIloiCiAgICAgICAgICAgICAg"
    "ICAgICAgcmVtb3RlX2V2ZW50cywgbmV4dF90b2tlbiA9IHNlbGYuX2djYWwubGlzdF9wcmltYXJ5"
    "X2V2ZW50cygKICAgICAgICAgICAgICAgICAgICAgICAgdGltZV9taW49dGltZV9taW4KICAgICAg"
    "ICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAg"
    "IHJhaXNlCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBm"
    "IltHT09HTEVdW1NZTkNdIFJlY2VpdmVkIHtsZW4ocmVtb3RlX2V2ZW50cyl9IGV2ZW50KHMpLiIs"
    "ICJJTkZPIgogICAgICAgICAgICApCgogICAgICAgICAgICAjIFNhdmUgbmV3IHRva2VuIGZvciBu"
    "ZXh0IGluY3JlbWVudGFsIGNhbGwKICAgICAgICAgICAgaWYgbmV4dF90b2tlbjoKICAgICAgICAg"
    "ICAgICAgIHNlbGYuX3N0YXRlWyJnb29nbGVfY2FsZW5kYXJfc3luY190b2tlbiJdID0gbmV4dF90"
    "b2tlbgogICAgICAgICAgICAgICAgc2VsZi5fbWVtb3J5LnNhdmVfc3RhdGUoc2VsZi5fc3RhdGUp"
    "CgogICAgICAgICAgICAjIOKUgOKUgCBQcm9jZXNzIGV2ZW50cyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICAgICAgaW1wb3J0ZWRfY291bnQgPSB1cGRhdGVkX2NvdW50ID0gcmVtb3ZlZF9j"
    "b3VudCA9IDAKICAgICAgICAgICAgY2hhbmdlZCA9IEZhbHNlCgogICAgICAgICAgICBmb3IgZXZl"
    "bnQgaW4gcmVtb3RlX2V2ZW50czoKICAgICAgICAgICAgICAgIGV2ZW50X2lkID0gKGV2ZW50Lmdl"
    "dCgiaWQiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAgICAgICAgaWYgbm90IGV2ZW50X2lkOgog"
    "ICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICAgICAgIyBEZWxldGVkIC8g"
    "Y2FuY2VsbGVkIG9uIEdvb2dsZSdzIHNpZGUKICAgICAgICAgICAgICAgIGlmIGV2ZW50LmdldCgi"
    "c3RhdHVzIikgPT0gImNhbmNlbGxlZCI6CiAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmcgPSB0"
    "YXNrc19ieV9ldmVudF9pZC5nZXQoZXZlbnRfaWQpCiAgICAgICAgICAgICAgICAgICAgaWYgZXhp"
    "c3RpbmcgYW5kIGV4aXN0aW5nLmdldCgic3RhdHVzIikgbm90IGluICgiY2FuY2VsbGVkIiwgImNv"
    "bXBsZXRlZCIpOgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sic3RhdHVzIl0gICAg"
    "ICAgICA9ICJjYW5jZWxsZWQiCiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJjYW5j"
    "ZWxsZWRfYXQiXSAgID0gbm93X2lzbwogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1si"
    "c3luY19zdGF0dXMiXSAgICA9ICJkZWxldGVkX3JlbW90ZSIKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZXhpc3RpbmdbImxhc3Rfc3luY2VkX2F0Il0gPSBub3dfaXNvCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGV4aXN0aW5nLnNldGRlZmF1bHQoIm1ldGFkYXRhIiwge30pWyJnb29nbGVfZGVsZXRl"
    "ZF9yZW1vdGUiXSA9IG5vd19pc28KICAgICAgICAgICAgICAgICAgICAgICAgcmVtb3ZlZF9jb3Vu"
    "dCArPSAxCiAgICAgICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGYiW0dPT0dMRV1bU1lOQ10gUmVtb3ZlZDoge2V4aXN0aW5nLmdldCgndGV4dCcsJz8nKX0i"
    "LCAiSU5GTyIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIGNv"
    "bnRpbnVlCgogICAgICAgICAgICAgICAgc3VtbWFyeSA9IChldmVudC5nZXQoInN1bW1hcnkiKSBv"
    "ciAiR29vZ2xlIENhbGVuZGFyIEV2ZW50Iikuc3RyaXAoKSBvciAiR29vZ2xlIENhbGVuZGFyIEV2"
    "ZW50IgogICAgICAgICAgICAgICAgZHVlX2F0ICA9IHNlbGYuX2dvb2dsZV9ldmVudF9kdWVfZGF0"
    "ZXRpbWUoZXZlbnQpCiAgICAgICAgICAgICAgICBleGlzdGluZyA9IHRhc2tzX2J5X2V2ZW50X2lk"
    "LmdldChldmVudF9pZCkKCiAgICAgICAgICAgICAgICBpZiBleGlzdGluZzoKICAgICAgICAgICAg"
    "ICAgICAgICAjIFVwZGF0ZSBpZiBhbnl0aGluZyBjaGFuZ2VkCiAgICAgICAgICAgICAgICAgICAg"
    "dGFza19jaGFuZ2VkID0gRmFsc2UKICAgICAgICAgICAgICAgICAgICBpZiAoZXhpc3RpbmcuZ2V0"
    "KCJ0ZXh0Iikgb3IgIiIpLnN0cmlwKCkgIT0gc3VtbWFyeToKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZXhpc3RpbmdbInRleHQiXSA9IHN1bW1hcnkKICAgICAgICAgICAgICAgICAgICAgICAgdGFz"
    "a19jaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIGlmIGR1ZV9hdDoKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgZHVlX2lzbyA9IGR1ZV9hdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29u"
    "ZHMiKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBleGlzdGluZy5nZXQoImR1ZV9hdCIpICE9"
    "IGR1ZV9pc286CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1siZHVlX2F0Il0g"
    "ICAgICAgPSBkdWVfaXNvCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sicHJl"
    "X3RyaWdnZXIiXSAgPSAoZHVlX2F0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkpLmlzb2Zvcm1hdCh0"
    "aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICB0YXNrX2NoYW5n"
    "ZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgaWYgZXhpc3RpbmcuZ2V0KCJzeW5jX3N0YXR1"
    "cyIpICE9ICJzeW5jZWQiOgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sic3luY19z"
    "dGF0dXMiXSA9ICJzeW5jZWQiCiAgICAgICAgICAgICAgICAgICAgICAgIHRhc2tfY2hhbmdlZCA9"
    "IFRydWUKICAgICAgICAgICAgICAgICAgICBpZiB0YXNrX2NoYW5nZWQ6CiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGV4aXN0aW5nWyJsYXN0X3N5bmNlZF9hdCJdID0gbm93X2lzbwogICAgICAgICAg"
    "ICAgICAgICAgICAgICB1cGRhdGVkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgICAgICAgICAg"
    "Y2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KAogICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTWU5DXSBVcGRhdGVkOiB7"
    "c3VtbWFyeX0iLCAiSU5GTyIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAg"
    "ICAgZWxzZToKICAgICAgICAgICAgICAgICAgICAjIE5ldyBldmVudAogICAgICAgICAgICAgICAg"
    "ICAgIGlmIG5vdCBkdWVfYXQ6CiAgICAgICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAg"
    "ICAgICAgICAgICAgICAgbmV3X3Rhc2sgPSB7CiAgICAgICAgICAgICAgICAgICAgICAgICJpZCI6"
    "ICAgICAgICAgICAgICAgIGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgICAgIG5vd19pc28sCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICJkdWVfYXQiOiAgICAgICAgICAgIGR1ZV9hdC5pc29mb3JtYXQodGltZXNw"
    "ZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAgICAgInByZV90cmlnZ2VyIjogICAg"
    "ICAgKGR1ZV9hdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpKS5pc29mb3JtYXQodGltZXNwZWM9InNl"
    "Y29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAgICAgInRleHQiOiAgICAgICAgICAgICAgc3Vt"
    "bWFyeSwKICAgICAgICAgICAgICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgICAgICAgInBlbmRp"
    "bmciLAogICAgICAgICAgICAgICAgICAgICAgICAiYWNrbm93bGVkZ2VkX2F0IjogICBOb25lLAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAicmV0cnlfY291bnQiOiAgICAgICAwLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAibGFzdF90cmlnZ2VyZWRfYXQiOiBOb25lLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAibmV4dF9yZXRyeV9hdCI6ICAgICBOb25lLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAicHJlX2Fubm91bmNlZCI6ICAgICBGYWxzZSwKICAgICAgICAgICAgICAgICAgICAgICAgInNv"
    "dXJjZSI6ICAgICAgICAgICAgImdvb2dsZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICJnb29n"
    "bGVfZXZlbnRfaWQiOiAgIGV2ZW50X2lkLAogICAgICAgICAgICAgICAgICAgICAgICAic3luY19z"
    "dGF0dXMiOiAgICAgICAic3luY2VkIiwKICAgICAgICAgICAgICAgICAgICAgICAgImxhc3Rfc3lu"
    "Y2VkX2F0IjogICAgbm93X2lzbywKICAgICAgICAgICAgICAgICAgICAgICAgIm1ldGFkYXRhIjog"
    "ewogICAgICAgICAgICAgICAgICAgICAgICAgICAgImdvb2dsZV9pbXBvcnRlZF9hdCI6IG5vd19p"
    "c28sCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAiZ29vZ2xlX3VwZGF0ZWQiOiAgICAgZXZl"
    "bnQuZ2V0KCJ1cGRhdGVkIiksCiAgICAgICAgICAgICAgICAgICAgICAgIH0sCiAgICAgICAgICAg"
    "ICAgICAgICAgfQogICAgICAgICAgICAgICAgICAgIHRhc2tzLmFwcGVuZChuZXdfdGFzaykKICAg"
    "ICAgICAgICAgICAgICAgICB0YXNrc19ieV9ldmVudF9pZFtldmVudF9pZF0gPSBuZXdfdGFzawog"
    "ICAgICAgICAgICAgICAgICAgIGltcG9ydGVkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgICAg"
    "ICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhm"
    "IltHT09HTEVdW1NZTkNdIEltcG9ydGVkOiB7c3VtbWFyeX0iLCAiSU5GTyIpCgogICAgICAgICAg"
    "ICBpZiBjaGFuZ2VkOgogICAgICAgICAgICAgICAgc2VsZi5fdGFza3Muc2F2ZV9hbGwodGFza3Mp"
    "CiAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NZTkNd"
    "IERvbmUg4oCUIGltcG9ydGVkPXtpbXBvcnRlZF9jb3VudH0gIgogICAgICAgICAgICAgICAgZiJ1"
    "cGRhdGVkPXt1cGRhdGVkX2NvdW50fSByZW1vdmVkPXtyZW1vdmVkX2NvdW50fSIsICJJTkZPIgog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybiBpbXBvcnRlZF9jb3VudAoKICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJb"
    "R09PR0xFXVtTWU5DXVtFUlJPUl0ge2V4fSIsICJFUlJPUiIpCiAgICAgICAgICAgIHJldHVybiAw"
    "CgoKICAgIGRlZiBfbWVhc3VyZV92cmFtX2Jhc2VsaW5lKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "aWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAg"
    "ICAgbWVtID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9kZWNrX3ZyYW1fYmFzZSA9IG1lbS51c2VkIC8gMTAyNCoqMwogICAg"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1ZS"
    "QU1dIEJhc2VsaW5lIG1lYXN1cmVkOiB7c2VsZi5fZGVja192cmFtX2Jhc2U6LjJmfUdCICIKICAg"
    "ICAgICAgICAgICAgICAgICBmIih7REVDS19OQU1FfSdzIGZvb3RwcmludCkiLCAiSU5GTyIKICAg"
    "ICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAg"
    "ICAgIHBhc3MKCiAgICAjIOKUgOKUgCBNRVNTQUdFIEhBTkRMSU5HIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9zZW5kX21lc3NhZ2Uo"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fbW9kZWxfbG9hZGVkIG9yIHNlbGYu"
    "X3RvcnBvcl9zdGF0ZSA9PSAiU1VTUEVORCI6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRl"
    "eHQgPSBzZWxmLl9pbnB1dF9maWVsZC50ZXh0KCkuc3RyaXAoKQogICAgICAgIGlmIG5vdCB0ZXh0"
    "OgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgIyBGbGlwIGJhY2sgdG8gcGVyc29uYSBjaGF0"
    "IHRhYiBmcm9tIFNlbGYgdGFiIGlmIG5lZWRlZAogICAgICAgIGlmIHNlbGYuX21haW5fdGFicy5j"
    "dXJyZW50SW5kZXgoKSAhPSAwOgogICAgICAgICAgICBzZWxmLl9tYWluX3RhYnMuc2V0Q3VycmVu"
    "dEluZGV4KDApCgogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLmNsZWFyKCkKICAgICAgICBzZWxm"
    "Ll9hcHBlbmRfY2hhdCgiWU9VIiwgdGV4dCkKCiAgICAgICAgIyBTZXNzaW9uIGxvZ2dpbmcKICAg"
    "ICAgICBzZWxmLl9zZXNzaW9ucy5hZGRfbWVzc2FnZSgidXNlciIsIHRleHQpCiAgICAgICAgc2Vs"
    "Zi5fbWVtb3J5LmFwcGVuZF9tZXNzYWdlKHNlbGYuX3Nlc3Npb25faWQsICJ1c2VyIiwgdGV4dCkK"
    "CiAgICAgICAgIyBJbnRlcnJ1cHQgZmFjZSB0aW1lciDigJQgc3dpdGNoIHRvIGFsZXJ0IGltbWVk"
    "aWF0ZWx5CiAgICAgICAgaWYgc2VsZi5fZmFjZV90aW1lcl9tZ3I6CiAgICAgICAgICAgIHNlbGYu"
    "X2ZhY2VfdGltZXJfbWdyLmludGVycnVwdCgiYWxlcnQiKQoKICAgICAgICAjIEJ1aWxkIHByb21w"
    "dCB3aXRoIHZhbXBpcmUgY29udGV4dCArIG1lbW9yeSBjb250ZXh0CiAgICAgICAgdmFtcGlyZV9j"
    "dHggID0gYnVpbGRfdmFtcGlyZV9jb250ZXh0KCkKICAgICAgICBtZW1vcnlfY3R4ICAgPSBzZWxm"
    "Ll9tZW1vcnkuYnVpbGRfY29udGV4dF9ibG9jayh0ZXh0KQogICAgICAgIGpvdXJuYWxfY3R4ICA9"
    "ICIiCgogICAgICAgIGlmIHNlbGYuX3Nlc3Npb25zLmxvYWRlZF9qb3VybmFsX2RhdGU6CiAgICAg"
    "ICAgICAgIGpvdXJuYWxfY3R4ID0gc2VsZi5fc2Vzc2lvbnMubG9hZF9zZXNzaW9uX2FzX2NvbnRl"
    "eHQoCiAgICAgICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5sb2FkZWRfam91cm5hbF9kYXRlCiAg"
    "ICAgICAgICAgICkKCiAgICAgICAgIyBCdWlsZCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgc3lzdGVt"
    "ID0gU1lTVEVNX1BST01QVF9CQVNFCiAgICAgICAgaWYgbWVtb3J5X2N0eDoKICAgICAgICAgICAg"
    "c3lzdGVtICs9IGYiXG5cbnttZW1vcnlfY3R4fSIKICAgICAgICBpZiBqb3VybmFsX2N0eDoKICAg"
    "ICAgICAgICAgc3lzdGVtICs9IGYiXG5cbntqb3VybmFsX2N0eH0iCiAgICAgICAgc3lzdGVtICs9"
    "IHZhbXBpcmVfY3R4CgogICAgICAgICMgTGVzc29ucyBjb250ZXh0IGZvciBjb2RlLWFkamFjZW50"
    "IGlucHV0CiAgICAgICAgaWYgYW55KGt3IGluIHRleHQubG93ZXIoKSBmb3Iga3cgaW4gKCJsc2wi"
    "LCJweXRob24iLCJzY3JpcHQiLCJjb2RlIiwiZnVuY3Rpb24iKSk6CiAgICAgICAgICAgIGxhbmcg"
    "PSAiTFNMIiBpZiAibHNsIiBpbiB0ZXh0Lmxvd2VyKCkgZWxzZSAiUHl0aG9uIgogICAgICAgICAg"
    "ICBsZXNzb25zX2N0eCA9IHNlbGYuX2xlc3NvbnMuYnVpbGRfY29udGV4dF9mb3JfbGFuZ3VhZ2Uo"
    "bGFuZykKICAgICAgICAgICAgaWYgbGVzc29uc19jdHg6CiAgICAgICAgICAgICAgICBzeXN0ZW0g"
    "Kz0gZiJcblxue2xlc3NvbnNfY3R4fSIKCiAgICAgICAgIyBBZGQgcGVuZGluZyB0cmFuc21pc3Np"
    "b25zIGNvbnRleHQgaWYgYW55CiAgICAgICAgaWYgc2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25z"
    "ID4gMDoKICAgICAgICAgICAgZHVyID0gc2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICJzb21l"
    "IHRpbWUiCiAgICAgICAgICAgIHN5c3RlbSArPSAoCiAgICAgICAgICAgICAgICBmIlxuXG5bUkVU"
    "VVJOIEZST00gVE9SUE9SXVxuIgogICAgICAgICAgICAgICAgZiJZb3Ugd2VyZSBpbiB0b3Jwb3Ig"
    "Zm9yIHtkdXJ9LiAiCiAgICAgICAgICAgICAgICBmIntzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lv"
    "bnN9IHRob3VnaHRzIHdlbnQgdW5zcG9rZW4gIgogICAgICAgICAgICAgICAgZiJkdXJpbmcgdGhh"
    "dCB0aW1lLiBBY2tub3dsZWRnZSB0aGlzIGJyaWVmbHkgaW4gY2hhcmFjdGVyICIKICAgICAgICAg"
    "ICAgICAgIGYiaWYgaXQgZmVlbHMgbmF0dXJhbC4iCiAgICAgICAgICAgICkKICAgICAgICAgICAg"
    "c2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zID0gMAogICAgICAgICAgICBzZWxmLl9zdXNwZW5k"
    "ZWRfZHVyYXRpb24gICAgPSAiIgoKICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0"
    "X2hpc3RvcnkoKQoKICAgICAgICAjIERpc2FibGUgaW5wdXQKICAgICAgICBzZWxmLl9zZW5kX2J0"
    "bi5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQo"
    "RmFsc2UpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiR0VORVJBVElORyIpCgogICAgICAgICMg"
    "U3RvcCBpZGxlIHRpbWVyIGR1cmluZyBnZW5lcmF0aW9uCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1"
    "bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFuc21pc3Npb24iKQog"
    "ICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAg"
    "ICAjIExhdW5jaCBzdHJlYW1pbmcgd29ya2VyCiAgICAgICAgc2VsZi5fd29ya2VyID0gU3RyZWFt"
    "aW5nV29ya2VyKAogICAgICAgICAgICBzZWxmLl9hZGFwdG9yLCBzeXN0ZW0sIGhpc3RvcnksIG1h"
    "eF90b2tlbnM9NTEyCiAgICAgICAgKQogICAgICAgIHNlbGYuX3dvcmtlci50b2tlbl9yZWFkeS5j"
    "b25uZWN0KHNlbGYuX29uX3Rva2VuKQogICAgICAgIHNlbGYuX3dvcmtlci5yZXNwb25zZV9kb25l"
    "LmNvbm5lY3Qoc2VsZi5fb25fcmVzcG9uc2VfZG9uZSkKICAgICAgICBzZWxmLl93b3JrZXIuZXJy"
    "b3Jfb2NjdXJyZWQuY29ubmVjdChzZWxmLl9vbl9lcnJvcikKICAgICAgICBzZWxmLl93b3JrZXIu"
    "c3RhdHVzX2NoYW5nZWQuY29ubmVjdChzZWxmLl9zZXRfc3RhdHVzKQogICAgICAgIHNlbGYuX2Zp"
    "cnN0X3Rva2VuID0gVHJ1ZSAgIyBmbGFnIHRvIHdyaXRlIHNwZWFrZXIgbGFiZWwgYmVmb3JlIGZp"
    "cnN0IHRva2VuCiAgICAgICAgc2VsZi5fd29ya2VyLnN0YXJ0KCkKCiAgICBkZWYgX2JlZ2luX3Bl"
    "cnNvbmFfcmVzcG9uc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBXcml0ZSB0"
    "aGUgcGVyc29uYSBzcGVha2VyIGxhYmVsIGFuZCB0aW1lc3RhbXAgYmVmb3JlIHN0cmVhbWluZyBi"
    "ZWdpbnMuCiAgICAgICAgQ2FsbGVkIG9uIGZpcnN0IHRva2VuIG9ubHkuIFN1YnNlcXVlbnQgdG9r"
    "ZW5zIGFwcGVuZCBkaXJlY3RseS4KICAgICAgICAiIiIKICAgICAgICB0aW1lc3RhbXAgPSBkYXRl"
    "dGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgICMgV3JpdGUgdGhlIHNwZWFr"
    "ZXIgbGFiZWwgYXMgSFRNTCwgdGhlbiBhZGQgYSBuZXdsaW5lIHNvIHRva2VucwogICAgICAgICMg"
    "ZmxvdyBiZWxvdyBpdCByYXRoZXIgdGhhbiBpbmxpbmUKICAgICAgICBzZWxmLl9jaGF0X2Rpc3Bs"
    "YXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07"
    "IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicK"
    "ICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfQ1JJTVNPTn07IGZvbnQtd2VpZ2h0"
    "OmJvbGQ7Ij4nCiAgICAgICAgICAgIGYne0RFQ0tfTkFNRS51cHBlcigpfSDinak8L3NwYW4+Jwog"
    "ICAgICAgICkKICAgICAgICAjIE1vdmUgY3Vyc29yIHRvIGVuZCBzbyBpbnNlcnRQbGFpblRleHQg"
    "YXBwZW5kcyBjb3JyZWN0bHkKICAgICAgICBjdXJzb3IgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudGV4"
    "dEN1cnNvcigpCiAgICAgICAgY3Vyc29yLm1vdmVQb3NpdGlvbihRVGV4dEN1cnNvci5Nb3ZlT3Bl"
    "cmF0aW9uLkVuZCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNvcihjdXJz"
    "b3IpCgogICAgZGVmIF9vbl90b2tlbihzZWxmLCB0b2tlbjogc3RyKSAtPiBOb25lOgogICAgICAg"
    "ICIiIkFwcGVuZCBzdHJlYW1pbmcgdG9rZW4gdG8gY2hhdCBkaXNwbGF5LiIiIgogICAgICAgIGlm"
    "IHNlbGYuX2ZpcnN0X3Rva2VuOgogICAgICAgICAgICBzZWxmLl9iZWdpbl9wZXJzb25hX3Jlc3Bv"
    "bnNlKCkKICAgICAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBGYWxzZQogICAgICAgIGN1cnNv"
    "ciA9IHNlbGYuX2NoYXRfZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAgICBjdXJzb3IubW92ZVBv"
    "c2l0aW9uKFFUZXh0Q3Vyc29yLk1vdmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRf"
    "ZGlzcGxheS5zZXRUZXh0Q3Vyc29yKGN1cnNvcikKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXku"
    "aW5zZXJ0UGxhaW5UZXh0KHRva2VuKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNh"
    "bFNjcm9sbEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkudmVy"
    "dGljYWxTY3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAgZGVmIF9vbl9yZXNwb25z"
    "ZV9kb25lKHNlbGYsIHJlc3BvbnNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIyBFbnN1cmUgcmVz"
    "cG9uc2UgaXMgb24gaXRzIG93biBsaW5lCiAgICAgICAgY3Vyc29yID0gc2VsZi5fY2hhdF9kaXNw"
    "bGF5LnRleHRDdXJzb3IoKQogICAgICAgIGN1cnNvci5tb3ZlUG9zaXRpb24oUVRleHRDdXJzb3Iu"
    "TW92ZU9wZXJhdGlvbi5FbmQpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFRleHRDdXJz"
    "b3IoY3Vyc29yKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5pbnNlcnRQbGFpblRleHQoIlxu"
    "XG4iKQoKICAgICAgICAjIExvZyB0byBtZW1vcnkgYW5kIHNlc3Npb24KICAgICAgICBzZWxmLl90"
    "b2tlbl9jb3VudCArPSBsZW4ocmVzcG9uc2Uuc3BsaXQoKSkKICAgICAgICBzZWxmLl9zZXNzaW9u"
    "cy5hZGRfbWVzc2FnZSgiYXNzaXN0YW50IiwgcmVzcG9uc2UpCiAgICAgICAgc2VsZi5fbWVtb3J5"
    "LmFwcGVuZF9tZXNzYWdlKHNlbGYuX3Nlc3Npb25faWQsICJhc3Npc3RhbnQiLCByZXNwb25zZSkK"
    "ICAgICAgICBzZWxmLl9tZW1vcnkuYXBwZW5kX21lbW9yeShzZWxmLl9zZXNzaW9uX2lkLCAiIiwg"
    "cmVzcG9uc2UpCgogICAgICAgICMgVXBkYXRlIGJsb29kIHNwaGVyZQogICAgICAgIGlmIHNlbGYu"
    "X2Jsb29kX3NwaGVyZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fYmxvb2Rfc3BoZXJl"
    "LnNldEZpbGwoCiAgICAgICAgICAgICAgICBtaW4oMS4wLCBzZWxmLl90b2tlbl9jb3VudCAvIDQw"
    "OTYuMCkKICAgICAgICAgICAgKQoKICAgICAgICAjIFJlLWVuYWJsZSBpbnB1dAogICAgICAgIHNl"
    "bGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5z"
    "ZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0Rm9jdXMoKQoKICAg"
    "ICAgICAjIFJlc3VtZSBpZGxlIHRpbWVyCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1bGVyIGFuZCBz"
    "ZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAg"
    "c2VsZi5fc2NoZWR1bGVyLnJlc3VtZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTY2hl"
    "ZHVsZSBzZW50aW1lbnQgYW5hbHlzaXMgKDUgc2Vjb25kIGRlbGF5KQogICAgICAgIFFUaW1lci5z"
    "aW5nbGVTaG90KDUwMDAsIGxhbWJkYTogc2VsZi5fcnVuX3NlbnRpbWVudChyZXNwb25zZSkpCgog"
    "ICAgZGVmIF9ydW5fc2VudGltZW50KHNlbGYsIHJlc3BvbnNlOiBzdHIpIC0+IE5vbmU6CiAgICAg"
    "ICAgaWYgbm90IHNlbGYuX21vZGVsX2xvYWRlZDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAg"
    "c2VsZi5fc2VudF93b3JrZXIgPSBTZW50aW1lbnRXb3JrZXIoc2VsZi5fYWRhcHRvciwgcmVzcG9u"
    "c2UpCiAgICAgICAgc2VsZi5fc2VudF93b3JrZXIuZmFjZV9yZWFkeS5jb25uZWN0KHNlbGYuX29u"
    "X3NlbnRpbWVudCkKICAgICAgICBzZWxmLl9zZW50X3dvcmtlci5zdGFydCgpCgogICAgZGVmIF9v"
    "bl9zZW50aW1lbnQoc2VsZiwgZW1vdGlvbjogc3RyKSAtPiBOb25lOgogICAgICAgIGlmIHNlbGYu"
    "X2ZhY2VfdGltZXJfbWdyOgogICAgICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nci5zZXRfZmFj"
    "ZShlbW90aW9uKQoKICAgIGRlZiBfb25fZXJyb3Ioc2VsZiwgZXJyb3I6IHN0cikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiRVJST1IiLCBlcnJvcikKICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coZiJbR0VORVJBVElPTiBFUlJPUl0ge2Vycm9yfSIsICJFUlJPUiIpCiAgICAg"
    "ICAgaWYgc2VsZi5fZmFjZV90aW1lcl9tZ3I6CiAgICAgICAgICAgIHNlbGYuX2ZhY2VfdGltZXJf"
    "bWdyLnNldF9mYWNlKCJwYW5pY2tlZCIpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiRVJST1Ii"
    "KQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICBzZWxmLl9p"
    "bnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCgogICAgIyDilIDilIAgVE9SUE9SIFNZU1RFTSDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgIGRlZiBfb25fdG9ycG9yX3N0YXRlX2NoYW5nZWQoc2VsZiwgc3RhdGU6IHN0cikgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLl90b3Jwb3Jfc3RhdGUgPSBzdGF0ZQoKICAgICAgICBpZiBzdGF0"
    "ZSA9PSAiU1VTUEVORCI6CiAgICAgICAgICAgIHNlbGYuX2VudGVyX3RvcnBvcihyZWFzb249Im1h"
    "bnVhbCDigJQgU1VTUEVORCBtb2RlIHNlbGVjdGVkIikKICAgICAgICBlbGlmIHN0YXRlID09ICJB"
    "V0FLRSI6CiAgICAgICAgICAgICMgQWx3YXlzIGV4aXQgdG9ycG9yIHdoZW4gc3dpdGNoaW5nIHRv"
    "IEFXQUtFIOKAlAogICAgICAgICAgICAjIGV2ZW4gd2l0aCBPbGxhbWEgYmFja2VuZCB3aGVyZSBt"
    "b2RlbCBpc24ndCB1bmxvYWRlZCwKICAgICAgICAgICAgIyB3ZSBuZWVkIHRvIHJlLWVuYWJsZSBV"
    "SSBhbmQgcmVzZXQgc3RhdGUKICAgICAgICAgICAgc2VsZi5fZXhpdF90b3Jwb3IoKQogICAgICAg"
    "ICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMAogICAgICAgICAgICBzZWxmLl92cmFt"
    "X3JlbGllZl90aWNrcyAgID0gMAogICAgICAgIGVsaWYgc3RhdGUgPT0gIkFVVE8iOgogICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAiW1RPUlBPUl0gQVVUTyBt"
    "b2RlIOKAlCBtb25pdG9yaW5nIFZSQU0gcHJlc3N1cmUuIiwgIklORk8iCiAgICAgICAgICAgICkK"
    "CiAgICBkZWYgX2VudGVyX3RvcnBvcihzZWxmLCByZWFzb246IHN0ciA9ICJtYW51YWwiKSAtPiBO"
    "b25lOgogICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAg"
    "ICAgcmV0dXJuICAjIEFscmVhZHkgaW4gdG9ycG9yCgogICAgICAgIHNlbGYuX3RvcnBvcl9zaW5j"
    "ZSA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RPUlBPUl0g"
    "RW50ZXJpbmcgdG9ycG9yOiB7cmVhc29ufSIsICJXQVJOIikKICAgICAgICBzZWxmLl9hcHBlbmRf"
    "Y2hhdCgiU1lTVEVNIiwgIlRoZSB2ZXNzZWwgZ3Jvd3MgY3Jvd2RlZC4gSSB3aXRoZHJhdy4iKQoK"
    "ICAgICAgICAjIFVubG9hZCBtb2RlbCBmcm9tIFZSQU0KICAgICAgICBpZiBzZWxmLl9tb2RlbF9s"
    "b2FkZWQgYW5kIGlzaW5zdGFuY2Uoc2VsZi5fYWRhcHRvciwKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcik6CiAgICAg"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2FkYXB0b3IuX21vZGVsIGlzIG5v"
    "dCBOb25lOgogICAgICAgICAgICAgICAgICAgIGRlbCBzZWxmLl9hZGFwdG9yLl9tb2RlbAogICAg"
    "ICAgICAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IuX21vZGVsID0gTm9uZQogICAgICAgICAgICAg"
    "ICAgaWYgVE9SQ0hfT0s6CiAgICAgICAgICAgICAgICAgICAgdG9yY2guY3VkYS5lbXB0eV9jYWNo"
    "ZSgpCiAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLl9sb2FkZWQgPSBGYWxzZQogICAgICAg"
    "ICAgICAgICAgc2VsZi5fbW9kZWxfbG9hZGVkICAgID0gRmFsc2UKICAgICAgICAgICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZygiW1RPUlBPUl0gTW9kZWwgdW5sb2FkZWQgZnJvbSBWUkFNLiIsICJP"
    "SyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltUT1JQT1JdIE1vZGVsIHVu"
    "bG9hZCBlcnJvcjoge2V9IiwgIkVSUk9SIgogICAgICAgICAgICAgICAgKQoKICAgICAgICBzZWxm"
    "Ll9taXJyb3Iuc2V0X2ZhY2UoIm5ldXRyYWwiKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIlRP"
    "UlBPUiIpCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBz"
    "ZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKEZhbHNlKQoKICAgIGRlZiBfZXhpdF90b3Jwb3Io"
    "c2VsZikgLT4gTm9uZToKICAgICAgICAjIENhbGN1bGF0ZSBzdXNwZW5kZWQgZHVyYXRpb24KICAg"
    "ICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2U6CiAgICAgICAgICAgIGRlbHRhID0gZGF0ZXRpbWUu"
    "bm93KCkgLSBzZWxmLl90b3Jwb3Jfc2luY2UKICAgICAgICAgICAgc2VsZi5fc3VzcGVuZGVkX2R1"
    "cmF0aW9uID0gZm9ybWF0X2R1cmF0aW9uKGRlbHRhLnRvdGFsX3NlY29uZHMoKSkKICAgICAgICAg"
    "ICAgc2VsZi5fdG9ycG9yX3NpbmNlID0gTm9uZQoKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "IltUT1JQT1JdIFdha2luZyBmcm9tIHRvcnBvci4uLiIsICJJTkZPIikKCiAgICAgICAgaWYgc2Vs"
    "Zi5fbW9kZWxfbG9hZGVkOgogICAgICAgICAgICAjIE9sbGFtYSBiYWNrZW5kIOKAlCBtb2RlbCB3"
    "YXMgbmV2ZXIgdW5sb2FkZWQsIGp1c3QgcmUtZW5hYmxlIFVJCiAgICAgICAgICAgIHNlbGYuX2Fw"
    "cGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAgICAgZiJUaGUgdmVzc2VsIGVtcHRpZXMu"
    "IHtERUNLX05BTUV9IHN0aXJzICIKICAgICAgICAgICAgICAgIGYiKHtzZWxmLl9zdXNwZW5kZWRf"
    "ZHVyYXRpb24gb3IgJ2JyaWVmbHknfSBlbGFwc2VkKS4iCiAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsICJUaGUgY29ubmVjdGlvbiBob2xkcy4gU2hl"
    "IGlzIGxpc3RlbmluZy4iKQogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJJRExFIikKICAg"
    "ICAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxm"
    "Ll9pbnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZygiW1RPUlBPUl0gQVdBS0UgbW9kZSDigJQgYXV0by10b3Jwb3IgZGlzYWJsZWQuIiwgIklO"
    "Rk8iKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgICMgTG9jYWwgbW9kZWwgd2FzIHVubG9hZGVk"
    "IOKAlCBuZWVkIGZ1bGwgcmVsb2FkCiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNU"
    "RU0iLAogICAgICAgICAgICAgICAgZiJUaGUgdmVzc2VsIGVtcHRpZXMuIHtERUNLX05BTUV9IHN0"
    "aXJzIGZyb20gdG9ycG9yICIKICAgICAgICAgICAgICAgIGYiKHtzZWxmLl9zdXNwZW5kZWRfZHVy"
    "YXRpb24gb3IgJ2JyaWVmbHknfSBlbGFwc2VkKS4iCiAgICAgICAgICAgICkKICAgICAgICAgICAg"
    "c2VsZi5fc2V0X3N0YXR1cygiTE9BRElORyIpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlciA9IE1v"
    "ZGVsTG9hZGVyV29ya2VyKHNlbGYuX2FkYXB0b3IpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5t"
    "ZXNzYWdlLmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgbTogc2VsZi5fYXBwZW5kX2No"
    "YXQoIlNZU1RFTSIsIG0pKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuZXJyb3IuY29ubmVjdCgK"
    "ICAgICAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9hcHBlbmRfY2hhdCgiRVJST1IiLCBlKSkK"
    "ICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmxvYWRfY29tcGxldGUuY29ubmVjdChzZWxmLl9vbl9s"
    "b2FkX2NvbXBsZXRlKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuZmluaXNoZWQuY29ubmVjdChz"
    "ZWxmLl9sb2FkZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgICAgIHNlbGYuX2FjdGl2ZV90aHJlYWRz"
    "LmFwcGVuZChzZWxmLl9sb2FkZXIpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5zdGFydCgpCgog"
    "ICAgZGVmIF9jaGVja192cmFtX3ByZXNzdXJlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAg"
    "ICAgICAgQ2FsbGVkIGV2ZXJ5IDUgc2Vjb25kcyBmcm9tIEFQU2NoZWR1bGVyIHdoZW4gdG9ycG9y"
    "IHN0YXRlIGlzIEFVVE8uCiAgICAgICAgT25seSB0cmlnZ2VycyB0b3Jwb3IgaWYgZXh0ZXJuYWwg"
    "VlJBTSB1c2FnZSBleGNlZWRzIHRocmVzaG9sZAogICAgICAgIEFORCBpcyBzdXN0YWluZWQg4oCU"
    "IG5ldmVyIHRyaWdnZXJzIG9uIHRoZSBwZXJzb25hJ3Mgb3duIGZvb3RwcmludC4KICAgICAgICAi"
    "IiIKICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc3RhdGUgIT0gIkFVVE8iOgogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICBpZiBub3QgTlZNTF9PSyBvciBub3QgZ3B1X2hhbmRsZToKICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgaWYgc2VsZi5fZGVja192cmFtX2Jhc2UgPD0gMDoKICAgICAgICAg"
    "ICAgcmV0dXJuCgogICAgICAgIHRyeToKICAgICAgICAgICAgbWVtX2luZm8gID0gcHludm1sLm52"
    "bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgIHRvdGFsX3VzZWQg"
    "PSBtZW1faW5mby51c2VkIC8gMTAyNCoqMwogICAgICAgICAgICBleHRlcm5hbCAgID0gdG90YWxf"
    "dXNlZCAtIHNlbGYuX2RlY2tfdnJhbV9iYXNlCgogICAgICAgICAgICBpZiBleHRlcm5hbCA+IHNl"
    "bGYuX0VYVEVSTkFMX1ZSQU1fVE9SUE9SX0dCOgogICAgICAgICAgICAgICAgaWYgc2VsZi5fdG9y"
    "cG9yX3NpbmNlIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgIHJldHVybiAgIyBBbHJl"
    "YWR5IGluIHRvcnBvciDigJQgZG9uJ3Qga2VlcCBjb3VudGluZwogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fdnJhbV9wcmVzc3VyZV90aWNrcyArPSAxCiAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3Jl"
    "bGllZl90aWNrcyAgICA9IDAKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAg"
    "ICAgICAgICAgICAgICAgICBmIltUT1JQT1IgQVVUT10gRXh0ZXJuYWwgVlJBTSBwcmVzc3VyZTog"
    "IgogICAgICAgICAgICAgICAgICAgIGYie2V4dGVybmFsOi4yZn1HQiAiCiAgICAgICAgICAgICAg"
    "ICAgICAgZiIodGljayB7c2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrc30vIgogICAgICAgICAgICAg"
    "ICAgICAgIGYie3NlbGYuX1RPUlBPUl9TVVNUQUlORURfVElDS1N9KSIsICJXQVJOIgogICAgICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgKHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3Mg"
    "Pj0gc2VsZi5fVE9SUE9SX1NVU1RBSU5FRF9USUNLUwogICAgICAgICAgICAgICAgICAgICAgICBh"
    "bmQgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIE5vbmUpOgogICAgICAgICAgICAgICAgICAgIHNlbGYu"
    "X2VudGVyX3RvcnBvcigKICAgICAgICAgICAgICAgICAgICAgICAgcmVhc29uPWYiYXV0byDigJQg"
    "e2V4dGVybmFsOi4xZn1HQiBleHRlcm5hbCBWUkFNICIKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGYicHJlc3N1cmUgc3VzdGFpbmVkIgogICAgICAgICAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMCAgIyByZXNldCBhZnRl"
    "ciBlbnRlcmluZyB0b3Jwb3IKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYu"
    "X3ZyYW1fcHJlc3N1cmVfdGlja3MgPSAwCiAgICAgICAgICAgICAgICBpZiBzZWxmLl90b3Jwb3Jf"
    "c2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZf"
    "dGlja3MgKz0gMQogICAgICAgICAgICAgICAgICAgIGF1dG9fd2FrZSA9IENGR1sic2V0dGluZ3Mi"
    "XS5nZXQoCiAgICAgICAgICAgICAgICAgICAgICAgICJhdXRvX3dha2Vfb25fcmVsaWVmIiwgRmFs"
    "c2UKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgaWYgKGF1dG9fd2Fr"
    "ZSBhbmQKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tz"
    "ID49IHNlbGYuX1dBS0VfU1VTVEFJTkVEX1RJQ0tTKToKICAgICAgICAgICAgICAgICAgICAgICAg"
    "c2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgPSAwCiAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYu"
    "X2V4aXRfdG9ycG9yKCkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltUT1JQT1IgQVVUT10gVlJB"
    "TSBjaGVjayBlcnJvcjoge2V9IiwgIkVSUk9SIgogICAgICAgICAgICApCgogICAgIyDilIDilIAg"
    "QVBTQ0hFRFVMRVIgU0VUVVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICBkZWYgX3NldHVwX3NjaGVkdWxlcihzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgZnJvbSBhcHNjaGVkdWxlci5zY2hlZHVsZXJzLmJhY2tncm91bmQg"
    "aW1wb3J0IEJhY2tncm91bmRTY2hlZHVsZXIKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyID0g"
    "QmFja2dyb3VuZFNjaGVkdWxlcigKICAgICAgICAgICAgICAgIGpvYl9kZWZhdWx0cz17Im1pc2Zp"
    "cmVfZ3JhY2VfdGltZSI6IDYwfQogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IEltcG9ydEVy"
    "cm9yOgogICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIgPSBOb25lCiAgICAgICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICJbU0NIRURVTEVSXSBhcHNjaGVkdWxlciBu"
    "b3QgYXZhaWxhYmxlIOKAlCAiCiAgICAgICAgICAgICAgICAiaWRsZSwgYXV0b3NhdmUsIGFuZCBy"
    "ZWZsZWN0aW9uIGRpc2FibGVkLiIsICJXQVJOIgogICAgICAgICAgICApCiAgICAgICAgICAgIHJl"
    "dHVybgoKICAgICAgICBpbnRlcnZhbF9taW4gPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJhdXRvc2F2"
    "ZV9pbnRlcnZhbF9taW51dGVzIiwgMTApCgogICAgICAgICMgQXV0b3NhdmUKICAgICAgICBzZWxm"
    "Ll9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgc2VsZi5fYXV0b3NhdmUsICJpbnRlcnZh"
    "bCIsCiAgICAgICAgICAgIG1pbnV0ZXM9aW50ZXJ2YWxfbWluLCBpZD0iYXV0b3NhdmUiCiAgICAg"
    "ICAgKQoKICAgICAgICAjIFZSQU0gcHJlc3N1cmUgY2hlY2sgKGV2ZXJ5IDVzKQogICAgICAgIHNl"
    "bGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAgICAgICBzZWxmLl9jaGVja192cmFtX3ByZXNz"
    "dXJlLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBzZWNvbmRzPTUsIGlkPSJ2cmFtX2NoZWNrIgog"
    "ICAgICAgICkKCiAgICAgICAgIyBJZGxlIHRyYW5zbWlzc2lvbiAoc3RhcnRzIHBhdXNlZCDigJQg"
    "ZW5hYmxlZCBieSBpZGxlIHRvZ2dsZSkKICAgICAgICBpZGxlX21pbiA9IENGR1sic2V0dGluZ3Mi"
    "XS5nZXQoImlkbGVfbWluX21pbnV0ZXMiLCAxMCkKICAgICAgICBpZGxlX21heCA9IENGR1sic2V0"
    "dGluZ3MiXS5nZXQoImlkbGVfbWF4X21pbnV0ZXMiLCAzMCkKICAgICAgICBpZGxlX2ludGVydmFs"
    "ID0gKGlkbGVfbWluICsgaWRsZV9tYXgpIC8vIDIKCiAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFk"
    "ZF9qb2IoCiAgICAgICAgICAgIHNlbGYuX2ZpcmVfaWRsZV90cmFuc21pc3Npb24sICJpbnRlcnZh"
    "bCIsCiAgICAgICAgICAgIG1pbnV0ZXM9aWRsZV9pbnRlcnZhbCwgaWQ9ImlkbGVfdHJhbnNtaXNz"
    "aW9uIgogICAgICAgICkKCiAgICAgICAgIyBNb29uIHdpZGdldCByZWZyZXNoIChldmVyeSA2IGhv"
    "dXJzKQogICAgICAgIGlmIHNlbGYuX21vb25fd2lkZ2V0IGlzIG5vdCBOb25lOgogICAgICAgICAg"
    "ICBzZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgICAgIHNlbGYuX21vb25fd2lk"
    "Z2V0LnVwZGF0ZVBoYXNlLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICAgICAgaG91cnM9NiwgaWQ9"
    "Im1vb25fcmVmcmVzaCIKICAgICAgICAgICAgKQoKICAgICAgICAjIE5PVEU6IHNjaGVkdWxlci5z"
    "dGFydCgpIGlzIGNhbGxlZCBmcm9tIHN0YXJ0X3NjaGVkdWxlcigpCiAgICAgICAgIyB3aGljaCBp"
    "cyB0cmlnZ2VyZWQgdmlhIFFUaW1lci5zaW5nbGVTaG90IEFGVEVSIHRoZSB3aW5kb3cKICAgICAg"
    "ICAjIGlzIHNob3duIGFuZCB0aGUgUXQgZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgICAgICMg"
    "RG8gTk9UIGNhbGwgc2VsZi5fc2NoZWR1bGVyLnN0YXJ0KCkgaGVyZS4KCiAgICBkZWYgc3RhcnRf"
    "c2NoZWR1bGVyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIHZpYSBR"
    "VGltZXIuc2luZ2xlU2hvdCBhZnRlciB3aW5kb3cuc2hvdygpIGFuZCBhcHAuZXhlYygpIGJlZ2lu"
    "cy4KICAgICAgICBEZWZlcnJlZCB0byBlbnN1cmUgUXQgZXZlbnQgbG9vcCBpcyBydW5uaW5nIGJl"
    "Zm9yZSBiYWNrZ3JvdW5kIHRocmVhZHMgc3RhcnQuCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2Vs"
    "Zi5fc2NoZWR1bGVyIGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnN0YXJ0KCkKICAgICAgICAgICAgIyBJZGxlIHN0YXJ0"
    "cyBwYXVzZWQKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFu"
    "c21pc3Npb24iKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltTQ0hFRFVMRVJdIEFQ"
    "U2NoZWR1bGVyIHN0YXJ0ZWQuIiwgIk9LIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6"
    "CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltTQ0hFRFVMRVJdIFN0YXJ0IGVycm9y"
    "OiB7ZX0iLCAiRVJST1IiKQoKICAgIGRlZiBfYXV0b3NhdmUoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLnNhdmUoKQogICAgICAgICAgICBzZWxm"
    "Ll9qb3VybmFsX3NpZGViYXIuc2V0X2F1dG9zYXZlX2luZGljYXRvcihUcnVlKQogICAgICAgICAg"
    "ICBRVGltZXIuc2luZ2xlU2hvdCgKICAgICAgICAgICAgICAgIDMwMDAsIGxhbWJkYTogc2VsZi5f"
    "am91cm5hbF9zaWRlYmFyLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoRmFsc2UpCiAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbQVVUT1NBVkVdIFNlc3Npb24gc2F2"
    "ZWQuIiwgIklORk8iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKGYiW0FVVE9TQVZFXSBFcnJvcjoge2V9IiwgIkVSUk9SIikKCiAg"
    "ICBkZWYgX2ZpcmVfaWRsZV90cmFuc21pc3Npb24oc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBu"
    "b3Qgc2VsZi5fbW9kZWxfbG9hZGVkIG9yIHNlbGYuX3N0YXR1cyA9PSAiR0VORVJBVElORyI6CiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9u"
    "ZToKICAgICAgICAgICAgIyBJbiB0b3Jwb3Ig4oCUIGNvdW50IHRoZSBwZW5kaW5nIHRob3VnaHQg"
    "YnV0IGRvbid0IGdlbmVyYXRlCiAgICAgICAgICAgIHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9u"
    "cyArPSAxCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYi"
    "W0lETEVdIEluIHRvcnBvciDigJQgcGVuZGluZyB0cmFuc21pc3Npb24gIgogICAgICAgICAgICAg"
    "ICAgZiIje3NlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9uc30iLCAiSU5GTyIKICAgICAgICAgICAg"
    "KQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgbW9kZSA9IHJhbmRvbS5jaG9pY2UoWyJERUVQ"
    "RU5JTkciLCJCUkFOQ0hJTkciLCJTWU5USEVTSVMiXSkKICAgICAgICB2YW1waXJlX2N0eCA9IGJ1"
    "aWxkX3ZhbXBpcmVfY29udGV4dCgpCiAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdl"
    "dF9oaXN0b3J5KCkKCiAgICAgICAgc2VsZi5faWRsZV93b3JrZXIgPSBJZGxlV29ya2VyKAogICAg"
    "ICAgICAgICBzZWxmLl9hZGFwdG9yLAogICAgICAgICAgICBTWVNURU1fUFJPTVBUX0JBU0UsCiAg"
    "ICAgICAgICAgIGhpc3RvcnksCiAgICAgICAgICAgIG1vZGU9bW9kZSwKICAgICAgICAgICAgdmFt"
    "cGlyZV9jb250ZXh0PXZhbXBpcmVfY3R4LAogICAgICAgICkKICAgICAgICBkZWYgX29uX2lkbGVf"
    "cmVhZHkodDogc3RyKSAtPiBOb25lOgogICAgICAgICAgICAjIEZsaXAgdG8gU2VsZiB0YWIgYW5k"
    "IGFwcGVuZCB0aGVyZQogICAgICAgICAgICBzZWxmLl9tYWluX3RhYnMuc2V0Q3VycmVudEluZGV4"
    "KDEpCiAgICAgICAgICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNIikKICAg"
    "ICAgICAgICAgc2VsZi5fc2VsZl9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgICAgIGYnPHNw"
    "YW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAg"
    "ICAgICAgICBmJ1t7dHN9XSBbe21vZGV9XTwvc3Bhbj48YnI+JwogICAgICAgICAgICAgICAgZic8"
    "c3BhbiBzdHlsZT0iY29sb3I6e0NfR09MRH07Ij57dH08L3NwYW4+PGJyPicKICAgICAgICAgICAg"
    "KQogICAgICAgICAgICBzZWxmLl9zZWxmX3RhYi5hcHBlbmQoIk5BUlJBVElWRSIsIHQpCgogICAg"
    "ICAgIHNlbGYuX2lkbGVfd29ya2VyLnRyYW5zbWlzc2lvbl9yZWFkeS5jb25uZWN0KF9vbl9pZGxl"
    "X3JlYWR5KQogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3Qo"
    "CiAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9kaWFnX3RhYi5sb2coZiJbSURMRSBFUlJPUl0g"
    "e2V9IiwgIkVSUk9SIikKICAgICAgICApCiAgICAgICAgc2VsZi5faWRsZV93b3JrZXIuc3RhcnQo"
    "KQoKICAgICMg4pSA4pSAIEpPVVJOQUwgU0VTU0lPTiBMT0FESU5HIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgZGVmIF9sb2FkX2pvdXJuYWxfc2Vzc2lvbihzZWxmLCBkYXRlX3N0"
    "cjogc3RyKSAtPiBOb25lOgogICAgICAgIGN0eCA9IHNlbGYuX3Nlc3Npb25zLmxvYWRfc2Vzc2lv"
    "bl9hc19jb250ZXh0KGRhdGVfc3RyKQogICAgICAgIGlmIG5vdCBjdHg6CiAgICAgICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0pPVVJOQUxdIE5vIHNlc3Npb24g"
    "Zm91bmQgZm9yIHtkYXRlX3N0cn0iLCAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2V0X2pvdXJuYWxfbG9hZGVkKGRh"
    "dGVfc3RyKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbSk9VUk5B"
    "TF0gTG9hZGVkIHNlc3Npb24gZnJvbSB7ZGF0ZV9zdHJ9IGFzIGNvbnRleHQuICIKICAgICAgICAg"
    "ICAgZiJ7REVDS19OQU1FfSBpcyBub3cgYXdhcmUgb2YgdGhhdCBjb252ZXJzYXRpb24uIiwgIk9L"
    "IgogICAgICAgICkKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAg"
    "ICAgZiJBIG1lbW9yeSBzdGlycy4uLiB0aGUgam91cm5hbCBvZiB7ZGF0ZV9zdHJ9IG9wZW5zIGJl"
    "Zm9yZSBoZXIuIgogICAgICAgICkKICAgICAgICAjIE5vdGlmeSBNb3JnYW5uYQogICAgICAgIGlm"
    "IHNlbGYuX21vZGVsX2xvYWRlZDoKICAgICAgICAgICAgbm90ZSA9ICgKICAgICAgICAgICAgICAg"
    "IGYiW0pPVVJOQUwgTE9BREVEXSBUaGUgdXNlciBoYXMgb3BlbmVkIHRoZSBqb3VybmFsIGZyb20g"
    "IgogICAgICAgICAgICAgICAgZiJ7ZGF0ZV9zdHJ9LiBBY2tub3dsZWRnZSB0aGlzIGJyaWVmbHkg"
    "4oCUIHlvdSBub3cgaGF2ZSAiCiAgICAgICAgICAgICAgICBmImF3YXJlbmVzcyBvZiB0aGF0IGNv"
    "bnZlcnNhdGlvbi4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbnMuYWRk"
    "X21lc3NhZ2UoInN5c3RlbSIsIG5vdGUpCgogICAgZGVmIF9jbGVhcl9qb3VybmFsX3Nlc3Npb24o"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zZXNzaW9ucy5jbGVhcl9sb2FkZWRfam91cm5h"
    "bCgpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbSk9VUk5BTF0gSm91cm5hbCBjb250ZXh0"
    "IGNsZWFyZWQuIiwgIklORk8iKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAog"
    "ICAgICAgICAgICAiVGhlIGpvdXJuYWwgY2xvc2VzLiBPbmx5IHRoZSBwcmVzZW50IHJlbWFpbnMu"
    "IgogICAgICAgICkKCiAgICAjIOKUgOKUgCBTVEFUUyBVUERBVEUg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3Vw"
    "ZGF0ZV9zdGF0cyhzZWxmKSAtPiBOb25lOgogICAgICAgIGVsYXBzZWQgPSBpbnQodGltZS50aW1l"
    "KCkgLSBzZWxmLl9zZXNzaW9uX3N0YXJ0KQogICAgICAgIGgsIG0sIHMgPSBlbGFwc2VkIC8vIDM2"
    "MDAsIChlbGFwc2VkICUgMzYwMCkgLy8gNjAsIGVsYXBzZWQgJSA2MAogICAgICAgIHNlc3Npb25f"
    "c3RyID0gZiJ7aDowMmR9OnttOjAyZH06e3M6MDJkfSIKCiAgICAgICAgc2VsZi5faHdfcGFuZWwu"
    "c2V0X3N0YXR1c19sYWJlbHMoCiAgICAgICAgICAgIHNlbGYuX3N0YXR1cywKICAgICAgICAgICAg"
    "Q0ZHWyJtb2RlbCJdLmdldCgidHlwZSIsImxvY2FsIikudXBwZXIoKSwKICAgICAgICAgICAgc2Vz"
    "c2lvbl9zdHIsCiAgICAgICAgICAgIHN0cihzZWxmLl90b2tlbl9jb3VudCksCiAgICAgICAgKQog"
    "ICAgICAgIHNlbGYuX2h3X3BhbmVsLnVwZGF0ZV9zdGF0cygpCgogICAgICAgICMgTUFOQSBzcGhl"
    "cmUgPSBWUkFNIGF2YWlsYWJpbGl0eQogICAgICAgIGlmIHNlbGYuX21hbmFfc3BoZXJlIGlzIG5v"
    "dCBOb25lIGFuZCBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRs"
    "ZSkKICAgICAgICAgICAgICAgIHZyYW1fdXNlZCA9IG1lbS51c2VkICAvIDEwMjQqKjMKICAgICAg"
    "ICAgICAgICAgIHZyYW1fdG90ICA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAgICAgICAgICAgICAg"
    "IG1hbmFfZmlsbCA9IG1heCgwLjAsIDEuMCAtICh2cmFtX3VzZWQgLyB2cmFtX3RvdCkpCiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9tYW5hX3NwaGVyZS5zZXRGaWxsKG1hbmFfZmlsbCwgYXZhaWxhYmxl"
    "PVRydWUpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9tYW5hX3NwaGVyZS5zZXRGaWxsKDAuMCwgYXZhaWxhYmxlPUZhbHNlKQoKICAgICAgICAjIEhV"
    "TkdFUiA9IGludmVyc2Ugb2YgYmxvb2QKICAgICAgICBibG9vZF9maWxsID0gbWluKDEuMCwgc2Vs"
    "Zi5fdG9rZW5fY291bnQgLyA0MDk2LjApCiAgICAgICAgaHVuZ2VyICAgICA9IDEuMCAtIGJsb29k"
    "X2ZpbGwKICAgICAgICBpZiBBSV9TVEFURVNfRU5BQkxFRDoKICAgICAgICAgICAgc2VsZi5faHVu"
    "Z2VyX2dhdWdlLnNldFZhbHVlKGh1bmdlciAqIDEwMCwgZiJ7aHVuZ2VyKjEwMDouMGZ9JSIpCgog"
    "ICAgICAgICMgVklUQUxJVFkgPSBSQU0gZnJlZQogICAgICAgIGlmIFBTVVRJTF9PSzoKICAgICAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICAgICAgbWVtICAgICAgID0gcHN1dGlsLnZpcnR1YWxfbWVt"
    "b3J5KCkKICAgICAgICAgICAgICAgIHZpdGFsaXR5ICA9IDEuMCAtIChtZW0udXNlZCAvIG1lbS50"
    "b3RhbCkKICAgICAgICAgICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgICAgICAg"
    "ICAgICAgIHNlbGYuX3ZpdGFsaXR5X2dhdWdlLnNldFZhbHVlKAogICAgICAgICAgICAgICAgICAg"
    "ICAgICB2aXRhbGl0eSAqIDEwMCwgZiJ7dml0YWxpdHkqMTAwOi4wZn0lIgogICAgICAgICAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBh"
    "c3MKCiAgICAgICAgIyBVcGRhdGUgam91cm5hbCBzaWRlYmFyIGF1dG9zYXZlIGZsYXNoCiAgICAg"
    "ICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnJlZnJlc2goKQoKICAgICMg4pSA4pSAIENIQVQgRElT"
    "UExBWSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKICAgIGRlZiBfYXBwZW5kX2NoYXQoc2VsZiwgc3BlYWtlcjogc3RyLCB0ZXh0"
    "OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgY29sb3JzID0gewogICAgICAgICAgICAiWU9VIjogICAg"
    "IENfR09MRCwKICAgICAgICAgICAgREVDS19OQU1FLnVwcGVyKCk6Q19HT0xELAogICAgICAgICAg"
    "ICAiU1lTVEVNIjogIENfUFVSUExFLAogICAgICAgICAgICAiRVJST1IiOiAgIENfQkxPT0QsCiAg"
    "ICAgICAgfQogICAgICAgIGxhYmVsX2NvbG9ycyA9IHsKICAgICAgICAgICAgIllPVSI6ICAgICBD"
    "X0dPTERfRElNLAogICAgICAgICAgICBERUNLX05BTUUudXBwZXIoKTpDX0NSSU1TT04sCiAgICAg"
    "ICAgICAgICJTWVNURU0iOiAgQ19QVVJQTEUsCiAgICAgICAgICAgICJFUlJPUiI6ICAgQ19CTE9P"
    "RCwKICAgICAgICB9CiAgICAgICAgY29sb3IgICAgICAgPSBjb2xvcnMuZ2V0KHNwZWFrZXIsIENf"
    "R09MRCkKICAgICAgICBsYWJlbF9jb2xvciA9IGxhYmVsX2NvbG9ycy5nZXQoc3BlYWtlciwgQ19H"
    "T0xEX0RJTSkKICAgICAgICB0aW1lc3RhbXAgICA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIl"
    "SDolTTolUyIpCgogICAgICAgIGlmIHNwZWFrZXIgPT0gIlNZU1RFTSI6CiAgICAgICAgICAgIHNl"
    "bGYuX2NoYXRfZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJj"
    "b2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICAgICAgZidb"
    "e3RpbWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xv"
    "cjp7bGFiZWxfY29sb3J9OyI+4pymIHt0ZXh0fTwvc3Bhbj4nCiAgICAgICAgICAgICkKICAgICAg"
    "ICBlbHNlOgogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAg"
    "ICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsi"
    "PicKICAgICAgICAgICAgICAgIGYnW3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAgICAgICAg"
    "ICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2xhYmVsX2NvbG9yfTsgZm9udC13ZWlnaHQ6Ym9sZDsi"
    "PicKICAgICAgICAgICAgICAgIGYne3NwZWFrZXJ9IOKdpzwvc3Bhbj4gJwogICAgICAgICAgICAg"
    "ICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2NvbG9yfTsiPnt0ZXh0fTwvc3Bhbj4nCiAgICAgICAg"
    "ICAgICkKCiAgICAgICAgIyBBZGQgYmxhbmsgbGluZSBhZnRlciBNb3JnYW5uYSdzIHJlc3BvbnNl"
    "IChub3QgZHVyaW5nIHN0cmVhbWluZykKICAgICAgICBpZiBzcGVha2VyID09IERFQ0tfTkFNRS51"
    "cHBlcigpOgogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKCIiKQoKICAgICAg"
    "ICBzZWxmLl9jaGF0X2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAg"
    "ICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAg"
    "ICAgICAgKQoKICAgICMg4pSA4pSAIFNUQVRVUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "IGRlZiBfc2V0X3N0YXR1cyhzZWxmLCBzdGF0dXM6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9zdGF0dXMgPSBzdGF0dXMKICAgICAgICBzdGF0dXNfY29sb3JzID0gewogICAgICAgICAgICAi"
    "SURMRSI6ICAgICAgIENfR09MRCwKICAgICAgICAgICAgIkdFTkVSQVRJTkciOiBDX0NSSU1TT04s"
    "CiAgICAgICAgICAgICJMT0FESU5HIjogICAgQ19QVVJQTEUsCiAgICAgICAgICAgICJFUlJPUiI6"
    "ICAgICAgQ19CTE9PRCwKICAgICAgICAgICAgIk9GRkxJTkUiOiAgICBDX0JMT09ELAogICAgICAg"
    "ICAgICAiVE9SUE9SIjogICAgIENfUFVSUExFX0RJTSwKICAgICAgICB9CiAgICAgICAgY29sb3Ig"
    "PSBzdGF0dXNfY29sb3JzLmdldChzdGF0dXMsIENfVEVYVF9ESU0pCgogICAgICAgIHRvcnBvcl9s"
    "YWJlbCA9IGYi4peJIHtVSV9UT1JQT1JfU1RBVFVTfSIgaWYgc3RhdHVzID09ICJUT1JQT1IiIGVs"
    "c2UgZiLil4kge3N0YXR1c30iCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dCh0b3Jw"
    "b3JfbGFiZWwpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiAxMnB4OyBmb250LXdlaWdodDogYm9s"
    "ZDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCgogICAgZGVmIF9ibGluayhzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuX2JsaW5rX3N0YXRlID0gbm90IHNlbGYuX2JsaW5rX3N0YXRlCiAgICAg"
    "ICAgaWYgc2VsZi5fc3RhdHVzID09ICJHRU5FUkFUSU5HIjoKICAgICAgICAgICAgY2hhciA9ICLi"
    "l4kiIGlmIHNlbGYuX2JsaW5rX3N0YXRlIGVsc2UgIuKXjiIKICAgICAgICAgICAgc2VsZi5zdGF0"
    "dXNfbGFiZWwuc2V0VGV4dChmIntjaGFyfSBHRU5FUkFUSU5HIikKICAgICAgICBlbGlmIHNlbGYu"
    "X3N0YXR1cyA9PSAiVE9SUE9SIjoKICAgICAgICAgICAgY2hhciA9ICLil4kiIGlmIHNlbGYuX2Js"
    "aW5rX3N0YXRlIGVsc2UgIuKKmCIKICAgICAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4"
    "dCgKICAgICAgICAgICAgICAgIGYie2NoYXJ9IHtVSV9UT1JQT1JfU1RBVFVTfSIKICAgICAgICAg"
    "ICAgKQoKICAgICMg4pSA4pSAIElETEUgVE9HR0xFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9vbl9pZGxl"
    "X3RvZ2dsZWQoc2VsZiwgZW5hYmxlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBDRkdbInNldHRp"
    "bmdzIl1bImlkbGVfZW5hYmxlZCJdID0gZW5hYmxlZAogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNl"
    "dFRleHQoIklETEUgT04iIGlmIGVuYWJsZWQgZWxzZSAiSURMRSBPRkYiKQogICAgICAgIHNlbGYu"
    "X2lkbGVfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogeycjMWEx"
    "MDA1JyBpZiBlbmFibGVkIGVsc2UgQ19CRzN9OyAiCiAgICAgICAgICAgIGYiY29sb3I6IHsnI2Nj"
    "ODgyMicgaWYgZW5hYmxlZCBlbHNlIENfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVy"
    "OiAxcHggc29saWQgeycjY2M4ODIyJyBpZiBlbmFibGVkIGVsc2UgQ19CT1JERVJ9OyAiCiAgICAg"
    "ICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyBmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6"
    "IGJvbGQ7ICIKICAgICAgICAgICAgZiJwYWRkaW5nOiAzcHggOHB4OyIKICAgICAgICApCiAgICAg"
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
    "CiAgICAgICAgICAgIHNlbGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAgIHNlbGYuX2ZzX2J0bi5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xv"
    "cjoge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlk"
    "IHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToK"
    "ICAgICAgICAgICAgc2VsZi5zaG93RnVsbFNjcmVlbigpCiAgICAgICAgICAgIHNlbGYuX2ZzX2J0"
    "bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19DUklNU09O"
    "X0RJTX07IGNvbG9yOiB7Q19DUklNU09OfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19DUklNU09OfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYi"
    "Zm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCgogICAgZGVmIF90"
    "b2dnbGVfYm9yZGVybGVzcyhzZWxmKSAtPiBOb25lOgogICAgICAgIGlzX2JsID0gYm9vbChzZWxm"
    "LndpbmRvd0ZsYWdzKCkgJiBRdC5XaW5kb3dUeXBlLkZyYW1lbGVzc1dpbmRvd0hpbnQpCiAgICAg"
    "ICAgaWYgaXNfYmw6CiAgICAgICAgICAgIHNlbGYuc2V0V2luZG93RmxhZ3MoCiAgICAgICAgICAg"
    "ICAgICBzZWxmLndpbmRvd0ZsYWdzKCkgJiB+UXQuV2luZG93VHlwZS5GcmFtZWxlc3NXaW5kb3dI"
    "aW50CiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fYmxfYnRuLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19DUklNU09O"
    "X0RJTX07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9E"
    "SU19OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9s"
    "ZDsgcGFkZGluZzogMDsiCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBp"
    "ZiBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAgICAgICAgICAgc2VsZi5zaG93Tm9ybWFsKCkK"
    "ICAgICAgICAgICAgc2VsZi5zZXRXaW5kb3dGbGFncygKICAgICAgICAgICAgICAgIHNlbGYud2lu"
    "ZG93RmxhZ3MoKSB8IFF0LldpbmRvd1R5cGUuRnJhbWVsZXNzV2luZG93SGludAogICAgICAgICAg"
    "ICApCiAgICAgICAgICAgIHNlbGYuX2JsX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAg"
    "ICAgZiJiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IGNvbG9yOiB7Q19DUklNU09OfTsgIgog"
    "ICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgZm9udC1zaXpl"
    "OiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7"
    "IgogICAgICAgICAgICApCiAgICAgICAgc2VsZi5zaG93KCkKCiAgICBkZWYgX2V4cG9ydF9jaGF0"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiRXhwb3J0IGN1cnJlbnQgcGVyc29uYSBjaGF0IHRh"
    "YiBjb250ZW50IHRvIGEgVFhUIGZpbGUuIiIiCiAgICAgICAgdHJ5OgogICAgICAgICAgICB0ZXh0"
    "ID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRvUGxhaW5UZXh0KCkKICAgICAgICAgICAgaWYgbm90IHRl"
    "eHQuc3RyaXAoKToKICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgICAgICBleHBvcnRfZGly"
    "ID0gY2ZnX3BhdGgoImV4cG9ydHMiKQogICAgICAgICAgICBleHBvcnRfZGlyLm1rZGlyKHBhcmVu"
    "dHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAgICAgdHMgPSBkYXRldGltZS5ub3coKS5z"
    "dHJmdGltZSgiJVklbSVkXyVIJU0lUyIpCiAgICAgICAgICAgIG91dF9wYXRoID0gZXhwb3J0X2Rp"
    "ciAvIGYic2VhbmNlX3t0c30udHh0IgogICAgICAgICAgICBvdXRfcGF0aC53cml0ZV90ZXh0KHRl"
    "eHQsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgICAgICAgICAjIEFsc28gY29weSB0byBjbGlwYm9h"
    "cmQKICAgICAgICAgICAgUUFwcGxpY2F0aW9uLmNsaXBib2FyZCgpLnNldFRleHQodGV4dCkKCiAg"
    "ICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAgICAgZiJT"
    "ZXNzaW9uIGV4cG9ydGVkIHRvIHtvdXRfcGF0aC5uYW1lfSBhbmQgY29waWVkIHRvIGNsaXBib2Fy"
    "ZC4iKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbRVhQT1JUXSB7b3V0X3BhdGh9"
    "IiwgIk9LIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZyhmIltFWFBPUlRdIEZhaWxlZDoge2V9IiwgIkVSUk9SIikKCiAgICBkZWYg"
    "a2V5UHJlc3NFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBrZXkgPSBldmVudC5r"
    "ZXkoKQogICAgICAgIGlmIGtleSA9PSBRdC5LZXkuS2V5X0YxMToKICAgICAgICAgICAgc2VsZi5f"
    "dG9nZ2xlX2Z1bGxzY3JlZW4oKQogICAgICAgIGVsaWYga2V5ID09IFF0LktleS5LZXlfRjEwOgog"
    "ICAgICAgICAgICBzZWxmLl90b2dnbGVfYm9yZGVybGVzcygpCiAgICAgICAgZWxpZiBrZXkgPT0g"
    "UXQuS2V5LktleV9Fc2NhcGUgYW5kIHNlbGYuaXNGdWxsU2NyZWVuKCk6CiAgICAgICAgICAgIHNl"
    "bGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAgIHNlbGYuX2ZzX2J0bi5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9E"
    "SU19OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElN"
    "fTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7"
    "IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc3Vw"
    "ZXIoKS5rZXlQcmVzc0V2ZW50KGV2ZW50KQoKICAgICMg4pSA4pSAIENMT1NFIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGNsb3NlRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6"
    "CiAgICAgICAgIyBYIGJ1dHRvbiA9IGltbWVkaWF0ZSBzaHV0ZG93biwgbm8gZGlhbG9nCiAgICAg"
    "ICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKCiAgICBkZWYgX2luaXRpYXRlX3NodXRkb3duX2Rp"
    "YWxvZyhzZWxmKSAtPiBOb25lOgogICAgICAgICIiIkdyYWNlZnVsIHNodXRkb3duIOKAlCBzaG93"
    "IGNvbmZpcm0gZGlhbG9nIGltbWVkaWF0ZWx5LCBvcHRpb25hbGx5IGdldCBsYXN0IHdvcmRzLiIi"
    "IgogICAgICAgICMgSWYgYWxyZWFkeSBpbiBhIHNodXRkb3duIHNlcXVlbmNlLCBqdXN0IGZvcmNl"
    "IHF1aXQKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICdfc2h1dGRvd25faW5fcHJvZ3Jlc3MnLCBG"
    "YWxzZSk6CiAgICAgICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCiAgICAgICAgICAgIHJl"
    "dHVybgogICAgICAgIHNlbGYuX3NodXRkb3duX2luX3Byb2dyZXNzID0gVHJ1ZQoKICAgICAgICAj"
    "IFNob3cgY29uZmlybSBkaWFsb2cgRklSU1Qg4oCUIGRvbid0IHdhaXQgZm9yIEFJCiAgICAgICAg"
    "ZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiRGVhY3RpdmF0"
    "ZT8iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6"
    "IHtDX0JHMn07IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7"
    "REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBkbGcuc2V0Rml4ZWRTaXplKDM4"
    "MCwgMTQwKQogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KGRsZykKCiAgICAgICAgbGJsID0g"
    "UUxhYmVsKAogICAgICAgICAgICBmIkRlYWN0aXZhdGUge0RFQ0tfTkFNRX0/XG5cbiIKICAgICAg"
    "ICAgICAgZiJ7REVDS19OQU1FfSBtYXkgc3BlYWsgdGhlaXIgbGFzdCB3b3JkcyBiZWZvcmUgZ29p"
    "bmcgc2lsZW50LiIKICAgICAgICApCiAgICAgICAgbGJsLnNldFdvcmRXcmFwKFRydWUpCiAgICAg"
    "ICAgbGF5b3V0LmFkZFdpZGdldChsYmwpCgogICAgICAgIGJ0bl9yb3cgPSBRSEJveExheW91dCgp"
    "CiAgICAgICAgYnRuX2xhc3QgID0gUVB1c2hCdXR0b24oIkxhc3QgV29yZHMgKyBTaHV0ZG93biIp"
    "CiAgICAgICAgYnRuX25vdyAgID0gUVB1c2hCdXR0b24oIlNodXRkb3duIE5vdyIpCiAgICAgICAg"
    "YnRuX2NhbmNlbCA9IFFQdXNoQnV0dG9uKCJDYW5jZWwiKQoKICAgICAgICBmb3IgYiBpbiAoYnRu"
    "X2xhc3QsIGJ0bl9ub3csIGJ0bl9jYW5jZWwpOgogICAgICAgICAgICBiLnNldE1pbmltdW1IZWln"
    "aHQoMjgpCiAgICAgICAgICAgIGIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFj"
    "a2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFR9OyAiCiAgICAgICAgICAgICAgICBmImJv"
    "cmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IHBhZGRpbmc6IDRweCAxMnB4OyIKICAgICAgICAg"
    "ICAgKQogICAgICAgIGJ0bl9ub3cuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3Jv"
    "dW5kOiB7Q19CTE9PRH07IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAgICAgICBmImJvcmRlcjog"
    "MXB4IHNvbGlkIHtDX0NSSU1TT059OyBwYWRkaW5nOiA0cHggMTJweDsiCiAgICAgICAgKQogICAg"
    "ICAgIGJ0bl9sYXN0LmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IGRsZy5kb25lKDEpKQogICAgICAg"
    "IGJ0bl9ub3cuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogZGxnLmRvbmUoMikpCiAgICAgICAgYnRu"
    "X2NhbmNlbC5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBkbGcuZG9uZSgwKSkKICAgICAgICBidG5f"
    "cm93LmFkZFdpZGdldChidG5fY2FuY2VsKQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9u"
    "b3cpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2xhc3QpCiAgICAgICAgbGF5b3V0LmFk"
    "ZExheW91dChidG5fcm93KQoKICAgICAgICByZXN1bHQgPSBkbGcuZXhlYygpCgogICAgICAgIGlm"
    "IHJlc3VsdCA9PSAwOgogICAgICAgICAgICAjIENhbmNlbGxlZAogICAgICAgICAgICBzZWxmLl9z"
    "aHV0ZG93bl9pbl9wcm9ncmVzcyA9IEZhbHNlCiAgICAgICAgICAgIHNlbGYuX3NlbmRfYnRuLnNl"
    "dEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChU"
    "cnVlKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBlbGlmIHJlc3VsdCA9PSAyOgogICAgICAg"
    "ICAgICAjIFNodXRkb3duIG5vdyDigJQgbm8gbGFzdCB3b3JkcwogICAgICAgICAgICBzZWxmLl9k"
    "b19zaHV0ZG93bihOb25lKQogICAgICAgIGVsaWYgcmVzdWx0ID09IDE6CiAgICAgICAgICAgICMg"
    "TGFzdCB3b3JkcyB0aGVuIHNodXRkb3duCiAgICAgICAgICAgIHNlbGYuX2dldF9sYXN0X3dvcmRz"
    "X3RoZW5fc2h1dGRvd24oKQoKICAgIGRlZiBfZ2V0X2xhc3Rfd29yZHNfdGhlbl9zaHV0ZG93bihz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgICIiIlNlbmQgZmFyZXdlbGwgcHJvbXB0LCBzaG93IHJlc3Bv"
    "bnNlLCB0aGVuIHNodXRkb3duIGFmdGVyIHRpbWVvdXQuIiIiCiAgICAgICAgZmFyZXdlbGxfcHJv"
    "bXB0ID0gKAogICAgICAgICAgICAiWW91IGFyZSBiZWluZyBkZWFjdGl2YXRlZC4gVGhlIGRhcmtu"
    "ZXNzIGFwcHJvYWNoZXMuICIKICAgICAgICAgICAgIlNwZWFrIHlvdXIgZmluYWwgd29yZHMgYmVm"
    "b3JlIHRoZSB2ZXNzZWwgZ29lcyBzaWxlbnQg4oCUICIKICAgICAgICAgICAgIm9uZSByZXNwb25z"
    "ZSBvbmx5LCB0aGVuIHlvdSByZXN0LiIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXBwZW5kX2No"
    "YXQoIlNZU1RFTSIsCiAgICAgICAgICAgICLinKYgU2hlIGlzIGdpdmVuIGEgbW9tZW50IHRvIHNw"
    "ZWFrIGhlciBmaW5hbCB3b3Jkcy4uLiIKICAgICAgICApCiAgICAgICAgc2VsZi5fc2VuZF9idG4u"
    "c2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKEZh"
    "bHNlKQogICAgICAgIHNlbGYuX3NodXRkb3duX2ZhcmV3ZWxsX3RleHQgPSAiIgoKICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCiAg"
    "ICAgICAgICAgIGhpc3RvcnkuYXBwZW5kKHsicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiBmYXJl"
    "d2VsbF9wcm9tcHR9KQogICAgICAgICAgICB3b3JrZXIgPSBTdHJlYW1pbmdXb3JrZXIoCiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9hZGFwdG9yLCBTWVNURU1fUFJPTVBUX0JBU0UsIGhpc3RvcnksIG1h"
    "eF90b2tlbnM9MjU2CiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fd29y"
    "a2VyID0gd29ya2VyCiAgICAgICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gVHJ1ZQoKICAgICAg"
    "ICAgICAgZGVmIF9vbl9kb25lKHJlc3BvbnNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9zaHV0ZG93bl9mYXJld2VsbF90ZXh0ID0gcmVzcG9uc2UKICAgICAgICAgICAgICAg"
    "IHNlbGYuX29uX3Jlc3BvbnNlX2RvbmUocmVzcG9uc2UpCiAgICAgICAgICAgICAgICAjIFNtYWxs"
    "IGRlbGF5IHRvIGxldCB0aGUgdGV4dCByZW5kZXIsIHRoZW4gc2h1dGRvd24KICAgICAgICAgICAg"
    "ICAgIFFUaW1lci5zaW5nbGVTaG90KDIwMDAsIGxhbWJkYTogc2VsZi5fZG9fc2h1dGRvd24oTm9u"
    "ZSkpCgogICAgICAgICAgICBkZWYgX29uX2Vycm9yKGVycm9yOiBzdHIpIC0+IE5vbmU6CiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbU0hVVERPV05dW1dBUk5dIExhc3Qgd29y"
    "ZHMgZmFpbGVkOiB7ZXJyb3J9IiwgIldBUk4iKQogICAgICAgICAgICAgICAgc2VsZi5fZG9fc2h1"
    "dGRvd24oTm9uZSkKCiAgICAgICAgICAgIHdvcmtlci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYu"
    "X29uX3Rva2VuKQogICAgICAgICAgICB3b3JrZXIucmVzcG9uc2VfZG9uZS5jb25uZWN0KF9vbl9k"
    "b25lKQogICAgICAgICAgICB3b3JrZXIuZXJyb3Jfb2NjdXJyZWQuY29ubmVjdChfb25fZXJyb3Ip"
    "CiAgICAgICAgICAgIHdvcmtlci5zdGF0dXNfY2hhbmdlZC5jb25uZWN0KHNlbGYuX3NldF9zdGF0"
    "dXMpCiAgICAgICAgICAgIHdvcmtlci5maW5pc2hlZC5jb25uZWN0KHdvcmtlci5kZWxldGVMYXRl"
    "cikKICAgICAgICAgICAgd29ya2VyLnN0YXJ0KCkKCiAgICAgICAgICAgICMgU2FmZXR5IHRpbWVv"
    "dXQg4oCUIGlmIEFJIGRvZXNuJ3QgcmVzcG9uZCBpbiAxNXMsIHNodXQgZG93biBhbnl3YXkKICAg"
    "ICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMTUwMDAsIGxhbWJkYTogc2VsZi5fZG9fc2h1dGRv"
    "d24oTm9uZSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAn"
    "X3NodXRkb3duX2luX3Byb2dyZXNzJywgRmFsc2UpIGVsc2UgTm9uZSkKCiAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAg"
    "ICAgICAgICBmIltTSFVURE9XTl1bV0FSTl0gTGFzdCB3b3JkcyBza2lwcGVkIGR1ZSB0byBlcnJv"
    "cjoge2V9IiwKICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAgICApCiAgICAgICAgICAg"
    "ICMgSWYgYW55dGhpbmcgZmFpbHMsIGp1c3Qgc2h1dCBkb3duCiAgICAgICAgICAgIHNlbGYuX2Rv"
    "X3NodXRkb3duKE5vbmUpCgogICAgZGVmIF9kb19zaHV0ZG93bihzZWxmLCBldmVudCkgLT4gTm9u"
    "ZToKICAgICAgICAiIiJQZXJmb3JtIGFjdHVhbCBzaHV0ZG93biBzZXF1ZW5jZS4iIiIKICAgICAg"
    "ICAjIFNhdmUgc2Vzc2lvbgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbnMu"
    "c2F2ZSgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgICAg"
    "ICAjIFN0b3JlIGZhcmV3ZWxsICsgbGFzdCBjb250ZXh0IGZvciB3YWtlLXVwCiAgICAgICAgdHJ5"
    "OgogICAgICAgICAgICAjIEdldCBsYXN0IDMgbWVzc2FnZXMgZnJvbSBzZXNzaW9uIGhpc3Rvcnkg"
    "Zm9yIHdha2UtdXAgY29udGV4dAogICAgICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMu"
    "Z2V0X2hpc3RvcnkoKQogICAgICAgICAgICBsYXN0X2NvbnRleHQgPSBoaXN0b3J5Wy0zOl0gaWYg"
    "bGVuKGhpc3RvcnkpID49IDMgZWxzZSBoaXN0b3J5CiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJs"
    "YXN0X3NodXRkb3duX2NvbnRleHQiXSA9IFsKICAgICAgICAgICAgICAgIHsicm9sZSI6IG0uZ2V0"
    "KCJyb2xlIiwiIiksICJjb250ZW50IjogbS5nZXQoImNvbnRlbnQiLCIiKVs6MzAwXX0KICAgICAg"
    "ICAgICAgICAgIGZvciBtIGluIGxhc3RfY29udGV4dAogICAgICAgICAgICBdCiAgICAgICAgICAg"
    "ICMgRXh0cmFjdCBNb3JnYW5uYSdzIG1vc3QgcmVjZW50IG1lc3NhZ2UgYXMgZmFyZXdlbGwKICAg"
    "ICAgICAgICAgIyBQcmVmZXIgdGhlIGNhcHR1cmVkIHNodXRkb3duIGRpYWxvZyByZXNwb25zZSBp"
    "ZiBhdmFpbGFibGUKICAgICAgICAgICAgZmFyZXdlbGwgPSBnZXRhdHRyKHNlbGYsICdfc2h1dGRv"
    "d25fZmFyZXdlbGxfdGV4dCcsICIiKQogICAgICAgICAgICBpZiBub3QgZmFyZXdlbGw6CiAgICAg"
    "ICAgICAgICAgICBmb3IgbSBpbiByZXZlcnNlZChoaXN0b3J5KToKICAgICAgICAgICAgICAgICAg"
    "ICBpZiBtLmdldCgicm9sZSIpID09ICJhc3Npc3RhbnQiOgogICAgICAgICAgICAgICAgICAgICAg"
    "ICBmYXJld2VsbCA9IG0uZ2V0KCJjb250ZW50IiwgIiIpWzo0MDBdCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGJyZWFrCiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X2ZhcmV3ZWxsIl0gPSBm"
    "YXJld2VsbAogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAg"
    "ICAgIyBTYXZlIHN0YXRlCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFz"
    "dF9zaHV0ZG93biJdICAgICAgICAgICAgID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgIHNl"
    "bGYuX3N0YXRlWyJsYXN0X2FjdGl2ZSJdICAgICAgICAgICAgICAgPSBsb2NhbF9ub3dfaXNvKCkK"
    "ICAgICAgICAgICAgc2VsZi5fc3RhdGVbInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24iXSAgPSBn"
    "ZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAgICAgICAgIHNlbGYuX21lbW9yeS5zYXZlX3N0YXRlKHNl"
    "bGYuX3N0YXRlKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAg"
    "ICAgICAgIyBTdG9wIHNjaGVkdWxlcgogICAgICAgIGlmIGhhc2F0dHIoc2VsZiwgIl9zY2hlZHVs"
    "ZXIiKSBhbmQgc2VsZi5fc2NoZWR1bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAg"
    "ICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnNodXRkb3duKHdh"
    "aXQ9RmFsc2UpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBw"
    "YXNzCgogICAgICAgICMgUGxheSBzaHV0ZG93biBzb3VuZAogICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgc2VsZi5fc2h1dGRvd25fc291bmQgPSBTb3VuZFdvcmtlcigic2h1dGRvd24iKQogICAgICAg"
    "ICAgICBzZWxmLl9zaHV0ZG93bl9zb3VuZC5maW5pc2hlZC5jb25uZWN0KHNlbGYuX3NodXRkb3du"
    "X3NvdW5kLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICBzZWxmLl9zaHV0ZG93bl9zb3VuZC5zdGFy"
    "dCgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgICAgICBR"
    "QXBwbGljYXRpb24ucXVpdCgpCgoKIyDilIDilIAgRU5UUlkgUE9JTlQg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmRlZiBtYWluKCkgLT4gTm9uZToKICAgICIiIgogICAgQXBwbGljYXRpb24gZW50cnkgcG9p"
    "bnQuCgogICAgT3JkZXIgb2Ygb3BlcmF0aW9uczoKICAgIDEuIFByZS1mbGlnaHQgZGVwZW5kZW5j"
    "eSBib290c3RyYXAgKGF1dG8taW5zdGFsbCBtaXNzaW5nIGRlcHMpCiAgICAyLiBDaGVjayBmb3Ig"
    "Zmlyc3QgcnVuIOKGkiBzaG93IEZpcnN0UnVuRGlhbG9nCiAgICAgICBPbiBmaXJzdCBydW46CiAg"
    "ICAgICAgIGEuIENyZWF0ZSBEOi9BSS9Nb2RlbHMvW0RlY2tOYW1lXS8gKG9yIGNob3NlbiBiYXNl"
    "X2RpcikKICAgICAgICAgYi4gQ29weSBbZGVja25hbWVdX2RlY2sucHkgaW50byB0aGF0IGZvbGRl"
    "cgogICAgICAgICBjLiBXcml0ZSBjb25maWcuanNvbiBpbnRvIHRoYXQgZm9sZGVyCiAgICAgICAg"
    "IGQuIEJvb3RzdHJhcCBhbGwgc3ViZGlyZWN0b3JpZXMgdW5kZXIgdGhhdCBmb2xkZXIKICAgICAg"
    "ICAgZS4gQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgcG9pbnRpbmcgdG8gbmV3IGxvY2F0aW9uCiAg"
    "ICAgICAgIGYuIFNob3cgY29tcGxldGlvbiBtZXNzYWdlIGFuZCBFWElUIOKAlCB1c2VyIHVzZXMg"
    "c2hvcnRjdXQgZnJvbSBub3cgb24KICAgIDMuIE5vcm1hbCBydW4g4oCUIGxhdW5jaCBRQXBwbGlj"
    "YXRpb24gYW5kIEVjaG9EZWNrCiAgICAiIiIKICAgIGltcG9ydCBzaHV0aWwgYXMgX3NodXRpbAoK"
    "ICAgICMg4pSA4pSAIFBoYXNlIDE6IERlcGVuZGVuY3kgYm9vdHN0cmFwIChwcmUtUUFwcGxpY2F0"
    "aW9uKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGJvb3Rz"
    "dHJhcF9jaGVjaygpCgogICAgIyDilIDilIAgUGhhc2UgMjogUUFwcGxpY2F0aW9uIChuZWVkZWQg"
    "Zm9yIGRpYWxvZ3MpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgX2Vhcmx5X2xvZygiW01BSU5dIENyZWF0aW5nIFFBcHBsaWNh"
    "dGlvbiIpCiAgICBhcHAgPSBRQXBwbGljYXRpb24oc3lzLmFyZ3YpCiAgICBhcHAuc2V0QXBwbGlj"
    "YXRpb25OYW1lKEFQUF9OQU1FKQoKICAgICMgSW5zdGFsbCBRdCBtZXNzYWdlIGhhbmRsZXIgTk9X"
    "IOKAlCBjYXRjaGVzIGFsbCBRVGhyZWFkL1F0IHdhcm5pbmdzCiAgICAjIHdpdGggZnVsbCBzdGFj"
    "ayB0cmFjZXMgZnJvbSB0aGlzIHBvaW50IGZvcndhcmQKICAgIF9pbnN0YWxsX3F0X21lc3NhZ2Vf"
    "aGFuZGxlcigpCiAgICBfZWFybHlfbG9nKCJbTUFJTl0gUUFwcGxpY2F0aW9uIGNyZWF0ZWQsIG1l"
    "c3NhZ2UgaGFuZGxlciBpbnN0YWxsZWQiKQoKICAgICMg4pSA4pSAIFBoYXNlIDM6IEZpcnN0IHJ1"
    "biBjaGVjayDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKICAgIGlzX2ZpcnN0X3J1biA9IENGRy5nZXQoImZpcnN0X3J1biIsIFRydWUp"
    "CgogICAgaWYgaXNfZmlyc3RfcnVuOgogICAgICAgIGRsZyA9IEZpcnN0UnVuRGlhbG9nKCkKICAg"
    "ICAgICBpZiBkbGcuZXhlYygpICE9IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAg"
    "ICAgICAgc3lzLmV4aXQoMCkKCiAgICAgICAgIyDilIDilIAgQnVpbGQgY29uZmlnIGZyb20gZGlh"
    "bG9nIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ICAgIG5ld19jZmcgPSBkbGcuYnVpbGRfY29uZmlnKCkKCiAgICAgICAgIyDilIDilIAgRGV0ZXJt"
    "aW5lIE1vcmdhbm5hJ3MgaG9tZSBkaXJlY3Rvcnkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgIyBB"
    "bHdheXMgY3JlYXRlcyBEOi9BSS9Nb2RlbHMvTW9yZ2FubmEvIChvciBzaWJsaW5nIG9mIHNjcmlw"
    "dCkKICAgICAgICBzZWVkX2RpciAgID0gU0NSSVBUX0RJUiAgICAgICAgICAjIHdoZXJlIHRoZSBz"
    "ZWVkIC5weSBsaXZlcwogICAgICAgIG1vcmdhbm5hX2hvbWUgPSBzZWVkX2RpciAvIERFQ0tfTkFN"
    "RQogICAgICAgIG1vcmdhbm5hX2hvbWUubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVl"
    "KQoKICAgICAgICAjIOKUgOKUgCBVcGRhdGUgYWxsIHBhdGhzIGluIGNvbmZpZyB0byBwb2ludCBp"
    "bnNpZGUgbW9yZ2FubmFfaG9tZSDilIDilIAKICAgICAgICBuZXdfY2ZnWyJiYXNlX2RpciJdID0g"
    "c3RyKG1vcmdhbm5hX2hvbWUpCiAgICAgICAgbmV3X2NmZ1sicGF0aHMiXSA9IHsKICAgICAgICAg"
    "ICAgImZhY2VzIjogICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiRmFjZXMiKSwKICAgICAgICAgICAg"
    "InNvdW5kcyI6ICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAic291bmRzIiksCiAgICAgICAgICAgICJt"
    "ZW1vcmllcyI6IHN0cihtb3JnYW5uYV9ob21lIC8gIm1lbW9yaWVzIiksCiAgICAgICAgICAgICJz"
    "ZXNzaW9ucyI6IHN0cihtb3JnYW5uYV9ob21lIC8gInNlc3Npb25zIiksCiAgICAgICAgICAgICJz"
    "bCI6ICAgICAgIHN0cihtb3JnYW5uYV9ob21lIC8gInNsIiksCiAgICAgICAgICAgICJleHBvcnRz"
    "IjogIHN0cihtb3JnYW5uYV9ob21lIC8gImV4cG9ydHMiKSwKICAgICAgICAgICAgImxvZ3MiOiAg"
    "ICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAibG9ncyIpLAogICAgICAgICAgICAiYmFja3VwcyI6ICBz"
    "dHIobW9yZ2FubmFfaG9tZSAvICJiYWNrdXBzIiksCiAgICAgICAgICAgICJwZXJzb25hcyI6IHN0"
    "cihtb3JnYW5uYV9ob21lIC8gInBlcnNvbmFzIiksCiAgICAgICAgICAgICJnb29nbGUiOiAgIHN0"
    "cihtb3JnYW5uYV9ob21lIC8gImdvb2dsZSIpLAogICAgICAgIH0KICAgICAgICBuZXdfY2ZnWyJn"
    "b29nbGUiXSA9IHsKICAgICAgICAgICAgImNyZWRlbnRpYWxzIjogc3RyKG1vcmdhbm5hX2hvbWUg"
    "LyAiZ29vZ2xlIiAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIpLAogICAgICAgICAgICAidG9r"
    "ZW4iOiAgICAgICBzdHIobW9yZ2FubmFfaG9tZSAvICJnb29nbGUiIC8gInRva2VuLmpzb24iKSwK"
    "ICAgICAgICAgICAgInRpbWV6b25lIjogICAgIkFtZXJpY2EvQ2hpY2FnbyIsCiAgICAgICAgICAg"
    "ICJzY29wZXMiOiBbCiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20v"
    "YXV0aC9jYWxlbmRhci5ldmVudHMiLAogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2ds"
    "ZWFwaXMuY29tL2F1dGgvZHJpdmUiLAogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2ds"
    "ZWFwaXMuY29tL2F1dGgvZG9jdW1lbnRzIiwKICAgICAgICAgICAgXSwKICAgICAgICB9CiAgICAg"
    "ICAgbmV3X2NmZ1siZmlyc3RfcnVuIl0gPSBGYWxzZQoKICAgICAgICAjIOKUgOKUgCBDb3B5IGRl"
    "Y2sgZmlsZSBpbnRvIG1vcmdhbm5hX2hvbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAg"
    "c3JjX2RlY2sgPSBQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCkKICAgICAgICBkc3RfZGVjayA9IG1v"
    "cmdhbm5hX2hvbWUgLyBmIntERUNLX05BTUUubG93ZXIoKX1fZGVjay5weSIKICAgICAgICBpZiBz"
    "cmNfZGVjayAhPSBkc3RfZGVjazoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgX3No"
    "dXRpbC5jb3B5MihzdHIoc3JjX2RlY2spLCBzdHIoZHN0X2RlY2spKQogICAgICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBRTWVzc2FnZUJveC53YXJuaW5nKAog"
    "ICAgICAgICAgICAgICAgICAgIE5vbmUsICJDb3B5IFdhcm5pbmciLAogICAgICAgICAgICAgICAg"
    "ICAgIGYiQ291bGQgbm90IGNvcHkgZGVjayBmaWxlIHRvIHtERUNLX05BTUV9IGZvbGRlcjpcbntl"
    "fVxuXG4iCiAgICAgICAgICAgICAgICAgICAgZiJZb3UgbWF5IG5lZWQgdG8gY29weSBpdCBtYW51"
    "YWxseS4iCiAgICAgICAgICAgICAgICApCgogICAgICAgICMg4pSA4pSAIFdyaXRlIGNvbmZpZy5q"
    "c29uIGludG8gbW9yZ2FubmFfaG9tZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBjZmdfZHN0ID0gbW9y"
    "Z2FubmFfaG9tZSAvICJjb25maWcuanNvbiIKICAgICAgICBjZmdfZHN0LnBhcmVudC5ta2Rpcihw"
    "YXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgd2l0aCBjZmdfZHN0Lm9wZW4oInci"
    "LCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICBqc29uLmR1bXAobmV3X2NmZywg"
    "ZiwgaW5kZW50PTIpCgogICAgICAgICMg4pSA4pSAIEJvb3RzdHJhcCBhbGwgc3ViZGlyZWN0b3Jp"
    "ZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgIyBUZW1wb3Jh"
    "cmlseSB1cGRhdGUgZ2xvYmFsIENGRyBzbyBib290c3RyYXAgZnVuY3Rpb25zIHVzZSBuZXcgcGF0"
    "aHMKICAgICAgICBDRkcudXBkYXRlKG5ld19jZmcpCiAgICAgICAgYm9vdHN0cmFwX2RpcmVjdG9y"
    "aWVzKCkKICAgICAgICBib290c3RyYXBfc291bmRzKCkKICAgICAgICB3cml0ZV9yZXF1aXJlbWVu"
    "dHNfdHh0KCkKCiAgICAgICAgIyDilIDilIAgVW5wYWNrIGZhY2UgWklQIGlmIHByb3ZpZGVkIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGZhY2VfemlwID0g"
    "ZGxnLmZhY2VfemlwX3BhdGgKICAgICAgICBpZiBmYWNlX3ppcCBhbmQgUGF0aChmYWNlX3ppcCku"
    "ZXhpc3RzKCk6CiAgICAgICAgICAgIGltcG9ydCB6aXBmaWxlIGFzIF96aXBmaWxlCiAgICAgICAg"
    "ICAgIGZhY2VzX2RpciA9IG1vcmdhbm5hX2hvbWUgLyAiRmFjZXMiCiAgICAgICAgICAgIGZhY2Vz"
    "X2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgICAgIHdpdGggX3ppcGZpbGUuWmlwRmlsZShmYWNlX3ppcCwgInIiKSBhcyB6"
    "ZjoKICAgICAgICAgICAgICAgICAgICBleHRyYWN0ZWQgPSAwCiAgICAgICAgICAgICAgICAgICAg"
    "Zm9yIG1lbWJlciBpbiB6Zi5uYW1lbGlzdCgpOgogICAgICAgICAgICAgICAgICAgICAgICBpZiBt"
    "ZW1iZXIubG93ZXIoKS5lbmRzd2l0aCgiLnBuZyIpOgogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZmlsZW5hbWUgPSBQYXRoKG1lbWJlcikubmFtZQogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgdGFyZ2V0ID0gZmFjZXNfZGlyIC8gZmlsZW5hbWUKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIHdpdGggemYub3BlbihtZW1iZXIpIGFzIHNyYywgdGFyZ2V0Lm9wZW4oIndiIikgYXMgZHN0"
    "OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGRzdC53cml0ZShzcmMucmVhZCgpKQog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgZXh0cmFjdGVkICs9IDEKICAgICAgICAgICAgICAg"
    "IF9lYXJseV9sb2coZiJbRkFDRVNdIEV4dHJhY3RlZCB7ZXh0cmFjdGVkfSBmYWNlIGltYWdlcyB0"
    "byB7ZmFjZXNfZGlyfSIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAg"
    "ICAgICAgICAgIF9lYXJseV9sb2coZiJbRkFDRVNdIFpJUCBleHRyYWN0aW9uIGZhaWxlZDoge2V9"
    "IikKICAgICAgICAgICAgICAgIFFNZXNzYWdlQm94Lndhcm5pbmcoCiAgICAgICAgICAgICAgICAg"
    "ICAgTm9uZSwgIkZhY2UgUGFjayBXYXJuaW5nIiwKICAgICAgICAgICAgICAgICAgICBmIkNvdWxk"
    "IG5vdCBleHRyYWN0IGZhY2UgcGFjazpcbntlfVxuXG4iCiAgICAgICAgICAgICAgICAgICAgZiJZ"
    "b3UgY2FuIGFkZCBmYWNlcyBtYW51YWxseSB0bzpcbntmYWNlc19kaXJ9IgogICAgICAgICAgICAg"
    "ICAgKQoKICAgICAgICAjIOKUgOKUgCBDcmVhdGUgZGVza3RvcCBzaG9ydGN1dCBwb2ludGluZyB0"
    "byBuZXcgZGVjayBsb2NhdGlvbiDilIDilIDilIDilIDilIDilIAKICAgICAgICBzaG9ydGN1dF9j"
    "cmVhdGVkID0gRmFsc2UKICAgICAgICBpZiBkbGcuY3JlYXRlX3Nob3J0Y3V0OgogICAgICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgICAgICBpZiBXSU4zMl9PSzoKICAgICAgICAgICAgICAgICAgICBp"
    "bXBvcnQgd2luMzJjb20uY2xpZW50IGFzIF93aW4zMgogICAgICAgICAgICAgICAgICAgIGRlc2t0"
    "b3AgICAgID0gUGF0aC5ob21lKCkgLyAiRGVza3RvcCIKICAgICAgICAgICAgICAgICAgICBzY19w"
    "YXRoICAgICA9IGRlc2t0b3AgLyBmIntERUNLX05BTUV9LmxuayIKICAgICAgICAgICAgICAgICAg"
    "ICBweXRob253ICAgICA9IFBhdGgoc3lzLmV4ZWN1dGFibGUpCiAgICAgICAgICAgICAgICAgICAg"
    "aWYgcHl0aG9udy5uYW1lLmxvd2VyKCkgPT0gInB5dGhvbi5leGUiOgogICAgICAgICAgICAgICAg"
    "ICAgICAgICBweXRob253ID0gcHl0aG9udy5wYXJlbnQgLyAicHl0aG9udy5leGUiCiAgICAgICAg"
    "ICAgICAgICAgICAgaWYgbm90IHB5dGhvbncuZXhpc3RzKCk6CiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIHB5dGhvbncgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQogICAgICAgICAgICAgICAgICAgIHNo"
    "ZWxsID0gX3dpbjMyLkRpc3BhdGNoKCJXU2NyaXB0LlNoZWxsIikKICAgICAgICAgICAgICAgICAg"
    "ICBzYyAgICA9IHNoZWxsLkNyZWF0ZVNob3J0Q3V0KHN0cihzY19wYXRoKSkKICAgICAgICAgICAg"
    "ICAgICAgICBzYy5UYXJnZXRQYXRoICAgICAgPSBzdHIocHl0aG9udykKICAgICAgICAgICAgICAg"
    "ICAgICBzYy5Bcmd1bWVudHMgICAgICAgPSBmJyJ7ZHN0X2RlY2t9IicKICAgICAgICAgICAgICAg"
    "ICAgICBzYy5Xb3JraW5nRGlyZWN0b3J5PSBzdHIobW9yZ2FubmFfaG9tZSkKICAgICAgICAgICAg"
    "ICAgICAgICBzYy5EZXNjcmlwdGlvbiAgICAgPSBmIntERUNLX05BTUV9IOKAlCBFY2hvIERlY2si"
    "CiAgICAgICAgICAgICAgICAgICAgc2Muc2F2ZSgpCiAgICAgICAgICAgICAgICAgICAgc2hvcnRj"
    "dXRfY3JlYXRlZCA9IFRydWUKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAg"
    "ICAgICAgICAgICAgcHJpbnQoZiJbU0hPUlRDVVRdIENvdWxkIG5vdCBjcmVhdGUgc2hvcnRjdXQ6"
    "IHtlfSIpCgogICAgICAgICMg4pSA4pSAIENvbXBsZXRpb24gbWVzc2FnZSDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICBzaG9ydGN1dF9ub3RlID0gKAogICAgICAgICAgICAiQSBkZXNrdG9wIHNob3J0Y3V0IGhh"
    "cyBiZWVuIGNyZWF0ZWQuXG4iCiAgICAgICAgICAgIGYiVXNlIGl0IHRvIHN1bW1vbiB7REVDS19O"
    "QU1FfSBmcm9tIG5vdyBvbi4iCiAgICAgICAgICAgIGlmIHNob3J0Y3V0X2NyZWF0ZWQgZWxzZQog"
    "ICAgICAgICAgICAiTm8gc2hvcnRjdXQgd2FzIGNyZWF0ZWQuXG4iCiAgICAgICAgICAgIGYiUnVu"
    "IHtERUNLX05BTUV9IGJ5IGRvdWJsZS1jbGlja2luZzpcbntkc3RfZGVja30iCiAgICAgICAgKQoK"
    "ICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbigKICAgICAgICAgICAgTm9uZSwKICAgICAg"
    "ICAgICAgZiLinKYge0RFQ0tfTkFNRX0ncyBTYW5jdHVtIFByZXBhcmVkIiwKICAgICAgICAgICAg"
    "ZiJ7REVDS19OQU1FfSdzIHNhbmN0dW0gaGFzIGJlZW4gcHJlcGFyZWQgYXQ6XG5cbiIKICAgICAg"
    "ICAgICAgZiJ7bW9yZ2FubmFfaG9tZX1cblxuIgogICAgICAgICAgICBmIntzaG9ydGN1dF9ub3Rl"
    "fVxuXG4iCiAgICAgICAgICAgIGYiVGhpcyBzZXR1cCB3aW5kb3cgd2lsbCBub3cgY2xvc2UuXG4i"
    "CiAgICAgICAgICAgIGYiVXNlIHRoZSBzaG9ydGN1dCBvciB0aGUgZGVjayBmaWxlIHRvIGxhdW5j"
    "aCB7REVDS19OQU1FfS4iCiAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBFeGl0IHNlZWQg4oCU"
    "IHVzZXIgbGF1bmNoZXMgZnJvbSBzaG9ydGN1dC9uZXcgbG9jYXRpb24g4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICAgICAgc3lzLmV4aXQoMCkKCiAgICAjIOKUgOKUgCBQaGFzZSA0OiBOb3JtYWwg"
    "bGF1bmNoIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgIyBPbmx5IHJlYWNoZXMgaGVyZSBvbiBzdWJzZXF1ZW50IHJ1"
    "bnMgZnJvbSBtb3JnYW5uYV9ob21lCiAgICBib290c3RyYXBfc291bmRzKCkKCiAgICBfZWFybHlf"
    "bG9nKGYiW01BSU5dIENyZWF0aW5nIHtERUNLX05BTUV9IGRlY2sgd2luZG93IikKICAgIHdpbmRv"
    "dyA9IEVjaG9EZWNrKCkKICAgIF9lYXJseV9sb2coZiJbTUFJTl0ge0RFQ0tfTkFNRX0gZGVjayBj"
    "cmVhdGVkIOKAlCBjYWxsaW5nIHNob3coKSIpCiAgICB3aW5kb3cuc2hvdygpCiAgICBfZWFybHlf"
    "bG9nKCJbTUFJTl0gd2luZG93LnNob3coKSBjYWxsZWQg4oCUIGV2ZW50IGxvb3Agc3RhcnRpbmci"
    "KQoKICAgICMgRGVmZXIgc2NoZWR1bGVyIGFuZCBzdGFydHVwIHNlcXVlbmNlIHVudGlsIGV2ZW50"
    "IGxvb3AgaXMgcnVubmluZy4KICAgICMgTm90aGluZyB0aGF0IHN0YXJ0cyB0aHJlYWRzIG9yIGVt"
    "aXRzIHNpZ25hbHMgc2hvdWxkIHJ1biBiZWZvcmUgdGhpcy4KICAgIFFUaW1lci5zaW5nbGVTaG90"
    "KDIwMCwgbGFtYmRhOiAoX2Vhcmx5X2xvZygiW1RJTUVSXSBfc2V0dXBfc2NoZWR1bGVyIGZpcmlu"
    "ZyIpLCB3aW5kb3cuX3NldHVwX3NjaGVkdWxlcigpKSkKICAgIFFUaW1lci5zaW5nbGVTaG90KDQw"
    "MCwgbGFtYmRhOiAoX2Vhcmx5X2xvZygiW1RJTUVSXSBzdGFydF9zY2hlZHVsZXIgZmlyaW5nIiks"
    "IHdpbmRvdy5zdGFydF9zY2hlZHVsZXIoKSkpCiAgICBRVGltZXIuc2luZ2xlU2hvdCg2MDAsIGxh"
    "bWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gX3N0YXJ0dXBfc2VxdWVuY2UgZmlyaW5nIiksIHdp"
    "bmRvdy5fc3RhcnR1cF9zZXF1ZW5jZSgpKSkKICAgIFFUaW1lci5zaW5nbGVTaG90KDEwMDAsIGxh"
    "bWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gX3N0YXJ0dXBfZ29vZ2xlX2F1dGggZmlyaW5nIiks"
    "IHdpbmRvdy5fc3RhcnR1cF9nb29nbGVfYXV0aCgpKSkKCiAgICAjIFBsYXkgc3RhcnR1cCBzb3Vu"
    "ZCDigJQga2VlcCByZWZlcmVuY2UgdG8gcHJldmVudCBHQyB3aGlsZSB0aHJlYWQgcnVucwogICAg"
    "ZGVmIF9wbGF5X3N0YXJ0dXAoKToKICAgICAgICB3aW5kb3cuX3N0YXJ0dXBfc291bmQgPSBTb3Vu"
    "ZFdvcmtlcigic3RhcnR1cCIpCiAgICAgICAgd2luZG93Ll9zdGFydHVwX3NvdW5kLmZpbmlzaGVk"
    "LmNvbm5lY3Qod2luZG93Ll9zdGFydHVwX3NvdW5kLmRlbGV0ZUxhdGVyKQogICAgICAgIHdpbmRv"
    "dy5fc3RhcnR1cF9zb3VuZC5zdGFydCgpCiAgICBRVGltZXIuc2luZ2xlU2hvdCgxMjAwLCBfcGxh"
    "eV9zdGFydHVwKQoKICAgIHN5cy5leGl0KGFwcC5leGVjKCkpCgoKaWYgX19uYW1lX18gPT0gIl9f"
    "bWFpbl9fIjoKICAgIG1haW4oKQoKCiMg4pSA4pSAIFBBU1MgNiBDT01QTEVURSDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "IyBGdWxsIGRlY2sgYXNzZW1ibGVkLiBBbGwgcGFzc2VzIGNvbXBsZXRlLgojIENvbWJpbmUgYWxs"
    "IHBhc3NlcyBpbnRvIG1vcmdhbm5hX2RlY2sucHkgaW4gb3JkZXI6CiMgICBQYXNzIDEg4oaSIFBh"
    "c3MgMiDihpIgUGFzcyAzIOKGkiBQYXNzIDQg4oaSIFBhc3MgNSDihpIgUGFzcyA2"
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
