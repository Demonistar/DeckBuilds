from __future__ import annotations

import json
import math
import traceback
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QDate, QDateTime, QObject, QPoint, QRect, Qt, QThread, QTime, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

MODULE_MANIFEST = {
    "key": "google_calendar",
    "display_name": "Google Calendar + Tasks",
    "version": "2.0.0",
    "deck_api_version": "1.0",
    "home_category": "Google",
    "entry_function": "register",
    "shared_resource": "google_auth",
    "description": "Full Google Calendar and Tasks module for Echo Deck.",
    "tab_definitions": [{"tab_id": "google_calendar_main", "tab_name": "Google Calendar"}],
    "emits": [
        "calendar.item.created",
        "calendar.item.updated",
        "calendar.item.deleted",
        "calendar.reminder.triggered",
        "task.created",
        "task.updated",
        "task.completed",
        "task.deleted",
        "task.due",
    ],
    "listens": ["calendar.item.*", "task.*"],
}

REQUIRED_SCOPES = {
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks",
}

TASK_PROMPT_DUE_TOMORROW = (
    "The following tasks are due tomorrow. List each on its own line as:\n"
    "[Task Name] — [Description]\n"
    "Do not add commentary per item. After the full list, comment freely."
)
TASK_PROMPT_DUE_TODAY = (
    "The following tasks are due today. List each on its own line as:\n"
    "[Task Name] — [Description]\n"
    "Do not add commentary per item. After the full list, comment freely."
)
TASK_PROMPT_PAST_DUE_1_30 = (
    "The following tasks are past due. List each on its own line as:\n"
    "[Task Name] — [Description]\n"
    "Do not add commentary per item. After the full list, comment freely."
)
TASK_PROMPT_CRITICALLY_OVERDUE = (
    "These tasks have been past due for over a month. Tell the user directly that these need to be resolved — "
    "marked done, rescheduled, or cancelled. List them, then push for a response."
)

# NOTE:
# Keep record models as plain Python classes (no dataclasses) so this module
# can be safely loaded via dynamic exec() loaders that do not populate
# sys.modules entries.

class CalendarRecord:
    def __init__(
        self,
        id: str,
        summary: str,
        access_role: str,
        background_color: str,
        foreground_color: str,
        selected: bool = True,
        hidden: bool = False,
        section: str = "My calendars",
    ) -> None:
        self.id = id
        self.summary = summary
        self.access_role = access_role
        self.background_color = background_color
        self.foreground_color = foreground_color
        self.selected = selected
        self.hidden = hidden
        self.section = section


class EventRecord:
    def __init__(
        self,
        google_event_id: str,
        calendar_id: str,
        calendar_name: str,
        summary: str,
        description: str,
        location: str,
        start_dt: datetime,
        end_dt: datetime,
        all_day: bool,
        status: str,
        source: str = "google",
        color_id: Optional[str] = None,
        background_color: str = "#4285F4",
        foreground_color: str = "#FFFFFF",
        reminder_overrides: Optional[list[dict[str, Any]]] = None,
        attendees: Optional[list[dict[str, Any]]] = None,
        html_link: str = "",
        conference_data: Optional[dict[str, Any]] = None,
    ) -> None:
        self.google_event_id = google_event_id
        self.calendar_id = calendar_id
        self.calendar_name = calendar_name
        self.summary = summary
        self.description = description
        self.location = location
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.all_day = all_day
        self.status = status
        self.source = source
        self.color_id = color_id
        self.background_color = background_color
        self.foreground_color = foreground_color
        self.reminder_overrides = list(reminder_overrides or [])
        self.attendees = list(attendees or [])
        self.html_link = html_link
        self.conference_data = dict(conference_data or {})


class TaskRecord:
    def __init__(
        self,
        google_task_id: str,
        task_list_id: str,
        task_list_name: str,
        title: str,
        notes: str,
        due_date: Optional[date],
        status: str,
        deleted: bool = False,
        hidden: bool = False,
    ) -> None:
        self.google_task_id = google_task_id
        self.task_list_id = task_list_id
        self.task_list_name = task_list_name
        self.title = title
        self.notes = notes
        self.due_date = due_date
        self.status = status
        self.deleted = deleted
        self.hidden = hidden


def _as_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_google_datetime(value: Optional[str], all_day_fallback: bool = False) -> tuple[datetime, bool]:
    if not value:
        now = datetime.now(UTC)
        return now, all_day_fallback
    if "T" not in value:
        d = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
        return d, True
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    d = datetime.fromisoformat(value)
    return _as_local(d), False


def _parse_google_task_due(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    if "T" in value:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    return datetime.strptime(value, "%Y-%m-%d").date()


def _format_dt(dt: datetime, all_day: bool = False) -> str:
    if all_day:
        return dt.date().isoformat()
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M")


def fit_font(widget: QWidget, text: str, max_size: int = 14, min_size: int = 7) -> None:
    if widget is None:
        return
    rect = widget.contentsRect()
    if rect.width() <= 4 or rect.height() <= 4:
        return
    for size in range(max_size, min_size - 1, -1):
        font = QFont(widget.font())
        font.setPointSize(size)
        fm = widget.fontMetrics()
        widget.setFont(font)
        fm = widget.fontMetrics()
        if fm.horizontalAdvance(text) <= rect.width() - 4 and fm.height() <= rect.height() - 2:
            return
    font = QFont(widget.font())
    font.setPointSize(min_size)
    widget.setFont(font)


class FontFitLabel(QLabel):
    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setWordWrap(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        fit_font(self, self.text())


class FontFitButton(QPushButton):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        fit_font(self, self.text())


class FontFitCheckBox(QCheckBox):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        fit_font(self, self.text())


class FontFitComboBox(QComboBox):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        fit_font(self, self.currentText())


class EventDetailPopup(QDialog):
    edit_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, event: EventRecord):
        super().__init__()
        self.event = event
        self.setWindowTitle("Event Details")
        self.setModal(True)
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {event.background_color};")
        top.addWidget(dot)
        title = FontFitLabel(event.summary)
        f = QFont(title.font())
        f.setPointSize(14)
        f.setBold(True)
        title.setFont(f)
        top.addWidget(title, 1)
        close_btn = FontFitButton("✕")
        close_btn.clicked.connect(self.close)
        top.addWidget(close_btn)
        layout.addLayout(top)

        time_label = FontFitLabel(f"{_format_dt(event.start_dt, event.all_day)} → {_format_dt(event.end_dt, event.all_day)}")
        layout.addWidget(time_label)

        reminder_text = "No reminder"
        if event.reminder_overrides:
            first = event.reminder_overrides[0]
            reminder_text = f"Reminder: {first.get('minutes', '?')}m ({first.get('method', 'popup')})"
        layout.addWidget(FontFitLabel(reminder_text))
        layout.addWidget(FontFitLabel(f"Calendar: {event.calendar_name}"))

        icon_row = QHBoxLayout()
        edit_btn = FontFitButton("✎")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(event.google_event_id))
        icon_row.addWidget(edit_btn)

        delete_btn = FontFitButton("🗑")
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(event.google_event_id))
        icon_row.addWidget(delete_btn)

        email_btn = FontFitButton("✉")
        email_btn.setToolTip("Coming Soon — Gmail module not installed.")
        icon_row.addWidget(email_btn)

        more_btn = FontFitButton("⋮")
        icon_row.addWidget(more_btn)
        layout.addLayout(icon_row)

        invite = FontFitButton("Invite via link")
        invite_link = ""
        if event.conference_data:
            links = event.conference_data.get("entryPoints", [])
            if links:
                invite_link = links[0].get("uri", "")
        if not invite_link:
            invite_link = event.html_link
        invite.setToolTip(invite_link)
        layout.addWidget(invite)


class WeekCalendarWidget(QWidget):
    event_clicked = Signal(str)
    empty_slot_clicked = Signal(datetime)

    def __init__(self):
        super().__init__()
        self.events: list[EventRecord] = []
        self.week_anchor = datetime.now(UTC).date()
        self.today = datetime.now(UTC).date()
        self.setMinimumHeight(600)

    def set_events(self, events: list[EventRecord]) -> None:
        self.events = events
        self.update()

    def set_anchor(self, d: date) -> None:
        self.week_anchor = d
        self.update()

    def mousePressEvent(self, event):
        rect = self.contentsRect()
        hour_col_w = 65
        header_h = 45
        day_w = max(1, (rect.width() - hour_col_w) / 7)
        body_h = rect.height() - header_h
        hour_h = max(1, body_h / 24)

        x = event.position().x()
        y = event.position().y()
        if x < hour_col_w or y < header_h:
            return
        day_idx = int((x - hour_col_w) // day_w)
        hour = int((y - header_h) // hour_h)
        clicked_dt = datetime.combine(self.week_anchor + timedelta(days=day_idx), time(hour=min(23, max(0, hour))), tzinfo=UTC)

        for rec in self.events:
            s = rec.start_dt
            e = rec.end_dt
            if s.date() <= clicked_dt.date() <= e.date():
                if s.date() == clicked_dt.date() and s.hour <= hour <= max(s.hour, e.hour):
                    self.event_clicked.emit(rec.google_event_id)
                    return
        self.empty_slot_clicked.emit(clicked_dt)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.contentsRect()

        hour_col_w = 65
        header_h = 45
        day_w = max(1, (rect.width() - hour_col_w) / 7)
        body_h = rect.height() - header_h
        hour_h = max(1, body_h / 24)

        p.fillRect(rect, QColor("#111418"))
        p.fillRect(QRect(rect.x(), rect.y(), hour_col_w, rect.height()), QColor("#1A1F27"))

        for h in range(24):
            y = int(rect.y() + header_h + h * hour_h)
            p.setPen(QPen(QColor("#2B3240"), 1))
            p.drawLine(rect.x() + hour_col_w, y, rect.right(), y)
            hour_label = datetime.combine(date.today(), time(h, 0)).strftime("%I %p").lstrip("0")
            p.setPen(QColor("#C8D1E6"))
            p.drawText(QRect(rect.x() + 4, y - 8, hour_col_w - 8, 16), Qt.AlignLeft | Qt.AlignVCenter, hour_label)

        for d in range(8):
            x = int(rect.x() + hour_col_w + d * day_w)
            p.setPen(QPen(QColor("#2B3240"), 1))
            p.drawLine(x, rect.y(), x, rect.bottom())

        for i in range(7):
            current = self.week_anchor + timedelta(days=i)
            x = int(rect.x() + hour_col_w + i * day_w)
            day_header = current.strftime("%a %d")
            header_rect = QRect(x + 2, rect.y() + 2, int(day_w) - 4, header_h - 4)
            if current == self.today:
                p.fillRect(header_rect, QColor("#1E3A8A"))
            p.setPen(QColor("#F6F8FF"))
            p.drawText(header_rect, Qt.AlignCenter, day_header)

        now = datetime.now(UTC)
        if self.week_anchor <= now.date() <= self.week_anchor + timedelta(days=6):
            day_idx = (now.date() - self.week_anchor).days
            x0 = int(rect.x() + hour_col_w + day_idx * day_w)
            y = int(rect.y() + header_h + (now.hour + now.minute / 60) * hour_h)
            p.setPen(QPen(QColor("#FF4D4D"), 2))
            p.drawLine(x0 + 1, y, int(x0 + day_w - 2), y)

        for ev in self.events:
            day_idx = (ev.start_dt.date() - self.week_anchor).days
            if day_idx < 0 or day_idx > 6:
                continue
            x = int(rect.x() + hour_col_w + day_idx * day_w + 2)
            start_hour = ev.start_dt.hour + ev.start_dt.minute / 60
            end_hour = ev.end_dt.hour + ev.end_dt.minute / 60
            if ev.all_day:
                start_hour, end_hour = 0, 1
            y = int(rect.y() + header_h + start_hour * hour_h + 1)
            h = max(18, int((end_hour - start_hour) * hour_h - 2))
            w = int(day_w - 4)
            p.fillRect(QRect(x, y, w, h), QColor(ev.background_color))
            p.setPen(QColor(ev.foreground_color))
            txt = f"{ev.summary}\n{ev.start_dt.strftime('%H:%M')}–{ev.end_dt.strftime('%H:%M')}"
            p.drawText(QRect(x + 3, y + 3, w - 6, h - 6), Qt.TextWordWrap, txt)


class SyncWorker(QObject):
    sync_completed = Signal(dict)
    sync_error = Signal(str)

    def __init__(self, runtime: "GoogleCalendarRuntime"):
        super().__init__()
        self.runtime = runtime
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.run_sync)

    def start(self):
        self.timer.start(self.runtime.current_sync_interval_ms())

    def trigger_now(self):
        self.run_sync()

    def run_sync(self):
        try:
            payload = self.runtime.perform_sync()
            self.sync_completed.emit(payload)
            self.timer.start(self.runtime.current_sync_interval_ms())
        except Exception as ex:
            self.sync_error.emit(str(ex))


class ReminderWorker(QObject):
    reminder_payload = Signal(dict)

    def __init__(self, runtime: "GoogleCalendarRuntime"):
        super().__init__()
        self.runtime = runtime
        self.minute_timer = QTimer(self)
        self.minute_timer.timeout.connect(self.evaluate_reminders)
        self.midnight_timer = QTimer(self)
        self.midnight_timer.timeout.connect(self._check_midnight)

    def start(self):
        QTimer.singleShot(60_000, self.evaluate_reminders)
        self.runtime.log("Reminder evaluation delay: 60 seconds placeholder for host wake observation.")
        self.minute_timer.start(60_000)
        self.midnight_timer.start(60_000)

    def _check_midnight(self):
        now = datetime.now(UTC)
        if now.hour == 0 and now.minute == 0:
            self.evaluate_reminders()

    def evaluate_reminders(self):
        for item in self.runtime.build_calendar_reminders():
            self.reminder_payload.emit(item)
        for batch in self.runtime.build_task_batches():
            self.reminder_payload.emit(batch)


class GoogleCalendarRuntime(QObject):
    data_changed = Signal()
    status_changed = Signal(str)
    request_open_event = Signal(str)
    request_focus_datetime = Signal(datetime)

    def __init__(self, deck_api: dict[str, Any]):
        super().__init__()
        self.deck_api = deck_api
        self.log: Callable[[str], None] = deck_api.get("log") if callable(deck_api.get("log")) else (lambda _m: None)
        self.cfg_get: Callable[[str, Any], Any] = (
            deck_api.get("cfg_get") if callable(deck_api.get("cfg_get")) else (lambda _k, d=None: d)
        )
        self.cfg_set: Callable[[str, Any], None] = (
            deck_api.get("cfg_set") if callable(deck_api.get("cfg_set")) else (lambda _k, _v: None)
        )
        self.cfg_path: Optional[Callable[[str], str]] = deck_api.get("cfg_path") if callable(deck_api.get("cfg_path")) else None
        self.ai_handoff: Optional[Callable[..., Any]] = (
            deck_api.get("request_ai_interpretation") if callable(deck_api.get("request_ai_interpretation")) else None
        )
        self.on_tab_change: Optional[Callable[..., Any]] = deck_api.get("set_active_module_tab")
        self.host_battery_status_getter: Optional[Callable[[], bool]] = deck_api.get("is_on_battery")

        self.auth_status = "pending_setup"
        self.auth_blocker = "Host-level google_auth state API unavailable from module scope; using local token inspection only."
        self.battery_blocker = "Host battery-state signal unavailable; battery interval settings active in UI/local config only."
        self.ai_blocker = "Host AI handoff unavailable from module scope."

        self.sync_token_by_calendar: dict[str, str] = {}
        self.google_colors_event_palette: dict[str, dict[str, str]] = {}
        self.calendars: dict[str, CalendarRecord] = {}
        self.events_by_google_id: dict[str, EventRecord] = {}
        self.tasks_by_google_id: dict[str, TaskRecord] = {}
        self.visible_calendar_ids: set[str] = set()
        self.last_synced_at: Optional[datetime] = None

        self.sync_settings = {
            "fetch_mode": self.cfg_get("google_calendar_fetch_mode", "new_only"),
            "interval_value": int(self.cfg_get("google_calendar_interval_value", 5)),
            "interval_unit": self.cfg_get("google_calendar_interval_unit", "minutes"),
            "battery_detection_enabled": bool(self.cfg_get("google_calendar_battery_detection_enabled", True)),
            "battery_interval_minutes": int(self.cfg_get("google_calendar_battery_interval_minutes", 10)),
            "battery_override_disabled": bool(self.cfg_get("google_calendar_battery_override_disabled", False)),
        }

        self._sync_thread: Optional[QThread] = None
        self._sync_worker: Optional[SyncWorker] = None
        self._reminder_thread: Optional[QThread] = None
        self._reminder_worker: Optional[ReminderWorker] = None

        self._google_calendar_service = None
        self._google_tasks_service = None

        self.init_auth_state()
        self._init_workers()

    def module_storage_path(self, filename: str) -> Path:
        if callable(self.cfg_path):
            p = Path(self.cfg_path(filename))
            p.parent.mkdir(parents=True, exist_ok=True)
            return p
        default_dir = Path.cwd() / "Google"
        default_dir.mkdir(parents=True, exist_ok=True)
        return default_dir / filename

    def init_auth_state(self) -> None:
        token_path = self.module_storage_path("token.json")
        if not token_path.exists():
            self.auth_status = "pending_setup"
            self.status_changed.emit("Google auth pending setup")
            return
        try:
            payload = json.loads(token_path.read_text(encoding="utf-8"))
            scopes = set(payload.get("scopes") or [])
            token = payload.get("token")
            if not token:
                self.auth_status = "pending_setup"
            elif not REQUIRED_SCOPES.issubset(scopes):
                self.auth_status = "reauth_required"
            else:
                self.auth_status = "ready"
            self.status_changed.emit(f"Google auth status: {self.auth_status}")
        except Exception:
            self.auth_status = "pending_setup"
            self.status_changed.emit("Google auth pending setup")

    def attach_google_services(self, calendar_service: Any, tasks_service: Any) -> None:
        self._google_calendar_service = calendar_service
        self._google_tasks_service = tasks_service

    def _init_workers(self) -> None:
        self._sync_thread = QThread()
        self._sync_worker = SyncWorker(self)
        self._sync_worker.moveToThread(self._sync_thread)
        self._sync_thread.started.connect(self._sync_worker.start)
        self._sync_worker.sync_completed.connect(self._on_sync_completed)
        self._sync_worker.sync_error.connect(self._on_sync_error)
        self._sync_thread.start()

        self._reminder_thread = QThread()
        self._reminder_worker = ReminderWorker(self)
        self._reminder_worker.moveToThread(self._reminder_thread)
        self._reminder_thread.started.connect(self._reminder_worker.start)
        self._reminder_worker.reminder_payload.connect(self._send_ai_payload)
        self._reminder_thread.start()

    def current_sync_interval_ms(self) -> int:
        value = max(1, int(self.sync_settings["interval_value"]))
        unit = self.sync_settings["interval_unit"]
        battery_active = False
        if self.host_battery_status_getter and callable(self.host_battery_status_getter):
            try:
                battery_active = bool(self.host_battery_status_getter())
                self.battery_blocker = ""
            except Exception:
                battery_active = False
        if (
            battery_active
            and self.sync_settings["battery_detection_enabled"]
            and not self.sync_settings["battery_override_disabled"]
        ):
            return max(1, int(self.sync_settings["battery_interval_minutes"])) * 60 * 1000
        if unit == "seconds":
            return value * 1000
        if unit == "hours":
            return value * 3600 * 1000
        return value * 60 * 1000

    def set_sync_setting(self, key: str, value: Any) -> None:
        self.sync_settings[key] = value
        self.cfg_set(f"google_calendar_{key}", value)

    def trigger_sync_now(self) -> None:
        if self._sync_worker:
            self._sync_worker.trigger_now()

    def _on_sync_completed(self, _payload: dict) -> None:
        self.last_synced_at = datetime.now(UTC)
        self.data_changed.emit()

    def _on_sync_error(self, error: str) -> None:
        self.log(f"GoogleCalendar sync error: {error}")

    def perform_sync(self) -> dict[str, Any]:
        if not self._google_calendar_service or not self._google_tasks_service:
            return {"status": "no_services"}

        calendars = self._fetch_calendars()
        palette = self._fetch_color_palette()
        self.google_colors_event_palette = palette

        for cal in calendars:
            cal_id = cal["id"]
            if self.sync_settings.get("fetch_mode", "new_only") == "full":
                self._sync_calendar_full(cal_id)
            else:
                token = self.sync_token_by_calendar.get(cal_id)
                if token:
                    ok = self._sync_calendar_incremental(cal_id, token)
                    if not ok:
                        self._sync_calendar_full(cal_id)
                else:
                    self._sync_calendar_full(cal_id)

        self._sync_tasks_all_lists()
        return {"status": "ok", "events": len(self.events_by_google_id), "tasks": len(self.tasks_by_google_id)}

    def _fetch_calendars(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page_token = None
        while True:
            req = self._google_calendar_service.calendarList().list(pageToken=page_token)
            res = req.execute()
            for item in res.get("items", []):
                section = "My calendars"
                if item.get("accessRole") in {"reader", "freeBusyReader"}:
                    section = "Other calendars"
                if "booking" in str(item.get("summary", "")).lower():
                    section = "Booking pages"
                rec = CalendarRecord(
                    id=item.get("id", ""),
                    summary=item.get("summary", "Untitled"),
                    access_role=item.get("accessRole", ""),
                    background_color=item.get("backgroundColor", "#4285F4"),
                    foreground_color=item.get("foregroundColor", "#FFFFFF"),
                    selected=bool(item.get("selected", True)),
                    hidden=bool(item.get("hidden", False)),
                    section=section,
                )
                self.calendars[rec.id] = rec
                if rec.id not in self.visible_calendar_ids and rec.selected and not rec.hidden:
                    self.visible_calendar_ids.add(rec.id)
                out.append(item)
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        return out

    def _fetch_color_palette(self) -> dict[str, dict[str, str]]:
        response = self._google_calendar_service.colors().get().execute()
        return response.get("event", {})

    def _full_pull_time_min(self) -> str:
        start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        time_min = start_of_day.isoformat() + "Z"
        return time_min

    def _sync_calendar_full(self, calendar_id: str) -> None:
        page_token = None
        next_sync_token = None
        while True:
            req = self._google_calendar_service.events().list(
                calendarId=calendar_id,
                pageToken=page_token,
                singleEvents=True,
                showDeleted=True,
                timeMin=self._full_pull_time_min(),
            )
            res = req.execute()
            for item in res.get("items", []):
                self._reconcile_event(calendar_id, item)
            page_token = res.get("nextPageToken")
            next_sync_token = res.get("nextSyncToken") or next_sync_token
            if not page_token:
                break
        if next_sync_token:
            self.sync_token_by_calendar[calendar_id] = next_sync_token

    def _sync_calendar_incremental(self, calendar_id: str, sync_token: str) -> bool:
        try:
            page_token = None
            next_sync_token = None
            while True:
                req = self._google_calendar_service.events().list(
                    calendarId=calendar_id,
                    pageToken=page_token,
                    singleEvents=True,
                    showDeleted=True,
                    syncToken=sync_token,
                )
                res = req.execute()
                for item in res.get("items", []):
                    self._reconcile_event(calendar_id, item)
                page_token = res.get("nextPageToken")
                next_sync_token = res.get("nextSyncToken") or next_sync_token
                if not page_token:
                    break
            if next_sync_token:
                self.sync_token_by_calendar[calendar_id] = next_sync_token
            return True
        except Exception:
            return False

    def _event_colors(self, calendar_id: str, item: dict[str, Any]) -> tuple[str, str]:
        color_id = item.get("colorId")
        if color_id and color_id in self.google_colors_event_palette:
            entry = self.google_colors_event_palette[color_id]
            return entry.get("background", "#4285F4"), entry.get("foreground", "#FFFFFF")
        cal = self.calendars.get(calendar_id)
        if cal:
            return cal.background_color, cal.foreground_color
        return "#4285F4", "#FFFFFF"

    def _reconcile_event(self, calendar_id: str, item: dict[str, Any]) -> None:
        google_event_id = item.get("id", "")
        if not google_event_id:
            return
        status = item.get("status", "confirmed")

        start_obj = item.get("start", {})
        end_obj = item.get("end", {})
        start_dt, is_all_day_start = _parse_google_datetime(start_obj.get("dateTime") or start_obj.get("date"))
        end_dt, is_all_day_end = _parse_google_datetime(end_obj.get("dateTime") or end_obj.get("date"))
        all_day = is_all_day_start or is_all_day_end
        background, foreground = self._event_colors(calendar_id, item)
        cal_name = self.calendars.get(calendar_id).summary if calendar_id in self.calendars else calendar_id

        existing = self.events_by_google_id.get(google_event_id)
        if status == "cancelled":
            if existing:
                existing.status = "cancelled"
            else:
                self.events_by_google_id[google_event_id] = EventRecord(
                    google_event_id=google_event_id,
                    calendar_id=calendar_id,
                    calendar_name=cal_name,
                    summary=item.get("summary", "(cancelled)"),
                    description=item.get("description", ""),
                    location=item.get("location", ""),
                    start_dt=start_dt,
                    end_dt=end_dt,
                    all_day=all_day,
                    status="cancelled",
                    color_id=item.get("colorId"),
                    background_color=background,
                    foreground_color=foreground,
                    reminder_overrides=item.get("reminders", {}).get("overrides", []),
                    attendees=item.get("attendees", []),
                    html_link=item.get("htmlLink", ""),
                    conference_data=item.get("conferenceData", {}),
                )
            return

        payload = EventRecord(
            google_event_id=google_event_id,
            calendar_id=calendar_id,
            calendar_name=cal_name,
            summary=item.get("summary", "Untitled"),
            description=item.get("description", ""),
            location=item.get("location", ""),
            start_dt=start_dt,
            end_dt=end_dt,
            all_day=all_day,
            status=status,
            color_id=item.get("colorId"),
            background_color=background,
            foreground_color=foreground,
            reminder_overrides=item.get("reminders", {}).get("overrides", []),
            attendees=item.get("attendees", []),
            html_link=item.get("htmlLink", ""),
            conference_data=item.get("conferenceData", {}),
        )

        self.events_by_google_id[google_event_id] = payload

    def _sync_tasks_all_lists(self) -> None:
        lists = self._google_tasks_service.tasklists().list().execute().get("items", [])
        for task_list in lists:
            list_id = task_list.get("id", "")
            list_name = task_list.get("title", "Tasks")
            tasks = self._google_tasks_service.tasks().list(tasklist=list_id, showCompleted=True, showDeleted=True).execute()
            for task in tasks.get("items", []):
                task_id = task.get("id", "")
                if not task_id:
                    continue
                self.tasks_by_google_id[task_id] = TaskRecord(
                    google_task_id=task_id,
                    task_list_id=list_id,
                    task_list_name=list_name,
                    title=task.get("title", "Untitled Task"),
                    notes=task.get("notes", ""),
                    due_date=_parse_google_task_due(task.get("due")),
                    status=task.get("status", "needsAction"),
                    deleted=bool(task.get("deleted", False)),
                    hidden=bool(task.get("hidden", False)),
                )

    def visible_events(self) -> list[EventRecord]:
        now = datetime.now(UTC)
        return [
            e
            for e in self.events_by_google_id.values()
            if e.calendar_id in self.visible_calendar_ids and e.status != "cancelled" and e.end_dt >= now
        ]

    def events_for_week(self, anchor: date) -> list[EventRecord]:
        end = anchor + timedelta(days=7)
        return [e for e in self.visible_events() if anchor <= e.start_dt.date() < end]

    def list_window_events(self, window: str) -> list[EventRecord]:
        now = datetime.now(UTC)
        days = 30
        if window == "3 Months":
            days = 90
        elif window == "1 Year":
            days = 365
        edge = now + timedelta(days=days)
        return [e for e in self.visible_events() if now <= e.start_dt <= edge]

    def build_calendar_reminders(self) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        payloads: list[dict[str, Any]] = []
        for e in self.visible_events():
            if e.status == "cancelled":
                continue
            for override in e.reminder_overrides:
                minutes = int(override.get("minutes", 0))
                trigger = e.start_dt - timedelta(minutes=minutes)
                if trigger <= now <= trigger + timedelta(minutes=1):
                    prompt = (
                        f"You have a calendar event coming up in {minutes} minutes:\n"
                        f"Title: {e.summary}\n"
                        f"Date: {e.start_dt.date().isoformat()}\n"
                        f"Time: {e.start_dt.strftime('%H:%M')} to {e.end_dt.strftime('%H:%M')}\n"
                        f"Description: {e.description}\n"
                        f"Calendar: {e.calendar_name}\n"
                        "Respond in character with awareness of this upcoming event."
                    )
                    payloads.append(
                        {
                            "type": "Calendar Reminder",
                            "title": e.summary,
                            "date": e.start_dt.date().isoformat(),
                            "start": e.start_dt.isoformat(),
                            "end": e.end_dt.isoformat(),
                            "description": e.description,
                            "calendar": e.calendar_name,
                            "reminder_trigger_window": f"{minutes} minutes",
                            "location": e.location,
                            "attendees": e.attendees,
                            "prompt": prompt,
                        }
                    )
                    break
        return payloads

    def build_task_batches(self) -> list[dict[str, Any]]:
        today = datetime.now(UTC).date()
        tomorrow = today + timedelta(days=1)
        batches: list[dict[str, Any]] = []
        all_tasks = [t for t in self.tasks_by_google_id.values() if t.status != "completed" and not t.deleted]

        due_tomorrow = [t for t in all_tasks if t.due_date == tomorrow]
        if due_tomorrow:
            batches.append(self._task_batch_payload("Due Tomorrow", TASK_PROMPT_DUE_TOMORROW, due_tomorrow))

        due_today = [t for t in all_tasks if t.due_date == today]
        if due_today:
            batches.append(self._task_batch_payload("Due Today", TASK_PROMPT_DUE_TODAY, due_today))

        past_due = [
            t
            for t in all_tasks
            if t.due_date is not None and timedelta(days=1) <= (today - t.due_date) <= timedelta(days=30)
        ]
        if past_due:
            batches.append(self._task_batch_payload("Past Due 1 to 30 days", TASK_PROMPT_PAST_DUE_1_30, past_due))

        critical = [t for t in all_tasks if t.due_date is not None and (today - t.due_date) > timedelta(days=30)]
        if critical:
            lines = "\n".join([f"{t.title} — {t.notes or '(No description)'}" for t in critical])
            batches.append(
                {
                    "type": "Task Reminder Batch",
                    "batch": "Critically Overdue 30+ days",
                    "prompt": f"{TASK_PROMPT_CRITICALLY_OVERDUE}\n{lines}",
                    "tasks": [self._task_as_dict(t) for t in critical],
                }
            )
        return batches

    def _task_batch_payload(self, name: str, prompt: str, tasks: list[TaskRecord]) -> dict[str, Any]:
        lines = "\n".join([f"{t.title} — {t.notes or '(No description)'}" for t in tasks])
        return {
            "type": "Task Reminder Batch",
            "batch": name,
            "prompt": f"{prompt}\n{lines}",
            "tasks": [self._task_as_dict(t) for t in tasks],
        }

    def _task_as_dict(self, t: TaskRecord) -> dict[str, Any]:
        return {
            "task_name": t.title,
            "description": t.notes,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "list": t.task_list_name,
        }

    def _send_ai_payload(self, payload: dict[str, Any]) -> None:
        if not callable(self.ai_handoff):
            return
        try:
            self.ai_handoff("google_calendar", payload)
            self.ai_blocker = ""
        except Exception:
            pass

    def send_event_to_ai(self, payload: dict[str, Any]) -> None:
        self._send_ai_payload(payload)

    def send_task_to_ai(self, payload: dict[str, Any]) -> None:
        self._send_ai_payload(payload)

    def send_list_to_ai(self, window: str, events: list[EventRecord]) -> None:
        lines = [f"{e.summary} — {_format_dt(e.start_dt, e.all_day)} — {e.calendar_name}" for e in events]
        prompt = f"Upcoming events for the next {window}:\n" + "\n".join(lines)
        self._send_ai_payload({"type": "Upcoming Events", "window": window, "prompt": prompt})


class TaskColumnWidget(QWidget):
    task_toggled = Signal(str, bool)

    def __init__(self, list_name: str, tasks: list[TaskRecord]):
        super().__init__()
        layout = QVBoxLayout(self)
        header_row = QHBoxLayout()
        header = FontFitLabel(list_name)
        f = QFont(header.font())
        f.setBold(True)
        header.setFont(f)
        header_row.addWidget(header)

        menu_btn = QToolButton()
        menu_btn.setText("⋮")
        menu = QMenu(menu_btn)
        for txt in [
            "Sort by: My order",
            "Sort by: Date",
            "Sort by: Deadline",
            "Sort by: Starred recently",
            "Sort by: Title",
            "Rename list",
            "Delete list",
            "Print list",
            "Delete all completed tasks",
            "Clean up old tasks",
        ]:
            menu.addAction(txt)
        menu_btn.setMenu(menu)
        menu_btn.setPopupMode(QToolButton.InstantPopup)
        header_row.addWidget(menu_btn)
        layout.addLayout(header_row)

        add_task_entry = QLineEdit()
        add_task_entry.setPlaceholderText("Add a task")
        layout.addWidget(add_task_entry)

        for task in tasks:
            row = QHBoxLayout()
            cb = QCheckBox()
            cb.setChecked(task.status == "completed")
            cb.stateChanged.connect(lambda state, gid=task.google_task_id: self.task_toggled.emit(gid, state == Qt.Checked))
            row.addWidget(cb)
            row_label = FontFitLabel(task.title)
            row.addWidget(row_label, 1)
            layout.addLayout(row)
        layout.addStretch(1)


class CompactTaskSidebar(QWidget):
    def __init__(self, runtime: GoogleCalendarRuntime):
        super().__init__()
        self.runtime = runtime
        layout = QVBoxLayout(self)
        layout.addWidget(FontFitLabel("All tasks"))
        layout.addWidget(FontFitLabel("Starred"))
        layout.addWidget(FontFitLabel("Lists"))
        list_widget = QListWidget()
        for list_name, tasks in self._grouped().items():
            item = QListWidgetItem(f"{list_name} ({len(tasks)})")
            list_widget.addItem(item)
        layout.addWidget(list_widget)
        layout.addWidget(FontFitButton("Create new list"))

    def _grouped(self) -> dict[str, list[TaskRecord]]:
        data: dict[str, list[TaskRecord]] = {}
        for t in self.runtime.tasks_by_google_id.values():
            if t.deleted:
                continue
            data.setdefault(t.task_list_name, []).append(t)
        return data


class GoogleWorkspaceWidget(QWidget):
    def __init__(self, runtime: GoogleCalendarRuntime):
        super().__init__()
        self.runtime = runtime
        self.current_anchor = datetime.now(UTC).date() - timedelta(days=datetime.now(UTC).weekday())
        self.mode = "calendar"

        main = QVBoxLayout(self)
        top = QHBoxLayout()

        self.today_btn = FontFitButton("Today")
        self.prev_btn = FontFitButton("◀")
        self.next_btn = FontFitButton("▶")
        self.period_label = FontFitLabel(datetime.now(UTC).strftime("%B %Y"))
        top.addWidget(self.today_btn)
        top.addWidget(self.prev_btn)
        top.addWidget(self.next_btn)
        top.addWidget(self.period_label, 1)

        self.view_selector = FontFitComboBox()
        self.view_selector.addItems(["Day", "Week", "Month", "Year", "Schedule", "4 Days"])
        self.view_selector.setCurrentText("Week")
        top.addWidget(self.view_selector)

        self.icon_col = QVBoxLayout()
        self.tasks_icon = FontFitButton("✓")
        self.contacts_icon = FontFitButton("👥")
        self.maps_icon = FontFitButton("🗺")
        self.plus_icon = FontFitButton("+")
        self.contacts_icon.setToolTip("Coming Soon")
        self.maps_icon.setToolTip("Coming Soon")
        self.icon_col.addWidget(self.tasks_icon)
        self.icon_col.addWidget(self.contacts_icon)
        self.icon_col.addWidget(self.maps_icon)
        self.icon_col.addWidget(self.plus_icon)
        icon_wrap = QWidget()
        icon_wrap.setLayout(self.icon_col)
        top.addWidget(icon_wrap)
        main.addLayout(top)

        self.splitter = QSplitter(Qt.Horizontal)
        self.calendar_widget = WeekCalendarWidget()
        self.task_sidebar = CompactTaskSidebar(runtime)
        self.task_sidebar.setVisible(False)
        self.splitter.addWidget(self.calendar_widget)
        self.splitter.addWidget(self.task_sidebar)
        self.splitter.setSizes([80, 20])
        main.addWidget(self.splitter, 1)

        self.task_full_widget = QWidget()
        self.task_full_layout = QHBoxLayout(self.task_full_widget)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.splitter)
        self.stack.addWidget(self.task_full_widget)
        main.addWidget(self.stack, 8)

        self.today_btn.clicked.connect(self._go_today)
        self.prev_btn.clicked.connect(lambda: self._shift(-7))
        self.next_btn.clicked.connect(lambda: self._shift(7))
        self.tasks_icon.clicked.connect(self.toggle_sidebar_tasks)
        self.calendar_widget.event_clicked.connect(self._open_event_popup)
        self.calendar_widget.empty_slot_clicked.connect(self._slot_clicked)
        self.runtime.data_changed.connect(self.refresh)
        self.refresh()

    def _go_today(self):
        now = datetime.now(UTC).date()
        self.current_anchor = now - timedelta(days=now.weekday())
        self.refresh()

    def _shift(self, days: int):
        self.current_anchor += timedelta(days=days)
        self.refresh()

    def toggle_sidebar_tasks(self):
        on = not self.task_sidebar.isVisible()
        self.task_sidebar.setVisible(on)
        if on:
            self.splitter.setSizes([80, 20])
        else:
            self.splitter.setSizes([100, 0])

    def set_mode(self, mode: str):
        self.mode = mode
        if mode == "tasks":
            self._build_task_columns()
            self.stack.setCurrentIndex(1)
        else:
            self.stack.setCurrentIndex(0)

    def _build_task_columns(self):
        while self.task_full_layout.count():
            child = self.task_full_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        grouped: dict[str, list[TaskRecord]] = {}
        for t in self.runtime.tasks_by_google_id.values():
            if t.deleted:
                continue
            grouped.setdefault(t.task_list_name, []).append(t)
        for list_name, tasks in grouped.items():
            self.task_full_layout.addWidget(TaskColumnWidget(list_name, tasks), 1)

    def _open_event_popup(self, event_id: str):
        ev = self.runtime.events_by_google_id.get(event_id)
        if not ev:
            return
        popup = EventDetailPopup(ev)
        popup.exec()

    def _slot_clicked(self, slot_dt: datetime):
        if callable(self.runtime.on_tab_change):
            try:
                self.runtime.on_tab_change("google_calendar_main", "Event Controls")
            except Exception:
                pass
        self.runtime.request_focus_datetime.emit(slot_dt)

    def navigate_to_event_date(self, d: datetime):
        self.current_anchor = d.date() - timedelta(days=d.weekday())
        self.set_mode("calendar")
        self.refresh()

    def refresh(self):
        self.period_label.setText(self.current_anchor.strftime("%B %Y"))
        self.calendar_widget.set_anchor(self.current_anchor)
        self.calendar_widget.set_events(self.runtime.events_for_week(self.current_anchor))


class EventControlsTab(QWidget):
    task_mode_requested = Signal(bool)

    def __init__(self, runtime: GoogleCalendarRuntime):
        super().__init__()
        self.runtime = runtime
        self.form_date_prefill: Optional[datetime] = None
        root = QVBoxLayout(self)

        self.calendar_groups: dict[str, QGroupBox] = {}
        for section in ["My calendars", "Other calendars", "Booking pages"]:
            group = QGroupBox(section)
            group.setCheckable(True)
            group.setChecked(True)
            group_layout = QVBoxLayout(group)
            group.setLayout(group_layout)
            root.addWidget(group)
            self.calendar_groups[section] = group

        form = QFormLayout()
        self.title = QLineEdit()
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.start = QTimeEdit()
        self.end = QTimeEdit()
        self.all_day = QCheckBox("All day")
        self.description = QTextEdit()
        self.location = QLineEdit()
        self.calendar_select = FontFitComboBox()
        self.reminder_minutes = QSpinBox()
        self.reminder_minutes.setRange(0, 10080)
        self.reminder_method = FontFitComboBox()
        self.reminder_method.addItems(["popup", "email"])
        self.recurrence = FontFitComboBox()
        self.recurrence.addItems(["none", "daily", "weekly", "monthly", "yearly", "custom"])

        form.addRow("Title", self.title)
        form.addRow("Date", self.date)
        form.addRow("Start time", self.start)
        form.addRow("End time", self.end)
        form.addRow("All day", self.all_day)
        form.addRow("Description", self.description)
        form.addRow("Location", self.location)
        form.addRow("Calendar", self.calendar_select)
        form.addRow("Reminder minutes before", self.reminder_minutes)
        form.addRow("Reminder method", self.reminder_method)
        form.addRow("Recurrence", self.recurrence)
        root.addLayout(form)

        btn_row = QHBoxLayout()
        self.btn_new = FontFitButton("New Event")
        self.btn_save = FontFitButton("Save")
        self.btn_delete = FontFitButton("Delete")
        self.btn_cancel = FontFitButton("Cancel")
        self.btn_ai = FontFitButton("Send to AI")
        for b in [self.btn_new, self.btn_save, self.btn_delete, self.btn_cancel, self.btn_ai]:
            btn_row.addWidget(b)
        root.addLayout(btn_row)

        self.btn_ai.clicked.connect(self.send_to_ai)
        self.runtime.data_changed.connect(self.refresh_calendars)
        self.runtime.request_focus_datetime.connect(self.prefill_from_slot)
        self.refresh_calendars()

    def prefill_from_slot(self, slot_dt: datetime):
        self.form_date_prefill = slot_dt
        self.date.setDate(QDate(slot_dt.year, slot_dt.month, slot_dt.day))
        self.start.setTime(QTime(slot_dt.hour, 0))
        self.end.setTime(QTime((slot_dt.hour + 1) % 24, 0))

    def refresh_calendars(self):
        for group in self.calendar_groups.values():
            layout = group.layout()
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()

        self.calendar_select.clear()
        for cal in self.runtime.calendars.values():
            row = QWidget()
            rlay = QHBoxLayout(row)
            cb = FontFitCheckBox(cal.summary)
            cb.setChecked(cal.id in self.runtime.visible_calendar_ids)
            cb.stateChanged.connect(lambda state, cid=cal.id: self._set_visible(cid, state == Qt.Checked))
            dot = QLabel("■")
            dot.setStyleSheet(f"color: {cal.background_color};")
            rlay.addWidget(dot)
            rlay.addWidget(cb, 1)
            self.calendar_groups.get(cal.section, self.calendar_groups["Other calendars"]).layout().addWidget(row)
            self.calendar_select.addItem(cal.summary, cal.id)

    def _set_visible(self, cal_id: str, visible: bool):
        if visible:
            self.runtime.visible_calendar_ids.add(cal_id)
        else:
            self.runtime.visible_calendar_ids.discard(cal_id)
        self.runtime.data_changed.emit()

    def send_to_ai(self):
        payload = {
            "type": "Calendar Event",
            "title": self.title.text(),
            "date": self.date.date().toString("yyyy-MM-dd"),
            "start": self.start.time().toString("HH:mm"),
            "end": self.end.time().toString("HH:mm"),
            "description": self.description.toPlainText(),
            "calendar": self.calendar_select.currentText(),
            "reminder": {
                "minutes": self.reminder_minutes.value(),
                "method": self.reminder_method.currentText(),
            },
        }
        self.runtime.send_event_to_ai(payload)


class TaskControlsTab(QWidget):
    mode_toggle = Signal(bool)

    def __init__(self, runtime: GoogleCalendarRuntime):
        super().__init__()
        self.runtime = runtime
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.notes = QTextEdit()
        self.due_date = QDateEdit()
        self.due_date.setCalendarPopup(True)
        self.list_selector = FontFitComboBox()
        form.addRow("Task name", self.name)
        form.addRow("Notes / description", self.notes)
        form.addRow("Due date", self.due_date)
        form.addRow("List selector", self.list_selector)
        layout.addLayout(form)

        row = QHBoxLayout()
        self.save_btn = FontFitButton("Save")
        self.del_btn = FontFitButton("Delete")
        self.cancel_btn = FontFitButton("Cancel")
        self.ai_btn = FontFitButton("Send to AI")
        for b in [self.save_btn, self.del_btn, self.cancel_btn, self.ai_btn]:
            row.addWidget(b)
        layout.addLayout(row)

        self.ai_btn.clicked.connect(self.send_to_ai)
        self.runtime.data_changed.connect(self.refresh_lists)
        self.refresh_lists()

    def refresh_lists(self):
        self.list_selector.clear()
        names = sorted(set([t.task_list_name for t in self.runtime.tasks_by_google_id.values()]))
        for n in names:
            self.list_selector.addItem(n)

    def send_to_ai(self):
        payload = {
            "type": "Task",
            "task_name": self.name.text(),
            "list": self.list_selector.currentText(),
            "due_date": self.due_date.date().toString("yyyy-MM-dd"),
            "notes": self.notes.toPlainText(),
        }
        self.runtime.send_task_to_ai(payload)


class ListTab(QWidget):
    event_open_requested = Signal(str)

    def __init__(self, runtime: GoogleCalendarRuntime, workspace: GoogleWorkspaceWidget):
        super().__init__()
        self.runtime = runtime
        self.workspace = workspace
        self.current_window = "1 Month"

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.window_dropdown = FontFitComboBox()
        self.window_dropdown.addItems(["1 Month", "3 Months", "1 Year"])
        self.refresh_btn = FontFitButton("Refresh List")
        self.ai_btn = FontFitButton("Send to AI")
        controls.addWidget(self.window_dropdown)
        controls.addWidget(self.refresh_btn)
        controls.addWidget(self.ai_btn)
        layout.addLayout(controls)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Title", "Start", "End", "Source calendar", "Status"])
        layout.addWidget(self.table)

        self.window_dropdown.currentTextChanged.connect(self._window_changed)
        self.refresh_btn.clicked.connect(self._refresh_list)
        self.ai_btn.clicked.connect(self._send_to_ai)
        self.table.cellDoubleClicked.connect(self._open_row)
        self.runtime.data_changed.connect(self.rebuild)
        self.rebuild()

    def _window_changed(self, text: str):
        self.current_window = text
        self.rebuild()

    def _refresh_list(self):
        self.runtime.trigger_sync_now()
        self.rebuild()

    def _send_to_ai(self):
        events = self.runtime.list_window_events(self.current_window)
        self.runtime.send_list_to_ai(self.current_window, events)

    def rebuild(self):
        events = self.runtime.list_window_events(self.current_window)
        self.table.setRowCount(len(events))
        for r, e in enumerate(events):
            self.table.setItem(r, 0, QTableWidgetItem(e.summary))
            self.table.setItem(r, 1, QTableWidgetItem(_format_dt(e.start_dt, e.all_day)))
            self.table.setItem(r, 2, QTableWidgetItem(_format_dt(e.end_dt, e.all_day)))
            self.table.setItem(r, 3, QTableWidgetItem(f"● {e.calendar_name}"))
            self.table.setItem(r, 4, QTableWidgetItem(e.status))
            self.table.item(r, 3).setForeground(QColor(e.background_color))
            self.table.item(r, 0).setData(Qt.UserRole, e.google_event_id)

    def _open_row(self, row: int, _col: int):
        item = self.table.item(row, 0)
        if not item:
            return
        event_id = item.data(Qt.UserRole)
        e = self.runtime.events_by_google_id.get(event_id)
        if not e:
            return
        self.workspace.navigate_to_event_date(e.start_dt)
        self.workspace._open_event_popup(event_id)


class ModulePanelWidget(QWidget):
    task_mode_changed = Signal(bool)

    def __init__(self, runtime: GoogleCalendarRuntime, workspace: GoogleWorkspaceWidget):
        super().__init__()
        self.runtime = runtime
        layout = QVBoxLayout(self)
        self.sync_label = FontFitLabel("Last synced: Never")
        layout.addWidget(self.sync_label)

        settings = QGroupBox("Sync Settings")
        settings_layout = QFormLayout(settings)
        self.fetch_mode = FontFitComboBox()
        self.fetch_mode.addItems(["new_only", "full"])
        self.fetch_mode.setCurrentText(runtime.sync_settings["fetch_mode"])
        self.interval_value = QSpinBox()
        self.interval_value.setRange(1, 10_000)
        self.interval_value.setValue(runtime.sync_settings["interval_value"])
        self.interval_unit = FontFitComboBox()
        self.interval_unit.addItems(["seconds", "minutes", "hours"])
        self.interval_unit.setCurrentText(runtime.sync_settings["interval_unit"])
        self.battery_detection_enabled = QCheckBox("Enable battery detection")
        self.battery_detection_enabled.setChecked(runtime.sync_settings["battery_detection_enabled"])
        self.battery_interval_minutes = QSpinBox()
        self.battery_interval_minutes.setRange(1, 10_000)
        self.battery_interval_minutes.setValue(runtime.sync_settings["battery_interval_minutes"])
        self.battery_override_disabled = QCheckBox("Disable battery override")
        self.battery_override_disabled.setChecked(runtime.sync_settings["battery_override_disabled"])
        self.sync_now = FontFitButton("Sync Now")

        settings_layout.addRow("Fetch mode", self.fetch_mode)
        settings_layout.addRow("Interval value", self.interval_value)
        settings_layout.addRow("Interval unit", self.interval_unit)
        settings_layout.addRow("Battery detect", self.battery_detection_enabled)
        settings_layout.addRow("Battery interval minutes", self.battery_interval_minutes)
        settings_layout.addRow("Battery override disabled", self.battery_override_disabled)
        settings_layout.addRow(self.sync_now)
        layout.addWidget(settings)

        self.tabs = QTabWidget()
        self.event_tab = EventControlsTab(runtime)
        self.task_tab = TaskControlsTab(runtime)
        self.list_tab = ListTab(runtime, workspace)
        self.tabs.addTab(self.event_tab, "Event Controls")
        self.tabs.addTab(self.task_tab, "Task Controls")
        self.tabs.addTab(self.list_tab, "List")
        layout.addWidget(self.tabs, 1)

        self.sync_now.clicked.connect(runtime.trigger_sync_now)
        self.fetch_mode.currentTextChanged.connect(lambda v: runtime.set_sync_setting("fetch_mode", v))
        self.interval_value.valueChanged.connect(lambda v: runtime.set_sync_setting("interval_value", v))
        self.interval_unit.currentTextChanged.connect(lambda v: runtime.set_sync_setting("interval_unit", v))
        self.battery_detection_enabled.stateChanged.connect(
            lambda v: runtime.set_sync_setting("battery_detection_enabled", v == Qt.Checked)
        )
        self.battery_interval_minutes.valueChanged.connect(lambda v: runtime.set_sync_setting("battery_interval_minutes", v))
        self.battery_override_disabled.stateChanged.connect(
            lambda v: runtime.set_sync_setting("battery_override_disabled", v == Qt.Checked)
        )
        self.tabs.currentChanged.connect(self._tab_changed)
        self.runtime.data_changed.connect(self._refresh_sync_label)
        self._refresh_sync_label()

    def _tab_changed(self, idx: int):
        name = self.tabs.tabText(idx)
        self.task_mode_changed.emit(name == "Task Controls")

    def _refresh_sync_label(self):
        if self.runtime.last_synced_at:
            self.sync_label.setText(f"Last synced: {self.runtime.last_synced_at.isoformat()}")
        else:
            self.sync_label.setText("Last synced: Never")


class GoogleCalendarModule:
    def __init__(self, deck_api: dict[str, Any]):
        self.deck_api = deck_api
        self.runtime = GoogleCalendarRuntime(deck_api)
        self.workspace_widget = GoogleWorkspaceWidget(self.runtime)
        self.module_panel = ModulePanelWidget(self.runtime, self.workspace_widget)
        self.module_panel.task_mode_changed.connect(
            lambda is_task: self.workspace_widget.set_mode("tasks" if is_task else "calendar")
        )

    def get_workspace_spec(self) -> dict[str, Any]:
        return {
            "workspace_count": 3,
            "workspace_titles": ["Google", "Drive", "Gmail"],
            "workspace_widgets": [self.build_google_workspace, self.build_drive_placeholder, self.build_gmail_placeholder],
            "ribbon": self.build_ribbon,
        }

    def build_google_workspace(self) -> QWidget:
        return self.workspace_widget

    def build_drive_placeholder(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lbl = FontFitLabel("Coming Soon — Google Drive")
        lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(lbl, 1)
        return w

    def build_gmail_placeholder(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lbl = FontFitLabel("Coming Soon — Google Gmail")
        lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(lbl, 1)
        return w

    def build_ribbon(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.addWidget(FontFitLabel("Google Ribbon"))
        return w

    def create_tab(self) -> QWidget:
        return self.module_panel

    def module_definition(self) -> dict[str, Any]:
        return {
            "key": MODULE_MANIFEST["key"],
            "display_name": MODULE_MANIFEST["display_name"],
            "deck_api_version": MODULE_MANIFEST["deck_api_version"],
            "home_category": MODULE_MANIFEST["home_category"],
            "tab_definitions": MODULE_MANIFEST["tab_definitions"],
            "manifest": MODULE_MANIFEST,
            "create_tab": self.create_tab,
            "get_workspace_spec": self.get_workspace_spec,
            "settings_sections": ["sync_interval", "battery"],
            "hooks": {
                "on_open": self.runtime.trigger_sync_now,
                "on_focus": self.runtime.trigger_sync_now,
            },
        }


def get_workspace_spec() -> dict[str, Any]:
    module = GoogleCalendarModule({})
    return module.get_workspace_spec()


def register(deck_api: dict[str, Any]) -> dict[str, Any]:
    module = GoogleCalendarModule(deck_api)
    return module.module_definition()
