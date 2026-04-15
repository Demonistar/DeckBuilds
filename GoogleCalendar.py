from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QDateTimeEdit,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


MODULE_MANIFEST = {
    "key": "google_calendar",
    "display_name": "Google Calendar + Tasks",
    "version": "1.0.0",
    "deck_api_version": "1.0",
    "home_category": "Google",
    "entry_function": "register",
    "shared_resource": "google_auth",
    "description": "Standalone Google Calendar + Tasks module with local-first bidirectional sync model.",
    "tab_definitions": [
        {
            "tab_id": "google_calendar_main",
            "tab_name": "Google Calendar",
        }
    ],
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
    "listens": [
        "calendar.item.*",
        "task.*",
    ],
}


UTC = timezone.utc
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _iso_to_dt(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _fingerprint(payload: dict[str, Any], keys: list[str]) -> str:
    material = {k: payload.get(k) for k in keys}
    raw = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CalendarRecord:
    def __init__(
        self,
        id: str,
        title: str,
        description: str,
        start_at: str,
        end_at: str,
        recurrence: str,
        status: str,
        source: str,
        google_event_id: str,
        sync_status: str,
        last_synced_at: str,
        metadata: dict[str, Any],
        origin: str,
        fingerprint: str,
    ):
        self.id = id
        self.title = title
        self.description = description
        self.start_at = start_at
        self.end_at = end_at
        self.recurrence = recurrence
        self.status = status
        self.source = source
        self.google_event_id = google_event_id
        self.sync_status = sync_status
        self.last_synced_at = last_synced_at
        self.metadata = metadata
        self.origin = origin
        self.fingerprint = fingerprint


class TaskRecord:
    def __init__(
        self,
        id: str,
        title: str,
        notes: str,
        due_at: str,
        recurrence: str,
        status: str,
        source: str,
        google_task_id: str,
        sync_status: str,
        last_synced_at: str,
        metadata: dict[str, Any],
        origin: str,
        fingerprint: str,
    ):
        self.id = id
        self.title = title
        self.notes = notes
        self.due_at = due_at
        self.recurrence = recurrence
        self.status = status
        self.source = source
        self.google_task_id = google_task_id
        self.sync_status = sync_status
        self.last_synced_at = last_synced_at
        self.metadata = metadata
        self.origin = origin
        self.fingerprint = fingerprint


def asdict(record: Any) -> dict[str, Any]:
    return dict(vars(record))


class GoogleCalendarRuntime:
    """Local-first runtime with conceptual shared-google-auth sync adapters."""

    def __init__(self, deck_api: dict[str, Any]):
        self._deck_api = deck_api
        self._log: Callable[[str], None] = deck_api.get("log") if callable(deck_api.get("log")) else (lambda _msg: None)
        self._cfg_get = deck_api.get("cfg_get") if callable(deck_api.get("cfg_get")) else (lambda _k, d=None: d)
        self._cfg_set = deck_api.get("cfg_set") if callable(deck_api.get("cfg_set")) else (lambda _k, _v: None)
        self._cfg_path = deck_api.get("cfg_path") if callable(deck_api.get("cfg_path")) else None
        self._broadcast = deck_api.get("broadcast") if callable(deck_api.get("broadcast")) else None

        self.calendar_records: dict[str, CalendarRecord] = {}
        self.task_records: dict[str, TaskRecord] = {}
        self.sync_state: dict[str, Any] = {
            "calendar_sync_token": "",
            "tasks_sync_token": "",
            "last_sync_at": "",
            "last_error": "",
            "mode": "local_only",
            "auth_status": "unknown",
        }
        self._storage_path = self._resolve_storage_path()
        self._google_storage_dir = self._resolve_google_storage_dir()
        self._token_path = self._google_storage_dir / "token.json" if self._google_storage_dir else None
        self._credentials_path = self._google_storage_dir / "google_credentials.json" if self._google_storage_dir else None
        self._load_state()

    def _resolve_storage_path(self) -> Optional[Path]:
        if not callable(self._cfg_path):
            return None
        try:
            p = self._cfg_path("google_calendar_module_state.json")
            if not p:
                return None
            path = Path(p)
            path.parent.mkdir(parents=True, exist_ok=True)
            return path
        except Exception as ex:
            self._log(f"GoogleCalendar storage path unavailable: {ex}")
            return None

    def _load_state(self) -> None:
        payload: dict[str, Any] = {}
        if self._storage_path and self._storage_path.exists():
            try:
                payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            except Exception as ex:
                self._log(f"GoogleCalendar failed to load storage file: {ex}")
        else:
            cfg_payload = self._cfg_get("module_google_calendar_state", {})
            if isinstance(cfg_payload, dict):
                payload = cfg_payload

        for item in payload.get("calendar_records", []):
            try:
                rec = CalendarRecord(**item)
                self.calendar_records[rec.id] = rec
            except Exception:
                continue

        for item in payload.get("task_records", []):
            try:
                rec = TaskRecord(**item)
                self.task_records[rec.id] = rec
            except Exception:
                continue

        state = payload.get("sync_state", {})
        if isinstance(state, dict):
            self.sync_state.update(state)

    def _resolve_google_storage_dir(self) -> Optional[Path]:
        if not callable(self._cfg_path):
            return None
        try:
            token_candidate = self._cfg_path("google_auth/token.json")
            if token_candidate:
                storage_dir = Path(token_candidate).parent
                storage_dir.mkdir(parents=True, exist_ok=True)
                return storage_dir
        except Exception as ex:
            self._log(f"GoogleCalendar token storage path unavailable: {ex}")
        return None

    def _save_state(self) -> None:
        payload = {
            "calendar_records": [asdict(x) for x in self.calendar_records.values()],
            "task_records": [asdict(x) for x in self.task_records.values()],
            "sync_state": dict(self.sync_state),
            "updated_at": _now_iso(),
        }

        if self._storage_path:
            try:
                self._storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as ex:
                self._log(f"GoogleCalendar failed to write storage file: {ex}")

        try:
            self._cfg_set("module_google_calendar_state", payload)
        except Exception:
            pass

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if not callable(self._broadcast):
            return
        envelope = {
            "event_type": event_type,
            "domain": "calendar" if event_type.startswith("calendar") else "tasks",
            "origin_module": "google_calendar",
            "payload": payload,
        }
        try:
            self._broadcast(envelope)
        except Exception:
            pass

    def _google_auth_snapshot(self) -> dict[str, Any]:
        shared = self._cfg_get("modules.shared_resources.google_auth", {})
        if not isinstance(shared, dict):
            shared = {}
        local_token_present = bool(self._token_path and self._token_path.exists())
        local_creds_present = bool(self._credentials_path and self._credentials_path.exists())
        token_present = bool(shared.get("token_present") or shared.get("token_path") or local_token_present)
        creds_present = bool(shared.get("credentials_present") or shared.get("credentials_path") or local_creds_present)
        refreshable = bool(shared.get("refreshable", True))
        valid = bool(shared.get("token_valid", token_present))
        return {
            "token_present": token_present,
            "credentials_present": creds_present,
            "token_valid": valid,
            "refreshable": refreshable,
        }

    def _set_shared_auth_state(self, token_valid: bool, token_present: bool, credentials_present: bool, credentials_path: str = "") -> None:
        payload = {
            "token_valid": bool(token_valid),
            "token_present": bool(token_present),
            "credentials_present": bool(credentials_present),
            "refreshable": True,
            "token_path": str(self._token_path) if token_present and self._token_path else "",
            "credentials_path": credentials_path if credentials_path else (str(self._credentials_path) if credentials_present and self._credentials_path else ""),
        }
        try:
            self._cfg_set("modules.shared_resources.google_auth", payload)
        except Exception:
            pass

    def authenticate_google(self, selected_credentials_path: str) -> tuple[bool, str]:
        if not self._google_storage_dir or not self._token_path or not self._credentials_path:
            return False, "Google auth storage location is unavailable."
        if not selected_credentials_path:
            return False, "No credentials file selected."
        selected_path = Path(selected_credentials_path)
        if not selected_path.exists():
            return False, "Selected credentials file does not exist."

        try:
            self._credentials_path.write_text(selected_path.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception as ex:
            self.sync_state["mode"] = "local_only"
            self.sync_state["auth_status"] = "missing"
            self.sync_state["last_error"] = f"Failed to store credentials: {ex}"
            self._save_state()
            return False, self.sync_state["last_error"]

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except Exception as ex:
            self.sync_state["mode"] = "local_only"
            self.sync_state["auth_status"] = "missing"
            self.sync_state["last_error"] = f"Google auth dependencies unavailable: {ex}"
            self._save_state()
            return False, self.sync_state["last_error"]

        creds = None
        try:
            if self._token_path.exists():
                try:
                    creds = Credentials.from_authorized_user_file(str(self._token_path), GOOGLE_SCOPES)
                except Exception:
                    creds = None

            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())

            if not creds or not creds.valid:
                flow = InstalledAppFlow.from_client_secrets_file(str(self._credentials_path), GOOGLE_SCOPES)
                creds = flow.run_local_server(port=0)

            self._token_path.write_text(creds.to_json(), encoding="utf-8")
            # Build clients once to validate token/scopes.
            build("calendar", "v3", credentials=creds)
            build("tasks", "v1", credentials=creds)

            self.sync_state["auth_status"] = "authenticated"
            self.sync_state["mode"] = "google_connected"
            self.sync_state["last_error"] = ""
            self._set_shared_auth_state(
                token_valid=True,
                token_present=True,
                credentials_present=True,
                credentials_path=str(self._credentials_path),
            )
            self._save_state()
            self._log("GoogleCalendar authentication successful; token.json generated.")
            return True, "Authentication successful."
        except Exception as ex:
            self.sync_state["mode"] = "local_only"
            self.sync_state["auth_status"] = "missing"
            self.sync_state["last_error"] = f"Google authentication failed: {ex}"
            self._set_shared_auth_state(
                token_valid=False,
                token_present=bool(self._token_path.exists()),
                credentials_present=bool(self._credentials_path.exists()),
                credentials_path=str(self._credentials_path),
            )
            self._save_state()
            self._log(self.sync_state["last_error"])
            return False, self.sync_state["last_error"]

    def evaluate_auth_status(self) -> str:
        auth = self._google_auth_snapshot()
        if auth["token_present"] and auth["token_valid"]:
            if self.sync_state.get("auth_status") != "authenticated":
                self.sync_state["auth_status"] = "token_ready"
            self.sync_state["mode"] = "google_connected"
        elif auth["credentials_present"]:
            self.sync_state["auth_status"] = "credentials_only"
            self.sync_state["mode"] = "local_only"
        else:
            self.sync_state["auth_status"] = "missing"
            self.sync_state["mode"] = "local_only"
        return self.sync_state["auth_status"]

    def _make_calendar_record(self, title: str, description: str, start_at: str, end_at: str, recurrence: str) -> CalendarRecord:
        base = {
            "title": title,
            "description": description,
            "start_at": start_at,
            "end_at": end_at,
            "recurrence": recurrence,
            "status": "active",
        }
        return CalendarRecord(
            id=str(uuid.uuid4()),
            source="local",
            google_event_id="",
            sync_status="pending_create",
            last_synced_at="",
            metadata={"kind": "calendar"},
            origin="local_user",
            fingerprint=_fingerprint(base, ["title", "description", "start_at", "end_at", "recurrence", "status"]),
            **base,
        )

    def _make_task_record(self, title: str, notes: str, due_at: str, recurrence: str) -> TaskRecord:
        base = {
            "title": title,
            "notes": notes,
            "due_at": due_at,
            "recurrence": recurrence,
            "status": "open",
        }
        return TaskRecord(
            id=str(uuid.uuid4()),
            source="local",
            google_task_id="",
            sync_status="pending_create",
            last_synced_at="",
            metadata={"kind": "task"},
            origin="local_user",
            fingerprint=_fingerprint(base, ["title", "notes", "due_at", "recurrence", "status"]),
            **base,
        )

    def create_calendar(self, title: str, description: str, start_at: str, end_at: str, recurrence: str) -> CalendarRecord:
        rec = self._make_calendar_record(title, description, start_at, end_at, recurrence)
        self.calendar_records[rec.id] = rec
        self._save_state()
        self._emit("calendar.item.created", asdict(rec))
        return rec

    def update_calendar(self, rec_id: str, title: str, description: str, start_at: str, end_at: str, recurrence: str) -> Optional[CalendarRecord]:
        rec = self.calendar_records.get(rec_id)
        if not rec:
            return None
        rec.title = title
        rec.description = description
        rec.start_at = start_at
        rec.end_at = end_at
        rec.recurrence = recurrence
        rec.fingerprint = _fingerprint(asdict(rec), ["title", "description", "start_at", "end_at", "recurrence", "status"])
        rec.sync_status = "pending_update" if rec.google_event_id else "pending_create"
        rec.source = "local"
        rec.origin = "local_edit"
        self._save_state()
        self._emit("calendar.item.updated", asdict(rec))
        return rec

    def cancel_calendar(self, rec_id: str) -> Optional[CalendarRecord]:
        rec = self.calendar_records.get(rec_id)
        if not rec:
            return None
        rec.status = "cancelled"
        rec.sync_status = "pending_delete" if rec.google_event_id else "local_cancelled"
        rec.source = "local"
        rec.origin = "local_delete"
        rec.fingerprint = _fingerprint(asdict(rec), ["title", "description", "start_at", "end_at", "recurrence", "status"])
        self._save_state()
        self._emit("calendar.item.deleted", asdict(rec))
        return rec

    def create_task(self, title: str, notes: str, due_at: str, recurrence: str) -> TaskRecord:
        rec = self._make_task_record(title, notes, due_at, recurrence)
        self.task_records[rec.id] = rec
        self._save_state()
        self._emit("task.created", asdict(rec))
        return rec

    def update_task(self, rec_id: str, title: str, notes: str, due_at: str, recurrence: str, status: str) -> Optional[TaskRecord]:
        rec = self.task_records.get(rec_id)
        if not rec:
            return None
        rec.title = title
        rec.notes = notes
        rec.due_at = due_at
        rec.recurrence = recurrence
        rec.status = status
        rec.sync_status = "pending_update" if rec.google_task_id else "pending_create"
        rec.source = "local"
        rec.origin = "local_edit"
        rec.fingerprint = _fingerprint(asdict(rec), ["title", "notes", "due_at", "recurrence", "status"])
        self._save_state()
        if status == "completed":
            self._emit("task.completed", asdict(rec))
        else:
            self._emit("task.updated", asdict(rec))
        return rec

    def delete_task(self, rec_id: str) -> Optional[TaskRecord]:
        rec = self.task_records.get(rec_id)
        if not rec:
            return None
        rec.status = "deleted"
        rec.sync_status = "pending_delete" if rec.google_task_id else "local_deleted"
        rec.source = "local"
        rec.origin = "local_delete"
        rec.fingerprint = _fingerprint(asdict(rec), ["title", "notes", "due_at", "recurrence", "status"])
        self._save_state()
        self._emit("task.deleted", asdict(rec))
        return rec

    # --- Conceptual Google sync adapter layer ---------------------------------
    # This module intentionally relies on shared google_auth ownership by host.

    def _fetch_google_changes(self, kind: str, sync_token: str) -> tuple[list[dict[str, Any]], str]:
        """
        Placeholder fetch hook for host-managed Google clients.
        Returns (items, next_sync_token). Raises ValueError("sync_token_invalid") for token reset.
        """
        return [], sync_token

    def _push_google_item(self, kind: str, operation: str, record: dict[str, Any]) -> dict[str, Any]:
        """Placeholder push hook for host-managed Google clients."""
        return {"ok": False, "reason": "not_connected", "external_id": ""}

    def _reconcile_google_calendar_item(self, item: dict[str, Any]) -> None:
        google_id = str(item.get("id") or "")
        if not google_id:
            return

        mapped = next((r for r in self.calendar_records.values() if r.google_event_id == google_id), None)
        if mapped:
            mapped.title = str(item.get("title") or mapped.title)
            mapped.description = str(item.get("description") or mapped.description)
            mapped.start_at = str(item.get("start_at") or mapped.start_at)
            mapped.end_at = str(item.get("end_at") or mapped.end_at)
            mapped.recurrence = str(item.get("recurrence") or mapped.recurrence)
            mapped.status = "cancelled" if item.get("status") in {"cancelled", "deleted"} else str(item.get("status") or "active")
            mapped.source = "google"
            mapped.origin = "google_sync"
            mapped.sync_status = "synced"
            mapped.last_synced_at = _now_iso()
            mapped.fingerprint = _fingerprint(asdict(mapped), ["title", "description", "start_at", "end_at", "recurrence", "status"])
            self._emit("calendar.item.updated", asdict(mapped))
            return

        # New inbound from Google: create local record with mapping.
        rec = self._make_calendar_record(
            title=str(item.get("title") or "Untitled Event"),
            description=str(item.get("description") or ""),
            start_at=str(item.get("start_at") or _now_iso()),
            end_at=str(item.get("end_at") or _now_iso()),
            recurrence=str(item.get("recurrence") or "none"),
        )
        rec.google_event_id = google_id
        rec.status = "cancelled" if item.get("status") in {"cancelled", "deleted"} else str(item.get("status") or "active")
        rec.source = "google"
        rec.origin = "google_sync"
        rec.sync_status = "synced"
        rec.last_synced_at = _now_iso()
        self.calendar_records[rec.id] = rec
        self._emit("calendar.item.created", asdict(rec))

    def _reconcile_google_task_item(self, item: dict[str, Any]) -> None:
        google_id = str(item.get("id") or "")
        if not google_id:
            return

        mapped = next((r for r in self.task_records.values() if r.google_task_id == google_id), None)
        if mapped:
            mapped.title = str(item.get("title") or mapped.title)
            mapped.notes = str(item.get("notes") or mapped.notes)
            mapped.due_at = str(item.get("due_at") or mapped.due_at)
            mapped.recurrence = str(item.get("recurrence") or mapped.recurrence)
            mapped.status = "deleted" if item.get("status") in {"cancelled", "deleted"} else str(item.get("status") or mapped.status)
            mapped.source = "google"
            mapped.origin = "google_sync"
            mapped.sync_status = "synced"
            mapped.last_synced_at = _now_iso()
            mapped.fingerprint = _fingerprint(asdict(mapped), ["title", "notes", "due_at", "recurrence", "status"])
            self._emit("task.updated", asdict(mapped))
            return

        rec = self._make_task_record(
            title=str(item.get("title") or "Untitled Task"),
            notes=str(item.get("notes") or ""),
            due_at=str(item.get("due_at") or _now_iso()),
            recurrence=str(item.get("recurrence") or "none"),
        )
        rec.google_task_id = google_id
        rec.status = "deleted" if item.get("status") in {"cancelled", "deleted"} else str(item.get("status") or "open")
        rec.source = "google"
        rec.origin = "google_sync"
        rec.sync_status = "synced"
        rec.last_synced_at = _now_iso()
        self.task_records[rec.id] = rec
        self._emit("task.created", asdict(rec))

    def sync_once(self) -> None:
        self.evaluate_auth_status()
        if self.sync_state.get("mode") != "google_connected":
            self.sync_state["last_error"] = "Google auth unavailable; running local-only."
            self._save_state()
            return

        try:
            # Outbound: push pending local changes without duplicate creates.
            for rec in self.calendar_records.values():
                if rec.sync_status == "synced":
                    continue
                if rec.google_event_id:
                    op = "delete" if rec.sync_status == "pending_delete" else "update"
                else:
                    op = "create"
                result = self._push_google_item("calendar", op, asdict(rec))
                if result.get("ok"):
                    if not rec.google_event_id:
                        rec.google_event_id = str(result.get("external_id") or rec.google_event_id)
                    rec.sync_status = "synced"
                    rec.last_synced_at = _now_iso()

            for rec in self.task_records.values():
                if rec.sync_status == "synced":
                    continue
                if rec.google_task_id:
                    op = "delete" if rec.sync_status == "pending_delete" else "update"
                else:
                    op = "create"
                result = self._push_google_item("tasks", op, asdict(rec))
                if result.get("ok"):
                    if not rec.google_task_id:
                        rec.google_task_id = str(result.get("external_id") or rec.google_task_id)
                    rec.sync_status = "synced"
                    rec.last_synced_at = _now_iso()

            # Inbound incremental; fall back to full if token invalid.
            cal_token = str(self.sync_state.get("calendar_sync_token") or "")
            task_token = str(self.sync_state.get("tasks_sync_token") or "")
            try:
                cal_items, next_cal_token = self._fetch_google_changes("calendar", cal_token)
            except ValueError as ex:
                if "sync_token_invalid" not in str(ex):
                    raise
                cal_items, next_cal_token = self._fetch_google_changes("calendar", "")
            try:
                task_items, next_task_token = self._fetch_google_changes("tasks", task_token)
            except ValueError as ex:
                if "sync_token_invalid" not in str(ex):
                    raise
                task_items, next_task_token = self._fetch_google_changes("tasks", "")

            for item in cal_items:
                self._reconcile_google_calendar_item(item)
            for item in task_items:
                self._reconcile_google_task_item(item)

            self.sync_state["calendar_sync_token"] = next_cal_token
            self.sync_state["tasks_sync_token"] = next_task_token
            self.sync_state["last_sync_at"] = _now_iso()
            self.sync_state["last_error"] = ""
            self._save_state()
        except Exception as ex:
            self.sync_state["last_error"] = str(ex)
            self._save_state()

    def due_reminders(self) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        window = now + timedelta(minutes=15)
        reminders: list[dict[str, Any]] = []

        for rec in self.calendar_records.values():
            if rec.status in {"cancelled", "deleted"}:
                continue
            start_dt = _iso_to_dt(rec.start_at)
            if start_dt and now <= start_dt <= window:
                payload = {"kind": "calendar", "id": rec.id, "title": rec.title, "due_at": rec.start_at}
                reminders.append(payload)
                self._emit("calendar.reminder.triggered", payload)

        for rec in self.task_records.values():
            if rec.status in {"completed", "deleted"}:
                continue
            due_dt = _iso_to_dt(rec.due_at)
            if due_dt and now <= due_dt <= window:
                payload = {"kind": "task", "id": rec.id, "title": rec.title, "due_at": rec.due_at}
                reminders.append(payload)
                self._emit("task.due", payload)

        return reminders


class GoogleCalendarTab(QWidget):
    def __init__(self, runtime: GoogleCalendarRuntime):
        super().__init__()
        self.runtime = runtime
        self._build_ui()
        self.refresh_all()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_calendar_view(), "Calendar")
        tabs.addTab(self._build_tasks_view(), "Tasks")
        tabs.addTab(self._build_sync_view(), "Sync / Status")
        root.addWidget(tabs)

    def _build_calendar_view(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)

        form_box = QGroupBox("Event Details", panel)
        form = QFormLayout(form_box)
        self.cal_title = QLineEdit(form_box)
        self.cal_desc = QTextEdit(form_box)
        self.cal_start = QDateTimeEdit(form_box)
        self.cal_start.setCalendarPopup(True)
        self.cal_start.setDateTime(datetime.now())
        self.cal_end = QDateTimeEdit(form_box)
        self.cal_end.setCalendarPopup(True)
        self.cal_end.setDateTime(datetime.now() + timedelta(hours=1))
        self.cal_recur = QLineEdit(form_box)
        self.cal_recur.setPlaceholderText("none / daily / weekly / RRULE...")

        form.addRow("Title", self.cal_title)
        form.addRow("Description", self.cal_desc)
        form.addRow("Start", self.cal_start)
        form.addRow("End", self.cal_end)
        form.addRow("Recurrence", self.cal_recur)
        layout.addWidget(form_box)

        btns = QHBoxLayout()
        self.cal_add_btn = QPushButton("Add Event", panel)
        self.cal_update_btn = QPushButton("Update Selected", panel)
        self.cal_cancel_btn = QPushButton("Cancel Selected", panel)
        self.cal_refresh_btn = QPushButton("Refresh", panel)
        btns.addWidget(self.cal_add_btn)
        btns.addWidget(self.cal_update_btn)
        btns.addWidget(self.cal_cancel_btn)
        btns.addWidget(self.cal_refresh_btn)
        layout.addLayout(btns)

        self.cal_list = QListWidget(panel)
        self.cal_list.itemSelectionChanged.connect(self._load_selected_calendar)
        layout.addWidget(self.cal_list)

        self.cal_add_btn.clicked.connect(self._add_calendar)
        self.cal_update_btn.clicked.connect(self._update_calendar)
        self.cal_cancel_btn.clicked.connect(self._cancel_calendar)
        self.cal_refresh_btn.clicked.connect(self.refresh_calendar)
        return panel

    def _build_tasks_view(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)

        form_box = QGroupBox("Task Details", panel)
        form = QFormLayout(form_box)
        self.task_title = QLineEdit(form_box)
        self.task_notes = QTextEdit(form_box)
        self.task_due = QDateTimeEdit(form_box)
        self.task_due.setCalendarPopup(True)
        self.task_due.setDateTime(datetime.now() + timedelta(hours=2))
        self.task_recur = QLineEdit(form_box)
        self.task_recur.setPlaceholderText("none / daily / weekly / RRULE...")
        self.task_status = QLineEdit(form_box)
        self.task_status.setPlaceholderText("open / completed")

        form.addRow("Title", self.task_title)
        form.addRow("Notes", self.task_notes)
        form.addRow("Due", self.task_due)
        form.addRow("Recurrence", self.task_recur)
        form.addRow("Status", self.task_status)
        layout.addWidget(form_box)

        btns = QHBoxLayout()
        self.task_add_btn = QPushButton("Add Task", panel)
        self.task_update_btn = QPushButton("Update Selected", panel)
        self.task_complete_btn = QPushButton("Complete Selected", panel)
        self.task_delete_btn = QPushButton("Delete Selected", panel)
        self.task_refresh_btn = QPushButton("Refresh", panel)
        btns.addWidget(self.task_add_btn)
        btns.addWidget(self.task_update_btn)
        btns.addWidget(self.task_complete_btn)
        btns.addWidget(self.task_delete_btn)
        btns.addWidget(self.task_refresh_btn)
        layout.addLayout(btns)

        self.task_list = QListWidget(panel)
        self.task_list.itemSelectionChanged.connect(self._load_selected_task)
        layout.addWidget(self.task_list)

        self.task_add_btn.clicked.connect(self._add_task)
        self.task_update_btn.clicked.connect(self._update_task)
        self.task_complete_btn.clicked.connect(self._complete_task)
        self.task_delete_btn.clicked.connect(self._delete_task)
        self.task_refresh_btn.clicked.connect(self.refresh_tasks)
        return panel

    def _build_sync_view(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        self.sync_label = QLabel(panel)
        self.sync_label.setWordWrap(True)
        layout.addWidget(self.sync_label)

        self.auth_google_btn = QPushButton("Authenticate Google", panel)
        self.sync_now_btn = QPushButton("Run Sync Now", panel)
        self.sync_refresh_btn = QPushButton("Refresh Status", panel)
        self.reminders_btn = QPushButton("Scan Upcoming Reminders", panel)
        layout.addWidget(self.auth_google_btn)
        layout.addWidget(self.sync_now_btn)
        layout.addWidget(self.sync_refresh_btn)
        layout.addWidget(self.reminders_btn)
        layout.addStretch(1)

        self.auth_google_btn.clicked.connect(self._authenticate_google)
        self.sync_now_btn.clicked.connect(self._run_sync)
        self.sync_refresh_btn.clicked.connect(self.refresh_sync)
        self.reminders_btn.clicked.connect(self._scan_reminders)
        return panel

    def _selected_id(self, widget: QListWidget) -> str:
        item = widget.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "")

    def _load_selected_calendar(self) -> None:
        rec_id = self._selected_id(self.cal_list)
        rec = self.runtime.calendar_records.get(rec_id)
        if not rec:
            return
        self.cal_title.setText(rec.title)
        self.cal_desc.setPlainText(rec.description)
        start = _iso_to_dt(rec.start_at)
        end = _iso_to_dt(rec.end_at)
        if start:
            self.cal_start.setDateTime(start.replace(tzinfo=None))
        if end:
            self.cal_end.setDateTime(end.replace(tzinfo=None))
        self.cal_recur.setText(rec.recurrence)

    def _load_selected_task(self) -> None:
        rec_id = self._selected_id(self.task_list)
        rec = self.runtime.task_records.get(rec_id)
        if not rec:
            return
        self.task_title.setText(rec.title)
        self.task_notes.setPlainText(rec.notes)
        due = _iso_to_dt(rec.due_at)
        if due:
            self.task_due.setDateTime(due.replace(tzinfo=None))
        self.task_recur.setText(rec.recurrence)
        self.task_status.setText(rec.status)

    def _add_calendar(self) -> None:
        if not self.cal_title.text().strip():
            QMessageBox.warning(self, "Missing title", "Please provide an event title.")
            return
        self.runtime.create_calendar(
            title=self.cal_title.text().strip(),
            description=self.cal_desc.toPlainText().strip(),
            start_at=self.cal_start.dateTime().toPython().replace(tzinfo=UTC).isoformat(),
            end_at=self.cal_end.dateTime().toPython().replace(tzinfo=UTC).isoformat(),
            recurrence=self.cal_recur.text().strip() or "none",
        )
        self.refresh_calendar()
        self.refresh_sync()

    def _update_calendar(self) -> None:
        rec_id = self._selected_id(self.cal_list)
        if not rec_id:
            return
        self.runtime.update_calendar(
            rec_id=rec_id,
            title=self.cal_title.text().strip() or "Untitled Event",
            description=self.cal_desc.toPlainText().strip(),
            start_at=self.cal_start.dateTime().toPython().replace(tzinfo=UTC).isoformat(),
            end_at=self.cal_end.dateTime().toPython().replace(tzinfo=UTC).isoformat(),
            recurrence=self.cal_recur.text().strip() or "none",
        )
        self.refresh_calendar()
        self.refresh_sync()

    def _cancel_calendar(self) -> None:
        rec_id = self._selected_id(self.cal_list)
        if not rec_id:
            return
        self.runtime.cancel_calendar(rec_id)
        self.refresh_calendar()
        self.refresh_sync()

    def _add_task(self) -> None:
        if not self.task_title.text().strip():
            QMessageBox.warning(self, "Missing title", "Please provide a task title.")
            return
        self.runtime.create_task(
            title=self.task_title.text().strip(),
            notes=self.task_notes.toPlainText().strip(),
            due_at=self.task_due.dateTime().toPython().replace(tzinfo=UTC).isoformat(),
            recurrence=self.task_recur.text().strip() or "none",
        )
        self.refresh_tasks()
        self.refresh_sync()

    def _update_task(self) -> None:
        rec_id = self._selected_id(self.task_list)
        if not rec_id:
            return
        self.runtime.update_task(
            rec_id=rec_id,
            title=self.task_title.text().strip() or "Untitled Task",
            notes=self.task_notes.toPlainText().strip(),
            due_at=self.task_due.dateTime().toPython().replace(tzinfo=UTC).isoformat(),
            recurrence=self.task_recur.text().strip() or "none",
            status=(self.task_status.text().strip() or "open"),
        )
        self.refresh_tasks()
        self.refresh_sync()

    def _complete_task(self) -> None:
        rec_id = self._selected_id(self.task_list)
        if not rec_id:
            return
        rec = self.runtime.task_records.get(rec_id)
        if not rec:
            return
        self.runtime.update_task(
            rec_id=rec_id,
            title=rec.title,
            notes=rec.notes,
            due_at=rec.due_at,
            recurrence=rec.recurrence,
            status="completed",
        )
        self.refresh_tasks()
        self.refresh_sync()

    def _delete_task(self) -> None:
        rec_id = self._selected_id(self.task_list)
        if not rec_id:
            return
        self.runtime.delete_task(rec_id)
        self.refresh_tasks()
        self.refresh_sync()

    def _run_sync(self) -> None:
        self.runtime.sync_once()
        self.refresh_all()

    def _authenticate_google(self) -> None:
        selected_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Google OAuth Credentials",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not selected_path:
            return
        ok, message = self.runtime.authenticate_google(selected_path)
        if ok:
            QMessageBox.information(self, "Google Authentication", message)
        else:
            QMessageBox.critical(self, "Google Authentication Failed", message)
        self.refresh_sync()

    def _scan_reminders(self) -> None:
        reminders = self.runtime.due_reminders()
        QMessageBox.information(self, "Reminder Scan", f"Detected {len(reminders)} upcoming reminder(s).")
        self.refresh_sync()

    def _calendar_row(self, rec: CalendarRecord) -> str:
        mode = "Google-origin" if rec.source == "google" else ("Synced" if rec.google_event_id else "Local")
        return f"{rec.title} | {rec.start_at} | status={rec.status} | {mode} | sync={rec.sync_status}"

    def _task_row(self, rec: TaskRecord) -> str:
        mode = "Google-origin" if rec.source == "google" else ("Synced" if rec.google_task_id else "Local")
        return f"{rec.title} | due={rec.due_at} | status={rec.status} | {mode} | sync={rec.sync_status}"

    def refresh_calendar(self) -> None:
        self.cal_list.clear()
        rows = sorted(self.runtime.calendar_records.values(), key=lambda r: (r.start_at, r.title))
        for rec in rows:
            item = QListWidgetItem(self._calendar_row(rec))
            item.setData(Qt.UserRole, rec.id)
            self.cal_list.addItem(item)

    def refresh_tasks(self) -> None:
        self.task_list.clear()
        rows = sorted(self.runtime.task_records.values(), key=lambda r: (r.due_at, r.title))
        for rec in rows:
            item = QListWidgetItem(self._task_row(rec))
            item.setData(Qt.UserRole, rec.id)
            self.task_list.addItem(item)

    def refresh_sync(self) -> None:
        self.runtime.evaluate_auth_status()
        state = self.runtime.sync_state
        auth = self.runtime._google_auth_snapshot()
        self.auth_google_btn.setVisible(state.get("auth_status") == "missing")
        text = (
            f"Mode: {state.get('mode')}\n"
            f"Auth status: {state.get('auth_status')}\n"
            f"Token present: {auth.get('token_present')}\n"
            f"Credentials present: {auth.get('credentials_present')}\n"
            f"Last sync: {state.get('last_sync_at') or 'never'}\n"
            f"Calendar token: {'set' if state.get('calendar_sync_token') else 'unset'}\n"
            f"Tasks token: {'set' if state.get('tasks_sync_token') else 'unset'}\n"
            f"Last error: {state.get('last_error') or 'none'}"
        )
        self.sync_label.setText(text)

    def refresh_all(self) -> None:
        self.refresh_calendar()
        self.refresh_tasks()
        self.refresh_sync()


def register(deck_api: dict) -> dict:
    deck_api_version = str(deck_api.get("deck_api_version") or "")
    if deck_api_version != "1.0":
        raise RuntimeError(f"Unsupported deck API version: {deck_api_version}")

    runtime = GoogleCalendarRuntime(deck_api)

    def _on_startup() -> None:
        runtime.evaluate_auth_status()
        runtime._save_state()

    def _on_message(message: Any) -> None:
        if not isinstance(message, dict):
            return
        event_type = str(message.get("event_type") or "").strip().lower()
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}

        # Schema-ready listener stubs for future event-bus wiring.
        if event_type.startswith("calendar.item.") and payload:
            rec_id = str(payload.get("id") or "")
            if rec_id and rec_id in runtime.calendar_records:
                runtime.update_calendar(
                    rec_id=rec_id,
                    title=str(payload.get("title") or runtime.calendar_records[rec_id].title),
                    description=str(payload.get("description") or runtime.calendar_records[rec_id].description),
                    start_at=str(payload.get("start_at") or runtime.calendar_records[rec_id].start_at),
                    end_at=str(payload.get("end_at") or runtime.calendar_records[rec_id].end_at),
                    recurrence=str(payload.get("recurrence") or runtime.calendar_records[rec_id].recurrence),
                )

        if event_type.startswith("task.") and payload:
            rec_id = str(payload.get("id") or "")
            if rec_id and rec_id in runtime.task_records:
                runtime.update_task(
                    rec_id=rec_id,
                    title=str(payload.get("title") or runtime.task_records[rec_id].title),
                    notes=str(payload.get("notes") or runtime.task_records[rec_id].notes),
                    due_at=str(payload.get("due_at") or runtime.task_records[rec_id].due_at),
                    recurrence=str(payload.get("recurrence") or runtime.task_records[rec_id].recurrence),
                    status=str(payload.get("status") or runtime.task_records[rec_id].status),
                )

    def _build_tab() -> QWidget:
        return GoogleCalendarTab(runtime)

    return {
        "deck_api_version": "1.0",
        "module_key": "google_calendar",
        "display_name": "Google Calendar + Tasks",
        "home_category": "Google",
        "tabs": [
            {
                "tab_id": "google_calendar_main",
                "tab_name": "Google Calendar",
                "get_content": _build_tab,
            }
        ],
        "hooks": {
            "on_startup": _on_startup,
            "on_message": _on_message,
        },
    }
