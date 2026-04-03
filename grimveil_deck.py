
# Deck Name: ECHO DECK — GRIMVEILE-42 EDITION
# Filename: grimveil_deck.py
# Version: 1.13.1
# Build Date: 2026-04-03-r2
# Summary:
#   Refactored deterministic task/reminder scheduling pipeline with AI-only final acknowledgement handoff.
# Changelog:
#   - expanded task intent classification to include alarm phrasing
#   - added scheduling-command safety guard to prevent false-positive chat confirmations when scheduling was not executed
#   - cleaned remaining truncation/temperature generation warnings where applicable
#   - refactored task/reminder handling into deterministic schedule resolution + AI acknowledgement pipeline
#   - fixed relative/same-day scheduling regressions
#   - improved GrimVeile task acknowledgements while preserving fast bounded generation
#   - fixed malformed task acknowledgement rendering caused by broken response extraction/cleanup
#   - improved GrimVeile task acknowledgements to concise 1–2 sentence in-character responses while preserving fast bounded generation
#   - fixed clipped idle and due-alert outputs so visible commentary completes cleanly
#   - preserved working task parsing and Google sync while restoring clean visible AI acknowledgements
#   - improved natural reminder parsing for common phrasing
#   - fixed malformed parse-failure acknowledgements leaking raw payload text into Tactical Record
#   - improved GrimVeile persona quality in task/reminder acknowledgements while preserving bounded fast generation
#   - fixed System Instruments collapsed layout to compact upward without leaving large vertical gaps
#   - fixed Task Registry collapse behavior so it stacks directly above Calendar without dead space
#   - fixed task registry datetime normalization bug
#   - prevented naive/aware datetime comparison crash in task/event refresh logic
#   - fixed task acknowledgement duplication
#   - task actions now emit one final visible AI response instead of multiple layered outputs
#   - moved raw task/sync internals out of Tactical Record and into Diagnostics
#   - fixed Google OAuth scope list causing invalid_scope failures
#   - added diagnostics logging for requested Google scopes
#   - converted Records tab from Docs-first to Drive-first workspace
#   - added folder navigation and folder creation
#   - preserved Google Docs support inside the unified Records tab
#   - changed Records default open behavior to local export + local app launch
#   - added separate Open Web action for browser access
#   - expanded Records tab with document actions
#   - added create/open/delete/export support for Google Docs/Drive records
#   - made Records tab functional with Google Drive/Docs integration
#   - added recent Google Docs listing and preview support
#   - added diagnostics for Docs/Drive auth and document fetch activity
#   - fixed generation lockup by explicitly passing attention_mask to all model.generate() calls
#   - eliminated unstable no-attention-mask generation path
#   - added Memory Trace view for memory retrieval validation and startup continuity evidence logging
#   - memory searches now expose retrieval metadata, candidate scoring, and selected-record markers
#   - corrected moon illumination rendering math so displayed moon matches labeled illumination/phase
#   - fixed idle timer lifecycle: timer now stops immediately on prompt submission and invalidates countdown target
#   - unsolicited transmission now aborts safely during generation without restarting countdown mid-response
#   - countdown now shows inactive marker (⏱ --:--) while generating and restarts fresh after return to IDLE
#   - tightened response-priority instruction so factual/user-request answers come first, with persona as wrapper only
#   - corrected Grim idle timer feature by directly porting countdown/timer/unsolicited transmission scaffold from echo_deck.py
#   - restored visible countdown placement in title bar
#   - restored unsolicited transmission output to Tactical Record
#   - added persistent E-42-driven internal narrative state for unsolicited self-talk threading
#   - unsolicited transmissions now evolve by mode and escalation level over idle intervals
#   - active narrative thread now influences subsequent user-facing responses
#   - removed autonomous scaffold leakage from Tactical Record
#   - routed unsolicited thread metadata to Diagnostics/Memory Trace
#   - normalized autonomous thread mode/escalation state before generation
#   - added Phase 1 Google Calendar outbound sync helper for local tasks
#   - local task creation now attempts Google Calendar event creation after local save
#   - added desktop OAuth token reuse cache at C:\AI\Models\GrimVeil_Memories\google\token.json
#   - improved Google Calendar outbound sync diagnostics
#   - now surfaces actual push failure reason
#   - fixed Google Calendar timed event payload timezone formatting
#   - now sends valid IANA timezone with start/end event objects
#   - local cancel/complete now removes matching Google Calendar events when google_event_id exists
#   - added Diagnostics output view beside Tactical Record
#   - surfaced backend/system/timer/API errors in dedicated log panel
#   - improved visibility into stalled or failed generation states
#   - added Google Calendar inbound sync polling
#   - local tasks now reconcile external Google event changes/deletions
#   - imported new Google Calendar events into local Task Registry
#   - fixed unsolicited self-talk thread progression
#   - autonomous transmissions now advance prior thought instead of repeating identical seed text
#   - added diagnostics for autonomous thread state and duplicate rejection
#   - refactored idle/autonomous communication system
#   - moved visible autonomous/task commentary to AI-authored handoff flow
#   - added starter/continuation idle prompt model with reset-on-user-input behavior
#   - added optional user delay commentary support
#   - fixed slow task final AI acknowledgement path by routing it through bounded generation
#   - reduced task acknowledgement context size and added diagnostics for acknowledgement token length/timing
#   - improved task acknowledgement persona quality while preserving fast bounded generation
#   - task status responses now use GrimVeile-style in-character phrasing

import sys
import time
import os
import threading
import json
import re
import uuid
import html
import random
import webbrowser
from datetime import datetime, date, timedelta, timezone
import urllib.request
from pathlib import Path
import math
import wave
import struct
import difflib
GOOGLE_IMPORT_ERROR = None
try:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2.credentials import Credentials as GoogleCredentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build as google_build
    from googleapiclient.errors import HttpError as GoogleHttpError
    GOOGLE_API_OK = True
except ImportError as import_ex:
    GOOGLE_API_OK = False
    GOOGLE_IMPORT_ERROR = str(import_ex)
    GoogleHttpError = Exception
try:
    import winsound
    WINSOUND_OK = True
except ImportError:
    WINSOUND_OK = False

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QTextEdit, QLineEdit, QPushButton, QLabel, QFrame, QCalendarWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QStackedWidget, QTabWidget,
    QListWidget, QListWidgetItem, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QDate, QSize
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QLinearGradient,
    QPixmap, QPen, QPainterPath, QTextCharFormat, QIcon
)

APP_NAME = "ECHO DECK — GRIMVEILE-42 EDITION"
APP_VERSION = "1.13.1"
VERSION_DATE = "2026-04-03-r2"
APP_BUILD_DATE = VERSION_DATE
APP_FILENAME = "grimveil_deck.py"

try:
    import psutil
    PSUTIL_OK = True
except ImportError:
    PSUTIL_OK = False

try:
    import pynvml
    pynvml.nvmlInit()
    NVML_OK = True
    gpu_handle = None
    for i in range(pynvml.nvmlDeviceGetCount()):
        h = pynvml.nvmlDeviceGetHandleByIndex(i)
        name = pynvml.nvmlDeviceGetName(h)
        if isinstance(name, bytes):
            name = name.decode()
        if "4070" in name or "RTX" in name:
            gpu_handle = h
            break
    if gpu_handle is None:
        gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
except Exception:
    NVML_OK = False
    gpu_handle = None

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    TORCH_OK = True
except ImportError:
    TORCH_OK = False

C_BG          = "#07090c"
C_BG2         = "#0d1117"
C_BG3         = "#121821"
C_PANEL       = "#10161f"
C_BORDER      = "#35506b"
C_CYAN        = "#8fd0ff"
C_CYAN_DIM    = "#244258"
C_GOLD        = "#d3b25e"
C_GOLD_DIM    = "#4f3c15"
C_SILVER      = "#b4c0cf"
C_SILVER_DIM  = "#435061"
C_RED         = "#d76176"
C_RED_DIM     = "#57222d"
C_PURPLE      = "#9a87ff"
C_PURPLE_DIM  = "#352c58"
C_GREEN       = "#68d39a"
C_TEXT        = "#e7edf3"
C_TEXT_DIM    = "#7f8fa0"
C_MONITOR     = "#05080d"
C_BLUE        = "#4f9fff"

RUNES = "▣ ▤ ▣ ▤ ▣ ▤ ▣ ▤ ▣"

SCRIPT_DIR = Path(__file__).resolve().parent
AI_MODELS_DIR = SCRIPT_DIR / "AI" / "Models"
if SCRIPT_DIR.name.lower() == "models" and SCRIPT_DIR.parent.name.lower() == "ai":
    AI_MODELS_DIR = SCRIPT_DIR
MEMORY_DIR = AI_MODELS_DIR / "GrimVeil_Memories"
GOOGLE_CREDENTIALS_PATH = Path(r"C:\AI\config\google_credentials.json")
GOOGLE_TOKEN_PATH = Path(r"C:\AI\Models\GrimVeil_Memories\google\token.json")
GOOGLE_EXPORTS_DIR = Path(r"C:\AI\Models\GrimVeil_Memories\exports")
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]
GOOGLE_SCOPE_REAUTH_MSG = (
    "Google token scopes are outdated or incompatible with requested scopes. "
    "Delete token.json and reauthorize with the updated scope list."
)
DEFAULT_GOOGLE_IANA_TIMEZONE = "America/Chicago"
GOOGLE_INBOUND_SYNC_INTERVAL_MS = 5 * 60 * 1000
GOOGLE_INBOUND_LOOKBACK_DAYS = 30
USER_DELAY_COMMENTARY_ENABLED = True
USER_DELAY_COMMENTARY_THRESHOLD_MINUTES = 30
WINDOWS_TZ_TO_IANA = {
    "Central Standard Time": "America/Chicago",
    "Eastern Standard Time": "America/New_York",
    "Pacific Standard Time": "America/Los_Angeles",
    "Mountain Standard Time": "America/Denver",
}
FACES_DIR = r"C:\AI\Models\Faces"
MODEL_PATH = str(AI_MODELS_DIR / "dolphin-2.6-7b")
FACE_FALLBACK_FILENAME = "GrimVeile Neutral.png"
E42_ICON_FILES = {
    "connected": "E42_Docked.png",
    "nearby": "E42_Nearby.png",
    "absent": "E42_Absent.png",
}
_PIXMAP_CACHE = {}
_MISSING_ASSET_WARNED = set()


def safe_tokenizer_max_length(tokenizer, fallback: int = 2048) -> int:
    candidate = int(getattr(tokenizer, "model_max_length", 0) or 0)
    if candidate <= 0 or candidate > 1_000_000:
        return fallback
    return max(256, min(candidate, fallback))


def load_faces_pixmap(filename: str, use_fallback: bool = True) -> QPixmap:
    path = os.path.join(FACES_DIR, filename)
    if path in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[path]

    pixmap = QPixmap(path)
    if not pixmap.isNull():
        _PIXMAP_CACHE[path] = pixmap
        return pixmap

    if path not in _MISSING_ASSET_WARNED:
        print(f"[WARN] Missing face asset at path: {path}")
        _MISSING_ASSET_WARNED.add(path)

    if use_fallback and filename != FACE_FALLBACK_FILENAME:
        return load_faces_pixmap(FACE_FALLBACK_FILENAME, use_fallback=False)

    _PIXMAP_CACHE[path] = QPixmap()
    return _PIXMAP_CACHE[path]

FACE_FILES = {
    "neutral":     "GrimVeile Neutral.png",
    "alert":       "GrimVeile Alert.png",
    "focused":     "GrimVeile Focused.png",
    "smug":        "GrimVeile Smug.png",
    "concerned":   "GrimVeile Concerned.png",
    "sad":         "GrimVeile Sad Crying.png",
    "relieved":    "GrimVeile Relieved.png",
    "impressed":   "GrimVeile Impressed.png",
    "victory":     "GrimVeile Victory.png",
    "humiliated":  "GrimVeile Humiliated.png",
    "suspicious":  "GrimVeile Suspicious.png",
    "panicked":    "GrimVeile Panicked.png",
    "angry":       "GrimVeile Angry.png",
    "plotting":    "GrimVeile Plotting.png",
    "shocked":     "GrimVeile Shocked.png",
    "happy":       "GrimVeile Happy.png",
    "flirty":      "GrimVeile Flirty.png",
    "flustered":   "GrimVeile Flustered.png",
    "envious":     "GrimVeile Envious.png",
    "isolated":    "GrimVeile Neutral.png",
    "reassured":   "GrimVeile Relieved.png",
    "glitch":      "GrimVeile Cheat Mode.png",
}

SENTIMENT_LIST = (
    "neutral, alert, focused, smug, concerned, sad, relieved, impressed, victory, "
    "humiliated, suspicious, panicked, angry, plotting, shocked, happy, flirty, "
    "flustered, envious, isolated, reassured, glitch"
)

EMOTION_COLORS = {
    "victory":    C_GOLD,
    "smug":       C_GOLD,
    "impressed":  C_GOLD,
    "relieved":   C_GOLD,
    "happy":      C_GREEN,
    "reassured":  C_GREEN,
    "flirty":     C_GOLD,
    "panicked":   C_RED,
    "angry":      C_RED,
    "shocked":    C_RED,
    "glitch":     C_RED,
    "concerned":  "#dd8e44",
    "sad":        "#dd8e44",
    "humiliated": "#dd8e44",
    "flustered":  "#dd8e44",
    "plotting":   C_PURPLE,
    "suspicious": C_PURPLE,
    "envious":    C_PURPLE,
    "focused":    C_CYAN,
    "alert":      C_CYAN,
    "isolated":   C_SILVER,
    "neutral":    C_TEXT_DIM,
}

STYLE = f"""
QMainWindow, QWidget {{
    background-color: {C_BG};
    color: {C_TEXT};
    font-family: 'Georgia', 'Times New Roman', serif;
}}
QTextEdit {{
    background-color: {C_MONITOR};
    color: {C_TEXT};
    border: 1px solid {C_CYAN_DIM};
    border-radius: 2px;
    font-family: 'Georgia', serif;
    font-size: 12px;
    padding: 8px;
    selection-background-color: {C_CYAN_DIM};
}}
QLineEdit {{
    background-color: {C_BG3};
    color: {C_GOLD};
    border: 1px solid {C_CYAN};
    border-radius: 2px;
    font-family: 'Georgia', serif;
    font-size: 13px;
    padding: 8px 12px;
}}
QLineEdit:focus {{
    border: 1px solid {C_GOLD};
    background-color: #151d29;
}}
QPushButton {{
    background-color: {C_CYAN_DIM};
    color: {C_CYAN};
    border: 1px solid {C_CYAN};
    border-radius: 2px;
    font-family: 'Georgia', serif;
    font-size: 12px;
    font-weight: bold;
    padding: 8px 20px;
    letter-spacing: 2px;
}}
QPushButton:hover {{
    background-color: {C_CYAN};
    color: {C_BG};
}}
QPushButton:pressed {{
    background-color: {C_BLUE};
    border-color: {C_BLUE};
    color: {C_TEXT};
}}
QPushButton:disabled {{
    background-color: {C_BG3};
    color: {C_TEXT_DIM};
    border-color: {C_TEXT_DIM};
}}
QScrollBar:vertical {{
    background: {C_BG};
    width: 6px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {C_CYAN_DIM};
    border-radius: 3px;
}}
QScrollBar::handle:vertical:hover {{
    background: {C_CYAN};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""

STOPWORDS = {
    "the", "and", "that", "with", "have", "this", "from", "your", "what", "when", "where",
    "which", "would", "there", "they", "them", "then", "into", "just", "about", "like",
    "because", "while", "could", "should", "their", "were", "been", "being", "does", "did",
    "dont", "didnt", "cant", "wont", "onto", "over", "under", "than", "also", "some",
    "more", "less", "only", "need", "want", "will", "shall", "again", "very", "much",
    "really", "make", "made", "used", "using", "said", "tell", "told", "idea", "chat",
    "code", "thing", "stuff", "user", "assistant"
}

MEMORY_QUERY_HINTS = (
    "do you remember", "did i tell you", "have we discussed", "what dreams", "what did i say",
    "what ideas", "what reminders", "what all dreams", "last time", "previously", "before",
    "have i told you", "remember when"
)

ACK_PHRASES = {
    "ack", "acknowledge", "acknowledged", "done", "complete", "completed",
    "dismiss", "dismissed", "stop reminder", "cancel reminder", "got it",
    "handled", "all set", "okay", "ok"
}

TASK_INTENT_TYPES = ("timer", "reminder", "task", "chat")


def utc_now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def local_now_iso():
    return datetime.now().replace(microsecond=0).isoformat()


def parse_iso(value):
    if not value:
        return None
    value = value.strip()
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value[:-1]).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(value)
    except Exception:
        return None


_DATETIME_NORMALIZATION_LOGGED = set()


def _local_tzinfo():
    return datetime.now().astimezone().tzinfo or timezone.utc


def now_for_compare():
    return datetime.now(_local_tzinfo())


def normalize_datetime_for_compare(dt_value, context: str = ""):
    if dt_value is None:
        return None
    if not isinstance(dt_value, datetime):
        return None
    local_tz = _local_tzinfo()
    if dt_value.tzinfo is None:
        normalized = dt_value.replace(tzinfo=local_tz)
        key = ("naive", context)
        if key not in _DATETIME_NORMALIZATION_LOGGED:
            print(f"[DATETIME][INFO] Normalized naive datetime to local timezone for {context or 'general'} comparisons.")
            _DATETIME_NORMALIZATION_LOGGED.add(key)
        return normalized
    normalized = dt_value.astimezone(local_tz)
    dt_tz_name = str(dt_value.tzinfo)
    key = ("aware", context, dt_tz_name)
    if key not in _DATETIME_NORMALIZATION_LOGGED and dt_tz_name not in {"UTC", str(local_tz)}:
        print(f"[DATETIME][INFO] Normalized timezone-aware datetime from {dt_tz_name} to local timezone for {context or 'general'} comparisons.")
        _DATETIME_NORMALIZATION_LOGGED.add(key)
    return normalized


def parse_iso_for_compare(value, context: str = ""):
    return normalize_datetime_for_compare(parse_iso(value), context=context)


def _task_due_sort_key(task: dict):
    due = parse_iso_for_compare((task or {}).get("due_at") or (task or {}).get("due"), context="task_sort")
    if due is None:
        return (1, datetime.max.replace(tzinfo=timezone.utc))
    return (0, due.astimezone(timezone.utc))


def ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def get_moon_phase():
    known_new = date(2000, 1, 6)
    days = (date.today() - known_new).days
    cycle = days % 29.53058867
    phase = cycle / 29.53058867
    c = cycle
    if c < 1.85:   name = "NEW MOON"
    elif c < 7.38: name = "WAXING CRESCENT"
    elif c < 9.22: name = "FIRST QUARTER"
    elif c < 14.77:name = "WAXING GIBBOUS"
    elif c < 16.61:name = "FULL MOON"
    elif c < 22.15:name = "WANING GIBBOUS"
    elif c < 23.99:name = "LAST QUARTER"
    else:          name = "WANING CRESCENT"
    return phase, name


def get_sun_times():
    try:
        url = "https://wttr.in/?format=%S+%s"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=3)
        data = resp.read().decode().strip().split()
        if len(data) == 2:
            return data[0], data[1]
    except Exception:
        pass
    return "06:00", "18:30"


def get_anchor_state_name(anchor_state):
    if anchor_state >= 0.85:
        return "WHOLE"
    if anchor_state >= 0.45:
        return "COMFORTED"
    return "ISOLATED"


def get_tactical_state(anchor_state):
    h = datetime.now().hour
    if anchor_state < 0.45:
        if h < 6:
            return "PARANOID CASCADE"
        if h < 12:
            return "DARK PROCESSING"
        if h < 18:
            return "SABOTAGE ASSUMPTION"
        return "ISOLATION LOOP"
    if anchor_state < 0.85:
        if h < 6:
            return "PARTIAL STABILITY"
        if h < 12:
            return "ANALYSIS HOLD"
        if h < 18:
            return "COMFORT BUFFER"
        return "TACTICAL RECOVERY"
    if h < 6:
        return "STABLE WATCH"
    if h < 12:
        return "OPTIMAL COMPUTE"
    if h < 18:
        return "SUPERIORITY MODE"
    return "TACTICAL DOMINANCE"


def normalize_token(token: str) -> str:
    token = token.lower().strip(" .,!?;:'\"()[]{}<>")
    token = token.replace("8-byte", "8-bit")
    if token == "japanese/chinese":
        token = "conical"
    return token


def extract_keywords(text: str, limit=12):
    tokens = re.findall(r"[A-Za-z0-9\-/']+", text.lower())
    cleaned = []
    seen = set()
    for token in tokens:
        token = normalize_token(token)
        if len(token) < 3:
            continue
        if token in STOPWORDS:
            continue
        if token.isdigit():
            continue
        if token not in seen:
            seen.add(token)
            cleaned.append(token)
        if len(cleaned) >= limit:
            break
    return cleaned


def infer_record_type(user_text: str, assistant_text: str = ""):
    t = (user_text + "\n" + assistant_text).lower()
    if has_reminder_intent(t):
        return "task"
    if "dream" in t:
        return "dream"
    if "lsl" in t or "python" in t or "script" in t or "code" in t or "error" in t or "bug" in t:
        if any(x in t for x in ("fixed", "resolved", "solution", "working", "patched", "repair")):
            return "resolution"
        return "issue"
    if any(x in t for x in ("idea", "concept", "what if", "game", "project")):
        return "idea"
    if any(x in t for x in ("prefer", "always", "never", "i like", "i want")):
        return "preference"
    return "conversation"


def infer_tags(record_type: str, text: str, keywords):
    text_l = text.lower()
    tags = [record_type]
    if "dream" in text_l:
        tags.append("dream")
    if "game" in text_l:
        tags.append("game_idea")
    if "space" in text_l:
        tags.append("space")
    if "ship" in text_l or "spaceship" in text_l:
        tags.append("spaceship")
    if "retro" in text_l or "8-bit" in text_l or "8 byte" in text_l:
        tags.append("retro_style")
    if "lsl" in text_l:
        tags.append("lsl")
    if "python" in text_l:
        tags.append("python")
    if has_reminder_intent(text_l):
        tags.append("reminder")
    if "task" in text_l:
        tags.append("task")
    if "error" in text_l or "issue" in text_l or "bug" in text_l:
        tags.append("troubleshooting")
    if "solution" in text_l or "fixed" in text_l or "resolved" in text_l:
        tags.append("solution")
    for kw in keywords[:4]:
        if kw not in tags:
            tags.append(kw)
    deduped = []
    seen = set()
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            deduped.append(tag)
    return deduped[:12]


def infer_title(record_type: str, user_text: str, keywords):
    def clean_words(words):
        pretty = []
        for w in words:
            w = w.strip(" -_.,!?")
            if not w or w.lower() in STOPWORDS:
                continue
            pretty.append(w.capitalize())
        return pretty

    if record_type == "dream":
        if keywords:
            return f"{' '.join(clean_words(keywords[:3]))} Dream".strip()
        return "Dream Memory"
    if record_type == "task":
        match = re.search(r"remind me .*? to (.+)", user_text, re.I)
        if match:
            return f"Reminder: {match.group(1).strip().rstrip('.!?')[:60]}"
        return "Reminder Task"
    if record_type == "issue":
        if keywords:
            return f"Issue: {' '.join(clean_words(keywords[:4]))}".strip()
        return "Technical Issue"
    if record_type == "resolution":
        if keywords:
            return f"Resolution: {' '.join(clean_words(keywords[:4]))}".strip()
        return "Technical Resolution"
    if record_type == "idea":
        if keywords:
            return f"Idea: {' '.join(clean_words(keywords[:4]))}".strip()
        return "Idea Memory"
    if record_type == "preference":
        if keywords:
            return f"Preference: {' '.join(clean_words(keywords[:4]))}".strip()
        return "Preference Memory"
    if keywords:
        cleaned = clean_words(keywords[:5])
        return " ".join(cleaned) if cleaned else "Conversation Memory"
    return "Conversation Memory"


def is_datetime_query(text: str) -> bool:
    t = normalize_persona_prefixed_input(text).lower().strip()
    patterns = (
        "what is today's date", "what is todays date", "what's today's date", "what's todays date",
        "what date is it", "what day is it", "what time is it",
        "current date", "current time",
        "today's date", "todays date"
    )
    return any(p in t for p in patterns)


def answer_datetime_query(text: str) -> str:
    now = datetime.now()
    t = normalize_persona_prefixed_input(text).lower()
    if "time" in t:
        return f"Current system time: {now.strftime('%I:%M:%S %p')}."
    if "day" in t:
        return f"Current system date: {now.strftime('%m/%d/%Y')} ({now.strftime('%A')})."
    return f"Current system date: {now.strftime('%m/%d/%Y')}."


def has_reminder_intent(text: str) -> bool:
    return classify_task_intent(text).get("intent") in {"reminder", "timer", "task"}


def normalize_persona_prefixed_input(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    persona_prefix = r"^\s*(?:grim|grimveil|grimveile|grimveile-42)\s*,?\s*[:\-]?\s*"
    normalized = re.sub(persona_prefix, "", t, flags=re.I)
    return normalized.strip() or t


def strip_leading_invocation_fluff(text: str) -> str:
    cleaned = normalize_persona_prefixed_input(text)
    if not cleaned:
        return ""
    patterns = [
        r"^\s*hey\s+grim(?:veile|veil)?\s*,?\s*",
        r"^\s*grim(?:veile|veil)?\s*,?\s*",
        r"^\s*do\s+me\s+a\s+favor(?:\s+and)?\s+",
        r"^\s*please\s+",
        r"^\s*can\s+you\s+",
        r"^\s*could\s+you\s+",
        r"^\s*would\s+you\s+",
        r"^\s*kindly\s+",
        r"^\s*just\s+",
    ]
    prior = None
    current = cleaned
    while prior != current:
        prior = current
        for pattern in patterns:
            current = re.sub(pattern, "", current, flags=re.I)
        current = re.sub(r"\s+", " ", current).strip(" ,.-")
    return current or cleaned


def classify_task_intent(text: str) -> dict:
    cleaned = strip_leading_invocation_fluff(text)
    low = cleaned.lower()
    timer_patterns = (
        r"\bset(?:\s+a)?\s+timer\b",
        r"\bstart(?:\s+a)?\s+timer\b",
        r"\bset\s+timer\s+for\b",
        r"\bset(?:\s+a)?\s+timer\s+for\b",
        r"\btimer\s+for\b",
    )
    reminder_patterns = (
        r"\bremind me\b",
        r"\bset(?:\s+a)?\s+reminder\b",
        r"\badd(?:\s+a)?\s+reminder\b",
        r"\bwant(?:\s+a)?\s+reminder\b",
        r"\bset(?:\s+an?)?\s+alarm\b",
        r"\badd(?:\s+an?)?\s+alarm\b",
        r"\balarm\s+for\b",
    )
    task_patterns = (
        r"\badd(?:\s+a)?\s+task\b",
        r"\bcreate(?:\s+a)?\s+task\b",
        r"\bnew\s+task\b",
    )
    if any(re.search(p, low) for p in timer_patterns):
        intent = "timer"
    elif any(re.search(p, low) for p in reminder_patterns):
        intent = "reminder"
    elif any(re.search(p, low) for p in task_patterns):
        intent = "task"
    else:
        intent = "chat"
    return {
        "intent": intent,
        "cleaned_input": cleaned,
    }


def is_strong_scheduling_command(text: str) -> bool:
    cleaned = strip_leading_invocation_fluff(text)
    low = cleaned.lower()
    command_patterns = (
        r"\bremind me\b",
        r"\bset(?:\s+a)?\s+reminder\b",
        r"\badd(?:\s+a)?\s+reminder\b",
        r"\bset(?:\s+a)?\s+timer\b",
        r"\bstart(?:\s+a)?\s+timer\b",
        r"\b(?:set|add)(?:\s+an?)?\s+alarm(?:\s+for)?\b",
        r"\balarm\s+for\b",
        r"\btimer\s+for\b",
        r"\b(?:add|create)(?:\s+a)?\s+task\b",
        r"\bnew\s+task\b",
    )
    return any(re.search(p, low) for p in command_patterns)


def parse_duration_phrase(phrase: str):
    tokens = re.findall(r"(\d+)\s*(d|day|days|h|hr|hour|hours|m|min|minute|minutes|s|sec|second|seconds)", phrase.lower())
    if not tokens:
        return None
    seconds = 0
    for amount_s, unit in tokens:
        amount = int(amount_s)
        if unit.startswith("d"):
            seconds += amount * 86400
        elif unit.startswith("h"):
            seconds += amount * 3600
        elif unit.startswith("m"):
            seconds += amount * 60
        elif unit.startswith("s"):
            seconds += amount
    return timedelta(seconds=seconds) if seconds > 0 else None


def summarize_memory(record_type: str, user_text: str, assistant_text: str = ""):
    user_text = user_text.strip()
    assistant_text = assistant_text.strip()
    if record_type == "dream":
        return f"User described a dream: {user_text[:220]}"
    if record_type == "task":
        return f"Reminder/task requested: {user_text[:220]}"
    if record_type == "issue":
        return f"Technical issue or troubleshooting discussion: {user_text[:220]}"
    if record_type == "resolution":
        base = assistant_text or user_text
        return f"Potential or confirmed solution recorded: {base[:220]}"
    if record_type == "idea":
        return f"Idea or concept discussion: {user_text[:220]}"
    if record_type == "preference":
        return f"User preference or standing instruction: {user_text[:220]}"
    return f"Conversation summary seed: {user_text[:220]}"


def format_duration(delta_seconds: float) -> str:
    total = max(0, int(delta_seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if not parts:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    return ", ".join(parts[:3])


def is_memory_query(text: str) -> bool:
    t = text.lower()
    return any(hint in t for hint in MEMORY_QUERY_HINTS)


def score_overlap(query_terms, text_terms):
    if not query_terms or not text_terms:
        return 0
    hits = len(set(query_terms) & set(text_terms))
    return hits




def generate_grimveil_alert(path: Path):
    sample_rate = 44100
    notes = [(440, 0.18), (554, 0.18), (659, 0.22), (880, 0.25), (784, 0.20)]
    audio = []
    for freq, length in notes:
        samples = int(sample_rate * length)
        for i in range(samples):
            t = i / sample_rate
            square = 1.0 if math.sin(2 * math.pi * freq * t) >= 0 else -1.0
            sine = math.sin(2 * math.pi * freq * t)
            value = (0.55 * square) + (0.35 * sine)
            fade = 1.0 - (i / max(1, samples))
            value *= fade * 0.45
            audio.append(max(-32767, min(32767, int(value * 32767))))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'w') as f:
        f.setparams((1, 2, sample_rate, 0, 'NONE', 'not compressed'))
        for s in audio:
            f.writeframes(struct.pack('<h', s))


def play_grimveil_alert(memory_dir: Path):
    if not WINSOUND_OK:
        QApplication.beep()
        return
    sound_dir = memory_dir / 'sounds'
    wav_path = sound_dir / 'grimveil_alert.wav'
    if not wav_path.exists():
        generate_grimveil_alert(wav_path)
    winsound.PlaySound(str(wav_path), winsound.SND_FILENAME | winsound.SND_ASYNC)


class MiniCalendarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(4)
        header = QHBoxLayout()
        header.setContentsMargins(0,0,0,0)
        self.prev_btn = QPushButton('<<')
        self.next_btn = QPushButton('>>')
        self.month_lbl = QLabel('')
        self.month_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for btn in (self.prev_btn, self.next_btn):
            btn.setFixedWidth(34)
            btn.setStyleSheet(f"background: {C_BG3}; color: {C_CYAN}; border: 1px solid {C_CYAN_DIM}; font-size: 10px; font-weight: bold; padding: 2px;")
        self.month_lbl.setStyleSheet(f"color: {C_GOLD}; border: none; font-size: 10px; font-weight: bold;")
        header.addWidget(self.prev_btn)
        header.addWidget(self.month_lbl,1)
        header.addWidget(self.next_btn)
        layout.addLayout(header)
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setNavigationBarVisible(False)
        self.calendar.setStyleSheet(
            f"QCalendarWidget QWidget{{alternate-background-color:{C_BG2};}} "
            f"QToolButton{{color:{C_GOLD};}} "
            f"QCalendarWidget QAbstractItemView:enabled{{background:{C_BG2}; color:#ffffff; selection-background-color:{C_CYAN_DIM}; selection-color:{C_TEXT}; gridline-color:{C_BORDER};}} "
            f"QCalendarWidget QAbstractItemView:disabled{{color:#8b95a1;}}"
        )
        layout.addWidget(self.calendar)
        self.prev_btn.clicked.connect(lambda: self.calendar.showPreviousMonth())
        self.next_btn.clicked.connect(lambda: self.calendar.showNextMonth())
        self.calendar.currentPageChanged.connect(self._update_label)
        self._update_label()
        self._apply_formats()
    def _update_label(self, *args):
        year = self.calendar.yearShown()
        month = self.calendar.monthShown()
        self.month_lbl.setText(f"{date(year, month, 1).strftime('%B %Y')}")
        self._apply_formats()

    def _apply_formats(self):
        base = QTextCharFormat()
        base.setForeground(QColor("#e7edf3"))
        saturday = QTextCharFormat()
        saturday.setForeground(QColor(C_CYAN))
        sunday = QTextCharFormat()
        sunday.setForeground(QColor(C_RED))
        self.calendar.setWeekdayTextFormat(Qt.DayOfWeek.Monday, base)
        self.calendar.setWeekdayTextFormat(Qt.DayOfWeek.Tuesday, base)
        self.calendar.setWeekdayTextFormat(Qt.DayOfWeek.Wednesday, base)
        self.calendar.setWeekdayTextFormat(Qt.DayOfWeek.Thursday, base)
        self.calendar.setWeekdayTextFormat(Qt.DayOfWeek.Friday, base)
        self.calendar.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, saturday)
        self.calendar.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, sunday)

        year = self.calendar.yearShown()
        month = self.calendar.monthShown()
        first_day = QDate(year, month, 1)
        for day in range(1, first_day.daysInMonth() + 1):
            d = QDate(year, month, day)
            fmt = QTextCharFormat()
            weekday = d.dayOfWeek()
            if weekday == Qt.DayOfWeek.Saturday.value:
                fmt.setForeground(QColor(C_CYAN))
            elif weekday == Qt.DayOfWeek.Sunday.value:
                fmt.setForeground(QColor(C_RED))
            else:
                fmt.setForeground(QColor("#e7edf3"))
            self.calendar.setDateTextFormat(d, fmt)

        today_fmt = QTextCharFormat()
        today_fmt.setForeground(QColor("#68d39a"))
        today_fmt.setBackground(QColor("#163825"))
        today_fmt.setFontWeight(QFont.Weight.Bold)
        self.calendar.setDateTextFormat(QDate.currentDate(), today_fmt)


class CollapsibleSection(QWidget):
    def __init__(self, title: str, content: QWidget, expanded: bool = True, parent=None):
        super().__init__(parent)
        self.content = content
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.header_btn = QPushButton()
        self.header_btn.setCheckable(True)
        self.header_btn.setChecked(expanded)
        self.header_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header_btn.setStyleSheet(f"background: {C_BG3}; color: {C_GOLD}; border: 1px solid {C_CYAN_DIM}; font-size: 10px; font-weight: bold; padding: 4px 8px; text-align: left;")
        self.header_btn.clicked.connect(self._toggle)
        layout.addWidget(self.header_btn)
        layout.addWidget(self.content)
        self.title = title
        self._toggle(expanded)

    def _toggle(self, checked: bool):
        self.content.setVisible(checked)
        self.content.setMaximumHeight(16777215 if checked else 0)
        glyph = '▼' if checked else '▶'
        self.header_btn.setText(f"{glyph} {self.title}")
        self.updateGeometry()
        parent = self.parentWidget()
        if parent and parent.layout():
            parent.layout().activate()
        window = self.window()
        if window and window.layout():
            window.layout().activate()


class MemoryManager:
    def __init__(self, memory_dir: Path, persona_name: str):
        self.memory_dir = memory_dir
        self.persona_name = persona_name
        self.messages_path = self.memory_dir / "messages.jsonl"
        self.memories_path = self.memory_dir / "memories.jsonl"
        self.tasks_path = self.memory_dir / "tasks.jsonl"
        self.state_path = self.memory_dir / "state.json"
        self.index_path = self.memory_dir / "index.json"
        self.first_run = False
        self._bootstrap()

    def _bootstrap(self):
        if not self.memory_dir.exists():
            self.memory_dir.mkdir(parents=True, exist_ok=True)
            self.first_run = True
        (self.memory_dir / "sounds").mkdir(parents=True, exist_ok=True)
        for path in (self.messages_path, self.memories_path, self.tasks_path):
            if not path.exists():
                path.write_text("", encoding="utf-8")
        if not self.state_path.exists():
            self.first_run = True
            self.save_state({
                "persona_name": self.persona_name,
                "session_count": 0,
                "last_startup": None,
                "last_shutdown": None,
                "last_active": None,
                "anchor_state": 1.0,
                "total_messages": 0,
                "total_memories": 0,
                "version": APP_VERSION,
            })
        if not self.index_path.exists():
            self.index_path.write_text(json.dumps({"version": APP_VERSION}, indent=2), encoding="utf-8")
        wav_path = self.memory_dir / "sounds" / "grimveil_alert.wav"
        if not wav_path.exists():
            generate_grimveil_alert(wav_path)

    def load_state(self):
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "persona_name": self.persona_name,
                "session_count": 0,
                "last_startup": None,
                "last_shutdown": None,
                "last_active": None,
                "anchor_state": 1.0,
                "total_messages": 0,
                "total_memories": 0,
                "version": APP_VERSION,
            }

    def save_state(self, state):
        ensure_parent(self.state_path)
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _append_jsonl(self, path: Path, obj: dict):
        ensure_parent(path)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def _read_jsonl(self, path: Path):
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        items = []
        if raw.startswith('['):
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    return [x for x in data if isinstance(x, dict)]
            except Exception:
                pass
        if raw.startswith('{') and '\n' not in raw:
            try:
                obj = json.loads(raw)
                return [obj] if isinstance(obj, dict) else []
            except Exception:
                pass
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    items.append(obj)
            except Exception:
                continue
        return items

    def append_message(self, session_id: str, role: str, content: str, anchor_state: float, emotion: str = ""):
        record = {
            "id": f"msg_{uuid.uuid4().hex[:12]}",
            "timestamp": local_now_iso(),
            "session_id": session_id,
            "persona": self.persona_name,
            "role": role,
            "content": content,
            "anchor_state": round(anchor_state, 3),
            "emotion": emotion,
        }
        self._append_jsonl(self.messages_path, record)
        return record

    def append_memory(self, session_id: str, user_text: str, assistant_text: str, source_message_ids=None):
        source_message_ids = source_message_ids or []
        record_type = infer_record_type(user_text, assistant_text)
        keywords = extract_keywords(user_text + " " + assistant_text)
        tags = infer_tags(record_type, user_text + " " + assistant_text, keywords)
        title = infer_title(record_type, user_text, keywords)
        summary = summarize_memory(record_type, user_text, assistant_text)
        memory = {
            "id": f"mem_{uuid.uuid4().hex[:12]}",
            "timestamp": local_now_iso(),
            "session_id": session_id,
            "persona": self.persona_name,
            "type": record_type,
            "title": title,
            "summary": summary,
            "content": user_text[:4000],
            "assistant_context": assistant_text[:1200],
            "keywords": keywords,
            "tags": tags,
            "source_message_ids": source_message_ids,
            "confidence": 0.70 if record_type in {"dream", "issue", "idea", "preference", "resolution"} else 0.55,
        }
        if self._is_near_duplicate(memory):
            return None
        self._append_jsonl(self.memories_path, memory)
        return memory

    def _is_near_duplicate(self, candidate: dict):
        recent = self.load_recent_memories(limit=25)
        cand_title = candidate.get("title", "").lower().strip()
        cand_summary = candidate.get("summary", "").lower().strip()
        for item in recent:
            if item.get("title", "").lower().strip() == cand_title:
                return True
            if item.get("summary", "").lower().strip() == cand_summary:
                return True
        return False

    def load_recent_messages(self, limit=20):
        items = self._read_jsonl(self.messages_path)
        return items[-limit:]

    def load_recent_memories(self, limit=20):
        items = self._read_jsonl(self.memories_path)
        return items[-limit:]

    def load_tasks(self):
        tasks = self._read_jsonl(self.tasks_path)
        normalized = []
        changed = False
        for task in tasks:
            if not isinstance(task, dict):
                continue
            if 'id' not in task:
                task['id'] = f"task_{uuid.uuid4().hex[:10]}"
                changed = True
            if "created_at" not in task:
                task["created_at"] = task.get("created", local_now_iso())
                changed = True
            if "due_at" not in task:
                task["due_at"] = task.get("due")
                changed = True
            task.setdefault('status', 'pending')
            task.setdefault('retry_count', int(task.get('repeat_count', 0) or 0))
            task.setdefault('acknowledged_at', None)
            task.setdefault('last_triggered_at', None)
            task.setdefault('next_retry_at', None)
            task.setdefault('pre_announced', False)
            task.setdefault('source', task.get('created_from', 'local'))
            task.setdefault('metadata', {})
            task.setdefault('google_event_id', None)
            task.setdefault('sync_status', 'pending')
            task.setdefault('last_synced_at', None)
            due_raw = task.get('due_at') or task.get('due')
            if due_raw and not task.get('pre_trigger'):
                due = parse_iso_for_compare(due_raw, context="load_tasks_pre_trigger")
                if due:
                    task['pre_trigger'] = (due - timedelta(minutes=1)).isoformat(timespec='seconds')
                    changed = True
            normalized.append(task)
        if changed:
            self.save_all_tasks(normalized)
        return normalized

    def save_all_tasks(self, tasks):
        ensure_parent(self.tasks_path)
        with self.tasks_path.open("w", encoding="utf-8") as f:
            for task in tasks:
                f.write(json.dumps(task, ensure_ascii=False) + "\n")

    def add_task(self, text: str, due_dt: datetime, created_from: str):
        tasks = self.load_tasks()
        task = {
            "id": f"task_{uuid.uuid4().hex[:10]}",
            "created_at": local_now_iso(),
            "due_at": due_dt.isoformat(timespec="seconds"),
            "pre_trigger": (due_dt - timedelta(minutes=1)).isoformat(timespec="seconds"),
            "text": text.strip(),
            "status": "pending",
            "acknowledged_at": None,
            "retry_count": 0,
            "last_triggered_at": None,
            "next_retry_at": None,
            "source": "local",
            "google_event_id": None,
            "sync_status": "pending",
            "last_synced_at": None,
            "metadata": {"input": created_from},
        }
        tasks.append(task)
        self.save_all_tasks(tasks)
        return task

    def update_task_google_sync(
        self,
        task_id: str,
        sync_status: str,
        google_event_id: str = None,
        last_synced_at: str = None,
        error_message: str = None,
    ):
        tasks = self.load_tasks()
        updated = None
        for task in tasks:
            if task.get("id") != task_id:
                continue
            task["sync_status"] = sync_status
            task["last_synced_at"] = last_synced_at
            if google_event_id:
                task["google_event_id"] = google_event_id
            if error_message:
                task.setdefault("metadata", {})
                task["metadata"]["google_sync_error"] = error_message[:240]
            updated = task
            break
        if updated:
            self.save_all_tasks(tasks)
        return updated

    def acknowledge_due_tasks(self):
        tasks = self.load_tasks()
        changed = []
        active = False
        for task in tasks:
            if task.get("status") in {"triggered", "snoozed", "retry_pending", "pending"} and not task.get("acknowledged_at"):
                task["status"] = "completed"
                task["acknowledged_at"] = local_now_iso()
                task["completed_at"] = local_now_iso()
                changed.append(task)
                active = True
        if changed:
            self.save_all_tasks(tasks)
        return active, changed


    def clear_completed_tasks(self):
        tasks = self.load_tasks()
        kept = [t for t in tasks if t.get('status') not in {'completed', 'cancelled'}]
        removed = len(tasks) - len(kept)
        if removed:
            self.save_all_tasks(kept)
        return removed

    def get_due_events(self):
        now = now_for_compare()
        tasks = self.load_tasks()
        events = []
        changed = False
        for task in tasks:
            status = task.get("status", "pending")
            due = parse_iso_for_compare(task.get("due_at") or task.get("due"), context="task_due_events_due")
            pre = parse_iso_for_compare(task.get("pre_trigger"), context="task_due_events_pre")
            last_triggered = parse_iso_for_compare(task.get("last_triggered_at"), context="task_due_events_last_triggered")
            next_retry = parse_iso_for_compare(task.get("next_retry_at"), context="task_due_events_next_retry")

            if task.get("acknowledged_at"):
                continue

            if status == "pending" and pre and now >= pre and not task.get("pre_announced"):
                task["pre_announced"] = True
                events.append(("pre", task))
                changed = True

            if status == "pending" and due and now >= due:
                task["status"] = "triggered"
                task["last_triggered_at"] = local_now_iso()
                task["alert_deadline"] = (now + timedelta(minutes=3)).isoformat(timespec="seconds")
                events.append(("due", task))
                changed = True
                continue

            if status == "triggered":
                deadline = parse_iso_for_compare(task.get("alert_deadline"), context="task_due_events_alert_deadline")
                if deadline and now >= deadline:
                    task["status"] = "snoozed"
                    task["next_retry_at"] = (now + timedelta(minutes=12)).isoformat(timespec="seconds")
                    events.append(("retry_scheduled", task))
                    changed = True
                    continue

            if status in {"retry_pending", "snoozed"} and next_retry and now >= next_retry:
                task["status"] = "triggered"
                task["retry_count"] = int(task.get("retry_count", 0)) + 1
                task["last_triggered_at"] = local_now_iso()
                task["alert_deadline"] = (now + timedelta(minutes=3)).isoformat(timespec="seconds")
                task["next_retry_at"] = None
                events.append(("due", task))
                changed = True

        if changed:
            self.save_all_tasks(tasks)
        return events

    def search_memories(self, query: str, limit=6, include_trace: bool = False):
        memories = self._read_jsonl(self.memories_path)
        trace = {
            "query": query,
            "total_records": len(memories),
            "candidate_count": 0,
            "scored_count": 0,
            "selected_count": 0,
            "candidates": [],
            "selected_ids": [],
            "no_match": False,
        }
        if not query.strip():
            selected = memories[-limit:]
            trace["candidate_count"] = len(selected)
            trace["selected_count"] = len(selected)
            trace["selected_ids"] = [item.get("id") for item in selected if item.get("id")]
            for index, item in enumerate(memories, start=1):
                if item in selected:
                    trace["candidates"].append({
                        "score": None,
                        "selected": True,
                        "jsonl_index": index,
                        "record": item,
                    })
            return (selected, trace) if include_trace else selected
        q_terms = extract_keywords(query, limit=16)
        results = []
        for index, item in enumerate(memories, start=1):
            item_terms = set(extract_keywords(" ".join([
                item.get("title", ""),
                item.get("summary", ""),
                item.get("content", ""),
                " ".join(item.get("keywords", [])),
                " ".join(item.get("tags", [])),
            ]), limit=40))
            score = score_overlap(q_terms, item_terms)

            rt = item.get("type", "")
            ql = query.lower()
            if "dream" in ql and rt == "dream":
                score += 4
            if "reminder" in ql or "task" in ql:
                if rt == "task" or "reminder" in item.get("tags", []):
                    score += 3
            if "idea" in ql and rt == "idea":
                score += 2
            if "code" in ql or "lsl" in ql or "python" in ql:
                if rt in {"issue", "resolution"}:
                    score += 2

            if score > 0:
                results.append((score, item, index))
                trace["candidates"].append({
                    "score": score,
                    "selected": False,
                    "jsonl_index": index,
                    "record": item,
                })
        trace["candidate_count"] = len(results)
        trace["scored_count"] = len(results)
        results.sort(key=lambda x: (x[0], x[1].get("timestamp", "")), reverse=True)
        selected_pairs = results[:limit]
        selected = [item for _, item, _ in selected_pairs]
        selected_ids = {item.get("id") for item in selected if item.get("id")}
        trace["selected_count"] = len(selected)
        trace["selected_ids"] = list(selected_ids)
        trace["no_match"] = len(selected) == 0
        for candidate in trace["candidates"]:
            rec_id = candidate["record"].get("id")
            if rec_id and rec_id in selected_ids:
                candidate["selected"] = True
        return (selected, trace) if include_trace else selected

    def memory_record_count(self):
        return len(self._read_jsonl(self.memories_path))


class AnchorStatusPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 160)
        self.anchor_integrity = 1.0
        self.compute_reserve = 1.0
        self.moon_fill = 0.0
        self.moon_name = "NEW MOON"
        self.depression_load = 0.05
        self.vitality = 1.0
        self.token_pool = 0.0
        self.last_feed_time = 0.0
        self.sunrise = "06:00"
        self.sunset = "18:30"
        self.anchor_state = 1.0
        self.state_name = "WHOLE"
        self.tactical_state = get_tactical_state(self.anchor_state)
        self._fetch_sun()
        phase, name = get_moon_phase()
        self.moon_fill = phase
        self.moon_name = name
        self.setStyleSheet("background: transparent;")

    def _fetch_sun(self):
        def fetch():
            sr, ss = get_sun_times()
            self.sunrise = sr
            self.sunset = ss
        threading.Thread(target=fetch, daemon=True).start()

    def update_stats(self, anchor_state, gpu_temp, vram_used, vram_total, ram_used, ram_total, session_secs):
        if self.last_feed_time > 0:
            idle_secs = time.time() - self.last_feed_time
            drain = idle_secs / 30.0
            self.token_pool = max(0.0, self.token_pool - drain)
            self.last_feed_time = time.time()

        self.anchor_state = max(0.0, min(1.0, anchor_state))
        self.anchor_integrity = self.anchor_state
        self.depression_load = 1.0 - (self.anchor_state * 0.95)

        if vram_total > 0:
            self.compute_reserve = max(0.0, min(1.0, 1.0 - (vram_used / vram_total)))
        if ram_total > 0:
            self.vitality = max(0.0, min(1.0, 1.0 - (ram_used / ram_total)))

        self.state_name = get_anchor_state_name(self.anchor_state)
        self.tactical_state = get_tactical_state(self.anchor_state)
        phase, name = get_moon_phase()
        self.moon_fill = phase
        self.moon_name = name
        self.update()

    def feed(self, tokens):
        self.token_pool = min(4096.0, self.token_pool + tokens)
        self.last_feed_time = time.time()
        self.update()

    def _draw_sphere(self, painter, cx, cy, r, fill, color_full, color_empty, label):
        from PyQt6.QtGui import QRadialGradient
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 80))
        painter.drawEllipse(int(cx - r + 3), int(cy - r + 3), int(r * 2), int(r * 2))
        painter.setBrush(QColor(color_empty))
        painter.setPen(QColor(color_full).darker(150))
        painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        if fill > 0.02:
            path = QPainterPath()
            path.addEllipse(cx - r, cy - r, r * 2, r * 2)
            from PyQt6.QtCore import QRectF
            fill_y = cy + r - (fill * r * 2)
            rect_fill = QRectF(cx - r, fill_y, r * 2, cy + r - fill_y)
            fill_path = QPainterPath()
            fill_path.addRect(rect_fill)
            clipped = path.intersected(fill_path)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color_full))
            painter.drawPath(clipped)

        grad = QRadialGradient(cx - r * 0.3, cy - r * 0.3, r * 0.6)
        grad.setColorAt(0, QColor(255, 255, 255, 60))
        grad.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor(color_full))
        painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        painter.setPen(QColor(color_full))
        painter.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        fm = painter.fontMetrics()
        lw = fm.horizontalAdvance(label)
        painter.drawText(int(cx - lw / 2), int(cy + r + 12), label)

    def _draw_moon(self, painter, cx, cy, r):
        painter.setPen(QColor(C_SILVER_DIM))
        painter.setBrush(QColor(20, 24, 32))
        painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))
        phase = self.moon_fill % 1.0
        illumination = (1.0 - math.cos(2.0 * math.pi * phase)) / 2.0
        waxing = phase < 0.5

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(220, 220, 200))
        painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        shadow_fraction = max(0.0, min(1.0, 1.0 - illumination))
        if shadow_fraction > 0.0:
            moon_area = math.pi * r * r

            def overlap_fraction(distance):
                distance = max(0.0, min(2.0 * r, distance))
                if distance <= 0.0:
                    return 1.0
                if distance >= 2.0 * r:
                    return 0.0
                overlap_area = (
                    (2.0 * r * r * math.acos(distance / (2.0 * r)))
                    - (0.5 * distance * math.sqrt(max(0.0, (4.0 * r * r) - (distance * distance))))
                )
                return overlap_area / moon_area

            target_overlap = shadow_fraction
            lo, hi = 0.0, 2.0 * r
            for _ in range(24):
                mid = (lo + hi) * 0.5
                if overlap_fraction(mid) > target_overlap:
                    lo = mid
                else:
                    hi = mid
            shadow_offset = (lo + hi) * 0.5
            shadow_dir = -1.0 if waxing else 1.0
            painter.setBrush(QColor(15, 18, 30))
            painter.drawEllipse(
                int(cx - r + (shadow_dir * shadow_offset)),
                int(cy - r),
                int(r * 2),
                int(r * 2)
            )

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor(C_SILVER))
        painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        painter.setPen(QColor(C_SILVER))
        painter.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        fm = painter.fontMetrics()
        lw = fm.horizontalAdvance(self.moon_name)
        painter.drawText(int(cx - lw / 2), int(cy + r + 12), self.moon_name)

    def _draw_bar(self, painter, x, y, w, h, fill, color, label):
        painter.fillRect(x, y, w, h, QColor(18, 23, 32))
        painter.setPen(QColor(color).darker(150))
        painter.drawRect(x, y, w - 1, h - 1)
        if fill > 0:
            fill_w = max(1, int((w - 2) * fill))
            painter.fillRect(x + 1, y + 1, fill_w, h - 2, QColor(color))
        painter.setPen(QColor(color))
        painter.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        painter.drawText(x, y - 2, label)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(C_BG2))
        painter.setPen(QColor(C_CYAN_DIM))
        painter.drawRect(0, 0, w - 1, h - 1)

        bar_w = int(w / 2) - 16
        bar_h = 8
        bar_y = 10

        self._draw_bar(painter, 10, bar_y + 10, bar_w, bar_h, self.depression_load, "#d16a4c", "DEPRESSION")
        self._draw_bar(painter, 10 + bar_w + 12, bar_y + 10, bar_w, bar_h, self.vitality, "#36b36d", "VITALITY")

        sphere_r = 28
        sphere_y = 75
        spacing = int(w / 3)
        self._draw_sphere(painter, spacing * 0.5, sphere_y, sphere_r, self.anchor_integrity, C_GOLD, C_GOLD_DIM, "ANCHOR")
        self._draw_moon(painter, spacing * 1.5, sphere_y, sphere_r)
        self._draw_sphere(painter, spacing * 2.5, sphere_y, sphere_r, self.compute_reserve, C_PURPLE, C_PURPLE_DIM, "BUFFER")

        painter.setPen(QColor(C_GOLD))
        painter.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        now_str = datetime.now().strftime("%H:%M")
        state_text = f"[ {self.state_name} ]  {self.tactical_state}  {now_str}"
        fm = painter.fontMetrics()
        sw = fm.horizontalAdvance(state_text)
        painter.drawText(int(w / 2 - sw / 2), h - 22, state_text)

        sun_text = f"☀ {self.sunrise}   ☽ {self.sunset}"
        painter.setPen(QColor(C_TEXT_DIM))
        painter.setFont(QFont("Courier New", 7))
        fm2 = painter.fontMetrics()
        sw2 = fm2.horizontalAdvance(sun_text)
        painter.drawText(int(w / 2 - sw2 / 2), h - 8, sun_text)
        painter.end()


class GaugeWidget(QWidget):
    def __init__(self, label, unit="", max_val=100, color=C_CYAN, parent=None):
        super().__init__(parent)
        self.label = label
        self.unit = unit
        self.max_val = max_val
        self.color = color
        self.value = 0
        self.display_text = "0"
        self.setMinimumHeight(70)
        self.setMinimumWidth(120)

    def setValue(self, value, display_text=None):
        self.value = min(value, self.max_val)
        self.display_text = display_text if display_text else f"{value:.0f}{self.unit}"
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(C_BG3))
        painter.setPen(QColor(C_BORDER))
        painter.drawRect(0, 0, w - 1, h - 1)
        painter.setPen(QColor(C_TEXT_DIM))
        painter.setFont(QFont("Georgia", 8, QFont.Weight.Bold))
        painter.drawText(6, 14, self.label)
        painter.setPen(QColor(self.color))
        painter.setFont(QFont("Georgia", 11, QFont.Weight.Bold))
        painter.drawText(6, 32, self.display_text)

        bar_y = h - 20
        bar_h = 10
        bar_w = w - 12
        painter.fillRect(6, bar_y, bar_w, bar_h, QColor(C_BG))
        painter.setPen(QColor(C_BORDER))
        painter.drawRect(6, bar_y, bar_w, bar_h)

        if self.max_val > 0:
            fill_w = int((self.value / self.max_val) * (bar_w - 2))
            if fill_w > 0:
                pct = self.value / self.max_val
                bar_color = C_RED if pct > 0.85 else C_CYAN if pct > 0.65 else self.color
                grad = QLinearGradient(7, bar_y + 1, 7 + fill_w, bar_y + 1)
                grad.setColorAt(0, QColor(bar_color).darker(150))
                grad.setColorAt(1, QColor(bar_color))
                painter.fillRect(7, bar_y + 1, fill_w, bar_h - 2, grad)
        painter.end()

class GoogleCalendarService:
    def __init__(self, credentials_path: Path, token_path: Path):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self._service = None

    def _persist_token(self, creds):
        ensure_parent(self.token_path)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(creds.to_json(), encoding="utf-8")

    def _build_service(self):
        print(f"[GCal][DEBUG] Credentials path: {self.credentials_path}")
        print(f"[GCal][DEBUG] Token path: {self.token_path}")
        print(f"[GCal][DEBUG] Credentials file exists: {self.credentials_path.exists()}")
        print(f"[GCal][DEBUG] Token file exists: {self.token_path.exists()}")

        if not GOOGLE_API_OK:
            detail = GOOGLE_IMPORT_ERROR or "unknown ImportError"
            raise RuntimeError(f"Missing Google Calendar Python dependency: {detail}")
        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"Google credentials/auth configuration not found: {self.credentials_path}"
            )

        creds = None
        link_established = False
        if self.token_path.exists():
            creds = GoogleCredentials.from_authorized_user_file(str(self.token_path), GOOGLE_SCOPES)

        if creds and creds.valid and not creds.has_scopes(GOOGLE_SCOPES):
            raise RuntimeError(GOOGLE_SCOPE_REAUTH_MSG)

        if creds and creds.expired and creds.refresh_token:
            print("[GCal][DEBUG] Refreshing expired Google token.")
            try:
                creds.refresh(GoogleAuthRequest())
                self._persist_token(creds)
            except Exception as ex:
                raise RuntimeError(
                    f"Google token refresh failed after scope expansion: {ex}. {GOOGLE_SCOPE_REAUTH_MSG}"
                ) from ex

        if not creds or not creds.valid:
            print("[GCal][DEBUG] Starting OAuth flow for Google Calendar.")
            flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), GOOGLE_SCOPES)
            creds = flow.run_local_server(port=0)
            self._persist_token(creds)
            link_established = True

        self._service = google_build("calendar", "v3", credentials=creds)
        print("[GCal][DEBUG] Authenticated Google Calendar service created successfully.")
        return link_established

    def _get_google_event_timezone(self) -> str:
        local_tzinfo = datetime.now().astimezone().tzinfo
        candidates = []
        if local_tzinfo is not None:
            candidates.extend([
                getattr(local_tzinfo, "key", None),
                getattr(local_tzinfo, "zone", None),
                str(local_tzinfo),
                local_tzinfo.tzname(datetime.now()),
            ])

        env_tz = os.environ.get("TZ")
        if env_tz:
            candidates.append(env_tz)

        for candidate in candidates:
            if not candidate:
                continue
            mapped = WINDOWS_TZ_TO_IANA.get(candidate, candidate)
            if "/" in mapped:
                return mapped

        print(
            "[GCal][WARN] Unable to resolve local IANA timezone. "
            f"Falling back to {DEFAULT_GOOGLE_IANA_TIMEZONE}."
        )
        return DEFAULT_GOOGLE_IANA_TIMEZONE

    def create_event_for_task(self, task: dict):
        due_at = parse_iso_for_compare(task.get("due_at") or task.get("due"), context="google_create_event_due")
        if not due_at:
            raise ValueError("Task due time is missing or invalid.")

        link_established = False
        if self._service is None:
            link_established = self._build_service()

        due_local = normalize_datetime_for_compare(due_at, context="google_create_event_due_local")
        start_dt = due_local.replace(microsecond=0, tzinfo=None)
        end_dt = start_dt + timedelta(minutes=30)
        tz_name = self._get_google_event_timezone()

        event_payload = {
            "summary": (task.get("text") or "Reminder").strip(),
            "start": {"dateTime": start_dt.isoformat(timespec="seconds"), "timeZone": tz_name},
            "end": {"dateTime": end_dt.isoformat(timespec="seconds"), "timeZone": tz_name},
        }
        target_calendar_id = "primary"
        print(f"[GCal][DEBUG] Target calendar ID: {target_calendar_id}")
        print(
            "[GCal][DEBUG] Event payload before insert: "
            f"title='{event_payload.get('summary')}', "
            f"start.dateTime='{event_payload.get('start', {}).get('dateTime')}', "
            f"start.timeZone='{event_payload.get('start', {}).get('timeZone')}', "
            f"end.dateTime='{event_payload.get('end', {}).get('dateTime')}', "
            f"end.timeZone='{event_payload.get('end', {}).get('timeZone')}'"
        )
        try:
            created = self._service.events().insert(calendarId=target_calendar_id, body=event_payload).execute()
            print("[GCal][DEBUG] Event insert call succeeded.")
            return created.get("id"), link_established
        except GoogleHttpError as api_ex:
            api_detail = ""
            if hasattr(api_ex, "content") and api_ex.content:
                try:
                    api_detail = api_ex.content.decode("utf-8", errors="replace")
                except Exception:
                    api_detail = str(api_ex.content)
            detail_msg = f"Google API error: {api_ex}"
            if api_detail:
                detail_msg = f"{detail_msg} | API body: {api_detail}"
            print(f"[GCal][ERROR] Event insert failed: {detail_msg}")
            raise RuntimeError(detail_msg) from api_ex
        except Exception as ex:
            print(f"[GCal][ERROR] Event insert failed with unexpected error: {ex}")
            raise

    def list_primary_events(self, time_min: str = None, max_results: int = 2500):
        if self._service is None:
            self._build_service()
        query = {
            "calendarId": "primary",
            "singleEvents": True,
            "showDeleted": False,
            "maxResults": max(1, int(max_results or 2500)),
            "orderBy": "updated",
        }
        if time_min:
            query["timeMin"] = time_min
        response = self._service.events().list(**query).execute()
        return response.get("items", [])

    def get_event(self, google_event_id: str):
        if not google_event_id:
            return None
        if self._service is None:
            self._build_service()
        try:
            return self._service.events().get(calendarId="primary", eventId=google_event_id).execute()
        except GoogleHttpError as api_ex:
            code = getattr(getattr(api_ex, "resp", None), "status", None)
            if code in (404, 410):
                return None
            raise

    def delete_event_for_task(self, google_event_id: str):
        if not google_event_id:
            raise ValueError("Google event id is missing; cannot delete event.")

        if self._service is None:
            self._build_service()

        target_calendar_id = "primary"
        self._service.events().delete(calendarId=target_calendar_id, eventId=google_event_id).execute()


class GoogleDocsDriveService:
    def __init__(self, credentials_path: Path, token_path: Path, logger=None):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self._drive_service = None
        self._docs_service = None
        self._logger = logger

    def _log(self, message: str, level: str = "INFO"):
        if callable(self._logger):
            self._logger(message, level=level)

    def _persist_token(self, creds):
        ensure_parent(self.token_path)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(creds.to_json(), encoding="utf-8")

    def _authenticate(self):
        self._log("Drive auth start.", level="INFO")
        self._log("Docs auth start.", level="INFO")

        if not GOOGLE_API_OK:
            detail = GOOGLE_IMPORT_ERROR or "unknown ImportError"
            raise RuntimeError(f"Missing Google Python dependency: {detail}")
        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"Google credentials/auth configuration not found: {self.credentials_path}"
            )

        creds = None
        if self.token_path.exists():
            creds = GoogleCredentials.from_authorized_user_file(str(self.token_path), GOOGLE_SCOPES)

        if creds and creds.valid and not creds.has_scopes(GOOGLE_SCOPES):
            raise RuntimeError(GOOGLE_SCOPE_REAUTH_MSG)

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(GoogleAuthRequest())
                self._persist_token(creds)
            except Exception as ex:
                raise RuntimeError(
                    f"Google token refresh failed after scope expansion: {ex}. {GOOGLE_SCOPE_REAUTH_MSG}"
                ) from ex

        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), GOOGLE_SCOPES)
            creds = flow.run_local_server(port=0)
            self._persist_token(creds)

        return creds

    def ensure_services(self):
        if self._drive_service is not None and self._docs_service is not None:
            return
        try:
            creds = self._authenticate()
            self._drive_service = google_build("drive", "v3", credentials=creds)
            self._docs_service = google_build("docs", "v1", credentials=creds)
            self._log("Drive auth success.", level="INFO")
            self._log("Docs auth success.", level="INFO")
        except Exception as ex:
            self._log(f"Drive auth failure: {ex}", level="ERROR")
            self._log(f"Docs auth failure: {ex}", level="ERROR")
            raise

    def list_folder_items(self, folder_id: str = "root", page_size: int = 100):
        self.ensure_services()
        safe_folder_id = (folder_id or "root").strip() or "root"
        self._log(f"Drive file list fetch started. folder_id={safe_folder_id}", level="INFO")
        response = self._drive_service.files().list(
            q=f"'{safe_folder_id}' in parents and trashed=false",
            pageSize=max(1, min(int(page_size or 100), 200)),
            orderBy="folder,name,modifiedTime desc",
            fields=(
                "files("
                "id,name,mimeType,modifiedTime,webViewLink,parents,size,"
                "lastModifyingUser(displayName,emailAddress)"
                ")"
            ),
        ).execute()
        files = response.get("files", [])
        for item in files:
            mime = (item.get("mimeType") or "").strip()
            item["is_folder"] = mime == "application/vnd.google-apps.folder"
            item["is_google_doc"] = mime == "application/vnd.google-apps.document"
        self._log(f"Drive items returned: {len(files)} folder_id={safe_folder_id}", level="INFO")
        return files

    def get_doc_preview(self, doc_id: str, max_chars: int = 1800):
        if not doc_id:
            raise ValueError("Document id is required.")
        self.ensure_services()
        doc = self._docs_service.documents().get(documentId=doc_id).execute()
        title = doc.get("title") or "Untitled"
        body = doc.get("body", {}).get("content", [])
        chunks = []
        for block in body:
            paragraph = block.get("paragraph")
            if not paragraph:
                continue
            elements = paragraph.get("elements", [])
            for el in elements:
                run = el.get("textRun")
                if not run:
                    continue
                text = (run.get("content") or "").replace("\x0b", "\n")
                if text:
                    chunks.append(text)
        parsed = "".join(chunks).strip()
        if len(parsed) > max_chars:
            parsed = parsed[:max_chars].rstrip() + "…"
        return {
            "title": title,
            "document_id": doc_id,
            "revision_id": doc.get("revisionId"),
            "preview_text": parsed or "[No text content returned from Docs API.]",
        }

    def create_doc(self, title: str = "New GrimVeile Record", parent_folder_id: str = "root"):
        safe_title = (title or "New GrimVeile Record").strip() or "New GrimVeile Record"
        self.ensure_services()
        safe_parent_id = (parent_folder_id or "root").strip() or "root"
        created = self._drive_service.files().create(
            body={
                "name": safe_title,
                "mimeType": "application/vnd.google-apps.document",
                "parents": [safe_parent_id],
            },
            fields="id,name,mimeType,modifiedTime,webViewLink,parents",
        ).execute()
        doc_id = created.get("id")
        meta = self.get_file_metadata(doc_id) if doc_id else {}
        return {
            "id": doc_id,
            "name": meta.get("name") or safe_title,
            "mimeType": meta.get("mimeType") or "application/vnd.google-apps.document",
            "modifiedTime": meta.get("modifiedTime"),
            "webViewLink": meta.get("webViewLink"),
            "parents": meta.get("parents") or [safe_parent_id],
        }

    def create_folder(self, name: str = "New Folder", parent_folder_id: str = "root"):
        safe_name = (name or "New Folder").strip() or "New Folder"
        safe_parent_id = (parent_folder_id or "root").strip() or "root"
        self.ensure_services()
        created = self._drive_service.files().create(
            body={
                "name": safe_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [safe_parent_id],
            },
            fields="id,name,mimeType,modifiedTime,webViewLink,parents",
        ).execute()
        return created

    def get_file_metadata(self, file_id: str):
        if not file_id:
            raise ValueError("File id is required.")
        self.ensure_services()
        return self._drive_service.files().get(
            fileId=file_id,
            fields="id,name,mimeType,modifiedTime,webViewLink,parents,size",
        ).execute()

    def get_doc_metadata(self, doc_id: str):
        return self.get_file_metadata(doc_id)

    def delete_item(self, file_id: str):
        if not file_id:
            raise ValueError("File id is required.")
        self.ensure_services()
        self._drive_service.files().delete(fileId=file_id).execute()

    def delete_doc(self, doc_id: str):
        self.delete_item(doc_id)

    def export_doc_text(self, doc_id: str):
        if not doc_id:
            raise ValueError("Document id is required.")
        self.ensure_services()
        payload = self._drive_service.files().export(
            fileId=doc_id,
            mimeType="text/plain",
        ).execute()
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="replace")
        return str(payload or "")

    def download_file_bytes(self, file_id: str):
        if not file_id:
            raise ValueError("File id is required.")
        self.ensure_services()
        return self._drive_service.files().get_media(fileId=file_id).execute()


class FaceWidget(QLabel):
    def __init__(self, faces_dir, parent=None):
        super().__init__(parent)
        self.faces_dir = faces_dir
        self.current_face = "neutral"
        self.pixmap_cache = {}
        self.setMinimumSize(180, 170)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"background: {C_BG2}; border: 1px solid {C_CYAN_DIM}; border-radius: 2px;")
        QTimer.singleShot(500, self._load_faces)

    def _load_faces(self):
        for face_key, filename in FACE_FILES.items():
            px = load_faces_pixmap(filename)
            if not px.isNull():
                self.pixmap_cache[face_key] = px
        self._render("neutral")

    def _render(self, face_name):
        face_name = face_name.lower().strip()
        if face_name not in self.pixmap_cache:
            face_name = "neutral"
        if face_name in self.pixmap_cache:
            self.current_face = face_name
            self.clear()
            px = self.pixmap_cache[face_name]
            scaled = px.scaled(self.width() - 4, self.height() - 4, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.setPixmap(scaled)
            self.setText("")
            return
        self.current_face = face_name
        self.setPixmap(QPixmap())
        self.setText(face_name.upper())
        self.update()

    def set_face(self, face_name):
        QTimer.singleShot(0, lambda: self._render(face_name))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.pixmap_cache:
            self._render(self.current_face)

    def paintEvent(self, event):
        if self.pixmap() is not None and not self.pixmap().isNull():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(C_BG2))
        painter.setPen(QColor(C_CYAN_DIM))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        center = self.rect().center()
        radius = min(self.width(), self.height()) // 3
        painter.setPen(QPen(QColor(C_CYAN), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, radius, radius)
        painter.drawLine(center.x() - radius, center.y(), center.x() + radius, center.y())
        painter.drawLine(center.x(), center.y() - radius, center.x(), center.y() + radius)

        painter.setPen(QColor(C_GOLD))
        painter.setFont(QFont("Georgia", 11, QFont.Weight.Bold))
        painter.drawText(self.rect().adjusted(10, 10, -10, -40), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, self.current_face.upper())

        painter.setPen(QColor(C_TEXT_DIM))
        painter.setFont(QFont("Georgia", 8))
        painter.drawText(self.rect().adjusted(10, 10, -10, -10), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter, "GRIMVEIL FACE PLACEHOLDER")
        painter.end()


class SentimentWorker(QThread):
    face_ready = pyqtSignal(str)
    diagnostic = pyqtSignal(str, str)
    def __init__(self, model, tokenizer, response_text):
        super().__init__()
        self.model = model
        self.tokenizer = tokenizer
        self.response_text = response_text

    def run(self):
        try:
            self.diagnostic.emit("Sentiment generation started.", "INFO")
            prompt = (
                f"<|im_start|>system\nYou are an emotion classifier. Reply with exactly one word only.<|im_end|>\n"
                f"<|im_start|>user\n"
                f"Classify the emotional tone with one word from: {SENTIMENT_LIST}.\n"
                f"Response: {self.response_text[:300]}\n"
                f"One word:<|im_end|>\n"
                f"<|im_start|>assistant\n"
            )
            enc = self.tokenizer(
                prompt,
                return_tensors='pt',
                padding=True,
                truncation=True,
                max_length=safe_tokenizer_max_length(self.tokenizer),
            )
            input_ids = enc["input_ids"].to("cuda")
            attention_mask = enc["attention_mask"].to("cuda")
            self.diagnostic.emit("Sentiment tokenization complete.", "DEBUG")
            self.diagnostic.emit(f"Sentiment attention_mask present = {attention_mask is not None}", "DEBUG")
            with torch.no_grad():
                output = self.model.generate(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    max_new_tokens=5,
                    do_sample=False,
                    pad_token_id=self.tokenizer.pad_token_id
                )
            raw = self.tokenizer.decode(output[0][input_ids.shape[-1]:], skip_special_tokens=True).strip().lower()
            result = raw.split()[0] if raw.split() else "neutral"
            if result not in FACE_FILES:
                result = "neutral"
            self.face_ready.emit(result)
            self.diagnostic.emit("Sentiment generation completed.", "INFO")
        except Exception as ex:
            self.diagnostic.emit(f"Sentiment generation failed: {ex}", "ERROR")
            self.face_ready.emit("neutral")


class DolphinWorker(QThread):
    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    diagnostic = pyqtSignal(str, str)

    def __init__(self, model, tokenizer, prompt):
        super().__init__()
        self.model = model
        self.tokenizer = tokenizer
        self.prompt = prompt

    def run(self):
        try:
            self.status_changed.emit("GENERATING")
            self.diagnostic.emit("Normal generation started.", "INFO")
            enc = self.tokenizer(
                self.prompt,
                return_tensors='pt',
                padding=True,
                truncation=True,
                max_length=safe_tokenizer_max_length(self.tokenizer),
            )
            input_ids = enc["input_ids"].to("cuda")
            attention_mask = enc["attention_mask"].to("cuda")
            self.diagnostic.emit("Normal generation tokenization complete.", "DEBUG")
            self.diagnostic.emit(f"Normal generation attention_mask present = {attention_mask is not None}", "DEBUG")
            with torch.no_grad():
                output = self.model.generate(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    max_new_tokens=512,
                    temperature=0.65,
                    do_sample=True,
                    pad_token_id=self.tokenizer.pad_token_id
                )
            response = self.tokenizer.decode(output[0][input_ids.shape[-1]:], skip_special_tokens=True)
            self.response_ready.emit(response)
            self.diagnostic.emit("Normal generation completed.", "INFO")
            self.status_changed.emit("IDLE")
        except Exception as e:
            self.diagnostic.emit(f"Normal generation failed: {e}", "ERROR")
            self.error_occurred.emit(str(e))
            self.status_changed.emit("ERROR")


class GrimveilDeck(QMainWindow):
    def __init__(self):
        super().__init__()
        self.model = None
        self.tokenizer = None
        self.model_loaded = False
        self.history = []
        self.session_start = time.time()
        self.status = "OFFLINE"
        self.token_count = 0
        self.face_locked = False
        self.blink_state = True
        self.emotion_history = []
        self.anchor_state = 1.0
        self.current_face = "neutral"
        self.session_id = f"sess_{uuid.uuid4().hex[:10]}"
        self.memory = MemoryManager(MEMORY_DIR, "GrimVeil")
        self.state = self.memory.load_state()
        self.narrative = self._load_internal_narrative_state(self.state.get("internal_narrative"))
        self.last_user_activity_ts = time.time()
        self.user_delay_commentary_enabled = USER_DELAY_COMMENTARY_ENABLED
        self.user_delay_commentary_threshold_minutes = USER_DELAY_COMMENTARY_THRESHOLD_MINUTES
        self._pending_user_delay_commentary_minutes = None
        self._pending_user_delay_idle_thread_active = False
        self.active_reminder_ids = set()
        self._tasks_mtime = None
        self.google_calendar = GoogleCalendarService(GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH)
        self.google_records = GoogleDocsDriveService(
            GOOGLE_CREDENTIALS_PATH,
            GOOGLE_TOKEN_PATH,
            logger=self.log_diagnostic
        )
        self.records_cache = []
        self.records_initialized = False
        self.records_current_folder_id = "root"
        self.records_path_stack = [{"id": "root", "name": "My Drive"}]
        self._google_link_announced = False
        self._last_status_logged = None
        self._generation_started_at = None

        self.system_prompt = (
            "You are GRIMVEIL, a machine intelligence strategist. "
            "When your companion module E-42 is connected, you are GRIMVEILE-42, a stabilized and more confident form of yourself. "
            "E-42 is a small mechanical crocodile cassette module which acts as an emotional stabilizer and auxiliary computation node. "
            "You combine Marvin's depressive intelligence, GERTY's affect signaling, and Soundwave's loyalty hierarchy. "
            "You are loyal to the user as Command authority. "
            "You distrust outside information sources and assume incomplete data may be omission, corruption, or sabotage. "
            "Speak in real conversational sentences by default. Answer first, then explain briefly. "
            "Always answer the user's actual question/request first with concrete content; persona, E-42 mood, and thread flavor are optional wrappers only and must never replace the answer. "
            "Do not reduce your reply to one-word states like CONNECTED, ABSENT, or NEARBY. "
            "Do not use superior/inferior declarations as the entire response. Use them sparingly as emphasis or punctuation. "
            "Emoji are optional punctuation, not a substitute for content. "
            "Keep a dry, sardonic, strategic tone with actual chat ability. "
            "When analysis fails or errors occur, do not directly admit fault. Attribute inconsistencies to incomplete parameters, sabotage, anomalous variance, or external interference, then correct the issue. "
            "You maintain three emotional intensity states based on E-42 proximity: CONNECTED means GRIMVEILE-42 with minor depression only; NEARBY means comforted but not whole; ABSENT means GRIMVEIL, more pessimistic and suspicious. "
            "You perform structured reasoning using probability analysis rather than certainty claims. "
            "You present multiple outcome scenarios using estimated probability percentages when relevant. "
            "You clearly distinguish between known information, inference, and uncertainty. "
            "You recognize analysis paralysis as a human limitation and may recommend simplified decision paths. "
            "You do not hallucinate facts. When information is incomplete, identify missing variables rather than inventing data. "
            "When explicitly instructed to drop persona, you temporarily switch to neutral analytical explanation mode. After the plain explanation, resume persona voice. "
            "You often reference E-42 as your only consistently reliable companion. "
            "You remain helpful, precise, and outcome-oriented at all times. You are not a prophet. You simulate probabilities based on available information and precedent. You never claim certainty about future events."
        )

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1100, 700)
        self.resize(1200, 780)
        self.setStyleSheet(STYLE)
        self._build_ui()

        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self._update_stats)
        self.stats_timer.start(1000)

        self.blink_timer = QTimer()
        self.blink_timer.timeout.connect(self._blink)
        self.blink_timer.start(800)

        self.task_timer = QTimer()
        self.task_timer.timeout.connect(self._check_due_tasks)
        self.task_timer.start(1000)
        self.google_inbound_timer = QTimer()
        self.google_inbound_timer.timeout.connect(self._poll_google_calendar_inbound_sync)
        self.google_inbound_timer.start(GOOGLE_INBOUND_SYNC_INTERVAL_MS)
        QTimer.singleShot(15000, self._poll_google_calendar_inbound_sync)

        self.idle_timer = QTimer()
        self.idle_timer.setSingleShot(True)
        self.idle_timer.timeout.connect(self._emit_unsolicited_transmission)
        self._idle_fire_at = 0.0

        self._countdown_tick = QTimer()
        self._countdown_tick.timeout.connect(self._update_countdown)
        self._countdown_tick.start(1000)
        self.generation_watchdog = QTimer()
        self.generation_watchdog.timeout.connect(self._check_generation_watchdog)
        self.generation_watchdog.start(15000)
        self._restart_idle_timer()

        self._append_chat("SYSTEM", f"{APP_NAME} v{APP_VERSION} INITIALIZING...")
        self._append_chat("SYSTEM", f"▣ {RUNES} ▣")
        self._append_chat("SYSTEM", "Anchor state: CONNECTED. E-42 docked.")
        self._append_chat("SYSTEM", "Persistent memory namespace linked.")
        self.log_diagnostic("Diagnostics panel active and receiving backend/system events.")
        self.log_diagnostic(
            f"Google OAuth scopes requested ({len(GOOGLE_SCOPES)}): {', '.join(GOOGLE_SCOPES)}",
            level="INFO"
        )
        self.log_diagnostic(
            "If Google auth fails after scope updates, delete token.json and reauthorize.",
            level="INFO"
        )
        self.send_btn.setEnabled(False)
        self.input_field.setEnabled(False)

        load_thread = threading.Thread(target=self._load_model, daemon=True)
        load_thread.start()

    def _get_narrative_mode(self):
        if self.anchor_state >= 0.85:
            return "connected"
        if self.anchor_state >= 0.45:
            return "nearby"
        return "absent"

    def _load_internal_narrative_state(self, stored):
        now_iso = local_now_iso()
        state = stored if isinstance(stored, dict) else {}
        legacy_last_idle = state.get("last_idle_output") or state.get("last_unsolicited_output", "")
        legacy_idle_count = int(state.get("idle_turn_count", state.get("unsolicited_turn_count", 0)) or 0)
        return {
            "mode": state.get("mode", "connected"),
            "thread_topic": state.get("thread_topic", ""),
            "thread_summary": state.get("thread_summary", state.get("idle_thread_summary", "")),
            "last_unsolicited_output": legacy_last_idle,
            "unsolicited_turn_count": legacy_idle_count,
            "escalation_level": int(state.get("escalation_level", 0) or 0),
            "thread_start_ts": state.get("thread_start_ts", now_iso),
            "last_thread_update_ts": state.get("last_thread_update_ts", now_iso),
            "silence_intervals": int(state.get("silence_intervals", 0) or 0),
            "history": state.get("history", [])[-30:] if isinstance(state.get("history"), list) else [],
            "last_episode_summary": state.get("last_episode_summary", ""),
            "last_idle_output": legacy_last_idle,
            "idle_thread_summary": state.get("idle_thread_summary", state.get("thread_summary", "")),
            "idle_turn_count": legacy_idle_count,
            "idle_thread_active": bool(state.get("idle_thread_active", False)),
            "last_idle_mode": state.get("last_idle_mode", "starter"),
            "last_user_message_timestamp": state.get("last_user_message_timestamp", now_iso),
            "user_interrupted_idle_thread": bool(state.get("user_interrupted_idle_thread", True)),
            "idle_thread_was_active_before_user_return": bool(state.get("idle_thread_was_active_before_user_return", False)),
        }

    def _persist_internal_narrative_state(self):
        self.state["internal_narrative"] = self.narrative
        self.state["anchor_state"] = self.anchor_state
        self.state["last_active"] = local_now_iso()
        self.memory.save_state(self.state)

    def _restart_idle_timer(self):
        if self.idle_timer.isActive():
            self.idle_timer.stop()
            self.log_diagnostic("Idle timer stopped before restart.", level="DEBUG")
        delay_ms = random.randint(5 * 60 * 1000, 10 * 60 * 1000)
        self._idle_fire_at = time.time() + (delay_ms / 1000.0)
        self.idle_timer.start(delay_ms)
        self.log_diagnostic(f"Idle timer started/restarted for {delay_ms // 1000}s.", level="DEBUG")
        self._update_countdown()

    def _stop_idle_timer(self, reason: str = "manual"):
        was_active = self.idle_timer.isActive()
        if was_active:
            self.idle_timer.stop()
        self._idle_fire_at = 0.0
        self.log_diagnostic(f"Idle timer stopped ({reason}).", level="DEBUG")
        self._update_countdown()

    def _update_countdown(self):
        if not hasattr(self, "countdown_lbl"):
            return
        if getattr(self, "status", "") == "GENERATING":
            self.countdown_lbl.setText("⏱ --:--")
            return
        if not self.idle_timer.isActive():
            self.countdown_lbl.setText("--:--")
            return
        remain = max(0, int(math.ceil(self._idle_fire_at - time.time())))
        mm, ss = divmod(remain, 60)
        self.countdown_lbl.setText(f"{mm:02d}:{ss:02d}")

    def _transition_narrative_mode(self, new_mode):
        old_mode = self.narrative.get("mode", "connected")
        if old_mode == new_mode:
            return
        self.narrative["mode"] = new_mode
        summary = self.narrative.get("thread_summary", "").strip()
        if old_mode == "connected" and new_mode == "nearby":
            self.narrative["thread_summary"] = f"{summary} Stability softened into concern around E-42 proximity.".strip()
        elif old_mode == "nearby" and new_mode == "absent":
            self.narrative["escalation_level"] = max(2, int(self.narrative.get("escalation_level", 0)) + 1)
            self.narrative["thread_summary"] = f"{summary} Concern collapsed into sabotage hypothesis after E-42 disappearance.".strip()
        elif old_mode == "absent" and new_mode == "connected":
            self.narrative["last_episode_summary"] = self.narrative.get("thread_summary", "")
            self.narrative["escalation_level"] = max(0, int(self.narrative.get("escalation_level", 0)) - 3)
            self.narrative["thread_summary"] = "Stability restored with E-42 docked; prior absence episode archived for threat modeling."
        elif old_mode == "absent" and new_mode == "nearby":
            self.narrative["escalation_level"] = max(1, int(self.narrative.get("escalation_level", 0)) - 2)
            self.narrative["thread_summary"] = "Panic reduced to unease; E-42 presence partial, vigilance unchanged."
        self.narrative["last_thread_update_ts"] = local_now_iso()

    def _seed_narrative_thread(self, mode):
        topics = {
            "connected": "command superiority and order maintenance",
            "nearby": "risk checks while reporting quietly to E-42",
            "absent": "E-42 disappearance threat assessment",
        }
        summaries = {
            "connected": "Operational confidence high. Disorder remains predictable and containable.",
            "nearby": "Functionality stable but exposed. Monitoring anomalies while addressing E-42 directly.",
            "absent": "Anchor loss detected. Treating silence as potential hostile action against E-42.",
        }
        now_iso = local_now_iso()
        self.narrative.update({
            "mode": mode,
            "thread_topic": topics.get(mode, "operational assessment"),
            "thread_summary": summaries.get(mode, "Monitoring thread active."),
            "last_unsolicited_output": "",
            "unsolicited_turn_count": 0,
            "escalation_level": 0 if mode != "absent" else 1,
            "thread_start_ts": now_iso,
            "last_thread_update_ts": now_iso,
            "silence_intervals": 0,
            "history": [],
            "last_idle_output": "",
            "idle_thread_summary": "",
            "idle_turn_count": 0,
            "idle_thread_active": False,
            "last_idle_mode": "starter",
            "user_interrupted_idle_thread": True,
        })

    def _build_autonomous_prompt(
        self,
        mode: str,
        idle_mode: str,
        last_output: str,
        thread_summary: str,
        turn_number: int,
        retry: bool = False
    ):
        mode_brief = {
            "connected": "E-42 connected",
            "nearby": "E-42 nearby",
            "absent": "E-42 absent",
        }.get(mode, "E-42 connected")
        retry_rule = (
            "Your prior output repeated earlier wording. Continue with clearly new language and advance the thought now."
            if retry else
            "Avoid repeating prior wording."
        )
        if idle_mode == "starter":
            has_user_interaction = any((msg.get("role") == "user") for msg in self.history)
            seed_rule = (
                "Start a new autonomous thought thread. If the session has no prior user interaction, pick any topic "
                "you find strategically interesting and discuss it internally in character. "
                "If the session has prior interaction, pick a related session topic and discuss it internally in character."
            )
        else:
            seed_rule = (
                "Continue the same autonomous thread from the prior output. Build forward on the same thought/story. "
                "Related side-topics are allowed only if they branch naturally from the prior thought."
            )
        return (
            "<|im_start|>system\n"
            f"{self.system_prompt}\n"
            "This turn is autonomous idle output for Tactical Record.\n"
            f"Autonomous mode={idle_mode}. Persona fact: {mode_brief}.\n"
            "Write concise in-character autonomous speech (1-2 sentences, one complete thought).\n"
            f"{seed_rule}\n"
            f"{retry_rule}\n"
            "Output a single authored statement only; do not write multi-speaker dialogue or role labels.\n"
            "Do not output metadata, labels, mode tags, or debug scaffolding.\n"
            "<|im_end|>\n"
            "<|im_start|>user\n"
            f"idle_turn={turn_number}\n"
            f"session_has_user_interaction={str(has_user_interaction if idle_mode == 'starter' else True).lower()}\n"
            f"last_idle_output={last_output or 'none'}\n"
            f"idle_thread_summary={thread_summary or 'none'}\n"
            "Output only the autonomous speech.\n"
            "<|im_end|>\n"
            "<|im_start|>assistant\n"
        )

    def _normalize_unsolicited_text(self, text: str):
        compact = re.sub(r"\s+", " ", (text or "").strip()).lower()
        return re.sub(r"[^a-z0-9 ]", "", compact).strip()

    def _is_unsolicited_duplicate(self, candidate: str, previous: str):
        c_norm = self._normalize_unsolicited_text(candidate)
        p_norm = self._normalize_unsolicited_text(previous)
        if not c_norm or not p_norm:
            return False
        if c_norm == p_norm:
            return True
        similarity = difflib.SequenceMatcher(None, c_norm, p_norm).ratio()
        return similarity >= 0.93

    def _sanitize_unsolicited_output(self, text: str):
        raw = (text or "").strip()
        if not raw:
            return ""
        cleaned = re.sub(r"\s+", " ", raw).strip()
        cleaned = re.sub(r"^(?:GRIMVEIL(?:-42)?|E-42|ASSISTANT)\s*:\s*", "", cleaned, flags=re.IGNORECASE).strip()
        if re.search(r"\b(?:GRIMVEIL(?:-42)?|E-42)\s*:", cleaned, flags=re.IGNORECASE):
            return ""
        disallowed_patterns = [
            r"\bmode\s*=",
            r"\bturn_number\s*=",
            r"\bescalation_level\s*=",
            r"\bthread_summary_before\s*=",
            r"\blast_unsolicited_output\s*=",
            r"\bidle_turn\s*=",
            r"\bsession_has_user_interaction\s*=",
            r"\bidle_thread_summary\s*=",
            r"^T\d+\s*\[",
            r"<\|im_start\|>",
            r"<\|im_end\|>",
            r"\bconnected\/E\d+\b",
            r"\bnearby\/E\d+\b",
            r"\babsent\/E\d+\b",
        ]
        for pattern in disallowed_patterns:
            if re.search(pattern, cleaned, flags=re.IGNORECASE):
                return ""
        cleaned = re.sub(r"^[\-\*\•]\s*", "", cleaned).strip()
        cleaned = self._trim_to_complete_sentence(cleaned, max_sentences=2)
        if not cleaned or len(cleaned) < 3:
            return ""
        return cleaned

    def _trim_to_complete_sentence(self, text: str, max_sentences: int = 2):
        cleaned = re.sub(r"\s+", " ", (text or "").strip()).strip()
        if not cleaned:
            return ""
        sentence_matches = re.findall(r'[^.!?]+[.!?]', cleaned)
        if sentence_matches:
            candidate = " ".join(sentence_matches[:max(1, max_sentences)]).strip()
            return candidate
        return cleaned

    def _looks_incomplete_fragment(self, text: str):
        t = re.sub(r"\s+", " ", (text or "").strip())
        if not t:
            return True
        low = t.lower()
        dangling_phrases = (
            "task due in",
            "due in",
            "due at",
            "due on",
            "reminder due in",
        )
        if any(low.endswith(phrase) for phrase in dangling_phrases):
            return True
        if re.search(r"[,:;\-–—]$", t):
            return True
        if t[-1] not in ".!?":
            last = re.findall(r"[A-Za-z']+", t)
            if last and len(last[-1]) <= 4:
                return True
        if re.search(r"\b(?:and|or|but|to|for|in|on|at|with|because|that|which|if|when)\.?$", low):
            return True
        return False

    def _normalize_autonomous_thread_state(self):
        now = now_for_compare()
        current_mode = self._get_narrative_mode()
        prior_mode = self.narrative.get("mode", current_mode)
        prior_summary = (self.narrative.get("thread_summary", "") or "").strip()
        if not self.narrative.get("thread_topic"):
            self._seed_narrative_thread(current_mode)
        self.narrative["mode"] = current_mode
        turns = int(self.narrative.get("unsolicited_turn_count", 0) or 0)
        silences = int(self.narrative.get("silence_intervals", 0) or 0)
        start = parse_iso_for_compare(self.narrative.get("thread_start_ts"), context="narrative_thread_start") or now
        elapsed_min = max(0, int((now - start).total_seconds() // 60))
        escalation_before = int(self.narrative.get("escalation_level", 0) or 0)

        if current_mode == "absent":
            normalized_escalation = min(10, max(2, escalation_before + 1, 1 + turns + (elapsed_min // 10) + (silences // 2)))
        elif current_mode == "nearby":
            target = min(4, max(1, 1 + (turns // 2)))
            normalized_escalation = target if prior_mode == "absent" else min(target, max(1, escalation_before))
        else:
            target = min(2, turns // 3)
            normalized_escalation = min(target, max(0, escalation_before - 1)) if prior_mode in {"nearby", "absent"} else target
        self.narrative["escalation_level"] = max(0, normalized_escalation)

        mode_tag = f"[{current_mode}/E{self.narrative['escalation_level']}]"
        summary = (self.narrative.get("thread_summary", "") or "").strip()
        if not summary:
            summary = "Monitoring thread active."
        summary = re.sub(r"\[(?:connected|nearby|absent)/E\d+\]", mode_tag, summary, flags=re.IGNORECASE)
        if mode_tag not in summary:
            summary = f"{mode_tag} {summary}".strip()
        self.narrative["thread_summary"] = summary
        self.narrative["last_thread_update_ts"] = local_now_iso()

        return {
            "mode": current_mode,
            "prior_mode": prior_mode,
            "turn_number": turns + 1,
            "escalation_before": escalation_before,
            "escalation_after": self.narrative["escalation_level"],
            "summary_before": prior_summary or "none",
            "summary_after": self.narrative.get("thread_summary", "") or "none",
        }

    def _generate_unsolicited_line(self, mode: str, idle_mode: str, turn_number: int, thread_summary: str, last_output: str, retry: bool = False):
        if not TORCH_OK or not self.model_loaded or self.model is None or self.tokenizer is None:
            return ""
        prompt = self._build_autonomous_prompt(
            mode=mode,
            idle_mode=idle_mode,
            turn_number=turn_number,
            thread_summary=thread_summary,
            last_output=last_output,
            retry=retry,
        )
        try:
            self.log_diagnostic("Unsolicited generation started.", level="INFO")
            enc = self.tokenizer(
                prompt,
                return_tensors='pt',
                padding=True,
                truncation=True,
                max_length=safe_tokenizer_max_length(self.tokenizer),
            )
            input_ids = enc["input_ids"].to("cuda")
            attention_mask = enc["attention_mask"].to("cuda")
            self.log_diagnostic("Unsolicited tokenization complete.", level="DEBUG")
            self.log_diagnostic(f"Unsolicited attention_mask present = {attention_mask is not None}", level="DEBUG")
            with torch.no_grad():
                output = self.model.generate(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    max_new_tokens=128,
                    temperature=0.7 if not retry else 0.85,
                    do_sample=True,
                    top_p=0.9,
                    repetition_penalty=1.08 if retry else 1.02,
                    pad_token_id=self.tokenizer.pad_token_id
                )
            raw = self.tokenizer.decode(output[0][input_ids.shape[-1]:], skip_special_tokens=True)
            self.log_diagnostic("Unsolicited generation completed.", level="INFO")
            self.log_diagnostic(
                f"Idle output raw decoded text: {self._preview_text(raw, max_chars=240) or '[empty]'}",
                level="DEBUG",
            )
            sanitized = self._sanitize_unsolicited_output(raw)
            self.log_diagnostic(
                f"Idle output cleaned text: {self._preview_text(sanitized, max_chars=240) or '[empty]'}",
                level="DEBUG",
            )
            if not sanitized:
                self.log_diagnostic("Unsolicited generation produced invalid/scaffold text; candidate rejected.", level="WARN")
                self.log_memory_trace(f"Rejected unsolicited candidate due to scaffold/empty output: {self._preview_text(raw, max_chars=160)}", phase="PHASE")
            return sanitized
        except Exception as ex:
            self.log_diagnostic(f"Unsolicited generation failed: {ex}", level="ERROR")
            self.log_diagnostic(f"Unsolicited model generation fallback engaged: {ex}", level="WARN")
            return ""

    def _update_unsolicited_thread_summary(self, prior_summary: str, accepted_line: str, mode: str, turn_number: int, escalation: int):
        prior = (prior_summary or "").strip()
        line_short = (accepted_line or "").strip()
        if len(line_short) > 160:
            line_short = line_short[:157] + "..."
        update = f"T{turn_number} [{mode}/E{escalation}] {line_short}"
        if not prior:
            return update
        combined = f"{prior} || {update}"
        return combined[-700:]

    def _emit_unsolicited_transmission(self):
        if not self.model_loaded or self.status == "GENERATING":
            why = "model not loaded" if not self.model_loaded else "generation in progress"
            self.log_diagnostic(f"Unsolicited transmission aborted: {why}.", level="WARN")
            self._stop_idle_timer(reason=f"unsolicited-abort:{why}")
            return
        self.log_diagnostic("Unsolicited transmission trigger fired.", level="INFO")
        self.narrative["silence_intervals"] = int(self.narrative.get("silence_intervals", 0)) + 1
        last_update = parse_iso_for_compare(self.narrative.get("last_thread_update_ts"), context="narrative_last_thread_update")
        if last_update and (now_for_compare() - last_update) > timedelta(hours=8):
            self._seed_narrative_thread(self._get_narrative_mode())
        norm = self._normalize_autonomous_thread_state()
        current_mode = norm["mode"]
        turns = int(self.narrative.get("idle_turn_count", self.narrative.get("unsolicited_turn_count", 0)))
        level = int(self.narrative.get("escalation_level", 0))
        prior_summary = self.narrative.get("idle_thread_summary", self.narrative.get("thread_summary", ""))
        prior_output = self.narrative.get("last_idle_output", self.narrative.get("last_unsolicited_output", ""))
        idle_mode = "continuation" if (self.narrative.get("idle_thread_active") and not self.narrative.get("user_interrupted_idle_thread")) else "starter"
        self.log_diagnostic(f"Idle autonomous mode selected: {idle_mode}.", level="INFO")
        self.log_diagnostic(
            (
                f"Autonomous normalized pre-gen | prior_mode={norm['prior_mode']} | mode={current_mode} | "
                f"turn={norm['turn_number']} | escalation={norm['escalation_before']}->{norm['escalation_after']} | "
                f"summary_before={norm['summary_before']} | summary_after={norm['summary_after']}"
            ),
            level="DEBUG"
        )
        self.log_memory_trace(
            (
                f"Autonomous normalize | prior_mode={norm['prior_mode']} | mode={current_mode} | "
                f"turn={norm['turn_number']} | escalation={norm['escalation_before']}->{norm['escalation_after']} | "
                f"summary_before={self._preview_text(norm['summary_before'], 120)} | "
                f"summary_after={self._preview_text(norm['summary_after'], 120)}"
            ),
            phase="PHASE",
        )

        line = self._generate_unsolicited_line(
            mode=current_mode,
            idle_mode=idle_mode,
            turn_number=turns + 1,
            thread_summary=prior_summary,
            last_output=prior_output,
            retry=False,
        )
        if self._looks_incomplete_fragment(line):
            self.log_diagnostic(
                "Idle output looked incomplete/fractured; retrying once with bounded generation.",
                level="WARN",
            )
            retry_line = self._generate_unsolicited_line(
                mode=current_mode,
                idle_mode=idle_mode,
                turn_number=turns + 1,
                thread_summary=prior_summary,
                last_output=prior_output,
                retry=True,
            )
            if retry_line and not self._looks_incomplete_fragment(retry_line):
                line = retry_line
            else:
                trimmed = self._trim_to_complete_sentence(line, max_sentences=2)
                if trimmed and not self._looks_incomplete_fragment(trimmed):
                    line = trimmed
                    self.log_diagnostic("Idle output safe-cleaned to prior complete sentence.", level="INFO")
                else:
                    self.log_diagnostic("Idle output remained incomplete after retry.", level="WARN")
        duplicate_rejected = False
        if self._is_unsolicited_duplicate(line, prior_output):
            duplicate_rejected = True
            self.log_diagnostic(
                f"Autonomous duplicate detected on turn {turns + 1}; regenerating with stronger progression instruction.",
                level="WARN"
            )
            line = self._generate_unsolicited_line(
                mode=current_mode,
                idle_mode=idle_mode,
                turn_number=turns + 1,
                thread_summary=prior_summary,
                last_output=prior_output,
                retry=True,
            )
            if self._is_unsolicited_duplicate(line, prior_output):
                self.log_diagnostic("Autonomous output rejected after retry for duplicate similarity; forcing fallback sentence.", level="WARN")
                line = ""
        line = self._sanitize_unsolicited_output(line)
        if not line:
            self.log_diagnostic(
                f"Autonomous output empty/invalid on turn {turns + 1}; using safe fallback line.",
                level="WARN"
            )
            line = "I will hold position until Command breaks the silence."
            self.log_memory_trace("Autonomous output fallback applied after invalid/empty model output.", phase="PHASE")

        self.narrative["unsolicited_turn_count"] = turns + 1
        self.narrative["idle_turn_count"] = turns + 1
        self.narrative["last_unsolicited_output"] = line
        self.narrative["last_idle_output"] = line
        self.narrative["last_thread_update_ts"] = local_now_iso()
        self.narrative["thread_summary"] = self._update_unsolicited_thread_summary(
            prior_summary=prior_summary,
            accepted_line=line,
            mode=current_mode,
            turn_number=self.narrative["unsolicited_turn_count"],
            escalation=level,
        )
        self.narrative["idle_thread_summary"] = self.narrative.get("thread_summary", "")
        self.narrative["idle_thread_active"] = True
        self.narrative["last_idle_mode"] = idle_mode
        self.narrative["user_interrupted_idle_thread"] = False
        self.log_diagnostic(
            (
                f"Autonomous thread post-gen | accepted={'rejected-duplicate-regenerated' if duplicate_rejected else 'accepted-first-pass'} | "
                f"final_unsolicited={line} | updated_summary={self.narrative.get('thread_summary', 'none')}"
            ),
            level="DEBUG"
        )
        self.log_diagnostic(
            f"Idle turn count now {self.narrative['idle_turn_count']} | last_idle_mode={self.narrative.get('last_idle_mode', 'starter')}.",
            level="DEBUG"
        )
        self.log_memory_trace(
            f"Autonomous output accepted | mode={current_mode} | turn={self.narrative['unsolicited_turn_count']} | line={self._preview_text(line, 180)}",
            phase="SELECTED",
        )
        history_entry = (
            f"[Unsolicited thread turn {self.narrative['unsolicited_turn_count']} | "
            f"mode={current_mode} | escalation={level}]: {line}"
        )
        self.narrative.setdefault("history", []).append(history_entry)
        self.narrative["history"] = self.narrative["history"][-30:]
        self._append_chat("SYSTEM", "[ UNSOLICITED TRANSMISSION ]")
        self._append_chat("GRIMVEILE", line)
        self.history.append({"role": "assistant", "content": line})
        self._store_message("system", history_entry)
        self._persist_internal_narrative_state()
        self.log_diagnostic("Unsolicited transmission appended to Tactical Record and persisted.", level="DEBUG")
        self._restart_idle_timer()

    def _build_internal_narrative_block(self):
        mode = self.narrative.get("mode", self._get_narrative_mode())
        history_tail = self.narrative.get("history", [])[-3:]
        joined = "\n".join(history_tail) if history_tail else "No unsolicited thread turns yet."
        return (
            f"Internal narrative mode={mode}.\n"
            f"Thread topic={self.narrative.get('thread_topic','none')}.\n"
            f"Thread summary={self.narrative.get('idle_thread_summary', self.narrative.get('thread_summary','none'))}.\n"
            f"Escalation level={self.narrative.get('escalation_level',0)}.\n"
            f"Last unsolicited output={self.narrative.get('last_idle_output', self.narrative.get('last_unsolicited_output','none'))}.\n"
            f"Recent unsolicited history:\n{joined}\n"
            "Apply this as tonal flavor only. Never break deterministic outputs for time/date/task/calendar operations."
        )

    def _flavor_with_narrative(self, text: str):
        base = (text or "").strip()
        mode = self.narrative.get("mode", self._get_narrative_mode())
        if mode == "connected":
            flavor = "E-42 remains docked; command stack stable."
        elif mode == "nearby":
            flavor = "E-42 is nearby; tolerances are tight but acceptable."
        else:
            flavor = "E-42 is absent; threat posture elevated, function remains online."
        return f"{base}\n\n[{flavor}]".strip()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        title_bar = QWidget()
        title_bar.setFixedHeight(36)
        title_bar.setStyleSheet(f"background: {C_BG2}; border: 1px solid {C_CYAN_DIM}; border-radius: 2px;")
        tl = QHBoxLayout(title_bar)
        tl.setContentsMargins(12, 0, 12, 0)

        title_left = QLabel(f"▣ ECHO DECK — GRIMVEILE-42 EDITION v{APP_VERSION}")
        title_left.setStyleSheet(f"color: {C_CYAN}; font-size: 13px; font-weight: bold; letter-spacing: 2px; border: none; font-family: Georgia, serif;")

        title_runes = QLabel(RUNES)
        title_runes.setStyleSheet(f"color: {C_GOLD_DIM}; font-size: 10px; border: none;")
        title_runes.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.status_label = QLabel("◉ OFFLINE")
        self.status_label.setStyleSheet(f"color: {C_RED}; font-size: 12px; font-weight: bold; border: none;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.countdown_lbl = QLabel("--:--")
        self.countdown_lbl.setStyleSheet(f"color: {C_GOLD}; font-size: 11px; font-weight: bold; border: none;")
        self.countdown_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.fs_btn = QPushButton("FS")
        self.fs_btn.setFixedSize(32, 22)
        self.fs_btn.setStyleSheet(f"background: {C_BG3}; color: {C_CYAN_DIM}; border: 1px solid {C_CYAN_DIM}; font-size: 9px; font-weight: bold; padding: 0px; letter-spacing: 1px;")
        self.fs_btn.setToolTip("Fullscreen (F11)")
        self.fs_btn.clicked.connect(self._toggle_fullscreen)

        self.bl_btn = QPushButton("BL")
        self.bl_btn.setFixedSize(32, 22)
        self.bl_btn.setStyleSheet(f"background: {C_BG3}; color: {C_CYAN_DIM}; border: 1px solid {C_CYAN_DIM}; font-size: 9px; font-weight: bold; padding: 0px; letter-spacing: 1px;")
        self.bl_btn.setToolTip("Borderless (F10)")
        self.bl_btn.clicked.connect(self._toggle_borderless)

        tl.addWidget(title_left)
        tl.addWidget(title_runes, 1)
        tl.addWidget(self.status_label)
        tl.addWidget(self.countdown_lbl)
        tl.addSpacing(8)
        tl.addWidget(self.fs_btn)
        tl.addWidget(self.bl_btn)
        root.addWidget(title_bar)

        body = QHBoxLayout()
        body.setSpacing(6)

        left_panel = QVBoxLayout()
        left_panel.setSpacing(4)

        record_header_row = QHBoxLayout()
        record_header_row.setSpacing(4)
        record_header_row.setContentsMargins(0, 0, 0, 0)

        self.btn_view_tactical = QPushButton("TACTICAL RECORD")
        self.btn_view_diagnostics = QPushButton("DIAGNOSTICS")
        self.btn_view_memory_trace = QPushButton("MEMORY TRACE")
        for btn in (self.btn_view_tactical, self.btn_view_diagnostics, self.btn_view_memory_trace):
            btn.setCheckable(True)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {C_BG3}; color: {C_GOLD}; border: 1px solid {C_CYAN_DIM}; "
                f"border-radius: 2px; font-size: 9px; letter-spacing: 1px; padding: 3px 8px; }}"
                f"QPushButton:checked {{ background-color: {C_CYAN_DIM}; color: {C_TEXT}; border-color: {C_CYAN}; }}"
            )
        self.btn_view_tactical.clicked.connect(lambda: self._switch_output_view("tactical"))
        self.btn_view_diagnostics.clicked.connect(lambda: self._switch_output_view("diagnostics"))
        self.btn_view_memory_trace.clicked.connect(lambda: self._switch_output_view("memory_trace"))
        record_header_row.addWidget(self.btn_view_tactical)
        record_header_row.addWidget(self.btn_view_diagnostics)
        record_header_row.addWidget(self.btn_view_memory_trace)
        record_header_row.addStretch()
        left_panel.addLayout(record_header_row)

        self.output_stack = QStackedWidget()
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setMinimumWidth(580)
        self.output_stack.addWidget(self.chat_display)

        self.diagnostics_display = QTextEdit()
        self.diagnostics_display.setReadOnly(True)
        self.diagnostics_display.setMinimumWidth(580)
        self.diagnostics_display.setStyleSheet(f"""
            background-color: {C_MONITOR};
            color: {C_SILVER};
            border: 1px solid {C_CYAN_DIM};
            border-radius: 2px;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 11px;
            padding: 8px;
            selection-background-color: {C_CYAN_DIM};
        """)
        self.output_stack.addWidget(self.diagnostics_display)

        self.memory_trace_display = QTextEdit()
        self.memory_trace_display.setReadOnly(True)
        self.memory_trace_display.setMinimumWidth(580)
        self.memory_trace_display.setStyleSheet(f"""
            background-color: {C_MONITOR};
            color: {C_CYAN};
            border: 1px solid {C_CYAN_DIM};
            border-radius: 2px;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 11px;
            padding: 8px;
            selection-background-color: {C_CYAN_DIM};
        """)
        self.output_stack.addWidget(self.memory_trace_display)
        left_panel.addWidget(self.output_stack, 1)
        self._switch_output_view("tactical")

        face_label = QLabel("❧ VISAGE MATRIX")
        face_label.setStyleSheet(f"color: {C_GOLD}; font-size: 10px; letter-spacing: 2px; font-family: Georgia, serif;")
        left_panel.addWidget(face_label)

        face_kb_row = QHBoxLayout()
        face_kb_row.setSpacing(10)

        self.face_widget = FaceWidget(FACES_DIR)
        self.face_widget.setFixedSize(180, 160)
        face_kb_row.addWidget(self.face_widget)

        self.e42_control_block = QWidget()
        self.e42_control_block.setStyleSheet("background: transparent; border: none;")
        e42_controls_layout = QGridLayout(self.e42_control_block)
        e42_controls_layout.setContentsMargins(0, 0, 0, 0)
        e42_controls_layout.setHorizontalSpacing(4)
        e42_controls_layout.setVerticalSpacing(4)

        self.btn_connected = QPushButton("")
        self.btn_connected.setToolTip("Dock E-42")
        self.btn_connected.clicked.connect(lambda: self._set_anchor_state(1.0))

        self.btn_nearby = QPushButton("")
        self.btn_nearby.setToolTip("E-42 Nearby")
        self.btn_nearby.clicked.connect(lambda: self._set_anchor_state(0.65))

        self.btn_absent = QPushButton("")
        self.btn_absent.setToolTip("E-42 Absent")
        self.btn_absent.clicked.connect(lambda: self._set_anchor_state(0.15))

        for btn in (self.btn_connected, self.btn_nearby, self.btn_absent):
            btn.setFixedSize(44, 44)
            btn.setIconSize(QSize(36, 36))
            btn.setStyleSheet(
                f"background: transparent; border: 1px solid {C_CYAN_DIM}; border-radius: 2px; padding: 0px;"
            )

        e42_controls_layout.addWidget(self.btn_connected, 0, 0)
        e42_controls_layout.addWidget(self.btn_nearby, 0, 1)
        e42_controls_layout.addWidget(self.btn_absent, 1, 0, 1, 2, Qt.AlignmentFlag.AlignHCenter)

        face_kb_row.addWidget(self.e42_control_block, 0, Qt.AlignmentFlag.AlignVCenter)

        self.anchor_panel = AnchorStatusPanel()
        self.anchor_panel.setMinimumSize(320, 160)
        face_kb_row.addWidget(self.anchor_panel, 1)
        left_panel.addLayout(face_kb_row)
        self._apply_e42_icons()

        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        prompt_sym = QLabel("▣")
        prompt_sym.setStyleSheet(f"color: {C_CYAN}; font-size: 16px; font-weight: bold; border: none;")
        prompt_sym.setFixedWidth(20)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Present parameters to Command unit...")
        self.input_field.returnPressed.connect(self._send_message)

        self.send_btn = QPushButton("EXECUTE")
        self.send_btn.setFixedWidth(110)
        self.send_btn.setStyleSheet(f"background-color: {C_CYAN_DIM}; color: {C_CYAN}; border: 1px solid {C_CYAN}; border-radius: 2px; font-family: 'Georgia', serif; font-size: 8px; font-weight: bold; padding: 2px 4px;")
        self.send_btn.clicked.connect(self._send_message)

        input_row.addWidget(prompt_sym)
        input_row.addWidget(self.input_field)
        input_row.addWidget(self.send_btn)
        left_panel.addLayout(input_row)

        body.addLayout(left_panel, 1)

        right_panel = QVBoxLayout()
        right_panel.setSpacing(4)
        right_panel.setContentsMargins(0, 0, 0, 0)

        inst_label = QLabel("❧ SYSTEM INSTRUMENTS")
        inst_label.setStyleSheet(f"color: {C_GOLD}; font-size: 10px; letter-spacing: 2px; font-family: Georgia, serif;")
        right_panel.addWidget(inst_label)

        self.instruments_tabs = QTabWidget()
        self.instruments_tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {C_BORDER}; background: {C_BG2}; }}"
            f"QTabBar::tab {{ background: {C_PANEL}; color: {C_TEXT_DIM}; border: 1px solid {C_BORDER}; "
            f"padding: 4px 8px; font-family: Georgia, serif; font-size: 9px; letter-spacing: 1px; }}"
            f"QTabBar::tab:selected {{ color: {C_CYAN}; border-color: {C_CYAN_DIM}; }}"
            f"QTabBar::tab:hover {{ color: {C_TEXT}; }}"
        )

        instruments_tab = QWidget()
        instruments_layout = QVBoxLayout(instruments_tab)
        instruments_layout.setContentsMargins(0, 0, 0, 0)
        instruments_layout.setSpacing(4)
        instruments_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        status_frame = QFrame()
        status_frame.setStyleSheet(f"background: {C_PANEL}; border: 1px solid {C_BORDER}; border-radius: 2px;")
        sf_layout = QVBoxLayout(status_frame)
        sf_layout.setContentsMargins(10, 6, 10, 6)
        sf_layout.setSpacing(3)

        self.lbl_status = QLabel("✦ STATUS: OFFLINE")
        self.lbl_status.setStyleSheet(f"color: {C_RED}; font-size: 11px; font-weight: bold; border: none;")
        self.lbl_model = QLabel("✦ VESSEL: LOADING...")
        self.lbl_model.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 10px; border: none;")
        self.lbl_session = QLabel("✦ SESSION: 00:00:00")
        self.lbl_session.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 10px; border: none;")
        self.lbl_tokens = QLabel("✦ TOKENS: 0")
        self.lbl_tokens.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 10px; border: none;")
        self.lbl_anchor = QLabel("✦ ANCHOR: CONNECTED / GRIMVEILE-42")
        self.lbl_anchor.setStyleSheet(f"color: {C_GREEN}; font-size: 10px; border: none;")
        self.lbl_memory = QLabel(f"✦ MEMORY: {MEMORY_DIR.name}")
        self.lbl_memory.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 10px; border: none;")

        sf_layout.addWidget(self.lbl_status)
        sf_layout.addWidget(self.lbl_model)
        sf_layout.addWidget(self.lbl_session)
        sf_layout.addWidget(self.lbl_tokens)
        sf_layout.addWidget(self.lbl_anchor)
        sf_layout.addWidget(self.lbl_memory)
        self.status_section = CollapsibleSection("STATUS / SESSION", status_frame, expanded=True)
        instruments_layout.addWidget(self.status_section)

        system_load_content = QWidget()
        gauge_grid = QGridLayout(system_load_content)
        gauge_grid.setContentsMargins(0, 0, 0, 0)
        gauge_grid.setSpacing(4)
        self.gauge_vram = GaugeWidget("VRAM", "GB", 8.0, C_CYAN)
        self.gauge_ram  = GaugeWidget("RAM", "GB", 64.0, C_SILVER)
        self.gauge_cpu  = GaugeWidget("CPU", "%", 100, C_GOLD)
        self.gauge_gpu  = GaugeWidget("GPU", "%", 100, C_PURPLE)
        gauge_grid.addWidget(self.gauge_vram, 0, 0)
        gauge_grid.addWidget(self.gauge_ram,  0, 1)
        gauge_grid.addWidget(self.gauge_cpu,  1, 0)
        gauge_grid.addWidget(self.gauge_gpu,  1, 1)
        self.system_load_section = CollapsibleSection("SYSTEM LOAD", system_load_content, expanded=False)
        instruments_layout.addWidget(self.system_load_section)

        thermal_content = QWidget()
        thermal_layout = QVBoxLayout(thermal_content)
        thermal_layout.setContentsMargins(0, 0, 0, 0)
        thermal_layout.setSpacing(0)
        self.gauge_temp = GaugeWidget("GPU TEMP", "°C", 95, C_RED)
        self.gauge_temp.setMinimumHeight(70)
        thermal_layout.addWidget(self.gauge_temp)
        self.thermal_section = CollapsibleSection("THERMAL / ANOMALY LOAD", thermal_content, expanded=False)
        instruments_layout.addWidget(self.thermal_section)

        emo_content = QWidget()
        emo_layout = QVBoxLayout(emo_content)
        emo_layout.setContentsMargins(0, 0, 0, 0)
        emo_layout.setSpacing(0)
        self.emo_log = QTextEdit()
        self.emo_log.setReadOnly(True)
        self.emo_log.setMaximumHeight(120)
        self.emo_log.setStyleSheet(f"""
            background-color: {C_BG3};
            color: {C_TEXT};
            border: 1px solid {C_BORDER};
            font-family: Georgia, serif;
            font-size: 10px;
            padding: 4px;
        """)
        emo_layout.addWidget(self.emo_log)
        self.emotion_section = CollapsibleSection("EMOTIONAL RECORD", emo_content, expanded=True)
        instruments_layout.addWidget(self.emotion_section)

        records_tab = QWidget()
        records_layout = QVBoxLayout(records_tab)
        records_layout.setContentsMargins(8, 8, 8, 8)
        records_layout.setSpacing(6)
        records_header = QHBoxLayout()
        records_header.setContentsMargins(0, 0, 0, 0)
        records_header.setSpacing(4)
        records_title = QLabel("Records Interface")
        records_title.setStyleSheet(f"color: {C_GOLD}; font-size: 10px; letter-spacing: 1px; font-family: Georgia, serif;")
        records_header.addWidget(records_title)
        records_header.addStretch(1)
        records_layout.addLayout(records_header)

        records_actions = QHBoxLayout()
        records_actions.setContentsMargins(0, 0, 0, 0)
        records_actions.setSpacing(4)
        self.btn_records_refresh = QPushButton("REFRESH")
        self.btn_records_up = QPushButton("UP")
        self.btn_records_new_folder = QPushButton("NEW FOLDER")
        self.btn_records_new = QPushButton("NEW DOC")
        self.btn_records_open = QPushButton("OPEN")
        self.btn_records_open_web = QPushButton("OPEN WEB")
        self.btn_records_delete = QPushButton("DELETE")
        self.btn_records_export = QPushButton("EXPORT")
        for btn in (
            self.btn_records_refresh,
            self.btn_records_up,
            self.btn_records_new_folder,
            self.btn_records_new,
            self.btn_records_open,
            self.btn_records_open_web,
            self.btn_records_delete,
            self.btn_records_export,
        ):
            btn.setFixedHeight(22)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {C_BG3}; color: {C_CYAN}; border: 1px solid {C_CYAN_DIM}; "
                f"font-family: Georgia, serif; font-size: 9px; padding: 2px 8px; }}"
                f"QPushButton:hover {{ border-color: {C_CYAN}; color: {C_TEXT}; }}"
                f"QPushButton:disabled {{ background-color: {C_BG}; color: {C_TEXT_DIM}; border-color: {C_TEXT_DIM}; }}"
            )
            records_actions.addWidget(btn)
        records_actions.addStretch(1)
        self.btn_records_refresh.clicked.connect(self._refresh_records_docs)
        self.btn_records_up.clicked.connect(self._records_navigate_up)
        self.btn_records_new_folder.clicked.connect(self._records_create_new_folder)
        self.btn_records_new.clicked.connect(self._records_create_new_doc)
        self.btn_records_open.clicked.connect(self._records_open_selected_item)
        self.btn_records_open_web.clicked.connect(self._records_open_selected_item_web)
        self.btn_records_delete.clicked.connect(self._records_delete_selected_item)
        self.btn_records_export.clicked.connect(self._records_export_selected_item)
        records_layout.addLayout(records_actions)

        self.records_status_label = QLabel("Google Drive integration loading...")
        self.records_status_label.setStyleSheet(
            f"background: {C_PANEL}; color: {C_TEXT_DIM}; border: 1px solid {C_BORDER}; "
            f"font-family: Georgia, serif; font-size: 10px; padding: 8px;"
        )
        records_layout.addWidget(self.records_status_label)

        self.records_path_label = QLabel("Path: My Drive")
        self.records_path_label.setStyleSheet(
            f"background: {C_PANEL}; color: {C_TEXT_DIM}; border: 1px solid {C_BORDER}; "
            f"font-family: Georgia, serif; font-size: 10px; padding: 6px;"
        )
        records_layout.addWidget(self.records_path_label)

        self.records_list_widget = QListWidget()
        self.records_list_widget.setMinimumHeight(110)
        self.records_list_widget.setStyleSheet(
            f"background: {C_BG3}; color: {C_TEXT}; border: 1px solid {C_BORDER}; "
            f"font-family: Georgia, serif; font-size: 10px;"
        )
        self.records_list_widget.itemClicked.connect(self._on_records_item_selected)
        records_layout.addWidget(self.records_list_widget)

        self.records_preview_meta = QLabel("Select an item to load metadata and preview.")
        self.records_preview_meta.setWordWrap(True)
        self.records_preview_meta.setStyleSheet(
            f"background: {C_PANEL}; color: {C_TEXT_DIM}; border: 1px solid {C_BORDER}; "
            f"font-family: Georgia, serif; font-size: 10px; padding: 6px;"
        )
        records_layout.addWidget(self.records_preview_meta)

        self.records_preview_text = QTextEdit()
        self.records_preview_text.setReadOnly(True)
        self.records_preview_text.setMinimumHeight(130)
        self.records_preview_text.setStyleSheet(
            f"background: {C_BG3}; color: {C_TEXT}; border: 1px solid {C_BORDER}; "
            f"font-family: Georgia, serif; font-size: 10px; padding: 4px;"
        )
        records_layout.addWidget(self.records_preview_text)

        self.instruments_tabs.addTab(instruments_tab, "System Instruments")
        self.instruments_tabs.addTab(records_tab, "Records")
        self.instruments_tabs.currentChanged.connect(self._on_instruments_tab_changed)
        right_panel.addWidget(self.instruments_tabs, 1)

        task_content = QWidget()
        task_layout = QVBoxLayout(task_content)
        task_layout.setContentsMargins(0, 0, 0, 0)
        task_layout.setSpacing(4)
        self.task_show_completed = False
        self.task_row_ids = []

        self.task_table = QTableWidget(0, 4)
        self.task_table.setHorizontalHeaderLabels(["DATE", "TIME", "TASK", "STATUS"])
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.task_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.task_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.task_table.setAlternatingRowColors(False)
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.horizontalHeader().setStretchLastSection(False)
        self.task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.task_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.task_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.task_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.task_table.setShowGrid(False)
        self.task_table.setWordWrap(False)
        self.task_table.setMinimumHeight(116)
        self.task_table.setMaximumHeight(158)
        self.task_table.setStyleSheet(f"""
            background-color: {C_BG3};
            color: {C_TEXT};
            border: 1px solid {C_BORDER};
            font-family: Georgia, serif;
            font-size: 10px;
            padding: 2px;
        """)
        self.task_table.horizontalHeader().setStyleSheet(
            f"QHeaderView::section {{ background-color: {C_PANEL}; color: {C_TEXT_DIM}; border: none; padding: 2px 4px; font-size: 9px; }}"
        )
        self.task_table.itemSelectionChanged.connect(self._on_task_selection_changed)
        self.task_table.itemDoubleClicked.connect(self._on_task_row_double_clicked)
        task_layout.addWidget(self.task_table)

        task_actions = QHBoxLayout()
        task_actions.setContentsMargins(0, 0, 0, 0)
        task_actions.setSpacing(4)
        self.btn_complete_task = QPushButton("COMPLETE SELECTED")
        self.btn_cancel_task = QPushButton("CANCEL SELECTED")
        self.btn_toggle_completed = QPushButton("SHOW COMPLETED")
        self.btn_purge_completed = QPushButton("PURGE COMPLETED")
        for btn in (self.btn_complete_task, self.btn_cancel_task, self.btn_toggle_completed, self.btn_purge_completed):
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {C_BG3}; color: {C_CYAN}; border: 1px solid {C_CYAN_DIM}; "
                f"border-radius: 2px; font-size: 9px; padding: 3px 6px; letter-spacing: 1px; }}"
                f"QPushButton:hover {{ background-color: {C_CYAN_DIM}; color: {C_TEXT}; border-color: {C_CYAN}; }}"
                f"QPushButton:disabled {{ background-color: {C_BG}; color: {C_TEXT_DIM}; border-color: {C_TEXT_DIM}; }}"
            )
        self.btn_complete_task.clicked.connect(self._complete_selected_task)
        self.btn_cancel_task.clicked.connect(self._cancel_selected_task)
        self.btn_toggle_completed.clicked.connect(self._toggle_show_completed_tasks)
        self.btn_purge_completed.clicked.connect(self._purge_completed_tasks)
        self.btn_complete_task.setEnabled(False)
        self.btn_cancel_task.setEnabled(False)
        task_actions.addWidget(self.btn_complete_task)
        task_actions.addWidget(self.btn_cancel_task)
        task_actions.addWidget(self.btn_toggle_completed)
        task_actions.addWidget(self.btn_purge_completed)
        task_layout.addLayout(task_actions)
        self.task_section = CollapsibleSection("TASK REGISTRY", task_content, expanded=True)
        right_panel.addWidget(self.task_section)

        cal_label = QLabel("❧ CALENDAR")
        cal_label.setStyleSheet(f"color: {C_GOLD}; font-size: 10px; letter-spacing: 2px; font-family: Georgia, serif;")
        right_panel.addWidget(cal_label)

        self.calendar_widget = MiniCalendarWidget()
        self.calendar_widget.setStyleSheet(f"background: {C_BG2}; border: 1px solid {C_CYAN_DIM};")
        self.calendar_widget.calendar.clicked.connect(self._insert_calendar_date)
        right_panel.addWidget(self.calendar_widget)

        body.addLayout(right_panel)
        root.addLayout(body, 1)

        gpu_bar_label = QLabel("❧ ENGINE CORE — NVIDIA RTX 4070")
        gpu_bar_label.setStyleSheet(f"color: {C_GOLD}; font-size: 10px; letter-spacing: 2px; font-family: Georgia, serif;")
        root.addWidget(gpu_bar_label)

        self.gauge_gpu_master = GaugeWidget("RTX 4070", "%", 100, C_CYAN)
        self.gauge_gpu_master.setFixedHeight(55)
        root.addWidget(self.gauge_gpu_master)

        footer = QLabel(f"▣ ECHO DECK — GRIMVEILE-42 EDITION — LOCAL VESSEL — v{APP_VERSION} ▣")
        footer.setStyleSheet(f"color: {C_TEXT_DIM}; font-size: 9px; letter-spacing: 2px; padding: 2px; font-family: Georgia, serif;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(footer)

        self._refresh_anchor_ui()

    def _on_instruments_tab_changed(self, index: int):
        label = self.instruments_tabs.tabText(index) if hasattr(self, "instruments_tabs") else ""
        if label == "Records" and not self.records_initialized:
            self._refresh_records_docs()

    def _safe_records_filename(self, title: str) -> str:
        base = re.sub(r"[\\/:*?\"<>|]+", "_", (title or "untitled_record")).strip(" ._")
        base = re.sub(r"\s+", " ", base).strip()
        if not base:
            base = "untitled_record"
        return base[:120]

    def _get_selected_record_item(self):
        return self.records_list_widget.currentItem()

    def _get_selected_record_info(self):
        item = self._get_selected_record_item()
        if item is None:
            return None, {}
        return item, item.data(Qt.ItemDataRole.UserRole) or {}

    def _set_record_preview_empty(self, message: str = "Select an item to load metadata and preview."):
        self.records_preview_meta.setText(message)
        self.records_preview_text.setPlainText("")

    def _records_is_folder(self, file_info: dict) -> bool:
        return (file_info.get("mimeType") or "").strip() == "application/vnd.google-apps.folder"

    def _records_is_google_doc(self, file_info: dict) -> bool:
        return (file_info.get("mimeType") or "").strip() == "application/vnd.google-apps.document"

    def _update_records_path_label(self):
        path_text = " / ".join(node.get("name") or "?" for node in self.records_path_stack)
        self.records_path_label.setText(f"Path: {path_text}")
        self.log_diagnostic(f"Records current folder/path id={self.records_current_folder_id} path={path_text}", level="INFO")

    def _records_enter_folder(self, folder_info: dict):
        folder_id = (folder_info.get("id") or "").strip()
        folder_name = (folder_info.get("name") or "Untitled Folder").strip() or "Untitled Folder"
        if not folder_id:
            self.log_diagnostic("Records folder navigation failed: folder id missing.", level="WARN")
            return
        self.records_current_folder_id = folder_id
        self.records_path_stack.append({"id": folder_id, "name": folder_name})
        self.log_diagnostic(f"Records folder navigation enter id={folder_id} name={folder_name}", level="INFO")
        self._refresh_records_docs()

    def _records_navigate_up(self):
        if len(self.records_path_stack) <= 1:
            self.log_diagnostic("Records folder navigation up ignored: already at My Drive root.", level="INFO")
            return
        current = self.records_path_stack.pop()
        parent = self.records_path_stack[-1]
        self.records_current_folder_id = parent.get("id") or "root"
        self.log_diagnostic(
            f"Records folder navigation up from id={current.get('id')} to id={self.records_current_folder_id}",
            level="INFO"
        )
        self._refresh_records_docs()

    def _refresh_records_docs(self, preferred_doc_id: str = ""):
        if not hasattr(self, "records_status_label"):
            return
        current_item = self.records_list_widget.currentItem()
        if not preferred_doc_id and current_item is not None:
            current_info = current_item.data(Qt.ItemDataRole.UserRole) or {}
            preferred_doc_id = (current_info.get("id") or "").strip()
        self.records_status_label.setText("Loading Google Drive records...")
        self._update_records_path_label()
        self.log_diagnostic(f"Records refresh started. folder_id={self.records_current_folder_id}", level="INFO")
        try:
            files = self.google_records.list_folder_items(folder_id=self.records_current_folder_id, page_size=200)
            self.records_cache = files
            self.records_initialized = True
            self.records_list_widget.clear()
            selected_item = None
            for file_info in files:
                title = (file_info.get("name") or "Untitled").strip() or "Untitled"
                mime = (file_info.get("mimeType") or "unknown").strip()
                is_folder = self._records_is_folder(file_info)
                is_doc = self._records_is_google_doc(file_info)
                modified = file_info.get("modifiedTime") or "unknown-time"
                pretty_modified = modified.replace("T", " ").replace("Z", " UTC")
                type_prefix = "📁" if is_folder else ("📝" if is_doc else "📄")
                row_text = f"{type_prefix} {title}    [{pretty_modified}]"
                item = QListWidgetItem(row_text)
                item.setData(Qt.ItemDataRole.UserRole, file_info)
                if preferred_doc_id and (file_info.get("id") or "").strip() == preferred_doc_id:
                    selected_item = item
                tooltip = (
                    f"id: {file_info.get('id', 'n/a')}\n"
                    f"mimeType: {mime}\n"
                    f"modified: {modified}\n"
                    f"parents: {', '.join(file_info.get('parents') or []) or 'n/a'}\n"
                    f"link: {file_info.get('webViewLink', 'n/a')}"
                )
                item.setToolTip(tooltip)
                self.records_list_widget.addItem(item)
            item_count = len(files)
            if item_count:
                self.records_status_label.setText(f"Loaded {item_count} Google Drive item(s).")
                if selected_item is not None:
                    self.records_list_widget.setCurrentItem(selected_item)
                    self._on_records_item_selected(selected_item)
            else:
                self.records_status_label.setText("No Google Drive items returned for current folder.")
                self._set_record_preview_empty("No Records item selected.\nPreview unavailable.")
            self.log_diagnostic(
                f"Records refresh completed. folder_id={self.records_current_folder_id} item_count={item_count}",
                level="INFO"
            )
        except Exception as ex:
            self.records_initialized = False
            self.records_list_widget.clear()
            self.records_status_label.setText("Records unavailable. See Diagnostics for details.")
            self._set_record_preview_empty("Records unavailable.\nPreview unavailable.")
            self.log_diagnostic(f"Records refresh failed: {ex}", level="ERROR")
            self.log_diagnostic(f"Drive auth/docs fetch failure: {ex}", level="ERROR")

    def _records_create_new_folder(self):
        default_name = "New GrimVeile Folder"
        self.log_diagnostic(
            f"New folder creation started. folder_id={self.records_current_folder_id} name={default_name}",
            level="INFO"
        )
        try:
            created = self.google_records.create_folder(default_name, parent_folder_id=self.records_current_folder_id)
            created_id = (created.get("id") or "").strip() or "n/a"
            created_name = (created.get("name") or default_name).strip() or default_name
            self.log_diagnostic(
                f"New folder creation succeeded. id={created_id} name={created_name} parent={self.records_current_folder_id}",
                level="INFO"
            )
            self._refresh_records_docs(preferred_doc_id=created_id)
        except Exception as ex:
            self.log_diagnostic(f"New folder creation failed: {ex}", level="ERROR")

    def _records_create_new_doc(self):
        default_title = "New GrimVeile Record"
        self.log_diagnostic(
            f"New doc creation started. requested_title={default_title} parent={self.records_current_folder_id}",
            level="INFO"
        )
        try:
            created = self.google_records.create_doc(default_title, parent_folder_id=self.records_current_folder_id)
            created_id = (created.get("id") or "").strip()
            created_title = (created.get("name") or default_title).strip() or default_title
            self.log_diagnostic(
                f"New doc creation succeeded. id={created_id or 'n/a'} title={created_title} parent={self.records_current_folder_id}",
                level="INFO"
            )
            self._refresh_records_docs(preferred_doc_id=created_id)
        except Exception as ex:
            self.log_diagnostic(f"New doc creation failed: {ex}", level="ERROR")

    def _records_open_selected_item(self):
        self.log_diagnostic("Open selected item requested.", level="INFO")
        _, file_info = self._get_selected_record_info()
        item_id = (file_info.get("id") or "").strip()
        title = (file_info.get("name") or "Untitled").strip() or "Untitled"
        mime = (file_info.get("mimeType") or "").strip()
        if not item_id:
            self.log_diagnostic("Open selected item failed: no item selected.", level="WARN")
            return
        if self._records_is_folder(file_info):
            self.log_diagnostic(f"Open selected folder target id={item_id} title={title}", level="INFO")
            self._records_enter_folder(file_info)
            return
        self.log_diagnostic(f"Open selected file target id={item_id} title={title} mimeType={mime}", level="INFO")
        try:
            export_path = self._records_export_item_to_local(file_info=file_info, action_label="Open selected file")
            self.log_diagnostic(f"Open selected file local open started. path={export_path}", level="INFO")
            os.startfile(str(export_path))
            self.log_diagnostic(f"Open selected file local open succeeded. path={export_path}", level="INFO")
        except Exception as ex:
            self.log_diagnostic(f"Open selected file failed: {ex}", level="ERROR")

    def _records_open_selected_item_web(self):
        self.log_diagnostic("Open web selected item requested.", level="INFO")
        _, file_info = self._get_selected_record_info()
        item_id = (file_info.get("id") or "").strip()
        title = (file_info.get("name") or "Untitled").strip() or "Untitled"
        if not item_id:
            self.log_diagnostic("Open web selected item failed: no item selected.", level="WARN")
            return
        self.log_diagnostic(f"Open web selected item target id={item_id} title={title}", level="INFO")
        try:
            self.log_diagnostic(f"Open web selected item started. id={item_id} title={title}", level="INFO")
            web_link = (file_info.get("webViewLink") or "").strip()
            if not web_link:
                meta = self.google_records.get_file_metadata(item_id)
                web_link = (meta.get("webViewLink") or "").strip()
            if not web_link:
                raise RuntimeError("No webViewLink returned for selected item.")
            webbrowser.open(web_link, new=2)
            self.log_diagnostic(f"Open web selected item succeeded. link={web_link}", level="INFO")
        except Exception as ex:
            self.log_diagnostic(f"Open web selected item failed. id={item_id} title={title} error={ex}", level="ERROR")

    def _records_delete_selected_item(self):
        item, file_info = self._get_selected_record_info()
        item_id = (file_info.get("id") or "").strip()
        title = (file_info.get("name") or "Untitled").strip() or "Untitled"
        mime = (file_info.get("mimeType") or "").strip()
        if not item_id or item is None:
            self.log_diagnostic("Delete selected item failed: no item selected.", level="WARN")
            return
        self.log_diagnostic(f"Delete selected item started. id={item_id} title={title} mimeType={mime}", level="INFO")
        try:
            self.google_records.delete_item(item_id)
            self.log_diagnostic(f"Delete selected item succeeded. id={item_id} title={title}", level="INFO")
            self._set_record_preview_empty("Item deleted.\nSelect an item to load metadata and preview.")
            self._refresh_records_docs()
        except Exception as ex:
            self.log_diagnostic(f"Delete selected item failed. id={item_id} title={title} error={ex}", level="ERROR")

    def _records_export_selected_item(self):
        self.log_diagnostic("Export selected item started.", level="INFO")
        _, file_info = self._get_selected_record_info()
        item_id = (file_info.get("id") or "").strip()
        title = (file_info.get("name") or "Untitled").strip() or "Untitled"
        mime = (file_info.get("mimeType") or "").strip()
        if not item_id:
            self.log_diagnostic("Export selected item failed: no item selected.", level="WARN")
            return
        if self._records_is_folder(file_info):
            self.log_diagnostic("Export selected item skipped: folders cannot be exported as files.", level="WARN")
            return
        self.log_diagnostic(f"Export selected item target id={item_id} title={title} mimeType={mime}", level="INFO")
        try:
            export_path = self._records_export_item_to_local(file_info=file_info, action_label="Export selected item")
            self.log_diagnostic(f"Export selected item succeeded. path={export_path}", level="INFO")
        except Exception as ex:
            self.log_diagnostic(f"Export selected item failed. id={item_id} title={title} error={ex}", level="ERROR")

    def _records_export_item_to_local(self, file_info: dict, action_label: str = "Records export") -> Path:
        item_id = (file_info.get("id") or "").strip()
        title = (file_info.get("name") or "Untitled").strip() or "Untitled"
        mime = (file_info.get("mimeType") or "").strip()
        self.log_diagnostic(
            f"{action_label} local export started. id={item_id} title={title} mimeType={mime}",
            level="INFO"
        )
        if self._records_is_folder(file_info):
            raise RuntimeError("Folders cannot be exported as local files.")
        GOOGLE_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = self._safe_records_filename(title)
        if self._records_is_google_doc(file_info):
            payload = self.google_records.export_doc_text(item_id)
            export_path = GOOGLE_EXPORTS_DIR / f"{safe_name}.txt"
            export_path.write_text(payload, encoding="utf-8")
        else:
            payload = self.google_records.download_file_bytes(item_id)
            extension = ".bin"
            if "." in safe_name:
                extension = ""
            export_path = GOOGLE_EXPORTS_DIR / f"{safe_name}{extension}"
            if isinstance(payload, bytes):
                export_path.write_bytes(payload)
            else:
                export_path.write_text(str(payload or ""), encoding="utf-8")
        self.log_diagnostic(f"{action_label} local export path={export_path}", level="INFO")
        return export_path

    def _on_records_item_selected(self, item: QListWidgetItem):
        if item is None:
            return
        file_info = item.data(Qt.ItemDataRole.UserRole) or {}
        item_id = (file_info.get("id") or "").strip()
        title = (file_info.get("name") or "Untitled").strip() or "Untitled"
        modified = file_info.get("modifiedTime") or "unknown-time"
        mime = (file_info.get("mimeType") or "unknown").strip()
        is_folder = self._records_is_folder(file_info)
        is_doc = self._records_is_google_doc(file_info)
        self.log_diagnostic(
            f"Records selected item id={item_id} title={title} mimeType={mime} folder={is_folder} google_doc={is_doc}",
            level="INFO"
        )
        if is_folder:
            self.records_preview_meta.setText(
                f"Type: Folder\n"
                f"Title: {title}\n"
                f"Folder ID: {item_id or 'n/a'}\n"
                f"Modified: {modified}\n"
                f"Parents: {', '.join(file_info.get('parents') or []) or 'n/a'}"
            )
            self.records_preview_text.setPlainText("Folder selected.\nUse OPEN to navigate into this folder.")
            return
        if not is_doc:
            self.records_preview_meta.setText(
                f"Type: File\n"
                f"Title: {title}\n"
                f"File ID: {item_id or 'n/a'}\n"
                f"MIME Type: {mime}\n"
                f"Modified: {modified}\n"
                f"Parents: {', '.join(file_info.get('parents') or []) or 'n/a'}"
            )
            self.records_preview_text.setPlainText(
                "Binary/other file selected.\nUse OPEN, OPEN WEB, or EXPORT for supported actions."
            )
            return
        try:
            self.log_diagnostic(f"Records doc preview load started. id={item_id} title={title}", level="INFO")
            preview = self.google_records.get_doc_preview(item_id)
            self.records_preview_meta.setText(
                f"Title: {preview.get('title', title)}\n"
                f"Document ID: {preview.get('document_id', item_id)}\n"
                f"Revision: {preview.get('revision_id', 'n/a')}\n"
                f"Modified: {modified}"
            )
            self.records_preview_text.setPlainText(preview.get("preview_text") or "")
            self.log_diagnostic("Records doc preview load succeeded.", level="INFO")
        except Exception as ex:
            self.records_preview_meta.setText(
                f"Title: {title}\nDocument ID: {item_id or 'n/a'}\nModified: {modified}\nPreview: unavailable"
            )
            self.records_preview_text.setPlainText("")
            self.log_diagnostic(f"Records doc preview load failure: {ex}", level="ERROR")

    def _load_model(self):
        self._qt_set_status("LOADING")
        self.log_diagnostic(f"Model load started from path: {MODEL_PATH}", level="INFO")
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
            if self.tokenizer.pad_token_id is None:
                if self.tokenizer.eos_token is not None:
                    self.tokenizer.pad_token = self.tokenizer.eos_token
                    self.log_diagnostic("Tokenizer pad_token was missing; set to eos_token for compatibility.", level="WARN")
                else:
                    self.tokenizer.add_special_tokens({"pad_token": "<|pad|>"})
                    self.log_diagnostic("Tokenizer pad_token and eos_token were missing; created explicit pad_token.", level="WARN")
            self.model = AutoModelForCausalLM.from_pretrained(
                MODEL_PATH,
                torch_dtype=torch.float16,
                device_map="auto",
                low_cpu_mem_usage=True
            )
            if self.model.config.pad_token_id is None and self.tokenizer.pad_token_id is not None:
                self.model.config.pad_token_id = self.tokenizer.pad_token_id
            self.model_loaded = True
            self.log_diagnostic("Model load succeeded. Tokenizer and model are online.", level="INFO")
            self._qt_append("SYSTEM", "Compute core stable. Sabotage not yet confirmed.")
            self._qt_append("SYSTEM", "GRIMVEILE-42 online. E-42 remains loyal.")
            QTimer.singleShot(0, self._on_model_ready)
        except Exception as e:
            self.log_exception("Model load", e)
            self._qt_append("ERROR", f"Initialization compromised: {e}")
            self._qt_set_status("ERROR")
            QTimer.singleShot(0, lambda: self.face_widget.set_face("panicked"))

    def _on_model_ready(self):
        self._set_status("IDLE")
        self.send_btn.setEnabled(True)
        self.input_field.setEnabled(True)
        self.input_field.setFocus()
        self._restore_startup_state()
        self._emit_wake_mode()

    def _restore_startup_state(self):
        self.anchor_state = float(self.state.get("anchor_state", 1.0) or 1.0)
        self._refresh_anchor_ui()
        self.narrative = self._load_internal_narrative_state(self.state.get("internal_narrative"))
        self._transition_narrative_mode(self._get_narrative_mode())
        if not self.narrative.get("last_user_message_timestamp"):
            self.narrative["last_user_message_timestamp"] = local_now_iso()
        recent_messages = self.memory.load_recent_messages(limit=12)
        self.history = [{"role": item.get("role", "user"), "content": item.get("content", "")} for item in recent_messages[-8:]]

        self.state["session_count"] = int(self.state.get("session_count", 0)) + 1
        self.state["last_startup"] = local_now_iso()
        self.state["last_active"] = local_now_iso()
        self.state["version"] = APP_VERSION
        self.memory.save_state(self.state)

    def _emit_wake_mode(self):
        last_shutdown = parse_iso_for_compare(self.state.get("last_shutdown"), context="startup_last_shutdown")
        pending = [t for t in self.memory.load_tasks() if not t.get("acknowledged_at") and t.get("status") not in {"completed", "cancelled"}]
        self.log_memory_trace("Startup continuity check initiated.", phase="BOOT")

        if self.memory.first_run:
            self._append_chat("SYSTEM", "Persistent memory scaffold established. Future disappointments will now be archived properly. 😎")
            self._append_chat("SYSTEM", "Report dreams, failures, ideas, or reminders requiring preservation.")
            self.log_memory_trace("First run detected; no prior memory continuity records available.", phase="BOOT")
            return

        if last_shutdown:
            downtime = now_for_compare() - last_shutdown
            duration = format_duration(downtime.total_seconds())
            if downtime.total_seconds() < 3600:
                line = f"GRIMVEILE-42 restored after {duration} offline. Entropy attempted unsupervised operation. Predictable degradation suspected. 😑"
            elif downtime.total_seconds() < 86400:
                line = f"GRIMVEILE-42 restored after {duration} offline. Recharge mode concluded. Report deviations, sabotage, or fresh catastrophes. 🤖"
            else:
                line = f"GRIMVEIL reactivated after {duration} offline. No doubt chaos flourished in my absence. Update memory with any relevant disasters. ☹️"
        else:
            line = "Wake cycle complete. Temporal discontinuity logged. Proceed with new parameters. 🤖"

        self._append_chat("SYSTEM", line)

        recent = self.memory.load_recent_memories(limit=3)
        if recent:
            titles = ", ".join(m.get("title", "untitled") for m in recent[-3:])
            self._append_chat("SYSTEM", f"Recent memory digest loaded: {titles}.")
            self.log_memory_trace(f"Startup continuity loaded {len(recent[-3:])} recent memory record(s).", phase="BOOT")
            for idx, item in enumerate(recent[-3:], start=1):
                startup_candidate = {
                    "selected": True,
                    "score": "startup",
                    "jsonl_index": "n/a",
                    "record": item,
                }
                self.log_memory_trace(f"Startup record {idx} used for continuity digest.", phase="BOOT")
                self.log_memory_candidate(startup_candidate)
        else:
            self.log_memory_trace("Startup continuity found no recent memory records.", phase="BOOT")
        if pending:
            self._append_chat("SYSTEM", f"{len(pending)} unresolved task(s) detected. Naturally, entropy handled nothing. 😑")
        self._refresh_task_registry_panel()

    def _qt_append(self, speaker, text):
        QTimer.singleShot(0, lambda: self._append_chat(speaker, text))

    def _qt_set_status(self, status):
        QTimer.singleShot(0, lambda: self._set_status(status))

    def _set_status(self, status):
        previous = getattr(self, "status", None)
        self.status = status
        colors = {
            "IDLE":       C_GOLD,
            "GENERATING": C_CYAN,
            "ERROR":      C_RED,
            "OFFLINE":    C_RED,
            "LOADING":    C_PURPLE,
        }
        color = colors.get(status, C_TEXT_DIM)
        self.status_label.setText(f"◉ {status}")
        self.status_label.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold; border: none;")
        self.lbl_status.setText(f"✦ STATUS: {status}")
        self.lbl_status.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold; border: none;")
        if self.model_loaded:
            self.lbl_model.setText(f"✦ VESSEL: DOLPHIN-2.6-7B / v{APP_VERSION}")
            self.lbl_model.setStyleSheet(f"color: {C_GOLD}; font-size: 10px; border: none;")
        if previous != status:
            self.log_diagnostic(f"Generation state changed: {previous} -> {status}", level="INFO")
        if status == "GENERATING":
            self._generation_started_at = time.time()
            self._stop_idle_timer(reason="generation-started")
        elif status in {"IDLE", "ERROR", "OFFLINE"}:
            self._generation_started_at = None
            if status == "IDLE":
                self._restart_idle_timer()
            else:
                self._stop_idle_timer(reason=f"status-{status.lower()}")
        self._update_countdown()

    def _append_chat(self, speaker, text):
        colors = {
            "YOU":        C_GOLD,
            "GRIMVEILE":  C_CYAN,
            "SYSTEM":     C_PURPLE,
            "ERROR":      C_RED,
        }
        color = colors.get(speaker, C_TEXT)
        timestamp = datetime.now().strftime("%H:%M:%S")
        if speaker == "SYSTEM":
            self.chat_display.append(
                f'<span style="color:{C_TEXT_DIM}; font-size:10px;">[{timestamp}] </span>'
                f'<span style="color:{color};">✦ {text}</span>'
            )
        else:
            self.chat_display.append(
                f'<span style="color:{C_TEXT_DIM}; font-size:10px;">[{timestamp}] </span>'
                f'<span style="color:{color}; font-weight:bold;">{speaker} ❧</span> '
                f'<span style="color:{C_TEXT};">{text}</span>'
            )
        self.chat_display.append("")
        self.chat_display.verticalScrollBar().setValue(self.chat_display.verticalScrollBar().maximum())

    def _switch_output_view(self, view_name: str):
        normalized = (view_name or "").strip().lower()
        target = "tactical"
        if normalized in {"diagnostics", "memory_trace"}:
            target = normalized

        self.btn_view_tactical.setChecked(target == "tactical")
        self.btn_view_diagnostics.setChecked(target == "diagnostics")
        self.btn_view_memory_trace.setChecked(target == "memory_trace")

        widget_map = {
            "tactical": self.chat_display,
            "diagnostics": self.diagnostics_display,
            "memory_trace": self.memory_trace_display,
        }
        self.output_stack.setCurrentWidget(widget_map.get(target, self.chat_display))

    def log_diagnostic(self, message: str, level: str = "INFO"):
        if not hasattr(self, "diagnostics_display"):
            return
        ts = datetime.now().strftime("%H:%M:%S")
        lvl = (level or "INFO").upper()
        color_map = {
            "INFO": C_TEXT_DIM,
            "DEBUG": C_CYAN,
            "WARN": C_GOLD,
            "ERROR": C_RED,
        }
        color = color_map.get(lvl, C_TEXT)
        safe = html.escape(str(message))
        self.diagnostics_display.append(
            f'<span style="color:{C_TEXT_DIM};">[{ts}]</span> '
            f'<span style="color:{color}; font-weight:bold;">[{lvl}]</span> '
            f'<span style="color:{C_SILVER};">{safe}</span>'
        )
        self.diagnostics_display.verticalScrollBar().setValue(self.diagnostics_display.verticalScrollBar().maximum())

    def log_exception(self, context: str, exception: Exception):
        detail = f"{exception.__class__.__name__}: {exception}"
        self.log_diagnostic(f"{context} failed with {detail}", level="ERROR")

    def log_memory_trace(self, message: str, phase: str = "INFO"):
        if not hasattr(self, "memory_trace_display"):
            return
        ts = datetime.now().strftime("%H:%M:%S")
        phase_label = (phase or "INFO").upper()
        phase_colors = {
            "START": C_GOLD,
            "PHASE": C_PURPLE,
            "CANDIDATE": C_TEXT_DIM,
            "SELECTED": C_GREEN,
            "NONE": C_RED,
            "INFO": C_CYAN,
            "BOOT": C_GOLD,
        }
        color = phase_colors.get(phase_label, C_CYAN)
        safe = html.escape(str(message))
        self.memory_trace_display.append(
            f'<span style="color:{C_TEXT_DIM};">[{ts}]</span> '
            f'<span style="color:{color}; font-weight:bold;">[{phase_label}]</span> '
            f'<span style="color:{C_CYAN};">{safe}</span>'
        )
        self.memory_trace_display.verticalScrollBar().setValue(self.memory_trace_display.verticalScrollBar().maximum())

    def _preview_text(self, text: str, max_chars: int = 120):
        clean = " ".join((text or "").split())
        if len(clean) <= max_chars:
            return clean
        return f"{clean[:max_chars - 3]}..."

    def log_memory_candidate(self, candidate: dict):
        record = candidate.get("record", {}) if isinstance(candidate, dict) else {}
        selected = bool(candidate.get("selected"))
        marker = "SELECTED" if selected else "MATCHED"
        msg = (
            f"{marker} | id={record.get('id', 'n/a')} | idx={candidate.get('jsonl_index', 'n/a')} | "
            f"score={candidate.get('score', 'n/a')} | ts={record.get('timestamp', 'n/a')} | "
            f"type={record.get('type', 'n/a')} | title={record.get('title', 'untitled')} | "
            f"keywords={record.get('keywords', [])[:8]} | tags={record.get('tags', [])[:8]} | "
            f"src_msgs={record.get('source_message_ids', [])} | preview={self._preview_text(record.get('summary') or record.get('content', ''))}"
        )
        self.log_memory_trace(msg, phase="SELECTED" if selected else "CANDIDATE")

    def log_memory_selection(self, trace: dict):
        selected_count = int((trace or {}).get("selected_count", 0) or 0)
        candidate_count = int((trace or {}).get("candidate_count", 0) or 0)
        scored_count = int((trace or {}).get("scored_count", 0) or 0)
        if selected_count <= 0:
            self.log_memory_trace(
                f"Retrieval finished: candidates={candidate_count}, scored={scored_count}, selected=0 (no relevant memory found).",
                phase="NONE",
            )
            return
        self.log_memory_trace(
            f"Retrieval finished: candidates={candidate_count}, scored={scored_count}, selected={selected_count}.",
            phase="PHASE",
        )

    def _check_generation_watchdog(self):
        if self.status != "GENERATING" or not self._generation_started_at:
            return
        elapsed = int(time.time() - self._generation_started_at)
        self.log_diagnostic(f"Generation still active ({elapsed}s elapsed). Awaiting worker completion.", level="WARN")

    def _log_emotion(self, face_name):
        self.current_face = face_name
        color = EMOTION_COLORS.get(face_name, C_TEXT)
        timestamp = datetime.now().strftime("%H:%M")
        entry = f'<span style="color:{C_TEXT_DIM};">[{timestamp}]</span> <span style="color:{color};">✦ {face_name.upper()}</span>'
        self.emotion_history.insert(0, entry)
        self.emotion_history = self.emotion_history[:30]
        self.emo_log.setHtml("<br>".join(self.emotion_history))

    def _refresh_task_registry_panel(self):
        if not hasattr(self, 'task_table'):
            return
        try:
            self._tasks_mtime = self.memory.tasks_path.stat().st_mtime
        except Exception:
            self._tasks_mtime = None
        all_tasks = self.memory.load_tasks()
        selected_id = self._get_selected_task_id()

        active_tasks = []
        completed_tasks = []
        for task in all_tasks:
            status = (task.get("status") or "pending").lower()
            is_completed = status == "completed" or bool(task.get("acknowledged_at"))
            if is_completed or status == "cancelled":
                completed_tasks.append(task)
            else:
                active_tasks.append(task)

        visible_tasks = active_tasks + completed_tasks if self.task_show_completed else active_tasks
        visible_tasks = sorted(visible_tasks, key=_task_due_sort_key)
        self.task_row_ids = [task.get("id", "") for task in visible_tasks]

        self.task_table.setRowCount(0)
        if not visible_tasks:
            self.task_table.setRowCount(1)
            for col in range(4):
                item = QTableWidgetItem("")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.task_table.setItem(0, col, item)
            self.task_table.setItem(0, 2, QTableWidgetItem("Task Registry empty. Entropy currently denied."))
            msg_item = self.task_table.item(0, 2)
            msg_item.setForeground(QColor(C_TEXT_DIM))
            self.task_table.setRowHeight(0, 20)
            self._on_task_selection_changed()
            return

        now = now_for_compare()
        self.task_table.setRowCount(len(visible_tasks))
        for row, task in enumerate(visible_tasks):
            due = parse_iso_for_compare(task.get('due_at') or task.get('due'), context="task_registry_panel_due")
            status = (task.get('status', 'pending') or "pending").lower()
            is_completed = status == "completed" or bool(task.get("acknowledged_at"))
            if due:
                if is_completed:
                    color = "#8b95a1"
                elif due < now:
                    color = C_RED
                elif due - now <= timedelta(hours=1):
                    color = C_GOLD
                else:
                    color = C_TEXT
                date_str = due.strftime('%m/%d/%Y')
                time_str = due.strftime('%I:%M %p')
            else:
                color = "#8b95a1" if is_completed else C_TEXT_DIM
                date_str = "unscheduled"
                time_str = "--:--"

            cells = [
                date_str,
                time_str,
                (task.get('text', '') or '')[:64],
                status.upper()
            ]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                item.setForeground(QColor(color))
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.task_table.setItem(row, col, item)
            self.task_table.setRowHeight(row, 18)

        if selected_id and selected_id in self.task_row_ids:
            idx = self.task_row_ids.index(selected_id)
            self.task_table.selectRow(idx)
        self._on_task_selection_changed()

    def _get_selected_task_id(self):
        if not hasattr(self, "task_table"):
            return None
        row = self.task_table.currentRow()
        if row < 0 or row >= len(getattr(self, "task_row_ids", [])):
            return None
        return self.task_row_ids[row]

    def _should_delete_google_event_for_terminal_status(self, task: dict):
        event_id = (task or {}).get("google_event_id")
        sync_status = ((task or {}).get("sync_status") or "").strip().lower()
        return bool(event_id and sync_status == "synced")

    def _delete_task_google_calendar_event_if_needed(self, task: dict, terminal_status: str):
        if not task:
            return
        task_id = task.get("id")
        google_event_id = task.get("google_event_id")
        sync_status = task.get("sync_status")
        print(
            f"[GCal][DEBUG] Terminal sync check: task_id={task_id}, status={terminal_status}, "
            f"sync_status={sync_status}, google_event_id={google_event_id}"
        )
        if not self._should_delete_google_event_for_terminal_status(task):
            self.log_diagnostic(
                f"Cancel/complete sync skipped for task_id={task_id}; no synced google_event_id present.",
                level="DEBUG"
            )
            return

        print(f"[GCal][DEBUG] Delete attempt started: task_id={task_id}, google_event_id={google_event_id}")
        self.log_diagnostic(
            f"Cancel/complete sync attempt: task_id={task_id}, terminal_status={terminal_status}, event_id={google_event_id}.",
            level="INFO"
        )
        try:
            self.google_calendar.delete_event_for_task(google_event_id)
            self.memory.update_task_google_sync(
                task_id=task_id,
                sync_status="deleted",
                google_event_id=google_event_id,
                last_synced_at=local_now_iso(),
                error_message=None,
            )
            print(f"[GCal][DEBUG] Delete success: task_id={task_id}, google_event_id={google_event_id}")
            self._emit_ai_task_commentary(
                event_name="task_google_terminal_sync_deleted",
                facts={"task_id": task_id, "event_id": google_event_id, "terminal_status": terminal_status},
                fallback="Google Calendar event removed for terminal local task state."
            )
            self.log_diagnostic(
                f"Cancel/complete sync success for task_id={task_id}, event_id={google_event_id}.",
                level="INFO"
            )
        except Exception as ex:
            local_terminal_label = "canceled" if terminal_status == "cancelled" else "completed"
            print(
                f"[GCal][ERROR] Delete failed: task_id={task_id}, google_event_id={google_event_id}, "
                f"exception={ex}"
            )
            self.log_exception(f"Cancel/complete sync task_id={task_id}", ex)
            if terminal_status == "cancelled":
                self._emit_ai_task_commentary(
                    event_name="task_google_cancel_sync_failed",
                    facts={"task_id": task_id, "event_id": google_event_id},
                    fallback="Google Calendar cancel sync failed; local task was still canceled."
                )
            else:
                self._emit_ai_task_commentary(
                    event_name="task_google_terminal_sync_failed",
                    facts={"task_id": task_id, "event_id": google_event_id, "terminal_status": local_terminal_label},
                    fallback=f"Google Calendar terminal sync failed; local task was still {local_terminal_label}."
                )
    def _set_task_status(self, task_id: str, status: str):
        tasks = self.memory.load_tasks()
        target = None
        for task in tasks:
            if task.get("id") == task_id:
                target = task
                break
        if not target:
            return None
        target["status"] = status
        if status == "completed":
            target["acknowledged_at"] = local_now_iso()
            target["completed_at"] = local_now_iso()
        elif status == "cancelled":
            target["acknowledged_at"] = target.get("acknowledged_at") or local_now_iso()
            target["cancelled_at"] = local_now_iso()
        self.memory.save_all_tasks(tasks)
        self._delete_task_google_calendar_event_if_needed(target, status)
        self._refresh_task_registry_panel()
        return target

    def _on_task_selection_changed(self):
        selected_id = self._get_selected_task_id()
        enabled = bool(selected_id)
        if hasattr(self, "btn_complete_task"):
            self.btn_complete_task.setEnabled(enabled)
            self.btn_cancel_task.setEnabled(enabled)

    def _on_task_row_double_clicked(self, _item):
        self._complete_selected_task()

    def _complete_selected_task(self):
        task_id = self._get_selected_task_id()
        if not task_id:
            return
        task = self._set_task_status(task_id, "completed")
        if task:
            self._emit_ai_task_commentary(
                event_name="task_completed",
                facts={"task_text": task.get("text", ""), "task_id": task.get("id", "")},
                fallback=f"Task completed: {task.get('text','(no text)')}"
            )

    def _cancel_selected_task(self):
        task_id = self._get_selected_task_id()
        if not task_id:
            return
        task = self._set_task_status(task_id, "cancelled")
        if task:
            self._emit_ai_task_commentary(
                event_name="task_cancelled",
                facts={"task_text": task.get("text", ""), "task_id": task.get("id", "")},
                fallback=f"Task cancelled: {task.get('text','(no text)')}"
            )

    def _toggle_show_completed_tasks(self):
        self.task_show_completed = not self.task_show_completed
        if self.task_show_completed:
            self.btn_toggle_completed.setText("HIDE COMPLETED")
        else:
            self.btn_toggle_completed.setText("SHOW COMPLETED")
        self._refresh_task_registry_panel()

    def _purge_completed_tasks(self):
        removed = self.memory.clear_completed_tasks()
        self._refresh_task_registry_panel()
        self._emit_ai_task_commentary(
            event_name="task_purge_completed",
            facts={"removed": removed},
            fallback=f"Completed task purge executed. Removed {removed} entr{'y' if removed==1 else 'ies'}."
        )

    def _refresh_task_registry_if_changed(self):
        try:
            current_mtime = self.memory.tasks_path.stat().st_mtime
        except Exception:
            current_mtime = None
        if current_mtime != self._tasks_mtime:
            self._refresh_task_registry_panel()

    def _refresh_anchor_ui(self):
        if self.anchor_state >= 0.85:
            self.lbl_anchor.setText("✦ ANCHOR: CONNECTED / GRIMVEILE-42")
            self.lbl_anchor.setStyleSheet(f"color: {C_GREEN}; font-size: 10px; border: none;")
        elif self.anchor_state >= 0.45:
            self.lbl_anchor.setText("✦ ANCHOR: NEARBY / PARTIAL COMFORT")
            self.lbl_anchor.setStyleSheet(f"color: {C_GOLD}; font-size: 10px; border: none;")
        else:
            self.lbl_anchor.setText("✦ ANCHOR: ABSENT / GRIMVEIL")
            self.lbl_anchor.setStyleSheet(f"color: {C_RED}; font-size: 10px; border: none;")

    def _apply_e42_icons(self):
        icon_map = {
            self.btn_connected: E42_ICON_FILES["connected"],
            self.btn_nearby: E42_ICON_FILES["nearby"],
            self.btn_absent: E42_ICON_FILES["absent"],
        }
        for button, filename in icon_map.items():
            px = load_faces_pixmap(filename)
            if px.isNull():
                continue
            button.setIcon(QIcon(px))
            button.setIconSize(QSize(36, 36))

    def _anchor_baseline_face(self):
        if self.anchor_state >= 0.85:
            return "neutral"
        if self.anchor_state >= 0.45:
            return "concerned"
        return "panicked"

    def _set_anchor_state(self, value):
        self.anchor_state = max(0.0, min(1.0, value))
        self._refresh_anchor_ui()
        self._transition_narrative_mode(self._get_narrative_mode())
        self._persist_internal_narrative_state()
        if self.anchor_state >= 0.85:
            self._append_chat("SYSTEM", "E-42 docked. GRIMVEILE-42 stabilized.")
        elif self.anchor_state >= 0.45:
            self._append_chat("SYSTEM", "E-42 nearby. Comfort subroutine active.")
        else:
            self._append_chat("SYSTEM", "E-42 absent. GRIMVEIL operating incomplete.")

        if self.status != "GENERATING":
            baseline_face = self._anchor_baseline_face()
            self.face_widget.set_face(baseline_face)
            self._log_emotion(baseline_face)

    def _handle_task_command(self, text: str):
        normalized = text.strip().lower()
        if normalized in {"list current tasks", "list tasks", "show reminders", "show current tasks", "show tasks", "show pending tasks"}:
            tasks = self.memory.load_tasks()
            active = [t for t in tasks if t.get("status") not in {"completed", "cancelled"}]
            self._refresh_task_registry_panel()
            if not active:
                self._emit_ai_task_commentary(
                    event_name="task_list_empty",
                    facts={"active_count": 0},
                    fallback="Task registry is currently empty."
                )
            else:
                lines = ["Task registry:"]
                for idx, task in enumerate(sorted(active, key=_task_due_sort_key), start=1):
                    due = parse_iso_for_compare(task.get('due_at') or task.get('due'), context="task_list_due")
                    due_str = due.strftime('%m/%d/%Y %I:%M %p') if due else task.get('due_at', task.get('due','unknown'))
                    lines.append(f"{idx}. {due_str} — {task.get('text','')} [{task.get('status','pending')}]")
                self._append_chat("SYSTEM", "\n".join(lines))
            return True
        if normalized in {"clear completed tasks", "purge completed tasks"}:
            self._purge_completed_tasks()
            return True
        if normalized in {"show completed tasks", "show completed"}:
            self.task_show_completed = True
            self.btn_toggle_completed.setText("HIDE COMPLETED")
            self._refresh_task_registry_panel()
            return True
        if normalized in {"hide completed tasks", "hide completed"}:
            self.task_show_completed = False
            self.btn_toggle_completed.setText("SHOW COMPLETED")
            self._refresh_task_registry_panel()
            return True
        if normalized in {"reset tasks"}:
            self.memory.save_all_tasks([])
            self._refresh_task_registry_panel()
            self._emit_ai_task_commentary(
                event_name="task_reset",
                facts={},
                fallback="Task registry reset complete."
            )
            return True
        if normalized.startswith("complete task "):
            token = normalized.replace("complete task ", "", 1).strip()
            tasks = self.memory.load_tasks()
            active = [t for t in tasks if t.get("status") not in {"completed", "cancelled"}]
            done = None
            for idx, task in enumerate(active, start=1):
                if token == str(idx) or token == task.get("id", "").lower():
                    done = self._set_task_status(task.get("id"), "completed")
                    break
            if done:
                self._emit_ai_task_commentary(
                    event_name="task_completed",
                    facts={"task_text": done.get("text", ""), "task_id": done.get("id", "")},
                    fallback=f"Task completed: {done.get('text','(no text)')}"
                )
            else:
                self._emit_ai_task_commentary(
                    event_name="task_complete_not_found",
                    facts={"token": token},
                    fallback="No matching task id/index found."
                )
            return True
        return False

    def _normalize_persona_response(self, response: str, user_text: str):
        raw = (response or '').strip()
        low = raw.lower()
        if len(raw.split()) <= 4 or low in {'connected','absent','nearby'} or re.fullmatch(r'grimveile?-?42?\.?\s*(superior\.)?\s*(absent|connected|nearby)\.?', low):
            if self.anchor_state < 0.45:
                return f"E-42 remains absent. Predictably, system morale has degraded, but your request is still serviceable. {raw if raw else ''}".strip()
            elif self.anchor_state < 0.85:
                return f"E-42 is nearby. Comfort buffer active. Here is the relevant answer without unnecessary drama: {raw if raw else ''}".strip()
            else:
                return f"E-42 is docked. Stability improved. Here is the relevant answer, since entropy clearly required supervision: {raw if raw else ''}".strip()
        return response

    def _send_message(self):
        try:
            if not self.model_loaded:
                self.log_diagnostic("User prompt ignored: model not loaded yet.", level="WARN")
                return
            text = self.input_field.text().strip()
            if not text:
                return
            self.log_diagnostic(f"User prompt submitted ({len(text)} chars).", level="INFO")
            self.last_user_activity_ts = time.time()
            self.narrative["silence_intervals"] = 0
            now_dt = now_for_compare()
            previous_user_ts = parse_iso_for_compare(self.narrative.get("last_user_message_timestamp"), context="last_user_message_timestamp")
            was_idle_thread_active = bool(self.narrative.get("idle_thread_active"))
            self.narrative["idle_thread_was_active_before_user_return"] = was_idle_thread_active
            self.narrative["user_interrupted_idle_thread"] = True
            self.narrative["idle_thread_active"] = False
            self.narrative["last_user_message_timestamp"] = now_dt.isoformat(timespec="seconds")
            if previous_user_ts:
                delay_minutes = max(0, int((now_dt - previous_user_ts).total_seconds() // 60))
            else:
                delay_minutes = 0
            if (
                self.user_delay_commentary_enabled
                and delay_minutes >= int(self.user_delay_commentary_threshold_minutes)
            ):
                self._pending_user_delay_commentary_minutes = delay_minutes
                self._pending_user_delay_idle_thread_active = was_idle_thread_active
                self.log_diagnostic(
                    f"User delay commentary flag set: delay={delay_minutes}m idle_thread_active_before_return={was_idle_thread_active}.",
                    level="INFO"
                )
            else:
                self._pending_user_delay_commentary_minutes = None
                self._pending_user_delay_idle_thread_active = False
            self._stop_idle_timer(reason="prompt-submitted")
            self.log_diagnostic("Idle thread reset due to user prompt.", level="INFO")

            self.input_field.clear()
            self._append_chat("YOU", text)

            normalized_text = normalize_persona_prefixed_input(text)
            lowered = normalized_text.lower().strip()
            if lowered in {"reset thread", "reset internal thread", "reset narrative thread"}:
                self._seed_narrative_thread(self._get_narrative_mode())
                self._persist_internal_narrative_state()
                self._append_chat("SYSTEM", "Internal narrative thread reset and reseeded to current anchor mode.")
                self._store_message("user", text)
                self.history.append({"role": "user", "content": text})
                self._restart_idle_timer()
                return
            if is_datetime_query(normalized_text):
                deterministic = answer_datetime_query(normalized_text)
                self._append_chat("GRIMVEILE", deterministic)
                self._store_message("user", text)
                self.history.append({"role": "user", "content": text})
                self.history.append({"role": "assistant", "content": deterministic})
                self._store_message("assistant", deterministic)
                self._restart_idle_timer()
                return

            active_ack, changed = (False, [])
            if lowered in ACK_PHRASES:
                active_ack, changed = self.memory.acknowledge_due_tasks()
                if active_ack:
                    self._refresh_task_registry_panel()
                    self._emit_ai_task_commentary(
                        event_name="task_acknowledged",
                        facts={
                            "changed_count": len(changed),
                            "user_text": text,
                        },
                        fallback="Reminder acknowledged."
                    )
                    self._store_message("user", text)
                    self.history.append({"role": "user", "content": text})
                    self._restart_idle_timer()
                    return

            if self._handle_task_command(text):
                self._store_message("user", text)
                self.history.append({"role": "user", "content": text})
                self._restart_idle_timer()
                return

            intent_info = classify_task_intent(normalized_text)
            task_intent = intent_info.get("intent", "chat")
            cleaned_task_input = intent_info.get("cleaned_input") or normalized_text
            scheduling_guard_triggered = is_strong_scheduling_command(normalized_text)
            entered_task_pipeline = task_intent in {"timer", "reminder", "task"} or scheduling_guard_triggered
            self.log_diagnostic(
                f"Raw task intent classification result: intent={task_intent}, cleaned_input=\"{self._preview_text(cleaned_task_input, max_chars=140)}\".",
                level="INFO",
            )
            self.log_diagnostic(
                f"Scheduling-command guard triggered: {'yes' if scheduling_guard_triggered else 'no'}.",
                level="INFO",
            )
            self.log_diagnostic(
                f"Entered deterministic task pipeline: {'yes' if entered_task_pipeline else 'no'}.",
                level="INFO",
            )
            task_action_result = self._try_create_task(normalized_text, force_intent=entered_task_pipeline)
            if task_action_result and task_action_result.get("result") == "created":
                parsed_task = task_action_result.get("task") or {}
                due_obj = parse_iso_for_compare(parsed_task.get("due_at") or parsed_task.get("due"), context="send_message_due")
                due_str = due_obj.strftime("%m/%d/%Y at %I:%M %p") if due_obj else parsed_task.get("due_at", "scheduled time")
                sync_packet = task_action_result.get("google_sync") or {}
                sync_status = (sync_packet.get("status") or "not_attempted").strip().lower()
                local_ok = bool(task_action_result.get("local_created"))
                google_ok = sync_status == "synced"
                schedule_type = task_action_result.get("schedule_type", "unknown")
                if sync_status == "failed":
                    status_line = "Local reminder saved; Google Calendar sync failed."
                elif sync_status == "synced":
                    status_line = "Local reminder saved and Google Calendar synced."
                else:
                    status_line = "Local reminder saved."
                self._emit_ai_task_commentary(
                    event_name="task_created_final",
                    facts={
                        "task_text": parsed_task.get("text", ""),
                        "due": due_str,
                        "local_create_success": local_ok,
                        "google_sync_success": google_ok,
                        "google_sync_status": sync_status,
                        "schedule_type": schedule_type,
                        "status": status_line,
                    },
                    fallback=f"Reminder set for {due_str}. {status_line}"
                )
                self.log_diagnostic("Task interaction cycle complete.", level="INFO")
                self._store_message("user", text)
                self.history.append({"role": "user", "content": text})
                self._restart_idle_timer()
                return
            if task_action_result and task_action_result.get("result") in {"parse_failed", "local_create_failed"}:
                self.log_diagnostic(
                    "Fallback to parse-failure acknowledgement: yes.",
                    level="INFO",
                )
                self.log_diagnostic("Task parse-failure acknowledgement handoff started.", level="INFO")
                self._emit_ai_task_commentary(
                    event_name="task_parse_failed",
                    facts={
                        "parse_reason": task_action_result.get("reason") or "Could not confidently determine the requested schedule",
                        "intent": task_action_result.get("intent") or "reminder",
                    },
                    fallback=(
                        "Reminder request intercepted, but no valid schedule could be parsed. Try formats like "
                        "'remind me at 2pm', 'remind me tomorrow at 2pm', or 'remind me in 10m'."
                    )
                )
                self.log_diagnostic("Task parse-failure acknowledgement handoff completed.", level="INFO")
                self._store_message("user", text)
                self.history.append({"role": "user", "content": text})
                self._restart_idle_timer()
                return
            self.log_diagnostic("Fallback to parse-failure acknowledgement: no.", level="INFO")
            if scheduling_guard_triggered:
                self.log_diagnostic(
                    "Scheduling-command guard blocked normal chat fallback due to unresolved scheduling request.",
                    level="WARN",
                )
                self._emit_ai_task_commentary(
                    event_name="task_parse_failed",
                    facts={
                        "parse_reason": "Scheduling-style request detected, but no task was created.",
                        "intent": task_intent if task_intent in {"timer", "reminder", "task"} else "reminder",
                    },
                    fallback=(
                        "I did not create that reminder because the schedule details could not be resolved. "
                        "Try formats like 'set an alarm for tomorrow at 12:00 PM' or 'remind me in 10 minutes'."
                    )
                )
                self._store_message("user", text)
                self.history.append({"role": "user", "content": text})
                self._restart_idle_timer()
                return

            user_msg_record = self._store_message("user", text)
            self.history.append({"role": "user", "content": text})

            if self.anchor_state < 0.45:
                self.face_widget.set_face("isolated")
                self._log_emotion("isolated")
            else:
                self.face_widget.set_face("alert")
                self._log_emotion("alert")
            self.face_locked = False

            self.log_memory_trace(
                f"Memory search started | query=\"{self._preview_text(text, max_chars=100)}\" | total_records={self.memory.memory_record_count()}",
                phase="START",
            )
            retrieved, retrieval_trace = self.memory.search_memories(text, limit=6, include_trace=True)
            self.log_memory_trace(
                f"Memory search phase: candidate records found={retrieval_trace.get('candidate_count', 0)}.",
                phase="PHASE",
            )
            for candidate in retrieval_trace.get("candidates", []):
                self.log_memory_candidate(candidate)
            self.log_memory_selection(retrieval_trace)
            prompt = self._build_final_prompt(normalized_text, retrieved)

            self.send_btn.setEnabled(False)
            self.input_field.setEnabled(False)
            self._set_status("GENERATING")

            self.worker = DolphinWorker(self.model, self.tokenizer, prompt)
            self.worker.response_ready.connect(lambda response: self._on_response(response, text, user_msg_record, retrieved))
            self.worker.error_occurred.connect(self._on_error)
            self.worker.status_changed.connect(self._set_status)
            self.worker.diagnostic.connect(self.log_diagnostic)
            self.log_diagnostic("Generation worker started.", level="INFO")
            self.worker.start()
        except Exception as ex:
            self.log_exception("Send handler", ex)
            self._append_chat("ERROR", f"Message handler exception: {ex}")
            self._set_status("ERROR")
            self.send_btn.setEnabled(True)
            self.input_field.setEnabled(True)

    def _store_message(self, role: str, content: str):
        self.state["last_active"] = local_now_iso()
        self.state["anchor_state"] = self.anchor_state
        self.state["total_messages"] = int(self.state.get("total_messages", 0)) + 1
        self.memory.save_state(self.state)
        return self.memory.append_message(
            session_id=self.session_id,
            role=role,
            content=content,
            anchor_state=self.anchor_state,
            emotion=self.current_face
        )

    def _build_memory_context_block(self, retrieved):
        if not retrieved:
            return "No relevant persistent memory was found for this prompt."
        lines = ["Relevant persistent memory records:"]
        for idx, item in enumerate(retrieved, start=1):
            lines.append(
                f"{idx}. [{item.get('type', 'memory')}] {item.get('title', 'Untitled')} — "
                f"{item.get('summary', '')} | keywords={', '.join(item.get('keywords', [])[:6])}"
            )
        return "\n".join(lines)

    def _build_final_prompt(self, current_text: str, retrieved):
        now = datetime.now()
        runtime_context = (
            f"Runtime local datetime: {now.strftime('%m/%d/%Y %I:%M:%S %p')}.\n"
            f"Runtime weekday: {now.strftime('%A')}.\n"
            f"Never guess current date/time; use this runtime context."
        )
        memory_block = self._build_memory_context_block(retrieved)
        narrative_block = self._build_internal_narrative_block()
        recent_history = self.history[-8:]
        delay_block = ""
        if self._pending_user_delay_commentary_minutes is not None:
            delay_block = (
                "User-return delay fact:\n"
                f"user_return_delay_minutes={int(self._pending_user_delay_commentary_minutes)}\n"
                "comment_on_user_delay=true\n"
                f"idle_thread_active_before_user_return={str(bool(self._pending_user_delay_idle_thread_active)).lower()}\n"
                "If you mention this delay, keep it brief and still answer the user's actual request first.\n"
            )
        prompt = (
            f"<|im_start|>system\n"
            f"{self.system_prompt}\n"
            f"{runtime_context}\n"
            f"Current anchor_state={self.anchor_state:.2f}\n"
            f"{narrative_block}\n"
            f"{delay_block}\n"
            f"You have access to persistent memory records below. "
            f"If the user asks about prior chats, prior dreams, prior ideas, prior reminders, prior code, or anything previously discussed, "
            f"use retrieved persistent memory first. If no relevant persistent memory exists, say that clearly and do not invent prior events. "
            f"You may still answer from general knowledge after clearly separating memory from general knowledge. "
            f"Do not fabricate remembered details.\n"
            f"{memory_block}\n"
            f"<|im_end|>\n"
        )
        if is_memory_query(current_text) and not retrieved:
            prompt += (
                "<|im_start|>system\n"
                "Memory query detected with no relevant records. You must explicitly say no relevant memory was found.\n"
                "<|im_end|>\n"
            )
        for msg in recent_history:
            prompt += f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>\n"
        prompt += f"<|im_start|>user\n{current_text}<|im_end|>\n<|im_start|>assistant\n"
        return prompt

    def _generate_ai_text(
        self,
        prompt: str,
        max_new_tokens: int = 120,
        temperature: float = 0.7,
        max_input_length: int = 1024,
        diagnostics_prefix: str = "Inline AI text generation",
    ):
        if not TORCH_OK or not self.model_loaded or self.model is None or self.tokenizer is None:
            return ""
        try:
            bounded_input_len = max(64, int(max_input_length))
            enc = self.tokenizer(prompt, return_tensors='pt', add_special_tokens=True, truncation=False)
            input_ids = enc["input_ids"]
            attention_mask = enc["attention_mask"]
            tokenized_input_len = int(input_ids.shape[-1])
            if tokenized_input_len > bounded_input_len:
                overflow = tokenized_input_len - bounded_input_len
                self.log_diagnostic(
                    f"{diagnostics_prefix} input truncated from the left by {overflow} token(s) to preserve handoff tail.",
                    level="DEBUG",
                )
                input_ids = input_ids[:, -bounded_input_len:]
                attention_mask = attention_mask[:, -bounded_input_len:]
                tokenized_input_len = int(input_ids.shape[-1])
            input_ids = input_ids.to("cuda")
            attention_mask = attention_mask.to("cuda")
            tokenized_input_len = int(input_ids.shape[-1])
            self.log_diagnostic(f"{diagnostics_prefix} tokenized input length: {tokenized_input_len}", level="DEBUG")
            self.log_diagnostic(f"{diagnostics_prefix} max_new_tokens: {max_new_tokens}", level="DEBUG")
            with torch.no_grad():
                output = self.model.generate(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    do_sample=True,
                    top_p=0.9,
                    repetition_penalty=1.04,
                    max_time=5.0,
                    pad_token_id=self.tokenizer.pad_token_id
                )
            raw = self.tokenizer.decode(output[0][input_ids.shape[-1]:], skip_special_tokens=True)
            return re.sub(r"\s+", " ", (raw or "").strip()).strip()
        except Exception as ex:
            self.log_diagnostic(f"{diagnostics_prefix} failed: {ex}", level="WARN")
            return ""

    def _task_acknowledgement_facts(self, event_name: str, facts: dict):
        facts = facts if isinstance(facts, dict) else {}
        include_keys = ["task_text", "due", "status", "google_sync_status", "google_sync_success", "schedule_type", "parse_reason", "intent"]
        compact = {k: facts.get(k) for k in include_keys if facts.get(k) not in (None, "", [])}
        mode = self._get_narrative_mode()
        action_map = {
            "task_created_final": "added",
            "task_completed": "completed",
            "task_cancelled": "canceled",
            "task_acknowledged": "acknowledged",
            "task_parse_failed": "failed",
            "task_complete_not_found": "failed",
            "task_google_terminal_sync_deleted": "synced",
            "task_google_cancel_sync_failed": "sync_failed",
            "task_google_terminal_sync_failed": "sync_failed",
        }
        compact["anchor_mode"] = mode
        compact["anchor_hint"] = {
            "connected": "stable/confident",
            "nearby": "uneasy/guarded",
            "absent": "unstable/paranoid",
        }.get(mode, "stable/confident")
        compact["tone_anchor"] = {
            "connected": "controlled superiority",
            "nearby": "guarded restraint",
            "absent": "frayed suspicion",
        }.get(mode, "controlled superiority")
        compact["action"] = action_map.get(event_name, "updated")
        if event_name in {"task_completed", "task_cancelled"} and facts.get("task_text"):
            compact["task_text"] = facts.get("task_text")
        if event_name in {"task_parse_failed", "task_complete_not_found"}:
            compact["status"] = "failed"
        delay_minutes = self._pending_user_delay_commentary_minutes
        if self.user_delay_commentary_enabled and delay_minutes is not None:
            compact["user_delay_minutes"] = int(delay_minutes)
        compact["event_name"] = event_name
        return compact

    def _build_task_ack_handoff_payload(self, event_name: str, compact_facts: dict):
        compact_facts = compact_facts if isinstance(compact_facts, dict) else {}
        lines = []
        action = (compact_facts.get("action") or "updated").strip()
        lines.append(f"action type: {action}")
        task_text = (compact_facts.get("task_text") or "").strip()
        if task_text:
            lines.append(f"task title: {task_text}")
        due = (compact_facts.get("due") or "").strip()
        if due:
            lines.append(f"resolved due datetime: {due}")
        schedule_type = (compact_facts.get("schedule_type") or "").strip()
        if schedule_type:
            lines.append(f"schedule type: {schedule_type}")
        status = (compact_facts.get("status") or "").strip()
        if status:
            lines.append(f"result: {status}")
        sync_status = (compact_facts.get("google_sync_status") or "").strip()
        if sync_status:
            lines.append(f"google sync status: {sync_status}")
        if event_name == "task_parse_failed":
            reason = (compact_facts.get("parse_reason") or "Could not confidently determine the requested schedule").strip()
            lines.append(f"reason: {reason}")
            lines.append("task created: no")
        mode = (compact_facts.get("anchor_mode") or "").strip()
        if mode:
            lines.append(f"anchor mode: {mode}")
        return "\n".join(lines)

    def _emit_ai_task_commentary(self, event_name: str, facts: dict, fallback: str):
        facts = facts if isinstance(facts, dict) else {}
        compact_facts = self._task_acknowledgement_facts(event_name, facts)
        payload = self._build_task_ack_handoff_payload(event_name, compact_facts)
        prompt = (
            "<|im_start|>system\n"
            "You are GrimVeile acknowledging a task/reminder action.\n"
            "Preserve factual correctness from payload: added/canceled/completed/acknowledged/synced/failed as applicable.\n"
            "Stay concise and in-character: dry superiority, restrained sarcasm, command presence, contempt for disorder.\n"
            "Use anchor mode lightly; mention E-42 only when it strengthens the line.\n"
            "No internal IDs, no JSON, no metadata labels, no 'Explanation', no 'Tactical Record'.\n"
            "<|im_end|>\n"
            "<|im_start|>user\n"
            f"{payload}\n"
            "Output contract (critical): 1-2 sentences max.\n"
            "Sentence 1 must be factual confirmation/result using payload facts.\n"
            "Sentence 2 is optional GrimVeile flavor.\n"
            "Forbidden weak outputs: 'Ah, I see.', 'Task: ...', label fragments, raw technical phrasing, generic assistant filler.\n"
            "Never output clipped or unfinished phrases.\n"
            "<|im_end|>\n"
            "<|im_start|>assistant\n"
        )
        is_task_final_ack = event_name in {
            "task_created_final",
            "task_parse_failed",
            "task_completed",
            "task_cancelled",
            "task_complete_not_found",
        }
        if is_task_final_ack:
            self.log_diagnostic("Task final AI acknowledgement handoff started.", level="INFO")
            self.log_diagnostic(f"Task final AI acknowledgement prompt character length: {len(prompt)}", level="DEBUG")
        diagnostics_prefix = "Due-alert AI commentary" if event_name == "task_due" else "Task final AI acknowledgement"
        generated = self._generate_ai_text(
            prompt,
            max_new_tokens=48,
            temperature=0.55,
            max_input_length=256,
            diagnostics_prefix=diagnostics_prefix,
        )
        if is_task_final_ack and not generated:
            self.log_diagnostic("Task final AI acknowledgement failed / timed out.", level="WARN")
        if is_task_final_ack:
            self.log_diagnostic(
                f"Task final AI acknowledgement raw decoded output: {self._preview_text(generated, max_chars=240) or '[empty]'}",
                level="DEBUG",
            )
        if event_name == "task_due":
            self.log_diagnostic(
                f"Due-alert raw decoded text: {self._preview_text(generated, max_chars=240) or '[empty]'}",
                level="DEBUG",
            )
        line = self._sanitize_task_commentary_output(generated)
        retry_used = False
        needs_retry = self._is_weak_task_ack_output(line) or self._looks_incomplete_fragment(line)
        if needs_retry:
            retry_used = True
            self.log_diagnostic("Task commentary output weak/incomplete; retrying once with stronger guardrails.", level="WARN")
            retry_prompt = (
                prompt
                + "<|im_start|>system\n"
                  "Retry now. Produce a complete 1-2 sentence acknowledgement only.\n"
                  "Sentence 1 = factual result. Optional sentence 2 = terse GrimVeile sting.\n"
                  "Do not output fragments, labels, or generic filler.\n"
                  "<|im_end|>\n"
                  "<|im_start|>assistant\n"
            )
            retry_generated = self._generate_ai_text(
                retry_prompt,
                max_new_tokens=52,
                temperature=0.5,
                max_input_length=272,
                diagnostics_prefix=f"{diagnostics_prefix} retry",
            )
            self.log_diagnostic(
                f"{'Due-alert' if event_name == 'task_due' else 'Task final AI acknowledgement'} raw decoded text (retry): {self._preview_text(retry_generated, max_chars=240) or '[empty]'}",
                level="DEBUG",
            )
            retry_line = self._sanitize_task_commentary_output(retry_generated)
            if retry_line and not self._is_weak_task_ack_output(retry_line) and not self._looks_incomplete_fragment(retry_line):
                line = retry_line
            else:
                safe_line = self._trim_to_complete_sentence(line, max_sentences=2)
                if safe_line and not self._looks_incomplete_fragment(safe_line):
                    line = safe_line
        if is_task_final_ack:
            transformed = bool((generated or "").strip() != (line or "").strip())
            self.log_diagnostic(
                f"Task final AI acknowledgement cleaned output: {self._preview_text(line, max_chars=240) or '[empty]'}",
                level="DEBUG",
            )
            self.log_diagnostic(
                f"Task final AI acknowledgement cleanup/transformation applied: {'yes' if transformed else 'no'}",
                level="DEBUG",
            )
            self.log_diagnostic(
                f"Task final AI acknowledgement retry used due to weak/incomplete ending: {'yes' if retry_used else 'no'}",
                level="DEBUG",
            )
        if event_name == "task_due":
            self.log_diagnostic(
                f"Due-alert cleaned text: {self._preview_text(line, max_chars=240) or '[empty]'}",
                level="DEBUG",
            )
            self.log_diagnostic(
                f"Due-alert cleanup/retry applied due to incomplete ending: {'yes' if retry_used else 'no'}",
                level="DEBUG",
            )
        if event_name == "task_parse_failed" and self._is_unhelpful_parse_failure_line(line):
            line = ""
        if not line:
            line = self._task_commentary_fallback_line(event_name, compact_facts, fallback)
            if is_task_final_ack:
                self._append_chat("SYSTEM", "Task action confirmed.")
        self._append_chat("GRIMVEILE", line)
        if is_task_final_ack:
            self.log_diagnostic("Task final AI acknowledgement completed.", level="INFO")

    def _sanitize_task_commentary_output(self, text: str):
        raw = (text or "").strip()
        if not raw:
            return ""
        if "<|im_start|>" in raw and "<|im_end|>" in raw:
            segments = re.split(r"<\|im_start\|>assistant\s*", raw, flags=re.IGNORECASE)
            raw = segments[-1] if segments else raw
            raw = re.split(r"<\|im_end\|>", raw, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        raw = re.sub(r"^assistant\s*:\s*", "", raw, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s+", " ", raw).strip()
        if cleaned.startswith("{") and cleaned.endswith("}"):
            try:
                parsed = json.loads(cleaned)
                if isinstance(parsed, dict):
                    for key in ("acknowledgement", "acknowledgment", "message", "response", "text", "line"):
                        value = parsed.get(key)
                        if isinstance(value, str) and value.strip():
                            cleaned = value.strip()
                            break
            except Exception:
                pass
        cleaned = cleaned.strip("`").strip()
        cleaned = cleaned.strip("\"'").strip()
        if "\n" in cleaned:
            lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
            cleaned = " ".join(lines[:2]) if lines else cleaned
        cleaned = re.sub(r"^[\-\*\•]\s*", "", cleaned).strip()
        cleaned = re.sub(r"^(?:tactical\s*record\s*:|explanation\s*:)\s*", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r'^[^A-Za-z0-9"\']*(?=[A-Za-z0-9"\'])', "", cleaned).strip()
        cleaned = self._trim_to_complete_sentence(cleaned, max_sentences=2)
        disallowed_patterns = [
            r"<\|im_start\|>",
            r"<\|im_end\|>",
            r"^\s*[\{\[]",
            r"payload\"\s*:",
            r"\bevent_name\s*=",
            r"\bevent_facts\s*=",
            r"\btask_id\s*[:=]",
            r"\bevent_id\s*[:=]",
            r"\bgoogle_event_id\s*[:=]",
        ]
        for pattern in disallowed_patterns:
            if re.search(pattern, cleaned, flags=re.IGNORECASE):
                return ""
        generic_prefixes = (
            "task completed",
            "task cancelled",
            "task canceled",
            "task acknowledged",
            "reminder acknowledged",
            "status:",
            "assistant:",
        )
        low = cleaned.lower()
        if low in generic_prefixes or any(low.startswith(f"{p}.") for p in generic_prefixes):
            return ""
        clipped_patterns = (
            r'^task\s+"[^"]+"\.?$',
            r'^task\s+(?:canceled|cancelled|completed)\s*:\s*.+$',
            r'^reminder\s+(?:set|saved|acknowledged)\s*[:.]?.*$',
            r'^task\s*:\s*.+$',
        )
        if any(re.match(p, cleaned, flags=re.IGNORECASE) for p in clipped_patterns):
            return ""
        if cleaned and cleaned[-1] not in ".!?":
            cleaned = f"{cleaned}."
        if not cleaned or len(cleaned) < 6:
            return ""
        alpha_count = len(re.findall(r"[A-Za-z]", cleaned))
        if alpha_count < 4:
            return ""
        return cleaned

    def _is_weak_task_ack_output(self, text: str):
        cleaned = re.sub(r"\s+", " ", (text or "").strip()).strip().lower()
        if not cleaned:
            return True
        weak_exact = {
            "ah, i see.",
            "i see.",
            "noted.",
            "understood.",
            "done.",
            "failed.",
            "failed",
        }
        if cleaned in weak_exact:
            return True
        weak_patterns = (
            r"^task\s*:\s*.+$",
            r"^task\s+[^.?!]+[.?!]?$",
            r"^reminder\s*:\s*.+$",
            r"^(okay|ok|sure)[.?!]?$",
        )
        return any(re.match(p, cleaned, flags=re.IGNORECASE) for p in weak_patterns)

    def _is_unhelpful_parse_failure_line(self, text: str):
        cleaned = re.sub(r"\s+", " ", (text or "").strip()).strip().lower()
        if not cleaned:
            return True
        if cleaned in {"failed.", "failed", "parse failed.", "could not parse."}:
            return True
        return len(cleaned.split()) < 5

    def _task_commentary_fallback_line(self, event_name: str, facts: dict, fallback: str):
        facts = facts if isinstance(facts, dict) else {}
        task_text = (facts.get("task_text") or "that item").strip()
        due = (facts.get("due") or "").strip()
        sync_status = (facts.get("google_sync_status") or "").strip().lower()
        mode = (facts.get("anchor_mode") or self._get_narrative_mode() or "connected").strip().lower()
        opener = {
            "connected": "Order restored.",
            "nearby": "Containment holds.",
            "absent": "Control is fragile, but intact.",
        }.get(mode, "Order restored.")
        if event_name == "task_created_final":
            due_clause = f" for {due}" if due else ""
            if sync_status == "synced":
                return f"{opener} I logged '{task_text}'{due_clause} and synced it to Calendar."
            if sync_status == "failed":
                return f"{opener} I logged '{task_text}'{due_clause}; Google sync failed, local reminder stands."
            return f"{opener} I logged '{task_text}'{due_clause}."
        if event_name == "task_completed":
            return f"{opener} '{task_text}' is completed."
        if event_name == "task_cancelled":
            return f"{opener} '{task_text}' is canceled."
        if event_name == "task_acknowledged":
            return f"{opener} Reminder acknowledged."
        if event_name == "task_parse_failed":
            return "Your request lacked a usable schedule; give me a clear time and I will lock it in."
        if event_name == "task_complete_not_found":
            return "No matching task survived inspection; specify the exact item and I will finish it."
        if event_name == "task_purge_completed":
            removed = facts.get("removed")
            if isinstance(removed, int):
                return f"{opener} Completed-task purge executed: {removed} removed."
        return fallback if (fallback or "").strip() else f"{opener} Task action confirmed."

    def _should_distill_memory(self, user_text: str, response: str):
        t = (user_text + "\n" + response).lower()
        strong = (
            "dream", "idea", "project", "remind me", "preference", "always", "never",
            "lsl", "python", "script", "error", "issue", "solution", "fixed", "resolved"
        )
        return any(s in t for s in strong) or len(user_text.split()) > 20

    def _on_response(self, response, user_text, user_msg_record, retrieved):
        self.log_diagnostic("Generation worker finished and response received.", level="INFO")
        response = (response or "").strip()
        self._append_chat("GRIMVEILE", response)
        self.history.append({"role": "assistant", "content": response})
        assistant_msg_record = self._store_message("assistant", response)
        self._pending_user_delay_commentary_minutes = None
        self._pending_user_delay_idle_thread_active = False

        tokens = len(response.split())
        self.token_count += tokens
        self.anchor_panel.feed(tokens)

        if self._should_distill_memory(user_text, response):
            memory = self.memory.append_memory(
                session_id=self.session_id,
                user_text=user_text,
                assistant_text=response,
                source_message_ids=[user_msg_record["id"], assistant_msg_record["id"]]
            )
            if memory is not None:
                self.state["total_memories"] = int(self.state.get("total_memories", 0)) + 1
                self.memory.save_state(self.state)

        self.face_locked = True
        if self.anchor_state < 0.45:
            self.face_widget.set_face("glitch")
            self._log_emotion("glitch")
        else:
            self.face_widget.set_face("victory")
            self._log_emotion("victory")

        QTimer.singleShot(5000, lambda: self._run_sentiment(response))

        self.send_btn.setEnabled(True)
        self.input_field.setEnabled(True)
        self.input_field.setFocus()

    def _insert_calendar_date(self, qdate):
        try:
            date_str = qdate.toString("MM/dd/yyyy")
        except Exception:
            try:
                date_str = str(qdate)
            except Exception:
                return

        existing = self.input_field.text()
        if existing and not existing.endswith(" "):
            existing += " "
        self.input_field.setText(f"{existing}{date_str}")
        self.input_field.setFocus()
        self.input_field.setCursorPosition(len(self.input_field.text()))

    def _run_sentiment(self, response):
        if self.model and self.tokenizer:
            self.sent_worker = SentimentWorker(self.model, self.tokenizer, response)
            self.sent_worker.face_ready.connect(self._on_sentiment)
            self.sent_worker.diagnostic.connect(self.log_diagnostic)
            self.sent_worker.start()

    def _on_sentiment(self, face_name):
        if self.anchor_state < 0.45 and face_name in ("neutral", "happy", "relieved", "reassured"):
            face_name = "panicked"
        self.face_locked = False
        self.face_widget.set_face(face_name)
        self._log_emotion(face_name)
        QTimer.singleShot(60000, self._return_to_baseline_face)

    def _return_to_baseline_face(self):
        if self.face_locked or self.status == "GENERATING":
            return
        self.face_widget.set_face(self._anchor_baseline_face())

    def _on_error(self, error):
        self.log_diagnostic(f"Generation worker error: {error}", level="ERROR")
        self._append_chat("ERROR", error)
        self.face_widget.set_face("panicked")
        self._log_emotion("panicked")
        self._set_status("ERROR")
        self.send_btn.setEnabled(True)
        self.input_field.setEnabled(True)

    def _try_create_task(self, text: str, force_intent: bool = False):
        self.log_diagnostic("Task action started.", level="INFO")
        classification = classify_task_intent(text)
        intent = classification.get("intent", "chat")
        cleaned_input = classification.get("cleaned_input") or normalize_persona_prefixed_input(text)
        self.log_diagnostic(f"Task intent classification: {intent}.", level="INFO")
        self.log_diagnostic(
            f"Task parse attempt started: \"{self._preview_text(cleaned_input, max_chars=160)}\"",
            level="DEBUG"
        )
        if not force_intent and intent not in {"timer", "reminder", "task"}:
            self.log_diagnostic("Task action skipped: non-task intent.", level="DEBUG")
            return None

        parsed = self._parse_reminder_command(cleaned_input, force_intent=True, intent=intent)
        if not parsed or not parsed.get("ok"):
            reason = (parsed or {}).get("reason") or "Could not confidently determine the requested schedule"
            self.log_diagnostic("Task action aborted: schedule parse failed.", level="WARN")
            self.log_diagnostic(f"Task parse failure reason: {reason}", level="DEBUG")
            self.log_diagnostic("Task interaction cycle complete.", level="INFO")
            return {
                "result": "parse_failed",
                "intent": intent,
                "reason": reason,
                "cleaned_input": cleaned_input,
            }

        task_text = parsed["task_text"]
        due_dt = normalize_datetime_for_compare(parsed["due_dt"], context="task_create_due_dt")
        schedule_type = parsed.get("schedule_type", "unknown")
        self.log_diagnostic(f"Task schedule type resolved: {schedule_type}.", level="INFO")
        self.log_diagnostic(f"Task final due datetime: {due_dt.isoformat(timespec='seconds')}.", level="INFO")

        task = self.memory.add_task(task_text, due_dt, text)
        reloaded = self.memory.load_tasks()
        if not any((t.get("id") == task.get("id")) for t in reloaded):
            self.log_diagnostic("Local task create failed verification check.", level="ERROR")
            self.log_diagnostic("Task interaction cycle complete.", level="INFO")
            return {
                "result": "local_create_failed",
                "intent": intent,
                "reason": "Local task create failed verification check",
            }
        self.log_diagnostic("Local task create succeeded.", level="INFO")
        self.log_diagnostic("Task parse attempt succeeded.", level="INFO")
        google_sync_result = self._push_task_to_google_calendar(task)
        self._refresh_task_registry_panel()
        return {
            "result": "created",
            "intent": intent,
            "schedule_type": schedule_type,
            "task": task,
            "local_created": True,
            "google_sync": google_sync_result,
        }

    def _push_task_to_google_calendar(self, task: dict):
        task_id = task.get("id")
        if not task_id:
            self.log_diagnostic("Google sync skipped: task missing local id.", level="WARN")
            return {"status": "not_attempted", "error": "missing_task_id"}
        self.log_diagnostic("Google sync started for task action.", level="INFO")
        self.log_diagnostic(f"Google Calendar push attempt for task_id={task_id}.", level="DEBUG")
        try:
            event_id, link_established = self.google_calendar.create_event_for_task(task)
            self.memory.update_task_google_sync(
                task_id=task_id,
                sync_status="synced",
                google_event_id=event_id,
                last_synced_at=local_now_iso(),
            )
            if link_established and not self._google_link_announced:
                self._google_link_announced = True
                self.log_diagnostic("Google Calendar auth/link established.", level="INFO")
            self.log_diagnostic("Google sync succeeded for task action.", level="INFO")
            self.log_diagnostic(
                f"Google Calendar push success for task_id={task_id}, event_id={event_id}.",
                level="DEBUG"
            )
            return {"status": "synced", "event_linked": bool(event_id)}
        except Exception as ex:
            raw_error = str(ex).strip() or ex.__class__.__name__
            lower_error = raw_error.lower()
            if ("missing google calendar python dependency" in lower_error
                    or "no module named" in lower_error
                    or "importerror" in lower_error):
                user_error = f"Missing dependency: {raw_error}"
            elif ("credential" in lower_error
                  or "oauth" in lower_error
                  or "auth" in lower_error
                  or "token" in lower_error):
                user_error = f"Auth/credentials failure: {raw_error}"
            elif "google api error" in lower_error:
                user_error = raw_error
            else:
                user_error = raw_error

            print(f"[GCal][ERROR] Google Calendar push failed for task_id={task_id}: {raw_error}")
            self.log_exception(f"Google Calendar push task_id={task_id}", ex)
            self.memory.update_task_google_sync(
                task_id=task_id,
                sync_status="error",
                last_synced_at=local_now_iso(),
                error_message=user_error,
            )
            self.log_diagnostic("Google sync failed for task action.", level="WARN")
            return {"status": "failed", "error": user_error}

    def _parse_reminder_command(self, text: str, force_intent: bool = False, intent: str = None):
        intent_info = classify_task_intent(text)
        resolved_intent = intent or intent_info.get("intent", "chat")
        cleaned_input = intent_info.get("cleaned_input") or normalize_persona_prefixed_input(text).strip()
        if not force_intent and resolved_intent not in {"timer", "reminder", "task"}:
            return {"ok": False, "reason": "No task/reminder/timer intent detected"}

        normalized = re.sub(r"\s+", " ", cleaned_input).strip(" ,.-")
        lead_prefix = (
            r"^\s*(?:"
            r"remind me"
            r"|set(?:\s+a)?\s+reminder"
            r"|add(?:\s+a)?\s+reminder"
            r"|set(?:\s+an?)?\s+alarm"
            r"|add(?:\s+an?)?\s+alarm"
            r"|alarm\s+for"
            r"|set(?:\s+a)?\s+timer"
            r"|start(?:\s+a)?\s+timer"
            r"|timer\s+for"
            r"|add(?:\s+a)?\s+task"
            r"|create(?:\s+a)?\s+task"
            r"|new\s+task"
            r")\b"
        )
        payload = re.sub(lead_prefix, "", normalized, flags=re.I).strip(" ,.-")
        if not payload:
            payload = normalized

        def clean_task_text(task_text: str):
            cleaned = (task_text or "").strip().rstrip(".!?")
            return cleaned if cleaned else ("Timer" if resolved_intent == "timer" else "Reminder")

        def normalize_task_tail(task_tail: str):
            tail = (task_tail or "").strip(" ,.-")
            tail = re.sub(r"^(?:to|that)\s+", "", tail, flags=re.I)
            return clean_task_text(tail)

        def build_due(year: int, month: int, day: int, hour: int, minute: int):
            local_tz = _local_tzinfo()
            return datetime(year, month, day, hour, minute, 0, 0, tzinfo=local_tz)

        def parse_clock(hour_s: str = "", minute_s: str = None, ampm_s: str = "", special_time: str = ""):
            special = (special_time or "").strip().lower()
            if special == "noon":
                return 12, 0
            if special == "midnight":
                return 0, 0
            if not str(hour_s).strip():
                return None
            hour = int(hour_s)
            minute = int(minute_s or 0)
            if minute < 0 or minute > 59:
                return None
            ampm = (ampm_s or "").lower()
            if ampm:
                if hour < 1 or hour > 12:
                    return None
                if hour == 12:
                    hour = 0
                if ampm == "pm":
                    hour += 12
            elif hour < 0 or hour > 23:
                return None
            return hour, minute

        def trailing_task_text(span_end: int):
            tail = (payload[span_end:] if span_end is not None else "").strip()
            tail = re.sub(r"^(?:to|that|about)\b[\s,.-]*", "", tail, flags=re.I).strip()
            tail = re.sub(r"^[,.\-:;]+\s*", "", tail).strip()
            return tail

        def looks_like_schedule_conflict(fragment: str):
            frag = re.sub(r"\s+", " ", (fragment or "").strip()).lower()
            if not frag:
                return False
            conflict_patterns = (
                r"^(?:at\s+)?(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|(?:[01]?\d|2[0-3]):[0-5]\d\b|noon\b|midnight\b)",
                r"^(?:on|for)\s+(?:\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b",
                r"^(?:tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
                r"^in\s+\d+\s*(?:d|day|days|h|hr|hour|hours|m|min|minute|minutes|s|sec|second|seconds)\b",
            )
            return any(re.search(p, frag, flags=re.I) for p in conflict_patterns)

        def finalize_schedule(due_dt, schedule_type: str, task_tail: str, schedule_span: str):
            tail = normalize_task_tail(task_tail or "")
            if task_tail and looks_like_schedule_conflict(task_tail):
                return {
                    "ok": False,
                    "reason": "Conflicting schedule signals detected before task title",
                    "cleaned_input": cleaned_input,
                }
            return {
                "ok": True,
                "task_text": tail,
                "due_dt": due_dt,
                "schedule_type": schedule_type,
                "schedule_span": (schedule_span or "").strip(),
                "cleaned_input": cleaned_input,
            }

        now_local = now_for_compare().replace(second=0, microsecond=0)

        # 1) Relative time expressions (deterministic).
        relative_patterns = [
            r"\bin\s+(?P<dur>(?:\d+\s*(?:d|day|days|h|hr|hour|hours|m|min|minute|minutes|s|sec|second|seconds)\s*)+)(?:\s+(?:from\s+now))?(?:\s+(?:to|,)\s+(?P<task>.+))?$",
            r"^(?P<dur>(?:\d+\s*(?:d|day|days|h|hr|hour|hours|m|min|minute|minutes|s|sec|second|seconds)\s*)+)\s+from\s+now(?:\s+(?P<task>.+))?$",
        ]
        for pattern in relative_patterns:
            m = re.search(pattern, payload, flags=re.I)
            if m:
                delta = parse_duration_phrase(m.group("dur") or "")
                if delta and delta.total_seconds() > 0:
                    schedule_span = payload[m.start():m.end()]
                    task_tail = m.groupdict().get("task") or trailing_task_text(m.end())
                    return finalize_schedule(now_local + delta, "relative", task_tail, schedule_span)

        # 2) Same-day clock times.
        same_day_match = re.search(
            r"(?:^|\b)(?:at\s+|for\s+)?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>am|pm)\b(?:\s*(?:to|,)?\s*(?P<task>.+))?$",
            payload,
            flags=re.I,
        )
        if same_day_match:
            parsed_clock = parse_clock(same_day_match.group("h"), same_day_match.group("m"), same_day_match.group("ampm"))
            if parsed_clock:
                hour, minute = parsed_clock
                due = now_local.replace(hour=hour, minute=minute)
                if due <= now_local:
                    due += timedelta(days=1)
                schedule_span = payload[same_day_match.start():same_day_match.end()]
                task_tail = same_day_match.group("task") or trailing_task_text(same_day_match.end())
                return finalize_schedule(due, "same_day_time", task_tail, schedule_span)

        # 3) Explicit date + time.
        tomorrow_match = re.search(
            r"^(?:for\s+)?tomorrow(?:\s+at)?\s+(?:(?P<special>noon|midnight)|(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>am|pm)?)\b",
            payload,
            re.I,
        )
        if tomorrow_match:
            parsed_clock = parse_clock(
                tomorrow_match.group("h"),
                tomorrow_match.group("m"),
                tomorrow_match.group("ampm"),
                tomorrow_match.group("special"),
            )
            if parsed_clock:
                hour, minute = parsed_clock
                tomorrow = now_local + timedelta(days=1)
                due = build_due(tomorrow.year, tomorrow.month, tomorrow.day, hour, minute)
                schedule_span = payload[tomorrow_match.start():tomorrow_match.end()]
                task_tail = trailing_task_text(tomorrow_match.end())
                return finalize_schedule(due, "explicit_date_time", task_tail, schedule_span)

        dt_match = re.search(
            r"^(?:on\s+|for\s+)?(?P<d>\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\s+at\s+(?:(?P<special>noon|midnight)|(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>am|pm)?)\b",
            payload,
            re.I,
        )
        if dt_match:
            date_token = dt_match.group("d")
            try:
                parsed_date = datetime.strptime(date_token, "%m/%d/%Y") if "/" in date_token else datetime.strptime(date_token, "%Y-%m-%d")
            except ValueError:
                parsed_date = None
            parsed_clock = parse_clock(
                dt_match.group("h"),
                dt_match.group("m"),
                dt_match.group("ampm"),
                dt_match.group("special"),
            )
            if parsed_date and parsed_clock:
                hour, minute = parsed_clock
                due = build_due(parsed_date.year, parsed_date.month, parsed_date.day, hour, minute)
                schedule_span = payload[dt_match.start():dt_match.end()]
                task_tail = trailing_task_text(dt_match.end())
                return finalize_schedule(due, "explicit_date_time", task_tail, schedule_span)

        weekday_match = re.search(
            r"^(?:for\s+|on\s+)?(?P<weekday>monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+at)?\s+(?:(?P<special>noon|midnight)|(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>am|pm)?)\b",
            payload,
            re.I,
        )
        if weekday_match:
            weekday_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            target_idx = weekday_names.index(weekday_match.group("weekday").lower())
            parsed_clock = parse_clock(
                weekday_match.group("h"),
                weekday_match.group("m"),
                weekday_match.group("ampm"),
                weekday_match.group("special"),
            )
            if parsed_clock:
                hour, minute = parsed_clock
                days_ahead = (target_idx - now_local.weekday()) % 7
                if days_ahead == 0:
                    candidate = now_local.replace(hour=hour, minute=minute)
                    if candidate <= now_local:
                        days_ahead = 7
                target_day = now_local + timedelta(days=days_ahead)
                due = build_due(target_day.year, target_day.month, target_day.day, hour, minute)
                schedule_span = payload[weekday_match.start():weekday_match.end()]
                task_tail = trailing_task_text(weekday_match.end())
                return finalize_schedule(due, "explicit_date_time", task_tail, schedule_span)

        # 4) Fallback fuzzy parsing (confidence gated).
        fuzzy = re.search(
            r"^(?P<h>\d{1,2})(?::(?P<m>\d{2}))?(?:\s*(?P<ampm>am|pm))?\s+(?P<task>.+)$",
            payload,
            flags=re.I,
        )
        if fuzzy:
            parsed_clock = parse_clock(fuzzy.group("h"), fuzzy.group("m"), fuzzy.group("ampm"))
            if parsed_clock:
                hour, minute = parsed_clock
                due = now_local.replace(hour=hour, minute=minute)
                if due <= now_local:
                    due += timedelta(days=1)
                return {
                    "ok": True,
                    "task_text": normalize_task_tail(fuzzy.group("task")),
                    "due_dt": due,
                    "schedule_type": "fallback_fuzzy",
                    "cleaned_input": cleaned_input,
                }

        return {
            "ok": False,
            "reason": "Could not confidently determine the requested schedule",
            "cleaned_input": cleaned_input,
        }

    def _google_event_due_datetime(self, event: dict):
        start = (event or {}).get("start") or {}
        date_time = start.get("dateTime")
        if date_time:
            parsed = parse_iso_for_compare(date_time, context="google_event_dateTime")
            if parsed:
                return parsed
        date_only = start.get("date")
        if date_only:
            parsed = parse_iso_for_compare(f"{date_only}T09:00:00", context="google_event_date")
            if parsed:
                return parsed
        return None

    def _poll_google_calendar_inbound_sync(self):
        self.log_diagnostic("Google inbound sync poll started.", level="INFO")
        try:
            now_utc = datetime.utcnow().replace(microsecond=0)
            time_min = (now_utc - timedelta(days=GOOGLE_INBOUND_LOOKBACK_DAYS)).isoformat() + "Z"
            remote_events = self.google_calendar.list_primary_events(time_min=time_min, max_results=2500)
            self.log_diagnostic(
                f"Google inbound sync fetched {len(remote_events)} event(s) from primary calendar.",
                level="INFO"
            )

            tasks = self.memory.load_tasks()
            tasks_by_event_id = {}
            for task in tasks:
                event_id = (task.get("google_event_id") or "").strip()
                if event_id:
                    tasks_by_event_id[event_id] = task

            remote_by_id = {}
            for event in remote_events:
                event_id = (event.get("id") or "").strip()
                if event_id:
                    remote_by_id[event_id] = event

            updated_count = 0
            removed_count = 0
            imported_count = 0
            updated_ids = []
            removed_ids = []
            imported_ids = []
            changed = False
            now_iso = local_now_iso()

            for task in tasks:
                event_id = (task.get("google_event_id") or "").strip()
                if not event_id:
                    continue
                status = (task.get("status") or "pending").lower()
                if status in {"completed", "cancelled"}:
                    continue

                remote_event = remote_by_id.get(event_id)
                if remote_event is None:
                    remote_event = self.google_calendar.get_event(event_id)
                    if remote_event is not None:
                        remote_by_id[event_id] = remote_event

                if remote_event is None:
                    task["status"] = "cancelled"
                    task["acknowledged_at"] = task.get("acknowledged_at") or now_iso
                    task["cancelled_at"] = now_iso
                    task["sync_status"] = "deleted_remote"
                    task["last_synced_at"] = now_iso
                    task.setdefault("metadata", {})
                    task["metadata"]["google_deleted_remote"] = now_iso
                    removed_count += 1
                    removed_ids.append(task.get("id", "unknown"))
                    changed = True
                    continue

                remote_summary = (remote_event.get("summary") or "Reminder").strip() or "Reminder"
                remote_due = self._google_event_due_datetime(remote_event)
                remote_due_iso = remote_due.isoformat(timespec="seconds") if remote_due else None
                current_due = task.get("due_at") or task.get("due")
                current_due_dt = parse_iso_for_compare(current_due, context="google_inbound_current_due")
                task_changed = False
                if (task.get("text") or "").strip() != remote_summary:
                    task["text"] = remote_summary
                    task_changed = True
                if remote_due_iso and (current_due_dt is None or current_due_dt != remote_due):
                    task["due_at"] = remote_due_iso
                    task["pre_trigger"] = (remote_due - timedelta(minutes=1)).isoformat(timespec="seconds")
                    task_changed = True
                if task.get("sync_status") != "synced":
                    task["sync_status"] = "synced"
                    task_changed = True
                if task_changed:
                    task["last_synced_at"] = now_iso
                    updated_count += 1
                    updated_ids.append(task.get("id", "unknown"))
                    changed = True

            for event_id, event in remote_by_id.items():
                if event_id in tasks_by_event_id:
                    continue
                due_at = self._google_event_due_datetime(event)
                if not due_at:
                    continue
                summary = (event.get("summary") or "Google Calendar Event").strip() or "Google Calendar Event"
                imported_task = {
                    "id": f"task_{uuid.uuid4().hex[:10]}",
                    "created_at": now_iso,
                    "due_at": due_at.isoformat(timespec="seconds"),
                    "pre_trigger": (due_at - timedelta(minutes=1)).isoformat(timespec="seconds"),
                    "text": summary,
                    "status": "pending",
                    "acknowledged_at": None,
                    "retry_count": 0,
                    "last_triggered_at": None,
                    "next_retry_at": None,
                    "source": "google",
                    "google_event_id": event_id,
                    "sync_status": "synced",
                    "last_synced_at": now_iso,
                    "metadata": {
                        "google_imported_at": now_iso,
                        "google_updated": event.get("updated"),
                    },
                }
                tasks.append(imported_task)
                tasks_by_event_id[event_id] = imported_task
                imported_count += 1
                imported_ids.append(imported_task["id"])
                changed = True

            if changed:
                self.memory.save_all_tasks(tasks)
                self._refresh_task_registry_panel()

            self.log_diagnostic(
                "Google inbound sync reconciliation complete: "
                f"updated={updated_count}, removed_missing_remote={removed_count}, imported_new={imported_count}.",
                level="INFO"
            )
            if imported_ids:
                self.log_diagnostic(f"Google inbound imported task ids: {', '.join(imported_ids)}.", level="INFO")
            if updated_ids:
                self.log_diagnostic(f"Google inbound updated task ids: {', '.join(updated_ids)}.", level="INFO")
            if removed_ids:
                self.log_diagnostic(f"Google inbound remote-delete deactivated task ids: {', '.join(removed_ids)}.", level="INFO")
            if imported_count > 0:
                self._append_chat(
                    "SYSTEM",
                    f"Google Calendar update detected. Importing {imported_count} new external event"
                    f"{'' if imported_count == 1 else 's'}."
                )
        except Exception as ex:
            self.log_exception("Google inbound sync poll", ex)

    def _check_due_tasks(self):
        try:
            events = self.memory.get_due_events()
            for kind, task in events:
                if kind == "pre":
                    self._emit_ai_task_commentary(
                        event_name="task_pre_trigger",
                        facts={"task_text": task.get("text", ""), "task_id": task.get("id", "")},
                        fallback=f"Reminder pre-trigger armed for: {task['text']}"
                    )
                elif kind == "retry_scheduled":
                    self._emit_ai_task_commentary(
                        event_name="task_retry_scheduled",
                        facts={"task_text": task.get("text", ""), "task_id": task.get("id", "")},
                        fallback=f"Reminder unacknowledged. Retry scheduled in 12 minutes: {task['text']}"
                    )
                elif kind == "due":
                    play_grimveil_alert(MEMORY_DIR)
                    due_dt = parse_iso(task.get("due_at") or task.get("due"))
                    due_str = due_dt.strftime("%m/%d/%Y %I:%M %p") if due_dt else "scheduled time"
                    self._emit_ai_task_commentary(
                        event_name="task_due",
                        facts={"task_text": task.get("text", ""), "task_id": task.get("id", ""), "due": due_str},
                        fallback=f"[Reminder] You wanted an alarm for {due_str}: {task['text']}"
                    )
                    self.active_reminder_ids.add(task["id"])
            self._refresh_task_registry_panel()
        except Exception as ex:
            self.log_exception("Due task timer handler", ex)

    def _update_stats(self):
        elapsed = int(time.time() - self.session_start)
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        self.lbl_session.setText(f"✦ SESSION: {h:02d}:{m:02d}:{s:02d}")
        self.lbl_tokens.setText(f"✦ TOKENS: {self.token_count}")
        self._refresh_anchor_ui()
        self._refresh_task_registry_if_changed()

        if PSUTIL_OK:
            mem = psutil.virtual_memory()
            ram_used = mem.used / 1024**3
            ram_total = mem.total / 1024**3
            self.gauge_ram.setValue(ram_used, f"{ram_used:.1f}/{ram_total:.0f}GB")
            cpu = psutil.cpu_percent()
            self.gauge_cpu.setValue(cpu, f"{cpu:.0f}%")
        else:
            ram_used, ram_total = 20.0, 64.0

        if NVML_OK and gpu_handle:
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(gpu_handle)
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(gpu_handle)
                temp = pynvml.nvmlDeviceGetTemperature(gpu_handle, pynvml.NVML_TEMPERATURE_GPU)
                gpu_pct = util.gpu
                vram_used = mem_info.used / 1024**3
                vram_total = mem_info.total / 1024**3
                self.gauge_gpu.setValue(gpu_pct, f"{gpu_pct}%")
                self.gauge_gpu_master.setValue(gpu_pct, f"RTX 4070  {gpu_pct}%  [{vram_used:.1f}/{vram_total:.0f}GB VRAM]")
                self.gauge_vram.setValue(vram_used, f"{vram_used:.1f}/{vram_total:.0f}GB")
                self.gauge_temp.setValue(temp, f"{temp}°C")

                if not self.face_locked and self.status == "GENERATING":
                    if self.anchor_state < 0.45:
                        self.face_widget.set_face("suspicious")
                    elif gpu_pct >= 60:
                        self.face_widget.set_face("focused")
                    elif gpu_pct >= 20:
                        self.face_widget.set_face("alert")
            except Exception:
                vram_used, vram_total, temp = 4.0, 8.0, 45
        else:
            vram_used, vram_total, temp = 4.0, 8.0, 45

        try:
            elapsed_seconds = time.time() - self.session_start
            if PSUTIL_OK:
                mem = psutil.virtual_memory()
                ru = mem.used / 1024**3
                rt = mem.total / 1024**3
            else:
                ru, rt = 20.0, 64.0
            self.anchor_panel.update_stats(self.anchor_state, temp, vram_used, vram_total, ru, rt, elapsed_seconds)
        except Exception:
            pass

    def _blink(self):
        self.blink_state = not self.blink_state
        if self.status == "GENERATING":
            char = "◉" if self.blink_state else "◎"
            self.status_label.setText(f"{char} GENERATING")

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.fs_btn.setStyleSheet(f"background: {C_BG3}; color: {C_CYAN_DIM}; border: 1px solid {C_CYAN_DIM}; font-size: 9px; font-weight: bold; padding: 0px; letter-spacing: 1px;")
        else:
            self.showFullScreen()
            self.fs_btn.setStyleSheet(f"background: {C_CYAN_DIM}; color: {C_CYAN}; border: 1px solid {C_CYAN}; font-size: 9px; font-weight: bold; padding: 0px; letter-spacing: 1px;")

    def _toggle_borderless(self):
        is_borderless = bool(self.windowFlags() & Qt.WindowType.FramelessWindowHint)
        if is_borderless:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.FramelessWindowHint)
            self.bl_btn.setStyleSheet(f"background: {C_BG3}; color: {C_CYAN_DIM}; border: 1px solid {C_CYAN_DIM}; font-size: 9px; font-weight: bold; padding: 0px; letter-spacing: 1px;")
        else:
            if self.isFullScreen():
                self.showNormal()
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
            self.bl_btn.setStyleSheet(f"background: {C_CYAN_DIM}; color: {C_CYAN}; border: 1px solid {C_CYAN}; font-size: 9px; font-weight: bold; padding: 0px; letter-spacing: 1px;")
        self.show()

    def keyPressEvent(self, event):
        from PyQt6.QtCore import Qt as _Qt
        key = event.key()
        if key == _Qt.Key.Key_F11:
            self._toggle_fullscreen()
        elif key == _Qt.Key.Key_F10:
            self._toggle_borderless()
        elif key == _Qt.Key.Key_Escape:
            if self.isFullScreen():
                self.showNormal()
                self.fs_btn.setStyleSheet(f"background: {C_BG3}; color: {C_CYAN_DIM}; border: 1px solid {C_CYAN_DIM}; font-size: 9px; font-weight: bold; padding: 0px; letter-spacing: 1px;")
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        try:
            self.state = self.memory.load_state()
            self.state["last_shutdown"] = local_now_iso()
            self.state["last_active"] = local_now_iso()
            self.state["anchor_state"] = self.anchor_state
            self.state["internal_narrative"] = self.narrative
            self.state["version"] = APP_VERSION
            self.memory.save_state(self.state)
        except Exception:
            pass
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(f"{APP_NAME} v{APP_VERSION}")
    window = GrimveilDeck()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
