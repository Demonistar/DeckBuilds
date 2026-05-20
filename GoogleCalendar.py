from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════════
# GOOGLE CALENDAR — Echo Deck Module  (built from scratch)
# Key          : google_calendar
# Display Name : Google Calendar
# Version      : 2.0.0
# Category     : Google
#
# Auth: shared token.json in google/ dir — same as gmail.py
#   First run asks for google_credentials.json via file browser.
#   Subsequent runs use token.json silently.
#
# Module tab (right panel):
#   - Auth / connect
#   - Mini calendar navigator (QCalendarWidget)
#   - Calendar list with visibility toggles + colour dots
#   - Upcoming events list (next 7 days)
#   - Task list with due-date indicators
#   - Sync status + manual sync
#   - Ask AI about schedule
#
# Workspace slot 1  — label "Calendar"
#   Week grid (QPainter) with ribbon:
#     Today / ◀ / ▶ / view switcher (Day · Week · Month · Agenda)
#   Clicking an event → detail popup
#   Clicking empty slot → quick-add dialog
#
# Workspace slot 2  — label "Tasks"
#   Task columns — one column per task list, checkbox completion
#
# Architecture rules (same as GoogleCalendar v3):
#   - NO QThread creation
#   - Sync runs via main-thread QTimer
#   - AI dispatch → ai_queue.db directly
#   - Scopes cover Calendar + Tasks
# ═══════════════════════════════════════════════════════════════════════════════

import json
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QDate, QRect, Qt, QTimer, Signal, QObject
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

# ─── Manifest ─────────────────────────────────────────────────────────────────

MODULE_MANIFEST = {
    "key": "GoogleCalendar",
    "display_name": "Google Calendar",
    "description": "Google Calendar + Tasks — week view, task columns, AI schedule briefings.",
    "version": "2.0.0",
    "deck_api_version": "1.0",
    "home_category": "Google",
    "secondary_categories": [],
    "entry_function": "register",
    "tab_definitions": [
        {"tab_id": "google_calendar_main", "tab_name": "Google Calendar"},
    ],
}

MODULE_KEY = "GoogleCalendar"

# Combined scopes — shared token.json covers all Google modules
# Same list used by GoogleMail so one token.json works for all
REQUIRED_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]

DEFAULT_SYNC_MS = 5 * 60 * 1000   # 5 minutes
REMINDER_TICK_MS = 60 * 1000       # 1 minute

# ─── Data Models ──────────────────────────────────────────────────────────────

class CalendarRecord:
    def __init__(self, cal_id, name, bg_color, fg_color, visible=True, section="My calendars"):
        self.cal_id    = cal_id
        self.name      = name
        self.bg_color  = bg_color
        self.fg_color  = fg_color
        self.visible   = visible
        self.section   = section

class EventRecord:
    def __init__(self, event_id, cal_id, cal_name, summary, description,
                 location, start_dt, end_dt, all_day, status,
                 bg_color="#4285F4", fg_color="#FFFFFF",
                 reminder_overrides=None, attendees=None, html_link=""):
        self.event_id   = event_id
        self.cal_id     = cal_id
        self.cal_name   = cal_name
        self.summary    = summary
        self.description = description
        self.location   = location
        self.start_dt   = start_dt
        self.end_dt     = end_dt
        self.all_day    = all_day
        self.status     = status
        self.bg_color   = bg_color
        self.fg_color   = fg_color
        self.reminder_overrides = list(reminder_overrides or [])
        self.attendees  = list(attendees or [])
        self.html_link  = html_link

class TaskRecord:
    def __init__(self, task_id, list_id, list_name, title, notes, due_date, status):
        self.task_id   = task_id
        self.list_id   = list_id
        self.list_name = list_name
        self.title     = title
        self.notes     = notes
        self.due_date  = due_date
        self.status    = status

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_dt(value: Optional[str]) -> tuple[datetime, bool]:
    """Parse Google datetime string exactly as returned. No conversion.
    The API returns times with the correct local offset already embedded."""
    if not value:
        return datetime.now(UTC), False
    if "T" not in value:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC), True
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value), False

def _parse_task_due(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    if "T" in value:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    return datetime.strptime(value, "%Y-%m-%d").date()

def _fmt_dt(dt: datetime, all_day=False) -> str:
    if all_day:
        return dt.date().isoformat()
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")

def _sunday(d: Optional[date] = None) -> date:
    d = d or datetime.now().astimezone().date()
    return d - timedelta(days=d.weekday() + 1) if d.weekday() != 6 else d

# ─── Runtime ──────────────────────────────────────────────────────────────────

class GoogleCalendarRuntime(QObject):
    data_changed = Signal()

    def __init__(self, deck_api: dict[str, Any]):
        super().__init__()
        self.deck_api = deck_api
        self.log: Callable = (
            deck_api.get("log") if callable(deck_api.get("log")) else lambda m: None
        )
        self.diag: Callable = (
            deck_api.get("diagnostics_log")
            if callable(deck_api.get("diagnostics_log"))
            else lambda m, lvl="INFO": self.log(f"[{lvl}] {m}")
        )
        self.cfg_get: Callable = (
            deck_api.get("cfg_get") if callable(deck_api.get("cfg_get")) else lambda k, d=None: d
        )

        self._google_dir = self._resolve_google_dir()
        self._ai_queue_path = self._resolve_ai_queue_path()
        self._cal_service = None
        self._tasks_service = None

        self.auth_status = "pending_setup"
        self.calendars:  dict[str, CalendarRecord] = {}
        self.events:     dict[str, EventRecord]    = {}
        self.tasks:      dict[str, TaskRecord]     = {}
        self.sync_tokens: dict[str, str]           = {}
        self.last_synced_at: Optional[datetime]    = None

        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._on_sync_tick)
        self._reminder_timer = QTimer(self)
        self._reminder_timer.timeout.connect(self._check_reminders)

        self._init_auth()
        self._try_attach()
        self.diag("[GoogleCalendar] Runtime ready.")

    # ── Paths ──────────────────────────────────────────────────────────────

    def _resolve_google_dir(self) -> Optional[Path]:
        cfg_path = self.deck_api.get("cfg_path")
        if callable(cfg_path):
            try:
                p = Path(str(cfg_path("google")))
                p.mkdir(parents=True, exist_ok=True)
                return p
            except Exception:
                pass
        deck_home = self.deck_api.get("deck_home")
        if deck_home:
            p = Path(str(deck_home)) / "google"
            p.mkdir(parents=True, exist_ok=True)
            return p
        return None

    def _resolve_ai_queue_path(self) -> Optional[Path]:
        cfg_path = self.deck_api.get("cfg_path")
        if callable(cfg_path):
            try:
                p = Path(str(cfg_path("memories"))) / "ai_queue.db"
                if p.exists():
                    return p
            except Exception:
                pass
        deck_home = self.deck_api.get("deck_home")
        if deck_home:
            p = Path(str(deck_home)) / "memories" / "ai_queue.db"
            if p.exists():
                return p
        return None

    def _gfile(self, name: str) -> Optional[Path]:
        return (self._google_dir / name) if self._google_dir else None

    # ── Auth ───────────────────────────────────────────────────────────────

    def _init_auth(self) -> None:
        token = self._gfile("token.json")
        if not token or not token.exists():
            self.auth_status = "pending_setup"
            return
        try:
            data = json.loads(token.read_text(encoding="utf-8"))
            scopes = set(data.get("scopes") or data.get("scope", "").split())
            # Accept token if it has calendar OR gmail scopes (shared token)
            has_google = any(("calendar" in s or "gmail" in s or "tasks" in s) for s in scopes)
            tok = data.get("token") or data.get("access_token")
            if not tok and not data.get("refresh_token"):
                self.auth_status = "pending_setup"
            elif not has_google:
                self.auth_status = "reauth_required"
            else:
                self.auth_status = "ready"
        except Exception as ex:
            self.auth_status = "pending_setup"
            self.diag(f"[GoogleCalendar] token.json parse failed: {ex}", "WARN")

    def _try_attach(self) -> None:
        if self.auth_status != "ready":
            return
        try:
            from google.auth.transport.requests import Request as GRequest
            from google.oauth2.credentials import Credentials as GCreds
            from googleapiclient.discovery import build as gbuild
            token = self._gfile("token.json")
            if not token or not token.exists():
                return
            creds = GCreds.from_authorized_user_file(str(token), REQUIRED_SCOPES)
            if creds.expired and creds.refresh_token:
                creds.refresh(GRequest())
                token.write_text(creds.to_json(), encoding="utf-8")
            self._cal_service   = gbuild("calendar", "v3", credentials=creds)
            self._tasks_service = gbuild("tasks",    "v1", credentials=creds)
            self.diag("[GoogleCalendar] Services attached.")
        except Exception as ex:
            self.diag(f"[GoogleCalendar] Attach failed: {ex}", "WARN")
            self._cal_service = self._tasks_service = None

    def run_oauth_flow(self, creds_path: str) -> bool:
        import shutil
        src = Path(creds_path)
        if not src.exists():
            self.diag(f"[GoogleCalendar] Creds not found: {src}", "ERROR")
            return False
        dest  = self._gfile("google_credentials.json")
        token = self._gfile("token.json")
        if not dest or not token:
            return False
        try:
            if src.resolve() != dest.resolve():
                shutil.copy2(str(src), str(dest))
        except Exception as ex:
            self.diag(f"[GoogleCalendar] Copy failed: {ex}", "ERROR")
            return False
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow  = InstalledAppFlow.from_client_secrets_file(str(dest), REQUIRED_SCOPES)
            creds = flow.run_local_server(
                port=0, open_browser=True,
                authorization_prompt_message="Authorize Google Calendar: {url}",
                success_message="Authorization complete. You may close this window.",
            )
            if not creds:
                return False
            token.write_text(creds.to_json(), encoding="utf-8")
            self.auth_status = "ready"
            self._try_attach()
            self.diag("[GoogleCalendar] OAuth complete.")
            return True
        except Exception as ex:
            self.diag(f"[GoogleCalendar] OAuth failed: {ex}", "ERROR")
            return False

    # ── Sync ───────────────────────────────────────────────────────────────

    def start_sync(self, _=None) -> None:
        if not self._sync_timer.isActive():
            self._sync_timer.start(DEFAULT_SYNC_MS)
            self._reminder_timer.start(REMINDER_TICK_MS)
        # Defer first sync so workspace renders before blocking network call
        QTimer.singleShot(500, self.trigger_sync_now)

    def stop_sync(self, _=None) -> None:
        self._sync_timer.stop()
        self._reminder_timer.stop()
        try:
            self.data_changed.disconnect()
        except Exception:
            pass

    def trigger_sync_now(self) -> None:
        self._on_sync_tick()

    def _on_sync_tick(self) -> None:
        if not self._cal_service or not self._tasks_service:
            return
        try:
            self._sync_calendars()
            self._sync_tasks()
            self.last_synced_at = datetime.now().astimezone()
            self.diag(f"[GoogleCalendar] Sync OK. {len(self.events)} events, {len(self.tasks)} tasks.")
            self.data_changed.emit()
        except Exception as ex:
            self.diag(f"[GoogleCalendar] Sync error: {ex}", "WARN")

    def _sync_calendars(self) -> None:
        page_token = None
        while True:
            res = self._cal_service.calendarList().list(pageToken=page_token).execute()
            for item in res.get("items", []):
                cal_id = item.get("id", "")
                section = "My calendars"
                if item.get("accessRole") in {"reader", "freeBusyReader"}:
                    section = "Other calendars"
                rec = CalendarRecord(
                    cal_id=cal_id,
                    name=item.get("summary", "Untitled"),
                    bg_color=item.get("backgroundColor", "#4285F4"),
                    fg_color=item.get("foregroundColor", "#FFFFFF"),
                    visible=bool(item.get("selected", True)),
                    section=section,
                )
                self.calendars[cal_id] = rec
                # Sync events for this calendar
                if rec.visible:
                    tok = self.sync_tokens.get(cal_id)
                    if tok:
                        ok = self._sync_cal_incremental(cal_id, tok)
                        if not ok:
                            self._sync_cal_full(cal_id)
                    else:
                        self._sync_cal_full(cal_id)
            page_token = res.get("nextPageToken")
            if not page_token:
                break

    def _sync_cal_full(self, cal_id: str) -> None:
        time_min = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
        page_token = None
        next_sync = None
        while True:
            res = self._cal_service.events().list(
                calendarId=cal_id, pageToken=page_token,
                singleEvents=True, showDeleted=True, timeMin=time_min,
            ).execute()
            for item in res.get("items", []):
                self._reconcile_event(cal_id, item)
            page_token = res.get("nextPageToken")
            next_sync  = res.get("nextSyncToken") or next_sync
            if not page_token:
                break
        if next_sync:
            self.sync_tokens[cal_id] = next_sync

    def _sync_cal_incremental(self, cal_id: str, sync_token: str) -> bool:
        try:
            page_token = None
            next_sync  = None
            while True:
                res = self._cal_service.events().list(
                    calendarId=cal_id, pageToken=page_token,
                    singleEvents=True, showDeleted=True, syncToken=sync_token,
                ).execute()
                for item in res.get("items", []):
                    self._reconcile_event(cal_id, item)
                page_token = res.get("nextPageToken")
                next_sync  = res.get("nextSyncToken") or next_sync
                if not page_token:
                    break
            if next_sync:
                self.sync_tokens[cal_id] = next_sync
            return True
        except Exception:
            return False

    def _reconcile_event(self, cal_id: str, item: dict) -> None:
        eid = item.get("id", "")
        if not eid:
            return
        if item.get("status") == "cancelled":
            self.events.pop(eid, None)
            return
        start_obj = item.get("start", {})
        end_obj   = item.get("end",   {})
        start_dt, all_day_s = _parse_dt(start_obj.get("dateTime") or start_obj.get("date"))
        end_dt,   all_day_e = _parse_dt(end_obj.get("dateTime")   or end_obj.get("date"))
        cal = self.calendars.get(cal_id)
        self.events[eid] = EventRecord(
            event_id=eid,
            cal_id=cal_id,
            cal_name=cal.name if cal else cal_id,
            summary=item.get("summary", "Untitled"),
            description=item.get("description", ""),
            location=item.get("location", ""),
            start_dt=start_dt,
            end_dt=end_dt,
            all_day=all_day_s or all_day_e,
            status=item.get("status", "confirmed"),
            bg_color=cal.bg_color if cal else "#4285F4",
            fg_color=cal.fg_color if cal else "#FFFFFF",
            reminder_overrides=item.get("reminders", {}).get("overrides", []),
            attendees=item.get("attendees", []),
            html_link=item.get("htmlLink", ""),
        )

    def _sync_tasks(self) -> None:
        lists = self._tasks_service.tasklists().list().execute().get("items", [])
        for tl in lists:
            lid  = tl.get("id", "")
            name = tl.get("title", "Tasks")
            for t in self._tasks_service.tasks().list(
                tasklist=lid, showCompleted=False, showDeleted=False
            ).execute().get("items", []):
                tid = t.get("id", "")
                if not tid:
                    continue
                self.tasks[tid] = TaskRecord(
                    task_id=tid, list_id=lid, list_name=name,
                    title=t.get("title", "Untitled"),
                    notes=t.get("notes", ""),
                    due_date=_parse_task_due(t.get("due")),
                    status=t.get("status", "needsAction"),
                )

    # ── Accessors ──────────────────────────────────────────────────────────

    def visible_events(self) -> list[EventRecord]:
        now = datetime.now().astimezone()
        visible_cals = {cid for cid, c in self.calendars.items() if c.visible}
        return [
            e for e in self.events.values()
            if e.cal_id in visible_cals
            and e.status != "cancelled"
            and e.end_dt >= now
        ]

    def events_for_week(self, anchor: date) -> list[EventRecord]:
        end = anchor + timedelta(days=7)
        return [e for e in self.visible_events()
                if anchor <= e.start_dt.date() < end]

    def events_for_day(self, d: date) -> list[EventRecord]:
        return [e for e in self.visible_events() if e.start_dt.astimezone().date() == d]

    def events_for_month(self, year: int, month: int) -> list[EventRecord]:
        return [e for e in self.visible_events()
                if e.start_dt.year == year and e.start_dt.month == month]

    def upcoming_events(self, days=7) -> list[EventRecord]:
        now = datetime.now().astimezone()
        edge = now + timedelta(days=days)
        return sorted(
            [e for e in self.visible_events() if now <= e.start_dt <= edge],
            key=lambda e: e.start_dt
        )

    def active_tasks(self) -> list[TaskRecord]:
        return [t for t in self.tasks.values() if t.status != "completed"]

    # ── Event CRUD ─────────────────────────────────────────────────────────

    def create_event(self, cal_id: str, summary: str, start_dt: datetime,
                     end_dt: datetime, description: str = "") -> bool:
        if not self._cal_service:
            return False
        try:
            body = {
                "summary": summary,
                "description": description,
                "start": {"dateTime": start_dt.astimezone().isoformat()},
                "end":   {"dateTime": end_dt.astimezone().isoformat()},
            }
            self._cal_service.events().insert(calendarId=cal_id, body=body).execute()
            self.diag(f"[GoogleCalendar] Event created: {summary}")
            QTimer.singleShot(500, self.trigger_sync_now)
            return True
        except Exception as ex:
            self.diag(f"[GoogleCalendar] Create event failed: {ex}", "WARN")
            return False

    def delete_event(self, cal_id: str, event_id: str) -> bool:
        if not self._cal_service:
            return False
        try:
            self._cal_service.events().delete(calendarId=cal_id, eventId=event_id).execute()
            self.events.pop(event_id, None)
            self.data_changed.emit()
            return True
        except Exception as ex:
            self.diag(f"[GoogleCalendar] Delete event failed: {ex}", "WARN")
            return False

    # ── Reminders ──────────────────────────────────────────────────────────

    def _check_reminders(self) -> None:
        now = datetime.now().astimezone()
        for e in self.visible_events():
            for override in e.reminder_overrides:
                mins = int(override.get("minutes", 0))
                trigger = e.start_dt - timedelta(minutes=mins)
                if trigger <= now <= trigger + timedelta(minutes=1):
                    self._queue_ai(
                        "GoogleCalendar",
                        f"Reminder: {e.summary}",
                        f"You have '{e.summary}' in {mins} minutes "
                        f"({e.start_dt.strftime('%H:%M')}). "
                        f"Respond in your persona voice. Under 40 words.",
                        priority="high",
                    )
                    break

    # ── AI queue ───────────────────────────────────────────────────────────

    def _queue_ai(self, source: str, title: str, prompt: str,
                  priority: str = "normal") -> bool:
        if not self._ai_queue_path:
            self._ai_queue_path = self._resolve_ai_queue_path()
        if not self._ai_queue_path or not self._ai_queue_path.exists():
            return False
        try:
            con = sqlite3.connect(str(self._ai_queue_path))
            con.execute(
                "INSERT INTO ai_queue (source,title,prompt,type,priority,"
                "expires_at,expiry_type,escalation_prompt,intent_key,context_data,created_at,status) "
                "VALUES (?,?,?,'visible',?,NULL,'soft',NULL,NULL,NULL,?,'pending')",
                (source, title, prompt, priority, datetime.now().isoformat())
            )
            con.commit()
            con.close()
            return True
        except Exception as ex:
            self.diag(f"[GoogleCalendar] AI queue failed: {ex}", "WARN")
            return False

    def send_upcoming_to_ai(self, days: int = 7) -> bool:
        events = self.upcoming_events(days)
        if not events:
            return False
        lines = "\n".join(
            f"• {e.summary} — {_fmt_dt(e.start_dt, e.all_day)} ({e.cal_name})"
            for e in events[:15]
        )
        return self._queue_ai(
            "GoogleCalendar",
            f"Schedule — next {days} days",
            f"Here are the user's upcoming calendar events for the next {days} days:\n{lines}\n\n"
            f"Respond in your persona voice with a brief useful summary. "
            f"Note anything time-sensitive. Under 80 words.",
        )

    def check_task_due_dates(self) -> None:
        today = datetime.now().astimezone().date()
        tomorrow = today + timedelta(days=1)
        all_t = self.active_tasks()
        def _lines(tasks):
            return "\n".join(f"• {t.title}" for t in tasks)
        due_today = [t for t in all_t if t.due_date == today]
        if due_today:
            self._queue_ai("GoogleCalendar", "Tasks due today",
                f"Tasks due today:\n{_lines(due_today)}\nRespond in persona. Under 60 words.",
                priority="high")
        overdue = [t for t in all_t
                   if t.due_date and timedelta(days=1) <= (today - t.due_date) <= timedelta(days=30)]
        if overdue:
            self._queue_ai("GoogleCalendar", "Overdue tasks",
                f"Overdue tasks:\n{_lines(overdue)}\nFlag these clearly. Under 60 words.",
                priority="high")
        critical = [t for t in all_t if t.due_date and (today - t.due_date) > timedelta(days=30)]
        if critical:
            self._queue_ai("GoogleCalendar", "Critically overdue tasks",
                f"These tasks are 30+ days overdue:\n{_lines(critical)}\n"
                f"Tell the user directly. Under 80 words.", priority="critical")


# ─── Quick-Add Event Dialog ────────────────────────────────────────────────────

class QuickAddDialog(QDialog):
    def __init__(self, runtime: GoogleCalendarRuntime,
                 start_dt: Optional[datetime] = None, parent=None):
        super().__init__(parent)
        self.runtime = runtime
        self.setWindowTitle("New Event")
        self.setMinimumWidth(380)
        self._build(start_dt or datetime.now().astimezone().replace(minute=0, second=0, microsecond=0))

    def _build(self, start_dt: datetime):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._title = QLineEdit()
        self._title.setPlaceholderText("Event title")
        form.addRow("Title:", self._title)

        # Calendar selector
        self._cal_combo = QComboBox()
        for cal in self.runtime.calendars.values():
            self._cal_combo.addItem(cal.name, cal.cal_id)
        form.addRow("Calendar:", self._cal_combo)

        # Start
        self._start_date = QDateEdit(QDate(start_dt.year, start_dt.month, start_dt.day))
        self._start_date.setCalendarPopup(True)
        self._start_date.setDisplayFormat("MM/dd/yyyy")
        form.addRow("Date:", self._start_date)

        self._start_time = QTimeEdit()
        from PySide6.QtCore import QTime
        self._start_time.setTime(QTime(start_dt.hour, 0))
        self._start_time.setDisplayFormat("hh:mm AP")
        form.addRow("Start time:", self._start_time)

        self._duration = QComboBox()
        for label, mins in [("30 min", 30), ("1 hour", 60), ("1.5 hours", 90),
                              ("2 hours", 120), ("3 hours", 180), ("All day", 0)]:
            self._duration.addItem(label, mins)
        self._duration.setCurrentIndex(1)
        form.addRow("Duration:", self._duration)

        self._desc = QTextEdit()
        self._desc.setFixedHeight(60)
        self._desc.setPlaceholderText("Description (optional)")
        form.addRow("Notes:", self._desc)

        layout.addLayout(form)

        btns = QHBoxLayout()
        ok_btn = QPushButton("Create Event")
        ok_btn.setStyleSheet(
            "QPushButton{background:#1a73e8;color:#fff;border:none;border-radius:4px;"
            "font-weight:700;padding:6px 16px;}"
            "QPushButton:hover{background:#1558b0;}"
        )
        ok_btn.clicked.connect(self._on_create)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        btns.addStretch()
        layout.addLayout(btns)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#f85149;font-size:11px;")
        layout.addWidget(self._status)

    def _on_create(self):
        title = self._title.text().strip()
        if not title:
            self._status.setText("Title is required.")
            return
        cal_id = self._cal_combo.currentData()
        if not cal_id:
            self._status.setText("Select a calendar.")
            return
        qd = self._start_date.date()
        qt = self._start_time.time()
        start = datetime(qd.year(), qd.month(), qd.day(),
                         qt.hour(), qt.minute(), tzinfo=UTC)
        mins = self._duration.currentData()
        end = start + timedelta(minutes=mins if mins else 60)
        desc = self._desc.toPlainText().strip()
        ok = self.runtime.create_event(cal_id, title, start, end, desc)
        if ok:
            self.accept()
        else:
            self._status.setText("Failed to create event. Check log.")


# ─── Event Detail Popup ────────────────────────────────────────────────────────

class EventDetailPopup(QDialog):
    def __init__(self, event: EventRecord, runtime: GoogleCalendarRuntime, parent=None):
        super().__init__(parent)
        self._event   = event
        self._runtime = runtime
        self.setWindowTitle(event.summary)
        self.setMinimumWidth(380)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)

        # Color dot + title
        top = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{self._event.bg_color};font-size:18px;")
        top.addWidget(dot)
        title = QLabel(self._event.summary)
        title.setStyleSheet("font-size:14px;font-weight:bold;")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        layout.addLayout(top)

        layout.addWidget(QLabel(
            f"{_fmt_dt(self._event.start_dt, self._event.all_day)} → "
            f"{_fmt_dt(self._event.end_dt, self._event.all_day)}"
        ))
        layout.addWidget(QLabel(f"Calendar: {self._event.cal_name}"))
        if self._event.location:
            layout.addWidget(QLabel(f"📍 {self._event.location}"))
        if self._event.description:
            desc = QTextEdit()
            desc.setReadOnly(True)
            desc.setPlainText(self._event.description)
            desc.setFixedHeight(80)
            layout.addWidget(desc)
        if self._event.attendees:
            count = len(self._event.attendees)
            layout.addWidget(QLabel(f"👥 {count} attendee{'s' if count != 1 else ''}"))

        btns = QHBoxLayout()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        delete_btn = QPushButton("Delete Event")
        delete_btn.setStyleSheet(
            "QPushButton{background:rgba(248,81,73,0.2);color:#f85149;"
            "border:1px solid #f85149;border-radius:4px;padding:4px 12px;}"
        )
        delete_btn.clicked.connect(self._on_delete)
        btns.addWidget(close_btn)
        btns.addWidget(delete_btn)
        btns.addStretch()
        layout.addLayout(btns)

    def _on_delete(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Delete Event")
        dlg.setText(f"Delete '{self._event.summary}'?")
        dlg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        dlg.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if dlg.exec() == QMessageBox.StandardButton.Yes:
            self._runtime.delete_event(self._event.cal_id, self._event.event_id)
            self.accept()


# ─── Week Grid (QPainter) ──────────────────────────────────────────────────────

class WeekGridWidget(QWidget):
    event_clicked      = Signal(str)   # event_id
    empty_slot_clicked = Signal(object)  # datetime

    HOUR_W  = 56
    HEADER_H = 42
    BG       = QColor("#0d1117")
    BG_HDR   = QColor("#161b22")
    BG_TODAY = QColor("#1e3a5f")
    LINE     = QColor("#21262d")
    HOUR_CLR = QColor("#8b949e")
    DAY_CLR  = QColor("#e6edf3")
    NOW_CLR  = QColor("#f85149")

    def __init__(self):
        super().__init__()
        self.events: list[EventRecord] = []
        self.anchor = _sunday()
        self.today  = datetime.now().astimezone().date()
        self.setMinimumHeight(600)
        self.setMouseTracking(True)

    def set_events(self, events):
        self.events = events
        self.update()

    def set_anchor(self, d: date):
        self.anchor = d
        self.update()

    def mousePressEvent(self, ev):
        r = self.contentsRect()
        day_w = max(1, (r.width() - self.HOUR_W) / 7)
        body_h = r.height() - self.HEADER_H
        hour_h = max(1, body_h / 24)
        x, y = ev.position().x(), ev.position().y()
        if x < self.HOUR_W or y < self.HEADER_H:
            return
        day_idx = int((x - self.HOUR_W) // day_w)
        hour    = int((y - self.HEADER_H) // hour_h)
        clicked_dt = datetime.combine(
            self.anchor + timedelta(days=min(6, max(0, day_idx))),
            time(hour=min(23, max(0, hour))), tzinfo=UTC,
        )
        for rec in self.events:
            if (rec.start_dt.date() <= clicked_dt.date() <= rec.end_dt.date()
                    and rec.start_dt.hour <= hour <= max(rec.start_dt.hour, rec.end_dt.hour)):
                self.event_clicked.emit(rec.event_id)
                return
        self.empty_slot_clicked.emit(clicked_dt)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.contentsRect()
        day_w  = max(1, (r.width() - self.HOUR_W) / 7)
        body_h = r.height() - self.HEADER_H
        hour_h = max(1, body_h / 24)

        p.fillRect(r, self.BG)
        p.fillRect(QRect(r.x(), r.y(), self.HOUR_W, r.height()), self.BG_HDR)

        # Hour lines + labels
        p.setPen(QPen(self.LINE, 1))
        for h in range(24):
            y = int(r.y() + self.HEADER_H + h * hour_h)
            p.drawLine(r.x() + self.HOUR_W, y, r.right(), y)
            lbl = datetime.combine(date.today(), time(h, 0)).strftime("%I %p").lstrip("0") or "12 AM"
            p.setPen(self.HOUR_CLR)
            p.drawText(QRect(r.x()+2, y-8, self.HOUR_W-4, 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, lbl)
            p.setPen(QPen(self.LINE, 1))

        # Column lines + headers
        for i in range(8):
            x = int(r.x() + self.HOUR_W + i * day_w)
            p.setPen(QPen(self.LINE, 1))
            p.drawLine(x, r.y(), x, r.bottom())

        for i in range(7):
            cur = self.anchor + timedelta(days=i)
            x   = int(r.x() + self.HOUR_W + i * day_w)
            hr  = QRect(x+2, r.y()+2, int(day_w)-4, self.HEADER_H-4)
            if cur == self.today:
                p.fillRect(hr, self.BG_TODAY)
            p.setPen(self.DAY_CLR)
            p.setFont(QFont("Arial", 9, QFont.Weight.Bold))
            p.drawText(hr, Qt.AlignmentFlag.AlignCenter, f"{cur.strftime("%a")} {cur.day}")

        # Now line — local time
        now = datetime.now().astimezone()
        if self.anchor <= now.date() < self.anchor + timedelta(days=7):
            di = (now.date() - self.anchor).days
            x0 = int(r.x() + self.HOUR_W + di * day_w)
            y  = int(r.y() + self.HEADER_H + (now.hour + now.minute / 60) * hour_h)
            p.setPen(QPen(self.NOW_CLR, 2))
            p.drawLine(x0+1, y, int(x0+day_w-2), y)

        # Events
        p.setFont(QFont("Arial", 8))
        for ev in self.events:
            di = (ev.start_dt.date() - self.anchor).days
            if di < 0 or di > 6:
                continue
            x = int(r.x() + self.HOUR_W + di * day_w + 2)
            if ev.all_day:
                sh, eh = 0.0, 1.0
            else:
                sh = ev.start_dt.hour + ev.start_dt.minute / 60
                eh = ev.end_dt.hour   + ev.end_dt.minute   / 60
            y = int(r.y() + self.HEADER_H + sh * hour_h + 1)
            h = max(18, int((eh - sh) * hour_h - 2))
            w = int(day_w - 4)
            p.fillRect(QRect(x, y, w, h), QColor(ev.bg_color))
            p.setPen(QColor(ev.fg_color))
            txt = ev.summary if ev.all_day else f"{ev.start_dt.strftime('%H:%M')} {ev.summary}"
            p.drawText(QRect(x+3, y+2, w-6, h-4),
                       Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, txt)
        p.end()


# ─── Agenda View ──────────────────────────────────────────────────────────────

class AgendaWidget(QWidget):
    event_clicked = Signal(str)

    def __init__(self, runtime: GoogleCalendarRuntime):
        super().__init__()
        self._rt = runtime
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget{background:#0d1117;color:#c9d1d9;border:none;font-size:12px;}"
            "QListWidget::item{padding:6px 8px;border-bottom:1px solid #21262d;}"
            "QListWidget::item:selected{background:#21262d;}"
        )
        self._list.itemClicked.connect(self._on_click)
        layout.addWidget(self._list)

    def refresh(self, days: int = 30):
        self._list.clear()
        events = self._rt.upcoming_events(days)
        if not events:
            self._list.addItem(QListWidgetItem("No upcoming events."))
            return
        current_date = None
        for ev in events:
            ev_date = ev.start_dt.date()
            if ev_date != current_date:
                current_date = ev_date
                hdr = QListWidgetItem(ev_date.strftime("─── %A, %B %d, %Y ───"))
                hdr.setForeground(QColor("#58a6ff"))
                hdr.setFont(QFont("Arial", 10, QFont.Weight.Bold))
                hdr.setFlags(Qt.ItemFlag.NoItemFlags)
                self._list.addItem(hdr)
            dot = QListWidgetItem()
            if ev.all_day:
                txt = f"  {ev.summary}  [{ev.cal_name}]"
            else:
                txt = (f"  {ev.start_dt.strftime('%I:%M %p')} – "
                       f"{ev.end_dt.strftime('%I:%M %p')}  "
                       f"{ev.summary}  [{ev.cal_name}]")
            dot.setText(txt)
            dot.setData(Qt.ItemDataRole.UserRole, ev.event_id)
            dot.setForeground(QColor(ev.fg_color))
            self._list.addItem(dot)

    def _on_click(self, item: QListWidgetItem):
        eid = item.data(Qt.ItemDataRole.UserRole)
        if eid:
            self.event_clicked.emit(eid)


# ─── Day View ──────────────────────────────────────────────────────────────────

class DayGridWidget(QWidget):
    event_clicked      = Signal(str)
    empty_slot_clicked = Signal(object)

    HOUR_W   = 64
    HEADER_H = 42
    BG       = QColor("#0d1117")
    BG_HDR   = QColor("#161b22")
    LINE     = QColor("#21262d")
    HOUR_CLR = QColor("#8b949e")
    DAY_CLR  = QColor("#e6edf3")
    NOW_CLR  = QColor("#f85149")

    def __init__(self):
        super().__init__()
        self.events: list[EventRecord] = []
        self.anchor = datetime.now().astimezone().date()
        self.today  = datetime.now().astimezone().date()
        self.setMinimumHeight(600)
        self.setMouseTracking(True)

    def set_events(self, events):
        self.events = events
        self.update()

    def set_anchor(self, d: date):
        self.anchor = d
        self.today  = datetime.now().astimezone().date()
        self.update()

    def mousePressEvent(self, ev):
        r = self.contentsRect()
        body_h = r.height() - self.HEADER_H
        hour_h = max(1, body_h / 24)
        y = ev.position().y()
        if y < self.HEADER_H:
            return
        hour = int((y - self.HEADER_H) // hour_h)
        clicked_dt = datetime.combine(self.anchor, time(hour=min(23, max(0, hour)))).astimezone()
        for rec in self.events:
            ls = rec.start_dt.astimezone()
            le = rec.end_dt.astimezone()
            if ls.date() == self.anchor and ls.hour <= hour <= le.hour:
                self.event_clicked.emit(rec.event_id)
                return
        self.empty_slot_clicked.emit(clicked_dt)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.contentsRect()
        body_h = r.height() - self.HEADER_H
        hour_h = max(1, body_h / 24)

        p.fillRect(r, self.BG)
        p.fillRect(QRect(r.x(), r.y(), self.HOUR_W, r.height()), self.BG_HDR)

        hdr_r = QRect(r.x() + self.HOUR_W + 2, r.y() + 2, r.width() - self.HOUR_W - 4, self.HEADER_H - 4)
        if self.anchor == self.today:
            p.fillRect(hdr_r, QColor("#1e3a5f"))
        p.setPen(self.DAY_CLR)
        p.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        p.drawText(hdr_r, Qt.AlignmentFlag.AlignCenter,
                   f"{self.anchor.strftime('%A, %B')} {self.anchor.day}, {self.anchor.year}")

        p.setPen(QPen(self.LINE, 1))
        for h in range(24):
            y = int(r.y() + self.HEADER_H + h * hour_h)
            p.drawLine(r.x() + self.HOUR_W, y, r.right(), y)
            lbl = datetime.combine(date.today(), time(h, 0)).strftime("%I %p").lstrip("0") or "12 AM"
            p.setPen(self.HOUR_CLR)
            p.drawText(QRect(r.x() + 2, y - 8, self.HOUR_W - 4, 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, lbl)
            p.setPen(QPen(self.LINE, 1))

        # Vertical separator
        p.drawLine(r.x() + self.HOUR_W, r.y(), r.x() + self.HOUR_W, r.bottom())

        now = datetime.now().astimezone()
        if now.date() == self.anchor:
            y = int(r.y() + self.HEADER_H + (now.hour + now.minute / 60) * hour_h)
            p.setPen(QPen(self.NOW_CLR, 2))
            p.drawLine(r.x() + self.HOUR_W + 1, y, r.right() - 1, y)

        p.setFont(QFont("Arial", 9))
        for ev in self.events:
            if ev.start_dt.date() != self.anchor:
                continue
            if ev.all_day:
                sh, eh = 0.0, 1.0
            else:
                sh = ev.start_dt.hour + ev.start_dt.minute / 60
                eh = ev.end_dt.hour + ev.end_dt.minute / 60
            y = int(r.y() + self.HEADER_H + sh * hour_h + 1)
            h = max(20, int((eh - sh) * hour_h - 2))
            x = r.x() + self.HOUR_W + 4
            w = r.width() - self.HOUR_W - 8
            p.fillRect(QRect(x, y, w, h), QColor(ev.bg_color))
            p.setPen(QColor(ev.fg_color))
            if ev.all_day:
                txt = ev.summary
            else:
                txt = f"{ev.start_dt.strftime('%I:%M %p').lstrip('0')} – {ev.end_dt.strftime('%I:%M %p').lstrip('0')}  {ev.summary}"
            p.drawText(QRect(x + 4, y + 3, w - 8, h - 6),
                       Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, txt)
        p.end()


# ─── Month View ─────────────────────────────────────────────────────────────────

class MonthGridWidget(QWidget):
    event_clicked      = Signal(str)
    empty_slot_clicked = Signal(object)

    BG        = QColor("#0d1117")
    BG_HDR    = QColor("#161b22")
    BG_TODAY  = QColor("#1e3a5f")
    BG_OTHER  = QColor("#080d14")
    LINE      = QColor("#21262d")
    DAY_CLR   = QColor("#e6edf3")
    DIM_CLR   = QColor("#8b949e")
    NOW_CLR   = QColor("#f85149")

    def __init__(self):
        super().__init__()
        self.events: list[EventRecord] = []
        self.anchor = datetime.now().astimezone().date().replace(day=1)
        self.today  = datetime.now().astimezone().date()
        self.setMinimumHeight(500)
        self.setMouseTracking(True)

    def set_events(self, events):
        self.events = events
        self.update()

    def set_anchor(self, d: date):
        self.anchor = d.replace(day=1)
        self.today  = datetime.now().astimezone().date()
        self.update()

    def _grid_start(self) -> date:
        first = self.anchor
        return first - timedelta(days=(first.weekday() + 1) % 7)

    def mousePressEvent(self, ev):
        r = self.contentsRect()
        hdr_h = 28
        cell_w = max(1, r.width() / 7)
        cell_h = max(1, (r.height() - hdr_h) / 6)
        x, y = ev.position().x(), ev.position().y() - hdr_h
        if y < 0:
            return
        col = min(6, int(x // cell_w))
        row = min(5, int(y // cell_h))
        clicked = self._grid_start() + timedelta(days=row * 7 + col)
        for ev_rec in self.events:
            if ev_rec.start_dt.astimezone().date() == clicked:
                self.event_clicked.emit(ev_rec.event_id)
                return
        self.empty_slot_clicked.emit(datetime.combine(clicked, time(9, 0)).astimezone())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.contentsRect()
        hdr_h  = 28
        cell_w = max(1, r.width() / 7)
        cell_h = max(1, (r.height() - hdr_h) / 6)

        p.fillRect(r, self.BG)

        # Day-of-week headers
        for i, d in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
            x = int(r.x() + i * cell_w)
            p.fillRect(QRect(x, r.y(), int(cell_w), hdr_h), self.BG_HDR)
            p.setPen(self.DIM_CLR)
            p.setFont(QFont("Arial", 9, QFont.Weight.Bold))
            p.drawText(QRect(x, r.y(), int(cell_w), hdr_h),
                       Qt.AlignmentFlag.AlignCenter, d)

        # Build events-by-date lookup
        events_by_date: dict = {}
        for ev in self.events:
            d = ev.start_dt.astimezone().date()
            events_by_date.setdefault(d, []).append(ev)

        grid_start = self._grid_start()
        for row in range(6):
            for col in range(7):
                cell_date = grid_start + timedelta(days=row * 7 + col)
                x = int(r.x() + col * cell_w)
                y = int(r.y() + hdr_h + row * cell_h)
                cw = int(cell_w)
                ch = int(cell_h)

                # Cell background
                if cell_date.month != self.anchor.month:
                    p.fillRect(QRect(x, y, cw, ch), self.BG_OTHER)
                elif cell_date == self.today:
                    p.fillRect(QRect(x, y, cw, ch), self.BG_TODAY)

                # Grid lines
                p.setPen(QPen(self.LINE, 1))
                p.drawRect(QRect(x, y, cw, ch))

                # Day number
                p.setPen(self.NOW_CLR if cell_date == self.today else
                         self.DAY_CLR if cell_date.month == self.anchor.month else self.DIM_CLR)
                p.setFont(QFont("Arial", 9, QFont.Weight.Bold if cell_date == self.today else QFont.Weight.Normal))
                p.drawText(QRect(x + 4, y + 2, cw - 8, 16),
                           Qt.AlignmentFlag.AlignRight, str(cell_date.day))

                # Event bars
                day_evs = events_by_date.get(cell_date, [])
                ev_y = y + 20
                for i, ev in enumerate(day_evs[:3]):
                    bar_h = 14
                    if ev_y + bar_h > y + ch - 2:
                        break
                    p.fillRect(QRect(x + 2, ev_y, cw - 4, bar_h), QColor(ev.bg_color))
                    p.setPen(QColor(ev.fg_color))
                    p.setFont(QFont("Arial", 7))
                    lbl = ev.summary
                    if not ev.all_day:
                        ls = ev.start_dt.astimezone()
                        lbl = f"{ls.strftime('%I:%M').lstrip('0')} {ev.summary}"
                    p.drawText(QRect(x + 4, ev_y + 1, cw - 8, bar_h - 2),
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, lbl)
                    ev_y += bar_h + 2

                if len(day_evs) > 3:
                    p.setPen(self.DIM_CLR)
                    p.setFont(QFont("Arial", 7))
                    p.drawText(QRect(x + 2, ev_y, cw - 4, 12),
                               Qt.AlignmentFlag.AlignLeft, f"+{len(day_evs)-3} more")
        p.end()



# ─── Calendar Workspace (slot 1) ──────────────────────────────────────────────

class CalendarWorkspaceWidget(QWidget):
    def __init__(self, runtime: GoogleCalendarRuntime):
        super().__init__()
        self._rt     = runtime
        self._anchor = _sunday()
        self._view   = "week"  # day | week | month | agenda
        self._build()
        self._rt.data_changed.connect(self.refresh)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Ribbon
        ribbon = QFrame()
        ribbon.setFixedHeight(40)
        ribbon.setStyleSheet(
            "QFrame{background:#161b22;border-bottom:1px solid #21262d;}"
        )
        rl = QHBoxLayout(ribbon)
        rl.setContentsMargins(8, 4, 8, 4)
        rl.setSpacing(6)

        def _rbtn(label, tip="", checkable=False):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.setFixedHeight(28)
            b.setCheckable(checkable)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            b.setStyleSheet(
                "QPushButton{background:#21262d;color:#c9d1d9;border:1px solid #30363d;"
                "border-radius:4px;padding:2px 10px;font-size:11px;}"
                "QPushButton:hover{background:#30363d;}"
                "QPushButton:checked{background:#1f3a5c;border-color:#58a6ff;color:#58a6ff;}"
            )
            return b

        self._today_btn = _rbtn("Today")
        self._prev_btn  = _rbtn("◀")
        self._prev_btn.setFixedSize(28, 28)
        self._next_btn  = _rbtn("▶")
        self._next_btn.setFixedSize(28, 28)

        self._period_lbl = QLabel()
        self._period_lbl.setStyleSheet("font-size:13px;font-weight:bold;color:#c9d1d9;")

        # View switcher
        self._view_btns: dict[str, QPushButton] = {}
        for v in ("Day", "Week", "Month", "Agenda"):
            b = _rbtn(v, checkable=True)
            b.setChecked(v.lower() == self._view)
            b.clicked.connect(lambda _, vv=v.lower(): self._set_view(vv))
            self._view_btns[v.lower()] = b
            rl.addWidget(b) if v == "Day" else None  # add after period label

        self._add_btn  = _rbtn("+ Event", "Create event")
        self._sync_btn = _rbtn("⟳ Sync")
        self._ai_btn   = _rbtn("⚡ AI")

        rl.addWidget(self._today_btn)
        rl.addWidget(self._prev_btn)
        rl.addWidget(self._next_btn)
        rl.addWidget(self._period_lbl, 1)
        for b in self._view_btns.values():
            rl.addWidget(b)
        rl.addWidget(self._add_btn)
        rl.addWidget(self._sync_btn)
        rl.addWidget(self._ai_btn)
        root.addWidget(ribbon)

        # View stack
        self._stack = QSplitter(Qt.Orientation.Horizontal)

        self._week_grid   = WeekGridWidget()
        self._day_grid    = DayGridWidget()
        self._month_grid  = MonthGridWidget()
        self._agenda_view = AgendaWidget(self._rt)

        # Task sidebar (toggleable)
        self._task_sidebar = _TaskSidebarWidget(self._rt)
        self._task_sidebar.setVisible(False)

        self._content_widget = QWidget()
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.addWidget(self._week_grid)
        self._content_layout.addWidget(self._day_grid)
        self._content_layout.addWidget(self._month_grid)
        self._content_layout.addWidget(self._agenda_view)
        self._day_grid.setVisible(False)
        self._month_grid.setVisible(False)
        self._agenda_view.setVisible(False)

        self._stack.addWidget(self._content_widget)
        self._stack.addWidget(self._task_sidebar)
        self._stack.setSizes([900, 0])
        root.addWidget(self._stack, 1)

        # Wire
        self._today_btn.clicked.connect(self._go_today)
        self._prev_btn.clicked.connect(lambda: self._shift(-7))
        self._next_btn.clicked.connect(lambda: self._shift(7))
        self._add_btn.clicked.connect(self._on_add_event)
        self._sync_btn.clicked.connect(self._rt.trigger_sync_now)
        self._ai_btn.clicked.connect(lambda: self._rt.send_upcoming_to_ai(7))
        self._week_grid.event_clicked.connect(self._on_event_clicked)
        self._week_grid.empty_slot_clicked.connect(self._on_empty_slot)
        self._day_grid.event_clicked.connect(self._on_event_clicked)
        self._day_grid.empty_slot_clicked.connect(self._on_empty_slot)
        self._month_grid.event_clicked.connect(self._on_event_clicked)
        self._month_grid.empty_slot_clicked.connect(self._on_empty_slot)
        self._agenda_view.event_clicked.connect(self._on_event_clicked)

        self._update_period_label()

    def _set_view(self, view: str):
        self._view = view
        for k, b in self._view_btns.items():
            b.setChecked(k == view)
        self._week_grid.setVisible(view == "week")
        self._day_grid.setVisible(view == "day")
        self._month_grid.setVisible(view == "month")
        self._agenda_view.setVisible(view == "agenda")
        if view == "agenda":
            self._agenda_view.refresh(60)
        elif view == "day":
            self._day_grid.set_anchor(self._anchor)
            self._day_grid.set_events(self._rt.events_for_day(self._anchor))
        elif view == "month":
            self._month_grid.set_anchor(self._anchor)
            self._month_grid.set_events(self._rt.events_for_month(
                self._anchor.year, self._anchor.month))
        self._update_period_label()

    def _go_today(self):
        self._anchor = _sunday()
        self.refresh()

    def _shift(self, days: int):
        if self._view == "month":
            # Navigate by month
            import calendar as _cal
            if days > 0:
                m = self._anchor.month + 1
                y = self._anchor.year + (1 if m > 12 else 0)
                m = 1 if m > 12 else m
            else:
                m = self._anchor.month - 1
                y = self._anchor.year - (1 if m < 1 else 0)
                m = 12 if m < 1 else m
            self._anchor = date(y, m, 1)
        elif self._view == "day":
            self._anchor += timedelta(days=1 if days > 0 else -1)
        else:
            self._anchor += timedelta(days=days)
        self.refresh()

    def _on_add_event(self):
        dlg = QuickAddDialog(self._rt, parent=self)
        dlg.exec()

    def _on_event_clicked(self, event_id: str):
        ev = self._rt.events.get(event_id)
        if ev:
            EventDetailPopup(ev, self._rt, parent=self).exec()

    def _on_empty_slot(self, dt: datetime):
        dlg = QuickAddDialog(self._rt, start_dt=dt, parent=self)
        dlg.exec()

    def _update_period_label(self):
        if self._view == "week":
            end = self._anchor + timedelta(days=6)
            if self._anchor.month == end.month:
                txt = f"{self._anchor.strftime('%B %Y')}  {self._anchor.day}–{end.day}"
            else:
                txt = f"{self._anchor.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
        elif self._view == "day":
            txt = self._anchor.strftime("%A, %B %-d, %Y") if hasattr(self._anchor, "strftime") else str(self._anchor)
            try:
                txt = f"{self._anchor.strftime('%A')}, {self._anchor.strftime('%B')} {self._anchor.day}, {self._anchor.year}"
            except Exception:
                txt = str(self._anchor)
        elif self._view == "month":
            txt = self._anchor.strftime("%B %Y")
        elif self._view == "agenda":
            txt = "Upcoming Events"
        else:
            txt = self._anchor.strftime("%B %Y")
        self._period_lbl.setText(txt)

    def refresh(self):
        if self._view == "week":
            self._week_grid.set_anchor(self._anchor)
            self._week_grid.set_events(self._rt.events_for_week(self._anchor))
        elif self._view == "day":
            self._day_grid.set_anchor(self._anchor)
            self._day_grid.set_events(self._rt.events_for_day(self._anchor))
        elif self._view == "month":
            self._month_grid.set_anchor(self._anchor)
            self._month_grid.set_events(self._rt.events_for_month(
                self._anchor.year, self._anchor.month))
        elif self._view == "agenda":
            self._agenda_view.refresh(60)
        self._task_sidebar.refresh()
        self._update_period_label()


# ─── Task Sidebar (used inside calendar splitter) ─────────────────────────────

class _TaskSidebarWidget(QWidget):
    def __init__(self, runtime: GoogleCalendarRuntime):
        super().__init__()
        self._rt = runtime
        self.setFixedWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        hdr = QLabel("Tasks")
        hdr.setStyleSheet("font-weight:bold;color:#c9d1d9;font-size:12px;")
        layout.addWidget(hdr)
        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget{background:#161b22;color:#c9d1d9;border:none;font-size:10px;}"
            "QListWidget::item{padding:3px 4px;}"
        )
        layout.addWidget(self._list, 1)

    def refresh(self):
        self._list.clear()
        today = datetime.now().astimezone().date()
        for t in sorted(self._rt.active_tasks(), key=lambda x: (x.due_date or date.max)):
            lbl = t.title
            if t.due_date:
                delta = (t.due_date - today).days
                if delta < 0:
                    lbl += f"  ⚠ {-delta}d overdue"
                elif delta == 0:
                    lbl += "  · today"
                elif delta == 1:
                    lbl += "  · tomorrow"
                else:
                    lbl += f"  · {t.due_date.isoformat()}"
            item = QListWidgetItem(lbl)
            if t.due_date and t.due_date < today:
                item.setForeground(QColor("#f85149"))
            elif t.due_date == today:
                item.setForeground(QColor("#e3b341"))
            self._list.addItem(item)


# ─── Task Columns Workspace (slot 2) ──────────────────────────────────────────

class TaskColumnsWorkspaceWidget(QWidget):
    def __init__(self, runtime: GoogleCalendarRuntime):
        super().__init__()
        self._rt = runtime
        self._build()
        self._rt.data_changed.connect(self.refresh)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setFixedHeight(40)
        header.setStyleSheet("QFrame{background:#161b22;border-bottom:1px solid #21262d;}")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(8, 4, 8, 4)
        title = QLabel("Tasks")
        title.setStyleSheet("font-size:13px;font-weight:bold;color:#c9d1d9;")
        hl.addWidget(title)
        hl.addStretch()
        check_btn = QPushButton("Check Due Dates")
        check_btn.setFixedHeight(28)
        check_btn.setStyleSheet(
            "QPushButton{background:#21262d;color:#58a6ff;border:1px solid #30363d;"
            "border-radius:4px;padding:2px 8px;font-size:11px;}"
            "QPushButton:hover{background:#1f3a5c;}"
        )
        check_btn.clicked.connect(self._rt.check_task_due_dates)
        hl.addWidget(check_btn)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea{border:none;background:#0d1117;}")
        self._cols_widget = QWidget()
        self._cols_widget.setStyleSheet("background:#0d1117;")
        self._cols_layout = QHBoxLayout(self._cols_widget)
        self._cols_layout.setContentsMargins(8, 8, 8, 8)
        self._cols_layout.setSpacing(12)
        self._cols_layout.addStretch()
        scroll.setWidget(self._cols_widget)
        root.addWidget(scroll, 1)
        self.refresh()

    def refresh(self):
        while self._cols_layout.count() > 1:
            item = self._cols_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        grouped: dict[str, list[TaskRecord]] = {}
        for t in self._rt.active_tasks():
            grouped.setdefault(t.list_name, []).append(t)

        today = datetime.now().astimezone().date()
        for list_name, tasks in grouped.items():
            col = QFrame()
            col.setStyleSheet(
                "QFrame{background:#161b22;border:1px solid #21262d;border-radius:6px;}"
            )
            col.setFixedWidth(240)
            cl = QVBoxLayout(col)
            cl.setContentsMargins(8, 8, 8, 8)
            cl.setSpacing(4)
            hdr = QLabel(list_name)
            hdr.setStyleSheet("font-weight:bold;font-size:12px;color:#c9d1d9;")
            cl.addWidget(hdr)
            cnt = QLabel(f"{len(tasks)} task{'s' if len(tasks) != 1 else ''}")
            cnt.setStyleSheet("font-size:10px;color:#8b949e;")
            cl.addWidget(cnt)
            div = QFrame()
            div.setFrameShape(QFrame.Shape.HLine)
            div.setStyleSheet("color:#21262d;")
            cl.addWidget(div)

            for t in sorted(tasks, key=lambda x: (x.due_date or date.max)):
                row = QHBoxLayout()
                cb = QCheckBox()
                cb.setStyleSheet("QCheckBox::indicator{width:14px;height:14px;}")
                name_lbl = QLabel(t.title)
                name_lbl.setWordWrap(True)
                name_lbl.setStyleSheet("font-size:11px;color:#c9d1d9;")
                row.addWidget(cb)
                row.addWidget(name_lbl, 1)
                if t.due_date:
                    delta = (t.due_date - today).days
                    if delta < 0:
                        due_txt, due_clr = f"⚠{-delta}d", "#f85149"
                    elif delta == 0:
                        due_txt, due_clr = "today", "#e3b341"
                    elif delta == 1:
                        due_txt, due_clr = "tmrw", "#3fb950"
                    else:
                        due_txt, due_clr = t.due_date.strftime("%b %d"), "#8b949e"
                    dl = QLabel(due_txt)
                    dl.setStyleSheet(f"font-size:9px;color:{due_clr};font-weight:bold;")
                    row.addWidget(dl)
                cl.addLayout(row)

            cl.addStretch()
            self._cols_layout.insertWidget(self._cols_layout.count()-1, col)


# ─── Module Tab Widget ─────────────────────────────────────────────────────────

class GoogleCalendarTabWidget(QWidget):
    def __init__(self, runtime: GoogleCalendarRuntime):
        super().__init__()
        self._rt = runtime
        self._build()
        self._rt.data_changed.connect(self.refresh)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        container = QWidget()
        container.setStyleSheet("background:transparent;")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(6)

        # Auth block
        auth_frame = QFrame()
        auth_frame.setStyleSheet(
            "QFrame{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);border-radius:4px;}"
        )
        al = QVBoxLayout(auth_frame)
        al.setContentsMargins(8, 6, 8, 6)
        al.setSpacing(4)
        self._auth_lbl = QLabel()
        self._auth_lbl.setStyleSheet("font-size:10px;color:rgba(255,255,255,0.55);background:transparent;")
        self._auth_lbl.setWordWrap(True)
        al.addWidget(self._auth_lbl)
        self._connect_btn = QPushButton("Connect Google Account")
        self._connect_btn.setFixedHeight(28)
        self._connect_btn.setStyleSheet(
            "QPushButton{background:#1a73e8;color:#fff;border:none;border-radius:4px;"
            "font-size:11px;font-weight:bold;}"
            "QPushButton:hover{background:#1558b0;}"
            "QPushButton:disabled{background:rgba(255,255,255,0.1);color:rgba(255,255,255,0.4);}"
        )
        self._connect_btn.clicked.connect(self._do_connect)
        al.addWidget(self._connect_btn)
        self._reauth_btn = QPushButton("Choose Different Credentials…")
        self._reauth_btn.setFixedHeight(22)
        self._reauth_btn.setStyleSheet(
            "QPushButton{background:transparent;color:rgba(255,255,255,0.45);border:none;"
            "font-size:10px;text-decoration:underline;}"
            "QPushButton:hover{color:#58a6ff;}"
        )
        self._reauth_btn.clicked.connect(self._do_reauth)
        self._reauth_btn.setVisible(False)
        al.addWidget(self._reauth_btn)
        vbox.addWidget(auth_frame)

        # Sync row
        sync_row = QHBoxLayout()
        self._sync_lbl = QLabel("Not synced")
        self._sync_lbl.setStyleSheet("color:rgba(255,255,255,0.4);font-size:10px;background:transparent;")
        sync_btn = QPushButton("⟳ Sync")
        sync_btn.setFixedHeight(24)
        sync_btn.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.08);color:#58a6ff;"
            "border:1px solid rgba(255,255,255,0.15);border-radius:3px;font-size:10px;}"
            "QPushButton:hover{background:rgba(88,166,255,0.15);}"
        )
        sync_btn.clicked.connect(self._rt.trigger_sync_now)
        sync_row.addWidget(self._sync_lbl, 1)
        sync_row.addWidget(sync_btn)
        vbox.addLayout(sync_row)

        # Calendar list
        cal_list_lbl = QLabel("Calendars")
        cal_list_lbl.setStyleSheet("color:rgba(255,255,255,0.6);font-size:10px;font-weight:700;background:transparent;")
        vbox.addWidget(cal_list_lbl)
        self._cal_list = QListWidget()
        self._cal_list.setFixedHeight(120)
        self._cal_list.setStyleSheet(
            "QListWidget{background:rgba(0,0,0,0.15);color:#c9d1d9;"
            "border:1px solid rgba(255,255,255,0.1);border-radius:3px;font-size:11px;}"
            "QListWidget::item{padding:4px 8px;}"
            "QListWidget::item:selected{background:#21262d;}"
        )
        self._cal_list.itemChanged.connect(self._on_cal_visibility_changed)
        vbox.addWidget(self._cal_list)

        # Upcoming events
        upcoming_lbl = QLabel("Upcoming — Next 7 Days")
        upcoming_lbl.setStyleSheet("color:rgba(255,255,255,0.6);font-size:10px;font-weight:700;background:transparent;")
        vbox.addWidget(upcoming_lbl)
        self._upcoming_list = QListWidget()
        self._upcoming_list.setFixedHeight(180)
        self._upcoming_list.setStyleSheet(
            "QListWidget{background:rgba(0,0,0,0.15);color:#c9d1d9;"
            "border:1px solid rgba(255,255,255,0.1);border-radius:3px;font-size:11px;}"
            "QListWidget::item{padding:4px 8px;border-bottom:1px solid rgba(255,255,255,0.05);}"
            "QListWidget::item:selected{background:#21262d;}"
        )
        vbox.addWidget(self._upcoming_list)

        # AI button
        ai_btn = QPushButton("Ask about my schedule")
        ai_btn.setFixedHeight(28)
        ai_btn.setStyleSheet(
            "QPushButton{background:rgba(26,115,232,0.2);color:#58a6ff;"
            "border:1px solid rgba(26,115,232,0.4);border-radius:4px;font-size:11px;}"
            "QPushButton:hover{background:rgba(26,115,232,0.35);}"
        )
        ai_btn.clicked.connect(lambda: self._rt.send_upcoming_to_ai(7))
        vbox.addWidget(ai_btn)

        # Task summary
        task_lbl = QLabel("Active Tasks")
        task_lbl.setStyleSheet("color:rgba(255,255,255,0.6);font-size:10px;font-weight:700;background:transparent;")
        vbox.addWidget(task_lbl)
        self._task_lbl = QLabel("No tasks loaded")
        self._task_lbl.setStyleSheet("color:rgba(255,255,255,0.55);font-size:10px;background:transparent;")
        self._task_lbl.setWordWrap(True)
        vbox.addWidget(self._task_lbl)
        check_due_btn = QPushButton("Check Due Dates")
        check_due_btn.setFixedHeight(24)
        check_due_btn.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.08);color:rgba(255,255,255,0.7);"
            "border:1px solid rgba(255,255,255,0.15);border-radius:3px;font-size:10px;}"
            "QPushButton:hover{background:rgba(255,255,255,0.15);}"
        )
        check_due_btn.clicked.connect(self._rt.check_task_due_dates)
        vbox.addWidget(check_due_btn)

        vbox.addStretch()
        scroll.setWidget(container)
        root.addWidget(scroll)

        self.refresh()

    def _do_connect(self):
        existing = self._rt._gfile("google_credentials.json")
        if existing and existing.exists():
            creds_path = str(existing)
        else:
            msg = QMessageBox(self)
            msg.setWindowTitle("Google Credentials")
            msg.setText(
                "To connect Google Calendar, you need a credentials file from Google Cloud Console.\n\n"
                "Steps:\n"
                "1. Go to console.cloud.google.com\n"
                "2. Create/select a project\n"
                "3. Enable Calendar API + Tasks API\n"
                "4. Create OAuth 2.0 credentials (Desktop app)\n"
                "5. Download the JSON file\n\n"
                "Click OK to browse for the file."
            )
            msg.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            if msg.exec() != QMessageBox.StandardButton.Ok:
                return
            creds_path, _ = QFileDialog.getOpenFileName(
                self, "Select Google Credentials File", "",
                "JSON Files (*.json);;All Files (*)"
            )
            if not creds_path:
                return
        self._connect_btn.setEnabled(False)
        self._connect_btn.setText("Opening browser…")
        ok = self._rt.run_oauth_flow(creds_path)
        if ok:
            self._connect_btn.setText("Connected ✓")
            self._rt.start_sync()
        else:
            self._connect_btn.setEnabled(True)
            self._connect_btn.setText("Connect Google Account")
        self.refresh()

    def _do_reauth(self):
        creds_path, _ = QFileDialog.getOpenFileName(
            self, "Select Google Credentials File", "",
            "JSON Files (*.json);;All Files (*)"
        )
        if not creds_path:
            return
        self._connect_btn.setEnabled(False)
        self._connect_btn.setText("Opening browser…")
        ok = self._rt.run_oauth_flow(creds_path)
        if ok:
            self._connect_btn.setText("Connected ✓")
            self._rt.start_sync()
        else:
            self._connect_btn.setEnabled(True)
            self._connect_btn.setText("Connect Google Account")
        self.refresh()

    def _on_cal_visibility_changed(self, item: QListWidgetItem):
        cal_id = item.data(Qt.ItemDataRole.UserRole)
        if cal_id and cal_id in self._rt.calendars:
            self._rt.calendars[cal_id].visible = (item.checkState() == Qt.CheckState.Checked)
            self._rt.data_changed.emit()

    def refresh(self):
        status_map = {
            "ready":           ("● Connected",                     "#3fb950"),
            "pending_setup":   ("○ Not connected — click to authorize", "#e3b341"),
            "reauth_required": ("⚠ Re-authorization required",     "#f85149"),
        }
        txt, clr = status_map.get(self._rt.auth_status, ("● Unknown", "#8b949e"))
        self._auth_lbl.setText(txt)
        self._auth_lbl.setStyleSheet(f"font-size:10px;color:{clr};background:transparent;")
        self._connect_btn.setVisible(self._rt.auth_status != "ready")
        self._reauth_btn.setVisible(self._rt.auth_status == "ready")
        self._connect_btn.setEnabled(True)
        if self._rt.auth_status == "ready":
            self._connect_btn.setText("Connected ✓")

        if self._rt.last_synced_at:
            self._sync_lbl.setText(f"Synced {self._rt.last_synced_at.strftime('%H:%M')}")

        # Calendar list
        self._cal_list.blockSignals(True)
        self._cal_list.clear()
        for cal in self._rt.calendars.values():
            item = QListWidgetItem(f"  {cal.name}")
            item.setData(Qt.ItemDataRole.UserRole, cal.cal_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if cal.visible else Qt.CheckState.Unchecked)
            item.setForeground(QColor(cal.bg_color))
            self._cal_list.addItem(item)
        self._cal_list.blockSignals(False)

        # Upcoming events
        self._upcoming_list.clear()
        for ev in self._rt.upcoming_events(7):
            if ev.all_day:
                txt = f"  {ev.start_dt.date().isoformat()}  {ev.summary}"
            else:
                txt = f"  {ev.start_dt.strftime('%a %b %d %I:%M %p')}  {ev.summary}"
            item = QListWidgetItem(txt)
            item.setForeground(QColor(ev.bg_color))
            self._upcoming_list.addItem(item)
        if not self._rt.upcoming_events(7):
            self._upcoming_list.addItem(QListWidgetItem("  No upcoming events"))

        # Task summary
        active = self._rt.active_tasks()
        today = datetime.now().astimezone().date()
        overdue = [t for t in active if t.due_date and t.due_date < today]
        due_today = [t for t in active if t.due_date == today]
        parts = [f"{len(active)} active"]
        if due_today:
            parts.append(f"{len(due_today)} due today")
        if overdue:
            parts.append(f"{len(overdue)} overdue")
        self._task_lbl.setText("  |  ".join(parts) if active else "No active tasks")


# ─── Module ────────────────────────────────────────────────────────────────────

class GoogleCalendarModule:
    def __init__(self, deck_api: dict[str, Any]):
        self.runtime  = GoogleCalendarRuntime(deck_api)
        self._tab:    Optional[GoogleCalendarTabWidget]      = None
        self._cal_ws: Optional[CalendarWorkspaceWidget]     = None
        self._task_ws: Optional[TaskColumnsWorkspaceWidget] = None

    def build_tab(self) -> QWidget:
        self._tab = GoogleCalendarTabWidget(self.runtime)
        return self._tab

    def build_calendar_workspace(self) -> QWidget:
        self._cal_ws = CalendarWorkspaceWidget(self.runtime)
        return self._cal_ws

    def build_task_workspace(self) -> QWidget:
        self._task_ws = TaskColumnsWorkspaceWidget(self.runtime)
        return self._task_ws

    def release(self, _=None) -> None:
        """Stop sync, disconnect all signals, destroy widget refs for clean uninstall."""
        # stop_sync also disconnects data_changed
        try:
            self.runtime.stop_sync()
        except Exception:
            pass
        if self._tab is not None:
            try:
                self._tab.hide()
                self._tab.deleteLater()
            except Exception:
                pass
            self._tab = None
        if self._cal_ws is not None:
            try:
                self._cal_ws.hide()
                self._cal_ws.deleteLater()
            except Exception:
                pass
            self._cal_ws = None
        if self._task_ws is not None:
            try:
                self._task_ws.hide()
                self._task_ws.deleteLater()
            except Exception:
                pass
            self._task_ws = None


# ─── Entry Point ───────────────────────────────────────────────────────────────

def register(deck_api: dict[str, Any]) -> dict[str, Any]:
    api_ver = str(deck_api.get("deck_api_version") or "")
    if api_ver != "1.0":
        raise RuntimeError(f"[GoogleCalendar] Unsupported deck_api_version: {api_ver!r}")

    module = GoogleCalendarModule(deck_api)

    return {
        "deck_api_version":     "1.0",
        "module_key":           MODULE_KEY,
        "display_name":         "Google Calendar",
        "description":          MODULE_MANIFEST["description"],
        "home_category":        "Google",
        "secondary_categories": [],
        "tabs": [
            {
                "tab_id":      "google_calendar_main",
                "tab_name":    "Google Calendar",
                "get_content": module.build_tab,
            }
        ],
        "workspace": {
            "tabs": [
                {
                    "slot":  1,
                    "id":    "gcal_calendar",
                    "label": "Calendar",
                    "build": module.build_calendar_workspace,
                },
                {
                    "slot":  2,
                    "id":    "gcal_tasks",
                    "label": "Tasks",
                    "build": module.build_task_workspace,
                },
            ],
            "on_activate":   module.runtime.start_sync,
            "on_deactivate": module.release,
            "on_release":    module.release,
        },
    }
