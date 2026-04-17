from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QDate, QDateTime, QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
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
    "https://www.googleapis.com/auth/calendar.events",
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


def _to_qdate(value: datetime) -> QDate:
    return QDate(value.year, value.month, value.day)


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
            "calendar_sync_tokens": {},
            "tasks_sync_token": "",
            "last_sync_at": "",
            "last_error": "",
            "mode": "local_only",
            "auth_status": "unknown",
            "last_calendar_fetched_count": 0,
            "last_calendar_visible_count": 0,
            "last_calendar_sync_mode": "none",
            "last_calendar_scanned_count": 0,
            "last_calendar_included_ids": [],
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
        if not isinstance(self.sync_state.get("calendar_sync_tokens"), dict):
            self.sync_state["calendar_sync_tokens"] = {}
        if not isinstance(self.sync_state.get("last_calendar_included_ids"), list):
            self.sync_state["last_calendar_included_ids"] = []

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

    def create_calendar_immediate(self, title: str, description: str, start_at: str, end_at: str, recurrence: str) -> CalendarRecord:
        self.evaluate_auth_status()
        if self.sync_state.get("mode") != "google_connected":
            raise RuntimeError("Google Calendar is not connected. Authenticate first.")

        rec = self._make_calendar_record(title, description, start_at, end_at, recurrence)
        result = self._push_google_item("calendar", "create", asdict(rec))
        if not result.get("ok"):
            raise RuntimeError(str(result.get("reason") or "Google Calendar create failed."))

        rec.google_event_id = str(result.get("external_id") or "")
        rec.sync_status = "synced"
        rec.last_synced_at = _now_iso()
        rec.source = "local"
        rec.origin = "local_user"
        rec.metadata = dict(rec.metadata or {})
        rec.metadata["source_calendar_id"] = "primary"
        rec.metadata["source_calendar_name"] = "Primary"
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

    def update_calendar_immediate(
        self, rec_id: str, title: str, description: str, start_at: str, end_at: str, recurrence: str
    ) -> Optional[CalendarRecord]:
        rec = self.calendar_records.get(rec_id)
        if not rec:
            return None

        self.evaluate_auth_status()
        if self.sync_state.get("mode") != "google_connected":
            raise RuntimeError("Google Calendar is not connected. Authenticate first.")

        proposed = asdict(rec)
        proposed.update(
            {
                "title": title,
                "description": description,
                "start_at": start_at,
                "end_at": end_at,
                "recurrence": recurrence,
                "status": "active",
            }
        )
        op = "update" if rec.google_event_id else "create"
        result = self._push_google_item("calendar", op, proposed)
        if not result.get("ok"):
            raise RuntimeError(str(result.get("reason") or "Google Calendar update failed."))

        rec.title = title
        rec.description = description
        rec.start_at = start_at
        rec.end_at = end_at
        rec.recurrence = recurrence
        if not rec.google_event_id:
            rec.google_event_id = str(result.get("external_id") or "")
        rec.sync_status = "synced"
        rec.last_synced_at = _now_iso()
        rec.source = "local"
        rec.origin = "local_edit"
        rec.metadata = dict(rec.metadata or {})
        rec.metadata["source_calendar_id"] = "primary"
        rec.metadata["source_calendar_name"] = "Primary"
        rec.fingerprint = _fingerprint(asdict(rec), ["title", "description", "start_at", "end_at", "recurrence", "status"])
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

    def cancel_calendar_immediate(self, rec_id: str) -> Optional[CalendarRecord]:
        rec = self.calendar_records.get(rec_id)
        if not rec:
            return None

        self.evaluate_auth_status()
        if rec.google_event_id:
            if self.sync_state.get("mode") != "google_connected":
                raise RuntimeError("Google Calendar is not connected. Authenticate first.")
            result = self._push_google_item("calendar", "delete", asdict(rec))
            if not result.get("ok"):
                raise RuntimeError(str(result.get("reason") or "Google Calendar delete failed."))

        rec.status = "cancelled"
        rec.sync_status = "synced"
        rec.last_synced_at = _now_iso()
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

    def _load_google_credentials(self) -> Any:
        if not self._token_path or not self._token_path.exists():
            raise RuntimeError("Google token missing. Authenticate first.")
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
        except Exception as ex:
            raise RuntimeError(f"Google auth dependencies unavailable: {ex}") from ex

        creds = Credentials.from_authorized_user_file(str(self._token_path), GOOGLE_SCOPES)
        if creds and creds.expired and creds.refresh_token:
            self._log("GoogleCalendar refreshing expired Google token.")
            creds.refresh(Request())
            self._token_path.write_text(creds.to_json(), encoding="utf-8")
            self._set_shared_auth_state(
                token_valid=True,
                token_present=True,
                credentials_present=bool(self._credentials_path and self._credentials_path.exists()),
                credentials_path=str(self._credentials_path) if self._credentials_path else "",
            )
        if not creds or not creds.valid:
            self._set_shared_auth_state(
                token_valid=False,
                token_present=bool(self._token_path and self._token_path.exists()),
                credentials_present=bool(self._credentials_path and self._credentials_path.exists()),
                credentials_path=str(self._credentials_path) if self._credentials_path else "",
            )
            raise RuntimeError("Google token is invalid. Re-authenticate.")
        return creds

    def _calendar_service(self) -> Any:
        try:
            from googleapiclient.discovery import build
        except Exception as ex:
            raise RuntimeError(f"google-api-python-client unavailable: {ex}") from ex
        return build("calendar", "v3", credentials=self._load_google_credentials(), cache_discovery=False)

    @staticmethod
    def _event_start_end_to_iso(payload: dict[str, Any]) -> tuple[str, str]:
        start_obj = payload.get("start") or {}
        end_obj = payload.get("end") or {}
        start_raw = str(start_obj.get("dateTime") or start_obj.get("date") or _now_iso())
        end_raw = str(end_obj.get("dateTime") or end_obj.get("date") or start_raw)
        if len(start_raw) == 10:
            start_raw = f"{start_raw}T00:00:00+00:00"
        if len(end_raw) == 10:
            end_raw = f"{end_raw}T00:00:00+00:00"
        return start_raw.replace("Z", "+00:00"), end_raw.replace("Z", "+00:00")

    @staticmethod
    def _local_calendar_visibility_filter(item: dict[str, Any]) -> bool:
        start_at = _iso_to_dt(str(item.get("start_at") or ""))
        if not start_at:
            return True
        now = datetime.now(UTC)
        window_start = now - timedelta(days=365)
        window_end = now + timedelta(days=365)
        return window_start <= start_at <= window_end

    def _discover_sync_calendars(self, service: Any) -> list[dict[str, str]]:
        calendar_api = service.calendarList()
        page_token = ""
        discovered: list[dict[str, str]] = []
        while True:
            params: dict[str, Any] = {"showHidden": False, "showDeleted": False, "minAccessRole": "reader"}
            if page_token:
                params["pageToken"] = page_token
            response = calendar_api.list(**params).execute()
            for raw in response.get("items", []):
                calendar_id = str(raw.get("id") or "").strip()
                if not calendar_id:
                    continue
                hidden = bool(raw.get("hidden", False))
                selected = raw.get("selected")
                summary = str(raw.get("summaryOverride") or raw.get("summary") or calendar_id)
                if hidden:
                    continue
                if selected is None:
                    include = True
                else:
                    include = bool(selected)
                if not include:
                    continue
                discovered.append(
                    {
                        "id": calendar_id,
                        "summary": summary,
                        "backgroundColor": str(raw.get("backgroundColor") or "#4285F4"),
                        "foregroundColor": str(raw.get("foregroundColor") or "#FFFFFF"),
                        "selected": bool(include),
                        "accessRole": str(raw.get("accessRole") or ""),
                    }
                )
            page_token = str(response.get("nextPageToken") or "")
            if not page_token:
                break
        if not discovered:
            discovered = [{"id": "primary", "summary": "Primary"}]
        self._log(
            "GoogleCalendar discovered calendars="
            + json.dumps([{"id": x["id"], "name": x["summary"]} for x in discovered], ensure_ascii=False)
        )
        return discovered

    def _fetch_calendar_changes_for_calendar(
        self,
        events_api: Any,
        calendar_id: str,
        calendar_name: str,
        calendar_background: str,
        calendar_foreground: str,
        sync_token: str,
    ) -> tuple[list[dict[str, Any]], str, str, int]:
        page_token = ""
        events_out: list[dict[str, Any]] = []
        next_sync_token = sync_token
        using_incremental = bool(sync_token)
        if using_incremental:
            self._log(
                "GoogleCalendar incremental sync start "
                f"(calendar={calendar_id}, syncToken only): token_present={bool(sync_token)}."
            )
        else:
            self._log(
                "GoogleCalendar full sync bootstrap start "
                f"(calendar={calendar_id}, no timeMin/timeMax, no server-side date filters)."
            )

        while True:
            params: dict[str, Any] = {
                "calendarId": calendar_id,
                "showDeleted": True,
                "maxResults": 2500,
            }
            if page_token:
                params["pageToken"] = page_token
            if using_incremental:
                params["syncToken"] = sync_token
            self._log(
                "GoogleCalendar fetch page params="
                + json.dumps({"has_sync_token": bool(params.get("syncToken")), "has_timeMin": False, "has_timeMax": False})
            )
            try:
                response = events_api.list(**params).execute()
            except Exception as ex:
                status = int(getattr(getattr(ex, "resp", None), "status", 0) or 0)
                if status == 410:
                    self._log(
                        "GoogleCalendar sync token expired (HTTP 410); "
                        f"calendar={calendar_id}; forcing full bootstrap resync."
                    )
                    raise ValueError("sync_token_invalid") from ex
                raise RuntimeError(f"Google calendar fetch failed for {calendar_id} (status={status}): {ex}") from ex
            for raw_item in response.get("items", []):
                start_at, end_at = self._event_start_end_to_iso(raw_item)
                events_out.append(
                    {
                        "id": str(raw_item.get("id") or ""),
                        "source_calendar_id": calendar_id,
                        "source_calendar_name": calendar_name,
                        "calendar_background_color": calendar_background,
                        "calendar_foreground_color": calendar_foreground,
                        "title": str(raw_item.get("summary") or "Untitled Event"),
                        "description": str(raw_item.get("description") or ""),
                        "start_at": start_at,
                        "end_at": end_at,
                        "recurrence": str(",".join(raw_item.get("recurrence") or [])) if raw_item.get("recurrence") else "none",
                        "status": str(raw_item.get("status") or "confirmed"),
                        "colorId": str(raw_item.get("colorId") or ""),
                        "location": str(raw_item.get("location") or ""),
                        "attendees": list(raw_item.get("attendees") or []),
                        "htmlLink": str(raw_item.get("htmlLink") or ""),
                        "organizer": raw_item.get("organizer") or {},
                        "reminders": raw_item.get("reminders") or {},
                    }
                )
            page_token = str(response.get("nextPageToken") or "")
            if not page_token:
                next_sync_token = str(response.get("nextSyncToken") or next_sync_token or "")
                break

        fetched_count = len(events_out)
        visible_items = [x for x in events_out if self._local_calendar_visibility_filter(x)]
        self._log(
            "GoogleCalendar per-calendar sync result "
            f"calendar={calendar_id} name={calendar_name!r} fetched={fetched_count} visible={len(visible_items)}."
        )
        if next_sync_token:
            self._log(f"GoogleCalendar nextSyncToken stored successfully for calendar={calendar_id}.")
        else:
            self._log(f"GoogleCalendar warning: no nextSyncToken returned by Google for calendar={calendar_id}.")
        return visible_items, next_sync_token, ("incremental" if using_incremental else "full"), fetched_count

    def _fetch_google_changes(self, kind: str, sync_token: str) -> tuple[list[dict[str, Any]], str]:
        if kind != "calendar":
            return [], sync_token

        service = self._calendar_service()
        events_api = service.events()
        calendars = self._discover_sync_calendars(service)
        self.sync_state["last_calendar_scanned_count"] = len(calendars)
        self.sync_state["last_calendar_included_ids"] = [c["id"] for c in calendars]
        self._log(
            "GoogleCalendar included calendars for sync="
            + json.dumps(self.sync_state["last_calendar_included_ids"], ensure_ascii=False)
        )

        token_map = self.sync_state.get("calendar_sync_tokens") or {}
        if not isinstance(token_map, dict):
            token_map = {}

        all_visible: list[dict[str, Any]] = []
        total_fetched = 0
        modes: set[str] = set()
        for cal in calendars:
            cal_id = cal["id"]
            cal_name = cal["summary"]
            cal_bg = str(cal.get("backgroundColor") or "#4285F4")
            cal_fg = str(cal.get("foregroundColor") or "#FFFFFF")
            cal_token = str(token_map.get(cal_id) or "")
            try:
                cal_items, cal_next_token, mode, fetched_count = self._fetch_calendar_changes_for_calendar(
                    events_api=events_api,
                    calendar_id=cal_id,
                    calendar_name=cal_name,
                    calendar_background=cal_bg,
                    calendar_foreground=cal_fg,
                    sync_token=cal_token,
                )
            except ValueError as ex:
                if "sync_token_invalid" not in str(ex):
                    raise
                token_map[cal_id] = ""
                self._log(f"GoogleCalendar cleared invalid sync token for calendar={cal_id}; retrying bootstrap.")
                cal_items, cal_next_token, mode, fetched_count = self._fetch_calendar_changes_for_calendar(
                    events_api=events_api,
                    calendar_id=cal_id,
                    calendar_name=cal_name,
                    calendar_background=cal_bg,
                    calendar_foreground=cal_fg,
                    sync_token="",
                )
            token_map[cal_id] = cal_next_token
            self._log(f"GoogleCalendar token update calendar={cal_id} token_present={bool(cal_next_token)}.")
            all_visible.extend(cal_items)
            total_fetched += fetched_count
            modes.add(mode)

        self.sync_state["calendar_sync_tokens"] = token_map
        # Retain legacy single-token field for backwards compatibility (primary if present).
        self.sync_state["calendar_sync_token"] = str(token_map.get("primary") or "")
        self.sync_state["last_calendar_fetched_count"] = total_fetched
        self.sync_state["last_calendar_visible_count"] = len(all_visible)
        if modes == {"incremental"}:
            self.sync_state["last_calendar_sync_mode"] = "incremental"
        elif "incremental" in modes and "full" in modes:
            self.sync_state["last_calendar_sync_mode"] = "mixed"
        else:
            self.sync_state["last_calendar_sync_mode"] = "full"
        self._log(
            "GoogleCalendar aggregate sync "
            f"calendars={len(calendars)} fetched_total={total_fetched} visible_total={len(all_visible)} "
            f"mode={self.sync_state['last_calendar_sync_mode']}."
        )
        return all_visible, self.sync_state["calendar_sync_token"]

    def _push_google_item(self, kind: str, operation: str, record: dict[str, Any]) -> dict[str, Any]:
        if kind != "calendar":
            return {"ok": True, "reason": "tasks_not_implemented", "external_id": str(record.get("google_task_id") or "")}
        service = self._calendar_service()
        events_api = service.events()

        google_id = str(record.get("google_event_id") or "")
        start_at = str(record.get("start_at") or _now_iso())
        end_at = str(record.get("end_at") or start_at)
        body = {
            "summary": str(record.get("title") or "Untitled Event"),
            "description": str(record.get("description") or ""),
            "start": {"dateTime": start_at},
            "end": {"dateTime": end_at},
            "status": "cancelled" if str(record.get("status") or "") in {"cancelled", "deleted"} else "confirmed",
        }
        recurrence = str(record.get("recurrence") or "").strip().lower()
        if recurrence and recurrence not in {"none", "null"}:
            rrule_map = {
                "daily": "RRULE:FREQ=DAILY",
                "weekly": "RRULE:FREQ=WEEKLY",
                "monthly": "RRULE:FREQ=MONTHLY",
                "yearly": "RRULE:FREQ=YEARLY",
            }
            if recurrence in rrule_map:
                body["recurrence"] = [rrule_map[recurrence]]

        try:
            if operation == "delete":
                if google_id:
                    events_api.delete(calendarId="primary", eventId=google_id).execute()
                self._log(f"GoogleCalendar push success: delete event google_id={google_id or 'none'}")
                return {"ok": True, "reason": "deleted", "external_id": google_id}

            if operation == "update" and google_id:
                updated = events_api.update(calendarId="primary", eventId=google_id, body=body).execute()
                self._log(f"GoogleCalendar push success: update event google_id={google_id}")
                return {"ok": True, "reason": "updated", "external_id": str(updated.get('id') or google_id)}

            if google_id:
                self._log(f"GoogleCalendar mapping reuse: existing google_event_id={google_id}; forcing update over create.")
                updated = events_api.update(calendarId="primary", eventId=google_id, body=body).execute()
                return {"ok": True, "reason": "updated", "external_id": str(updated.get('id') or google_id)}

            created = events_api.insert(calendarId="primary", body=body).execute()
            created_id = str(created.get("id") or "")
            self._log(f"GoogleCalendar push success: create event google_id={created_id}")
            return {"ok": True, "reason": "created", "external_id": created_id}
        except Exception as ex:
            self._log(f"GoogleCalendar push failed ({operation}): {ex}")
            return {"ok": False, "reason": str(ex), "external_id": google_id}

    def _reconcile_google_calendar_item(self, item: dict[str, Any]) -> None:
        def _is_cancelled_or_deleted(payload: dict[str, Any]) -> bool:
            status = str(payload.get("status") or "").strip().lower()
            if status in {"cancelled", "deleted"}:
                return True
            if bool(payload.get("deleted")):
                return True
            return False

        google_id = str(item.get("id") or "")
        if not google_id:
            return
        source_calendar_id = str(item.get("source_calendar_id") or "")
        source_calendar_name = str(item.get("source_calendar_name") or "")
        calendar_bg = str(item.get("calendar_background_color") or "")
        calendar_fg = str(item.get("calendar_foreground_color") or "")
        is_cancelled = _is_cancelled_or_deleted(item)

        mapped = next(
            (
                r
                for r in self.calendar_records.values()
                if r.google_event_id == google_id
                and (
                    not source_calendar_id
                    or str((r.metadata or {}).get("source_calendar_id") or "") in {"", source_calendar_id}
                )
            ),
            None,
        )
        if mapped is None:
            mapped = next((r for r in self.calendar_records.values() if r.google_event_id == google_id), None)

        if mapped:
            self._log(f"GoogleCalendar reconcile mapping reuse for google_event_id={google_id}.")
            if is_cancelled:
                mapped.status = "cancelled"
                mapped.source = "google"
                mapped.origin = "google_sync"
                mapped.sync_status = "synced"
                mapped.last_synced_at = _now_iso()
                mapped.metadata = dict(mapped.metadata or {})
                if source_calendar_id:
                    mapped.metadata["source_calendar_id"] = source_calendar_id
                if source_calendar_name:
                    mapped.metadata["source_calendar_name"] = source_calendar_name
                mapped.fingerprint = _fingerprint(asdict(mapped), ["title", "description", "start_at", "end_at", "recurrence", "status"])
                self._emit("calendar.item.deleted", asdict(mapped))
                # Purge cancelled/deleted inbound mappings so they are not counted as active reminders/events.
                self.calendar_records.pop(mapped.id, None)
                self._save_state()
                return

            mapped.title = str(item.get("title") or mapped.title)
            mapped.description = str(item.get("description") or mapped.description)
            mapped.start_at = str(item.get("start_at") or mapped.start_at)
            mapped.end_at = str(item.get("end_at") or mapped.end_at)
            mapped.recurrence = str(item.get("recurrence") or mapped.recurrence)
            mapped.status = str(item.get("status") or "active")
            mapped.source = "google"
            mapped.origin = "google_sync"
            mapped.sync_status = "synced"
            mapped.last_synced_at = _now_iso()
            mapped.metadata = dict(mapped.metadata or {})
            if source_calendar_id:
                mapped.metadata["source_calendar_id"] = source_calendar_id
            if source_calendar_name:
                mapped.metadata["source_calendar_name"] = source_calendar_name
            if calendar_bg:
                mapped.metadata["calendar_background_color"] = calendar_bg
            if calendar_fg:
                mapped.metadata["calendar_foreground_color"] = calendar_fg
            mapped.metadata["event_color_id"] = str(item.get("colorId") or "")
            mapped.metadata["location"] = str(item.get("location") or mapped.metadata.get("location") or "")
            mapped.metadata["attendees"] = list(item.get("attendees") or mapped.metadata.get("attendees") or [])
            mapped.metadata["htmlLink"] = str(item.get("htmlLink") or mapped.metadata.get("htmlLink") or "")
            reminders = item.get("reminders") or {}
            overrides = reminders.get("overrides") if isinstance(reminders, dict) else None
            if overrides and isinstance(overrides, list):
                mapped.metadata["reminder_minutes"] = int((overrides[0] or {}).get("minutes") or 10)
                mapped.metadata["reminder_method"] = str((overrides[0] or {}).get("method") or "popup")
            mapped.fingerprint = _fingerprint(asdict(mapped), ["title", "description", "start_at", "end_at", "recurrence", "status"])
            self._emit("calendar.item.updated", asdict(mapped))
            self._save_state()
            return

        if is_cancelled:
            self._log(
                f"GoogleCalendar reconcile inbound cancellation for google_event_id={google_id} "
                "(no local mapping found; no local create)."
            )
            self._save_state()
            return

        # New inbound from Google: create local record with mapping.
        self._log(f"GoogleCalendar reconcile inbound create for google_event_id={google_id} (no local mapping found).")
        rec = self._make_calendar_record(
            title=str(item.get("title") or "Untitled Event"),
            description=str(item.get("description") or ""),
            start_at=str(item.get("start_at") or _now_iso()),
            end_at=str(item.get("end_at") or _now_iso()),
            recurrence=str(item.get("recurrence") or "none"),
        )
        rec.google_event_id = google_id
        rec.status = str(item.get("status") or "active")
        rec.source = "google"
        rec.origin = "google_sync"
        rec.sync_status = "synced"
        rec.last_synced_at = _now_iso()
        rec.metadata = dict(rec.metadata or {})
        if source_calendar_id:
            rec.metadata["source_calendar_id"] = source_calendar_id
        if source_calendar_name:
            rec.metadata["source_calendar_name"] = source_calendar_name
        if calendar_bg:
            rec.metadata["calendar_background_color"] = calendar_bg
        if calendar_fg:
            rec.metadata["calendar_foreground_color"] = calendar_fg
        rec.metadata["event_color_id"] = str(item.get("colorId") or "")
        rec.metadata["location"] = str(item.get("location") or "")
        rec.metadata["attendees"] = list(item.get("attendees") or [])
        rec.metadata["htmlLink"] = str(item.get("htmlLink") or "")
        reminders = item.get("reminders") or {}
        overrides = reminders.get("overrides") if isinstance(reminders, dict) else None
        if overrides and isinstance(overrides, list):
            rec.metadata["reminder_minutes"] = int((overrides[0] or {}).get("minutes") or 10)
            rec.metadata["reminder_method"] = str((overrides[0] or {}).get("method") or "popup")
        self.calendar_records[rec.id] = rec
        self._emit("calendar.item.created", asdict(rec))
        self._save_state()

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
            cal_items, next_cal_token = self._fetch_google_changes("calendar", cal_token)
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


class GoogleCalendarWorkspaceModule:
    """Workspace-first Google Calendar module UI."""

    def __init__(self, runtime: GoogleCalendarRuntime, deck_api: dict[str, Any]):
        self.runtime = runtime
        self._deck_api = deck_api
        self._log: Callable[[str], None] = deck_api.get("log") if callable(deck_api.get("log")) else (lambda _msg: None)
        self._claim_workspaces = deck_api.get("claim_workspaces") if callable(deck_api.get("claim_workspaces")) else None
        self._request_ai = deck_api.get("request_ai_interpretation") if callable(deck_api.get("request_ai_interpretation")) else None
        self._send_to_session = deck_api.get("send_to_session") if callable(deck_api.get("send_to_session")) else None
        self._module_send_to_session = deck_api.get("module_send_to_session") if callable(deck_api.get("module_send_to_session")) else None
        self._handoff_workspace_context = deck_api.get("handoff_workspace_context") if callable(deck_api.get("handoff_workspace_context")) else None
        self._module_key = "google_calendar"

        self.active_view = "Week"
        self.focused_workspace = "calendar"
        self.selected_calendar_id = ""
        self.selected_task_id = ""
        self.current_date = datetime.now().date()
        self.visible_calendar_ids: set[str] = set()
        self.sidebar_mode = ""

        self.panel_widget: Optional[QWidget] = None
        self.calendar_workspace_widget: Optional[QWidget] = None
        self.drive_workspace_widget: Optional[QWidget] = None
        self.gmail_workspace_widget: Optional[QWidget] = None
        self.ribbon_widget: Optional[QWidget] = None
        self.editor_tabs: Optional[QTabWidget] = None
        self.event_detail_overlay: Optional[QFrame] = None
        self.workspace_claim_status = "Workspace claim pending."
        self.last_action_status = "Ready."
        self._daily_task_reminder_date = ""
        self._daily_task_reminder_minute_fired = False
        self.reminder_timer = QTimer()
        self.reminder_timer.setInterval(30000)
        self.reminder_timer.timeout.connect(self._process_reminders)
        self.reminder_timer.start()

    def _fit_text_widget(self, widget: QWidget, text: str) -> None:
        if not text:
            return
        fm = widget.fontMetrics()
        if widget.width() <= 24:
            return
        px = widget.width() - 16
        current = widget.font().pointSizeF() or 10.0
        while current > 7.0 and fm.horizontalAdvance(text) > px:
            current -= 0.5
            f = widget.font()
            f.setPointSizeF(current)
            widget.setFont(f)
            fm = widget.fontMetrics()

    def _apply_font_scaling(self) -> None:
        if not self.panel_widget:
            return
        font_widgets: list[QWidget] = []
        for widget_type in (QLabel, QPushButton, QCheckBox, QToolButton, QComboBox):
            font_widgets.extend(self.panel_widget.findChildren(widget_type))
        for w in font_widgets:
            text = ""
            if hasattr(w, "text"):
                text = str(w.text())
            elif isinstance(w, QComboBox):
                text = str(w.currentText())
            self._fit_text_widget(w, text)
        if hasattr(self, "calendar_grid"):
            for c in range(self.calendar_grid.columnCount()):
                item = self.calendar_grid.horizontalHeaderItem(c)
                if item:
                    self._fit_text_widget(self.calendar_grid.horizontalHeader(), item.text())

    # ---- Builders ---------------------------------------------------------
    def build_module_panel(self) -> QWidget:
        if self.panel_widget is not None:
            return self.panel_widget
        panel = QWidget()
        root = QVBoxLayout(panel)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        sync_box = QGroupBox("Sync / Auth", panel)
        sync_layout = QVBoxLayout(sync_box)
        self.sync_label = QLabel(sync_box)
        self.sync_label.setWordWrap(True)
        sync_layout.addWidget(self.sync_label)
        sync_btn_row = QHBoxLayout()
        self.auth_google_btn = QPushButton("Authenticate Google", sync_box)
        self.sync_now_btn = QPushButton("Run Sync Now", sync_box)
        self.sync_refresh_btn = QPushButton("Refresh Status", sync_box)
        sync_btn_row.addWidget(self.auth_google_btn)
        sync_btn_row.addWidget(self.sync_now_btn)
        sync_btn_row.addWidget(self.sync_refresh_btn)
        sync_layout.addLayout(sync_btn_row)
        root.addWidget(sync_box)

        self.action_status_label = QLabel(panel)
        self.action_status_label.setWordWrap(True)
        self.action_status_label.setText(self.last_action_status)
        root.addWidget(self.action_status_label)

        self.editor_tabs = QTabWidget(panel)
        self.editor_tabs.addTab(self._build_panel_event_editor(self.editor_tabs), "Event Controls")
        self.editor_tabs.addTab(self._build_panel_task_editor(self.editor_tabs), "Task Controls")
        self.editor_tabs.addTab(self._build_panel_event_list(self.editor_tabs), "List")
        self.editor_tabs.currentChanged.connect(self._on_editor_tab_changed)
        root.addWidget(self.editor_tabs, stretch=1)

        self.panel_widget = panel
        self.auth_google_btn.clicked.connect(self._authenticate_google)
        self.sync_now_btn.clicked.connect(self._run_sync)
        self.sync_refresh_btn.clicked.connect(self.refresh_sync)
        self.refresh_all()
        self._apply_font_scaling()
        return panel

    def _build_panel_event_editor(self, parent: QWidget) -> QWidget:
        box = QWidget(parent)
        layout = QVBoxLayout(box)
        calendar_group = QGroupBox("Calendars", box)
        calendar_layout = QVBoxLayout(calendar_group)
        self.calendar_list_scroll = QScrollArea(calendar_group)
        self.calendar_list_scroll.setWidgetResizable(True)
        self.calendar_list_container = QWidget()
        self.calendar_list_layout = QVBoxLayout(self.calendar_list_container)
        self.calendar_list_scroll.setWidget(self.calendar_list_container)
        calendar_layout.addWidget(self.calendar_list_scroll)
        layout.addWidget(calendar_group)

        form_box = QGroupBox("Event Form", box)
        form = QFormLayout(form_box)
        self.cal_title = QLineEdit(form_box)
        self.cal_date = QDateEdit(form_box)
        self.cal_date.setCalendarPopup(True)
        self.cal_date.setDate(datetime.now().date())
        self.cal_start = QDateTimeEdit(form_box)
        self.cal_start.setCalendarPopup(True)
        self.cal_start.setDateTime(datetime.now())
        self.cal_end = QDateTimeEdit(form_box)
        self.cal_end.setCalendarPopup(True)
        self.cal_end.setDateTime(datetime.now() + timedelta(hours=1))
        self.cal_all_day = QCheckBox("All Day", form_box)
        self.cal_desc = QTextEdit(form_box)
        self.cal_location = QLineEdit(form_box)
        self.cal_selector = QComboBox(form_box)
        self.cal_reminder_minutes = QLineEdit(form_box)
        self.cal_reminder_minutes.setPlaceholderText("10")
        self.cal_reminder_method = QComboBox(form_box)
        self.cal_reminder_method.addItems(["popup", "email"])
        self.cal_recur = QComboBox(form_box)
        self.cal_recur.addItems(["None", "Daily", "Weekly", "Monthly", "Yearly"])
        form.addRow("Title", self.cal_title)
        form.addRow("Date", self.cal_date)
        form.addRow("Start time", self.cal_start)
        form.addRow("End time", self.cal_end)
        form.addRow("", self.cal_all_day)
        form.addRow("Description", self.cal_desc)
        form.addRow("Location", self.cal_location)
        form.addRow("Calendar", self.cal_selector)
        form.addRow("Reminder (min)", self.cal_reminder_minutes)
        form.addRow("Reminder method", self.cal_reminder_method)
        form.addRow("Recurrence", self.cal_recur)
        layout.addWidget(form_box)

        btns = QHBoxLayout()
        self.cal_add_btn = QPushButton("New Event", box)
        self.cal_update_btn = QPushButton("Save", box)
        self.cal_delete_btn = QPushButton("Delete", box)
        self.cal_cancel_btn = QPushButton("Cancel", box)
        self.cal_send_ai_btn = QPushButton("Send to AI", box)
        btns.addWidget(self.cal_add_btn)
        btns.addWidget(self.cal_update_btn)
        btns.addWidget(self.cal_delete_btn)
        btns.addWidget(self.cal_cancel_btn)
        btns.addWidget(self.cal_send_ai_btn)
        layout.addLayout(btns)

        self.cal_add_btn.clicked.connect(self._blank_event_form)
        self.cal_update_btn.clicked.connect(self._update_calendar)
        self.cal_delete_btn.clicked.connect(self._cancel_calendar)
        self.cal_cancel_btn.clicked.connect(self._blank_event_form)
        self.cal_send_ai_btn.clicked.connect(self._send_event_form_to_ai)
        return box

    def _build_panel_task_editor(self, parent: QWidget) -> QWidget:
        box = QWidget(parent)
        layout = QVBoxLayout(box)
        sidebar = QGroupBox("Task Lists", box)
        side_layout = QVBoxLayout(sidebar)
        self.task_sidebar = QListWidget(sidebar)
        self.task_sidebar.itemSelectionChanged.connect(self._on_task_panel_selection)
        side_layout.addWidget(self.task_sidebar)
        layout.addWidget(sidebar)

        form_box = QGroupBox("Task Form", box)
        form = QFormLayout(form_box)
        self.task_title = QLineEdit(form_box)
        self.task_notes = QTextEdit(form_box)
        self.task_due = QDateEdit(form_box)
        self.task_due.setCalendarPopup(True)
        self.task_due.setDate(datetime.now().date())
        self.task_list_selector = QComboBox(form_box)
        form.addRow("Task name", self.task_title)
        form.addRow("Notes", self.task_notes)
        form.addRow("Due date", self.task_due)
        form.addRow("List", self.task_list_selector)
        layout.addWidget(form_box)

        btns = QHBoxLayout()
        self.task_add_btn = QPushButton("Save", box)
        self.task_delete_btn = QPushButton("Delete", box)
        self.task_cancel_btn = QPushButton("Cancel", box)
        self.task_send_ai_btn = QPushButton("Send to AI", box)
        btns.addWidget(self.task_add_btn)
        btns.addWidget(self.task_delete_btn)
        btns.addWidget(self.task_cancel_btn)
        btns.addWidget(self.task_send_ai_btn)
        layout.addLayout(btns)
        self.task_add_btn.clicked.connect(self._update_task)
        self.task_delete_btn.clicked.connect(self._delete_task)
        self.task_cancel_btn.clicked.connect(self._blank_task_form)
        self.task_send_ai_btn.clicked.connect(self._send_task_form_to_ai)
        return box

    def _build_panel_event_list(self, parent: QWidget) -> QWidget:
        box = QWidget(parent)
        layout = QVBoxLayout(box)
        top = QHBoxLayout()
        self.upcoming_window = QComboBox(box)
        self.upcoming_window.addItems(["1 Month", "3 Months", "1 Year"])
        self.upcoming_window.setCurrentText("1 Month")
        self.event_list_refresh_btn = QPushButton("Refresh List", box)
        self.event_list_send_ai_btn = QPushButton("Send to AI", box)
        top.addWidget(QLabel("Window", box))
        top.addWidget(self.upcoming_window)
        top.addStretch(1)
        top.addWidget(self.event_list_refresh_btn)
        top.addWidget(self.event_list_send_ai_btn)
        layout.addLayout(top)
        self.calendar_records_table = QTableWidget(box)
        self.calendar_records_table.setColumnCount(5)
        self.calendar_records_table.setHorizontalHeaderLabels(["Title", "Start", "End", "Source calendar", "Status"])
        self.calendar_records_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.calendar_records_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.calendar_records_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.calendar_records_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.calendar_records_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.calendar_records_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.calendar_records_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.calendar_records_table.itemSelectionChanged.connect(self._on_calendar_panel_selection)
        layout.addWidget(self.calendar_records_table)
        self.event_list_refresh_btn.clicked.connect(self._refresh_upcoming_list)
        self.event_list_send_ai_btn.clicked.connect(self._send_upcoming_to_ai)
        return box

    def _placeholder_workspace(self, title: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel(title, page)
        label.setAlignment(Qt.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(label)
        layout.addStretch(1)
        return page

    def build_calendar_workspace(self) -> QWidget:
        if self.calendar_workspace_widget is not None:
            return self.calendar_workspace_widget
        page = QWidget()
        root = QVBoxLayout(page)
        top = QHBoxLayout()
        self.today_btn = QPushButton("Today", page)
        self.prev_btn = QPushButton("◀", page)
        self.next_btn = QPushButton("▶", page)
        self.month_label = QLabel("", page)
        self.view_selector = QComboBox(page)
        self.view_selector.addItems(["Day", "Week", "Month", "Year", "Schedule", "4 Days"])
        self.view_selector.setCurrentText("Week")
        top.addWidget(self.today_btn)
        top.addWidget(self.prev_btn)
        top.addWidget(self.next_btn)
        top.addWidget(self.month_label)
        top.addStretch(1)
        top.addWidget(self.view_selector)
        root.addLayout(top)

        self.workspace_splitter = QSplitter(Qt.Horizontal, page)
        left = QWidget(page)
        left_layout = QVBoxLayout(left)
        self.calendar_grid = QTableWidget(left)
        self.calendar_grid.setRowCount(24)
        self.calendar_grid.setColumnCount(8)
        self.calendar_grid.setHorizontalHeaderLabels(["Time", "", "", "", "", "", "", ""])
        self.calendar_grid.verticalHeader().setVisible(False)
        self.calendar_grid.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.calendar_grid.cellClicked.connect(self._on_calendar_grid_clicked)
        left_layout.addWidget(self.calendar_grid)
        self.workspace_splitter.addWidget(left)

        right = QWidget(page)
        right_layout = QHBoxLayout(right)
        self.sidebar_icons = QVBoxLayout()
        self.sidebar_tasks_btn = QToolButton(right)
        self.sidebar_tasks_btn.setText("✓")
        self.sidebar_contacts_btn = QToolButton(right)
        self.sidebar_contacts_btn.setText("@")
        self.sidebar_maps_btn = QToolButton(right)
        self.sidebar_maps_btn.setText("⌖")
        self.sidebar_extra_btn = QToolButton(right)
        self.sidebar_extra_btn.setText("⋯")
        for b in [self.sidebar_tasks_btn, self.sidebar_contacts_btn, self.sidebar_maps_btn, self.sidebar_extra_btn]:
            b.setCheckable(True)
            self.sidebar_icons.addWidget(b)
        self.sidebar_icons.addStretch(1)
        right_layout.addLayout(self.sidebar_icons)
        self.sidebar_panel = QFrame(right)
        self.sidebar_panel.setFrameShape(QFrame.StyledPanel)
        self.sidebar_panel_layout = QVBoxLayout(self.sidebar_panel)
        self.sidebar_panel_label = QLabel("Coming Soon", self.sidebar_panel)
        self.sidebar_panel_layout.addWidget(self.sidebar_panel_label)
        right_layout.addWidget(self.sidebar_panel)
        self.workspace_splitter.addWidget(right)
        self.workspace_splitter.setSizes([80, 20])
        root.addWidget(self.workspace_splitter)

        self.event_detail_overlay = QFrame(page)
        self.event_detail_overlay.setVisible(False)
        overlay_layout = QVBoxLayout(self.event_detail_overlay)
        self.event_detail_text = QLabel(self.event_detail_overlay)
        self.event_detail_text.setWordWrap(True)
        overlay_actions = QHBoxLayout()
        self.event_edit_btn = QPushButton("Edit", self.event_detail_overlay)
        self.event_delete_btn = QPushButton("Delete", self.event_detail_overlay)
        self.event_email_btn = QPushButton("Email", self.event_detail_overlay)
        self.event_menu_btn = QPushButton("Menu", self.event_detail_overlay)
        self.event_close_btn = QPushButton("Close", self.event_detail_overlay)
        for w in [self.event_edit_btn, self.event_delete_btn, self.event_email_btn, self.event_menu_btn, self.event_close_btn]:
            overlay_actions.addWidget(w)
        overlay_layout.addWidget(self.event_detail_text)
        overlay_layout.addLayout(overlay_actions)
        root.addWidget(self.event_detail_overlay)

        self.today_btn.clicked.connect(self._go_today)
        self.prev_btn.clicked.connect(lambda: self._shift_date(-1))
        self.next_btn.clicked.connect(lambda: self._shift_date(1))
        self.view_selector.currentTextChanged.connect(self._set_view)
        self.sidebar_tasks_btn.clicked.connect(lambda: self._toggle_sidebar("tasks"))
        self.sidebar_contacts_btn.clicked.connect(lambda: self._toggle_sidebar("contacts"))
        self.sidebar_maps_btn.clicked.connect(lambda: self._toggle_sidebar("maps"))
        self.sidebar_extra_btn.clicked.connect(lambda: self._toggle_sidebar("extra"))
        self.event_close_btn.clicked.connect(lambda: self.event_detail_overlay.setVisible(False))
        self.event_edit_btn.clicked.connect(self._switch_to_event_controls)
        self.event_delete_btn.clicked.connect(self._cancel_calendar)

        self.calendar_workspace_widget = page
        self.refresh_calendar_workspace()
        return page

    def build_drive_workspace(self) -> QWidget:
        if self.drive_workspace_widget is None:
            self.drive_workspace_widget = self._placeholder_workspace("Coming Soon")
        return self.drive_workspace_widget

    def build_gmail_workspace(self) -> QWidget:
        if self.gmail_workspace_widget is None:
            self.gmail_workspace_widget = self._placeholder_workspace("Coming Soon")
        return self.gmail_workspace_widget

    def build_ribbon(self) -> QWidget:
        ribbon = QWidget()
        row = QHBoxLayout(ribbon)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        today = QPushButton("Today", ribbon)
        prev = QPushButton("Prev", ribbon)
        nxt = QPushButton("Next", ribbon)
        view = QComboBox(ribbon)
        view.addItems(["Day", "Week", "Month", "Year", "Schedule", "4 Days"])
        view.setCurrentText(self.active_view)
        sync = QPushButton("Run Sync Now", ribbon)
        for w in [today, prev, nxt, view, sync]:
            row.addWidget(w)
        row.addStretch(1)
        today.clicked.connect(self._go_today)
        prev.clicked.connect(lambda: self._shift_date(-1))
        nxt.clicked.connect(lambda: self._shift_date(1))
        view.currentTextChanged.connect(self._set_view)
        sync.clicked.connect(self._run_sync)
        self.ribbon_widget = ribbon
        return ribbon

    # ---- Builders ---------------------------------------------------------
    # ---- Workspace lifecycle hooks ----------------------------------------
    def on_workspace_activate(self, _claim: dict[str, Any]) -> None:
        self.workspace_claim_status = "Workspace claim active: Google, Drive, Gmail. Numbering is host-controlled."
        self._set_action_status(self.workspace_claim_status, log=True)
        self.refresh_all()

    def on_workspace_deactivate(self, _claim: dict[str, Any]) -> None:
        pass

    def on_workspace_release(self, _claim: dict[str, Any]) -> None:
        self.selected_calendar_id = ""
        self.selected_task_id = ""
        self.workspace_claim_status = "Workspace claim released."
        self._set_action_status(self.workspace_claim_status, log=True)

    # ---- UI event handlers -------------------------------------------------
    def _go_today(self) -> None:
        self.current_date = datetime.now().date()
        self.refresh_calendar_workspace()

    def _shift_date(self, delta: int) -> None:
        selected = self.current_date
        if self.active_view == "Year":
            shifted = selected.replace(year=max(1, selected.year + delta))
        elif self.active_view in {"Week", "4 Days"}:
            shifted = selected + timedelta(days=7 * delta)
        else:
            shifted = selected + timedelta(days=delta)
        self.current_date = shifted
        self.refresh_calendar_workspace()

    def _set_view(self, view_name: str) -> None:
        self.active_view = str(view_name or "Week")
        if hasattr(self, "view_selector") and self.view_selector.currentText() != self.active_view:
            self.view_selector.blockSignals(True)
            self.view_selector.setCurrentText(self.active_view)
            self.view_selector.blockSignals(False)
        self.refresh_calendar_workspace()

    def _on_editor_tab_changed(self, index: int) -> None:
        if index == 1:
            self.focused_workspace = "tasks"
        elif index == 0:
            self.focused_workspace = "calendar"
        self.refresh_calendar_workspace()

    def _toggle_sidebar(self, mode: str) -> None:
        if self.sidebar_mode == mode:
            self.sidebar_mode = ""
        else:
            self.sidebar_mode = mode
        for btn, btn_mode in [
            (self.sidebar_tasks_btn, "tasks"),
            (self.sidebar_contacts_btn, "contacts"),
            (self.sidebar_maps_btn, "maps"),
            (self.sidebar_extra_btn, "extra"),
        ]:
            btn.blockSignals(True)
            btn.setChecked(self.sidebar_mode == btn_mode)
            btn.blockSignals(False)
        if not self.sidebar_mode:
            self.workspace_splitter.setSizes([100, 1])
            self.sidebar_panel_label.setText("Coming Soon")
        else:
            self.workspace_splitter.setSizes([80, 20])
            if self.sidebar_mode == "tasks":
                open_tasks = [t for t in self.runtime.task_records.values() if t.status != "completed"]
                preview = "\n".join([f"• {t.title}" for t in open_tasks[:12]]) or "No open tasks"
                self.sidebar_panel_label.setText(preview)
            else:
                self.sidebar_panel_label.setText("Coming Soon")

    def _on_calendar_panel_selection(self) -> None:
        if not hasattr(self, "calendar_records_table"):
            return
        selected = self.calendar_records_table.selectedItems()
        if not selected:
            return
        rec_id = str(selected[0].data(Qt.UserRole) or "")
        rec = self.runtime.calendar_records.get(rec_id)
        if not rec:
            return
        self.focused_workspace = "calendar"
        self.selected_calendar_id = rec.id
        self._populate_calendar_editor(rec)
        self.current_date = (_iso_to_dt(rec.start_at) or datetime.now()).date()
        self._open_event_detail(rec)
        self._update_send_ai_enabled()
        self.refresh_calendar_workspace()

    def _on_task_panel_selection(self) -> None:
        if not hasattr(self, "task_sidebar"):
            return
        item = self.task_sidebar.currentItem()
        if item is None:
            return
        rec_id = str(item.data(Qt.UserRole) or "")
        rec = self.runtime.task_records.get(rec_id)
        if not rec:
            return
        self.focused_workspace = "tasks"
        self.selected_task_id = rec.id
        self._populate_task_editor(rec)
        self._update_task_details(rec)
        self._update_send_ai_enabled()

    def _populate_calendar_editor(self, rec: CalendarRecord) -> None:
        if not hasattr(self, "cal_title"):
            return
        self.cal_title.setText(rec.title)
        self.cal_desc.setPlainText(rec.description)
        start = _iso_to_dt(rec.start_at)
        end = _iso_to_dt(rec.end_at)
        if start:
            self.cal_start.setDateTime(start.replace(tzinfo=None))
        if end:
            self.cal_end.setDateTime(end.replace(tzinfo=None))
        self.cal_recur.setCurrentText(self._recurrence_label(rec.recurrence))

    def _populate_task_editor(self, rec: TaskRecord) -> None:
        if not hasattr(self, "task_title"):
            return
        self.task_title.setText(rec.title)
        self.task_notes.setPlainText(rec.notes)
        due = _iso_to_dt(rec.due_at)
        if due:
            self.task_due.setDate(due.date())
        if hasattr(self, "task_list_selector"):
            source = str((rec.metadata or {}).get("task_list_name") or "Default")
            self.task_list_selector.setCurrentText(source)

    @staticmethod
    def _ui_datetime_to_utc_iso(value: datetime) -> str:
        dt = value
        if dt.tzinfo is None:
            local_tz = datetime.now().astimezone().tzinfo
            dt = dt.replace(tzinfo=local_tz or UTC)
        return dt.astimezone(UTC).isoformat()

    def _blank_event_form(self) -> None:
        self.selected_calendar_id = ""
        self.cal_title.setText("")
        self.cal_desc.setPlainText("")
        self.cal_location.setText("")
        self.cal_date.setDate(self.current_date)
        self.cal_start.setDateTime(datetime.now().replace(minute=0, second=0, microsecond=0))
        self.cal_end.setDateTime(datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        self.cal_reminder_minutes.setText("10")

    def _update_calendar(self) -> None:
        rec_id = self.selected_calendar_id
        try:
            if rec_id:
                self.runtime.update_calendar_immediate(
                    rec_id=rec_id,
                    title=self.cal_title.text().strip() or "Untitled Event",
                    description=self.cal_desc.toPlainText().strip(),
                    start_at=self._ui_datetime_to_utc_iso(self.cal_start.dateTime().toPython()),
                    end_at=self._ui_datetime_to_utc_iso(self.cal_end.dateTime().toPython()),
                    recurrence=self._recurrence_value(self.cal_recur.currentText()),
                )
            else:
                rec = self.runtime.create_calendar_immediate(
                    title=self.cal_title.text().strip() or "Untitled Event",
                    description=self.cal_desc.toPlainText().strip(),
                    start_at=self._ui_datetime_to_utc_iso(self.cal_start.dateTime().toPython()),
                    end_at=self._ui_datetime_to_utc_iso(self.cal_end.dateTime().toPython()),
                    recurrence=self._recurrence_value(self.cal_recur.currentText()),
                )
                self.selected_calendar_id = rec.id
            if self.selected_calendar_id in self.runtime.calendar_records:
                rec = self.runtime.calendar_records[self.selected_calendar_id]
                rec.metadata = dict(rec.metadata or {})
                rec.metadata["location"] = self.cal_location.text().strip()
                rec.metadata["reminder_minutes"] = int(self.cal_reminder_minutes.text().strip() or "10")
                rec.metadata["reminder_method"] = self.cal_reminder_method.currentText()
        except Exception as ex:
            self._log(f"GoogleCalendar Update Selected failed: {ex}")
            QMessageBox.critical(self.panel_widget or QWidget(), "Update Event Failed", str(ex))
            self._set_action_status(f"Update selected event failed: {ex}", log=True)
            self.refresh_all()
            return
        self._set_action_status("Updated selected event.", log=True)
        self.refresh_all()

    def _cancel_calendar(self) -> None:
        rec_id = self.selected_calendar_id
        if not rec_id:
            return
        try:
            self.runtime.cancel_calendar_immediate(rec_id)
        except Exception as ex:
            self._log(f"GoogleCalendar Delete Selected failed: {ex}")
            QMessageBox.critical(self.panel_widget or QWidget(), "Delete Event Failed", str(ex))
            self._set_action_status(f"Delete selected event failed: {ex}", log=True)
            self.refresh_all()
            return
        self.selected_calendar_id = ""
        self._set_action_status("Deleted selected event.", log=True)
        self.refresh_all()

    def _blank_task_form(self) -> None:
        self.selected_task_id = ""
        self.task_title.setText("")
        self.task_notes.setPlainText("")
        self.task_due.setDate(datetime.now().date())

    def _update_task(self) -> None:
        rec_id = self.selected_task_id
        due = datetime.combine(self.task_due.date().toPython(), datetime.min.time()).replace(tzinfo=UTC).isoformat()
        if rec_id:
            self.runtime.update_task(
                rec_id=rec_id,
                title=self.task_title.text().strip() or "Untitled Task",
                notes=self.task_notes.toPlainText().strip(),
                due_at=due,
                recurrence="none",
                status="open",
            )
        else:
            rec = self.runtime.create_task(
                title=self.task_title.text().strip() or "Untitled Task",
                notes=self.task_notes.toPlainText().strip(),
                due_at=due,
                recurrence="none",
            )
            rec.metadata["task_list_name"] = self.task_list_selector.currentText()
            self.selected_task_id = rec.id
        self._set_action_status("Updated selected task.", log=True)
        self.refresh_all()

    def _complete_task(self) -> None:
        rec_id = self.selected_task_id
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
        self._set_action_status("Marked selected task complete.", log=True)
        self.refresh_all()

    def _delete_task(self) -> None:
        rec_id = self.selected_task_id
        if not rec_id:
            return
        self.runtime.delete_task(rec_id)
        self.selected_task_id = ""
        self._set_action_status("Deleted selected task.", log=True)
        self.refresh_all()

    def _run_sync(self) -> None:
        self.runtime.sync_once()
        self._set_action_status("Run Sync Now completed.", log=True)
        self.refresh_all()

    def _authenticate_google(self) -> None:
        selected_path, _ = QFileDialog.getOpenFileName(
            self.panel_widget or QWidget(),
            "Select Google OAuth Credentials",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not selected_path:
            return
        ok, message = self.runtime.authenticate_google(selected_path)
        if ok:
            QMessageBox.information(self.panel_widget or QWidget(), "Google Authentication", message)
            self._set_action_status("Google authentication succeeded.", log=True)
        else:
            QMessageBox.critical(self.panel_widget or QWidget(), "Google Authentication Failed", message)
            self._set_action_status(f"Google authentication failed: {message}", log=True)
        self.refresh_sync()

    def _send_selected_to_ai(self) -> None:
        payload = self._build_selected_payload()
        if payload and self._send_payload_to_ai(payload):
            self._set_action_status("Send to AI succeeded via host handoff.", log=True)
            return
        self._set_action_status("Send to AI failed: no host handoff path available.", log=True)

    def _build_selected_payload(self) -> Optional[dict[str, Any]]:
        rec = self.runtime.calendar_records.get(self.selected_calendar_id)
        if rec:
            return {
                "type": "Calendar Event",
                "title": rec.title,
                "date": rec.start_at.split("T")[0] if rec.start_at else "",
                "description": rec.description,
                "start": rec.start_at,
                "end": rec.end_at,
                "calendar": str((rec.metadata or {}).get("source_calendar_name") or rec.source),
                "location": str((rec.metadata or {}).get("location") or ""),
                "reminder": {
                    "minutes_before": (rec.metadata or {}).get("reminder_minutes"),
                    "method": (rec.metadata or {}).get("reminder_method"),
                },
            }
        task = self.runtime.task_records.get(self.selected_task_id)
        if task:
            return {
                "type": "Task",
                "task_name": task.title,
                "notes": task.notes,
                "due_date": task.due_at.split("T")[0] if task.due_at else "",
                "list": str((task.metadata or {}).get("task_list_name") or "Default"),
            }
        return None

    def _send_payload_to_ai(self, payload: dict[str, Any]) -> bool:
        try:
            if callable(self._module_send_to_session):
                return bool(self._module_send_to_session(self._module_key, payload, True))
            if callable(self._handoff_workspace_context):
                return bool(self._handoff_workspace_context(self._module_key, payload, True))
            if callable(self._send_to_session):
                return bool(self._send_to_session(self._module_key, payload))
            if callable(self._request_ai):
                return bool(self._request_ai(self._module_key, payload))
        except Exception as ex:
            self._set_action_status(f"Send to AI failed with exception: {ex}", log=True)
            return False
        return False

    def _set_action_status(self, text: str, log: bool = False) -> None:
        self.last_action_status = text
        if hasattr(self, "action_status_label"):
            self.action_status_label.setText(text)
        if log:
            self._log(f"GoogleCalendar UI: {text}")

    def _recurrence_label(self, recurrence_value: str) -> str:
        normalized = str(recurrence_value or "none").strip().lower()
        mapping = {
            "none": "None",
            "daily": "Daily",
            "weekly": "Weekly",
            "monthly": "Monthly",
            "yearly": "Yearly",
        }
        return mapping.get(normalized, "None")

    def _recurrence_value(self, recurrence_label: str) -> str:
        return str(recurrence_label or "None").strip().lower() or "none"

    def _update_send_ai_enabled(self) -> None:
        return

    def _selected_table_id(self, table: Optional[QTableWidget]) -> str:
        if table is None:
            return ""
        selected = table.selectedItems()
        if not selected:
            return ""
        return str(selected[0].data(Qt.UserRole) or "")

    @staticmethod
    def _split_dt_cell(iso_value: str) -> tuple[str, str]:
        dt = _iso_to_dt(iso_value)
        if not dt:
            return "", ""
        local_dt = dt.astimezone()
        return local_dt.strftime("%Y-%m-%d"), local_dt.strftime("%H:%M")

    @staticmethod
    def _table_dt_cell(iso_value: str) -> str:
        dt = _iso_to_dt(iso_value)
        if not dt:
            return ""
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _short_cell_text(text: str, limit: int = 90) -> str:
        cleaned = " ".join(str(text or "").split())
        if len(cleaned) <= limit:
            return cleaned
        return f"{cleaned[: max(0, limit - 1)]}…"

    def _select_calendar_table_row(self, rec_id: str) -> None:
        if not hasattr(self, "calendar_records_table"):
            return
        table = self.calendar_records_table
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item and str(item.data(Qt.UserRole) or "") == rec_id:
                table.blockSignals(True)
                table.selectRow(row)
                table.blockSignals(False)
                return

    def _select_task_table_row(self, rec_id: str) -> None:
        if not hasattr(self, "task_records_table"):
            return
        table = self.task_records_table
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item and str(item.data(Qt.UserRole) or "") == rec_id:
                table.blockSignals(True)
                table.selectRow(row)
                table.blockSignals(False)
                return

    # ---- Rendering helpers -------------------------------------------------
    def _calendar_row(self, rec: CalendarRecord) -> str:
        mode = "Google-origin" if rec.source == "google" else ("Synced" if rec.google_event_id else "Local")
        return f"{rec.title} | {rec.start_at} | status={rec.status} | {mode} | sync={rec.sync_status}"

    def _task_row(self, rec: TaskRecord) -> str:
        mode = "Google-origin" if rec.source == "google" else ("Synced" if rec.google_task_id else "Local")
        return f"{rec.title} | due={rec.due_at} | status={rec.status} | {mode} | sync={rec.sync_status}"

    def _update_calendar_details(self, rec: Optional[CalendarRecord]) -> None:
        if not hasattr(self, "calendar_details"):
            return
        if not rec:
            self.calendar_details.setText("No event selected.")
            return
        self.calendar_details.setText(
            f"Title: {rec.title}\n"
            f"Start: {rec.start_at}\nEnd: {rec.end_at}\n"
            f"Recurrence: {rec.recurrence}\nStatus: {rec.status}\n"
            f"Source: {rec.source} ({rec.sync_status})\n"
            f"Description: {rec.description or 'none'}"
        )

    def _update_task_details(self, rec: Optional[TaskRecord]) -> None:
        if not hasattr(self, "task_details"):
            return
        if not rec:
            self.task_details.setText("No task selected.")
            return
        self.task_details.setText(
            f"Title: {rec.title}\nDue: {rec.due_at}\n"
            f"Status: {rec.status}\nRecurrence: {rec.recurrence}\n"
            f"Source: {rec.source} ({rec.sync_status})\n"
            f"Notes: {rec.notes or 'none'}"
        )

    def refresh_calendar_workspace(self) -> None:
        rows = sorted([r for r in self.runtime.calendar_records.values() if r.status not in {"cancelled", "deleted"}], key=lambda r: (r.start_at, r.title))
        if hasattr(self, "month_label"):
            self.month_label.setText(self.current_date.strftime("%B %Y"))
        self._render_calendar_grid(rows)
        self._refresh_upcoming_list()
        self._refresh_calendar_checkboxes()
        self._apply_font_scaling()

    def refresh_tasks_workspace(self) -> None:
        if not hasattr(self, "task_sidebar"):
            return
        rows = sorted([r for r in self.runtime.task_records.values() if r.status != "deleted"], key=lambda r: (r.due_at, r.title))
        self.task_sidebar.clear()
        list_names: set[str] = set()
        for rec in rows:
            item = QListWidgetItem(f"{'☑' if rec.status == 'completed' else '◯'} {rec.title}")
            item.setData(Qt.UserRole, rec.id)
            self.task_sidebar.addItem(item)
            list_names.add(str((rec.metadata or {}).get("task_list_name") or "Default"))
        self.task_list_selector.clear()
        self.task_list_selector.addItems(sorted(list_names or {"Default"}))
        self._apply_font_scaling()

    def _refresh_upcoming_list(self) -> None:
        if not hasattr(self, "calendar_records_table"):
            return
        window = self.upcoming_window.currentText()
        days = 30 if window == "1 Month" else (90 if window == "3 Months" else 365)
        now = datetime.now(UTC)
        end = now + timedelta(days=days)
        rows = []
        seen: set[tuple[str, str]] = set()
        for rec in self.runtime.calendar_records.values():
            start = _iso_to_dt(rec.start_at)
            if not start or start < now or start > end or rec.status in {"cancelled", "deleted"}:
                continue
            key = (rec.google_event_id or rec.id, start.isoformat())
            if key in seen:
                continue
            seen.add(key)
            rows.append(rec)
        rows.sort(key=lambda r: (r.start_at, r.title))
        table = self.calendar_records_table
        table.blockSignals(True)
        table.setRowCount(len(rows))
        for idx, rec in enumerate(rows):
            values = [
                rec.title or "Untitled Event",
                self._table_dt_cell(rec.start_at),
                self._table_dt_cell(rec.end_at),
                str((rec.metadata or {}).get("source_calendar_name") or "local"),
                rec.status,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 0:
                    item.setData(Qt.UserRole, rec.id)
                table.setItem(idx, col, item)
        table.blockSignals(False)

    def refresh_sync(self) -> None:
        if not hasattr(self, "sync_label"):
            return
        self.runtime.evaluate_auth_status()
        state = self.runtime.sync_state
        auth = self.runtime._google_auth_snapshot()
        self.auth_google_btn.setVisible(state.get("auth_status") == "missing")
        self.sync_label.setText(
            f"Mode: {state.get('mode')}\n"
            f"Auth status: {state.get('auth_status')}\n"
            f"Token present: {auth.get('token_present')}\n"
            f"Credentials present: {auth.get('credentials_present')}\n"
            f"Calendar sync mode: {state.get('last_calendar_sync_mode')}\n"
            f"Calendars scanned: {state.get('last_calendar_scanned_count', 0)}\n"
            f"Calendars included: {', '.join(state.get('last_calendar_included_ids', [])) or 'none'}\n"
            f"Calendar fetched (remote pre-filter): {state.get('last_calendar_fetched_count', 0)}\n"
            f"Calendar visible (local post-filter): {state.get('last_calendar_visible_count', 0)}\n"
            f"Last sync: {state.get('last_sync_at') or 'never'}\n"
            f"Last error: {state.get('last_error') or 'none'}"
        )
        self._set_action_status(
            f"Status refreshed. Auth={state.get('auth_status')}, mode={state.get('mode')}, "
            f"events={len(self.runtime.calendar_records)}, tasks={len(self.runtime.task_records)}.",
            log=True,
        )

    def _refresh_calendar_checkboxes(self) -> None:
        if not hasattr(self, "calendar_list_layout"):
            return
        while self.calendar_list_layout.count():
            item = self.calendar_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        calendars: dict[str, dict[str, str]] = {}
        for rec in self.runtime.calendar_records.values():
            cid = str((rec.metadata or {}).get("source_calendar_id") or "primary")
            calendars[cid] = {
                "name": str((rec.metadata or {}).get("source_calendar_name") or cid),
                "background": str((rec.metadata or {}).get("calendar_background_color") or "#4285F4"),
            }
        self.cal_selector.blockSignals(True)
        self.cal_selector.clear()
        for cid, info in sorted(calendars.items(), key=lambda x: x[1]["name"].lower()):
            cb = QCheckBox(info["name"])
            if not self.visible_calendar_ids:
                self.visible_calendar_ids.add(cid)
            cb.setChecked(cid in self.visible_calendar_ids)
            cb.setStyleSheet(f"QCheckBox::indicator:unchecked{{background:{info['background']};}}QCheckBox::indicator:checked{{background:{info['background']};}}")
            cb.toggled.connect(lambda checked, cal_id=cid: self._toggle_calendar_visibility(cal_id, checked))
            self.calendar_list_layout.addWidget(cb)
            self.cal_selector.addItem(info["name"], userData=cid)
        self.cal_selector.blockSignals(False)
        self.calendar_list_layout.addStretch(1)

    def _toggle_calendar_visibility(self, calendar_id: str, checked: bool) -> None:
        if checked:
            self.visible_calendar_ids.add(calendar_id)
        else:
            self.visible_calendar_ids.discard(calendar_id)
        self.refresh_calendar_workspace()

    def _render_calendar_grid(self, rows: list[CalendarRecord]) -> None:
        if not hasattr(self, "calendar_grid"):
            return
        grid = self.calendar_grid
        if self.focused_workspace == "tasks":
            task_lists: dict[str, list[TaskRecord]] = {}
            for task in self.runtime.task_records.values():
                if task.status == "deleted":
                    continue
                list_name = str((task.metadata or {}).get("task_list_name") or "Default")
                task_lists.setdefault(list_name, []).append(task)
            headers = ["List"] + list(task_lists.keys())
            grid.setColumnCount(max(2, len(headers)))
            grid.setRowCount(20)
            grid.setHorizontalHeaderLabels(headers + [""] * (grid.columnCount() - len(headers)))
            for r in range(grid.rowCount()):
                for c in range(grid.columnCount()):
                    grid.setItem(r, c, QTableWidgetItem(""))
            for col, (list_name, tasks) in enumerate(task_lists.items(), start=1):
                grid.setItem(0, col, QTableWidgetItem(f"{list_name}"))
                grid.setItem(1, col, QTableWidgetItem("+ Add a task"))
                for row_idx, task in enumerate(tasks[:17], start=2):
                    grid.setItem(row_idx, col, QTableWidgetItem(f"{'☑' if task.status == 'completed' else '◯'} {task.title}"))
            return
        days = [self.current_date - timedelta(days=self.current_date.weekday()) + timedelta(days=i) for i in range(7)]
        grid.setColumnCount(8)
        grid.setHorizontalHeaderLabels(["Time"] + [d.strftime("%a %m/%d") for d in days])
        for hour in range(24):
            grid.setVerticalHeaderItem(hour, QTableWidgetItem(""))
            time_item = QTableWidgetItem(f"{hour:02d}:00")
            grid.setItem(hour, 0, time_item)
            for col in range(1, 8):
                empty = QTableWidgetItem("")
                if days[col - 1] == datetime.now().date():
                    empty.setBackground(Qt.lightGray)
                grid.setItem(hour, col, empty)
        for rec in rows:
            start_dt = _iso_to_dt(rec.start_at)
            if not start_dt:
                continue
            cal_id = str((rec.metadata or {}).get("source_calendar_id") or "primary")
            if self.visible_calendar_ids and cal_id not in self.visible_calendar_ids:
                continue
            local_start = start_dt.astimezone()
            if local_start.date() not in days:
                continue
            col = days.index(local_start.date()) + 1
            row = max(0, min(23, local_start.hour))
            item = QTableWidgetItem(rec.title)
            color = str((rec.metadata or {}).get("event_background_color") or (rec.metadata or {}).get("calendar_background_color") or "#4285F4")
            item.setBackground(QColor(color))
            item.setData(Qt.UserRole, rec.id)
            grid.setItem(row, col, item)
        self._draw_current_time_line(days)

    def _draw_current_time_line(self, days: list[Any]) -> None:
        now = datetime.now().astimezone()
        if now.date() not in days:
            return
        col = days.index(now.date()) + 1
        row = now.hour
        item = self.calendar_grid.item(row, col)
        if item:
            item.setText(f"━━ {item.text()}")

    def _on_calendar_grid_clicked(self, row: int, col: int) -> None:
        if col == 0:
            return
        item = self.calendar_grid.item(row, col)
        rec_id = str(item.data(Qt.UserRole) or "") if item else ""
        rec = self.runtime.calendar_records.get(rec_id)
        if rec:
            self.selected_calendar_id = rec.id
            self._populate_calendar_editor(rec)
            self._open_event_detail(rec)
            return
        day = self.current_date - timedelta(days=self.current_date.weekday()) + timedelta(days=col - 1)
        dt = datetime(day.year, day.month, day.day, row, 0)
        self._switch_to_event_controls()
        self._blank_event_form()
        self.cal_date.setDate(day)
        self.cal_start.setDateTime(dt)
        self.cal_end.setDateTime(dt + timedelta(hours=1))

    def _switch_to_event_controls(self) -> None:
        if self.editor_tabs:
            self.editor_tabs.setCurrentIndex(0)

    def _open_event_detail(self, rec: CalendarRecord) -> None:
        if not self.event_detail_overlay:
            return
        source_name = str((rec.metadata or {}).get("source_calendar_name") or "Calendar")
        reminder = str((rec.metadata or {}).get("reminder_minutes") or "default")
        self.event_detail_text.setText(
            f"● {rec.title}\n{self._table_dt_cell(rec.start_at)} - {self._table_dt_cell(rec.end_at)}\n"
            f"Invite: {(rec.metadata or {}).get('htmlLink', 'N/A')}\nReminder: {reminder}\nOwner: {source_name}"
        )
        self.event_detail_overlay.setVisible(True)

    def _send_event_form_to_ai(self) -> None:
        payload = {
            "type": "Calendar Event",
            "title": self.cal_title.text().strip(),
            "date": self.cal_date.date().toString("yyyy-MM-dd"),
            "start": self.cal_start.dateTime().toString(Qt.ISODate),
            "end": self.cal_end.dateTime().toString(Qt.ISODate),
            "description": self.cal_desc.toPlainText().strip(),
            "calendar": self.cal_selector.currentText(),
            "reminder": {"minutes_before": self.cal_reminder_minutes.text().strip(), "method": self.cal_reminder_method.currentText()},
        }
        if not self._send_payload_to_ai(payload):
            self._set_action_status("Send to AI failed: no host handoff path available.", log=True)

    def _send_task_form_to_ai(self) -> None:
        payload = {
            "type": "Task",
            "task_name": self.task_title.text().strip(),
            "list": self.task_list_selector.currentText(),
            "due_date": self.task_due.date().toString("yyyy-MM-dd"),
            "notes": self.task_notes.toPlainText().strip(),
        }
        if not self._send_payload_to_ai(payload):
            self._set_action_status("Send to AI failed: no host handoff path available.", log=True)

    def _send_upcoming_to_ai(self) -> None:
        lines = []
        for row in range(self.calendar_records_table.rowCount()):
            t = self.calendar_records_table.item(row, 0).text()
            s = self.calendar_records_table.item(row, 1).text()
            c = self.calendar_records_table.item(row, 3).text()
            lines.append(f"{t} — {s} — {c}")
        payload = {
            "type": "Upcoming Events List",
            "window": self.upcoming_window.currentText(),
            "lines": [f"Upcoming events for the next {self.upcoming_window.currentText()}: {line}" for line in lines],
        }
        self._send_payload_to_ai(payload)

    def _process_reminders(self) -> None:
        now = datetime.now(UTC)
        for rec in self.runtime.calendar_records.values():
            if rec.status in {"cancelled", "deleted"}:
                continue
            start_dt = _iso_to_dt(rec.start_at)
            if not start_dt:
                continue
            minutes = int((rec.metadata or {}).get("reminder_minutes") or 10)
            trigger = start_dt - timedelta(minutes=minutes)
            if trigger <= now <= trigger + timedelta(seconds=35):
                payload = {
                    "type": "Calendar Reminder",
                    "event_title": rec.title,
                    "event_date": start_dt.date().isoformat(),
                    "start_time": start_dt.strftime("%H:%M"),
                    "end_time": (_iso_to_dt(rec.end_at) or start_dt).strftime("%H:%M"),
                    "description": rec.description,
                    "calendar_name": str((rec.metadata or {}).get("source_calendar_name") or ""),
                    "reminder_trigger_window": f"{minutes} minutes",
                    "location": str((rec.metadata or {}).get("location") or ""),
                    "attendees": list((rec.metadata or {}).get("attendees") or []),
                }
                self._send_payload_to_ai(payload)
        self._process_task_reminder_batches(now)

    def _process_task_reminder_batches(self, now: datetime) -> None:
        today = now.date()
        if self._daily_task_reminder_date != today.isoformat():
            self._daily_task_reminder_date = today.isoformat()
            self._daily_task_reminder_minute_fired = False
        if now.hour == 0:
            self._daily_task_reminder_minute_fired = False
        if now.hour == 0 and now.minute < 2 and not self._daily_task_reminder_minute_fired:
            self._daily_task_reminder_minute_fired = True
        if now.minute < 1 and not self._daily_task_reminder_minute_fired:
            return
        batches = {"Due Tomorrow": [], "Due Today": [], "Past Due": [], "Critically Overdue": []}
        for rec in self.runtime.task_records.values():
            if rec.status == "completed":
                continue
            due_dt = _iso_to_dt(rec.due_at)
            if not due_dt:
                continue
            days = (today - due_dt.date()).days
            line = f"{rec.title} — {rec.notes or ''}"
            if days == -1:
                batches["Due Tomorrow"].append(line)
            elif days == 0:
                batches["Due Today"].append(line)
            elif 1 <= days <= 30:
                batches["Past Due"].append(line)
            elif days > 30:
                batches["Critically Overdue"].append(line)
        for batch_name in ["Due Tomorrow", "Due Today", "Past Due", "Critically Overdue"]:
            lines = batches[batch_name]
            if not lines:
                continue
            payload = {
                "type": "Task Reminder Batch",
                "batch_name": batch_name,
                "current_date": today.isoformat(),
                "visible_task_lines": lines,
                "instruction": "no per-item commentary while listing; comment only after the full batch list",
            }
            self._send_payload_to_ai(payload)

    def refresh_all(self) -> None:
        self._process_reminders()
        self.refresh_calendar_workspace()
        self.refresh_tasks_workspace()
        self.refresh_sync()

    def get_workspace_spec(self) -> dict[str, Any]:
        return {
            "tabs": [
                {"id": "google_workspace", "label": "Google", "build": self.build_calendar_workspace},
                {"id": "drive_workspace", "label": "Drive", "build": self.build_drive_workspace},
                {"id": "gmail_workspace", "label": "Gmail", "build": self.build_gmail_workspace},
            ],
            "build_ribbon": self.build_ribbon,
            "on_activate": self.on_workspace_activate,
            "on_deactivate": self.on_workspace_deactivate,
            "on_release": self.on_workspace_release,
        }


def register(deck_api: dict) -> dict:
    deck_api_version = str(deck_api.get("deck_api_version") or "")
    if deck_api_version != "1.0":
        raise RuntimeError(f"Unsupported deck API version: {deck_api_version}")

    runtime = GoogleCalendarRuntime(deck_api)
    ui = GoogleCalendarWorkspaceModule(runtime, deck_api)

    def _on_startup() -> None:
        runtime.evaluate_auth_status()
        runtime._save_state()
        if callable(ui._claim_workspaces):
            try:
                ui._claim_workspaces("google_calendar")
                ui.workspace_claim_status = "Workspace claim requested on startup."
                ui._log("GoogleCalendar workspace claim requested on startup.")
            except Exception as ex:
                ui.workspace_claim_status = f"Workspace claim request failed: {ex}"
                ui._log(f"GoogleCalendar workspace claim request failed: {ex}")

    def _on_message(message: Any) -> None:
        if not isinstance(message, dict):
            return
        event_type = str(message.get("event_type") or "").strip().lower()
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}

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
        ui.refresh_all()

    return {
        "deck_api_version": "1.0",
        "module_key": "google_calendar",
        "display_name": "Google Calendar + Tasks",
        "home_category": "Google",
        "tabs": [
            {
                "tab_id": "google_calendar_main",
                "tab_name": "Google Calendar",
                "get_content": ui.build_module_panel,
            }
        ],
        "workspace": ui.get_workspace_spec(),
        "supports_workspaces": True,
        "workspace_tabs": ui.get_workspace_spec()["tabs"],
        "get_workspace_spec": ui.get_workspace_spec,
        "build_ribbon": ui.build_ribbon,
        "on_workspace_activate": ui.on_workspace_activate,
        "on_workspace_deactivate": ui.on_workspace_deactivate,
        "on_workspace_release": ui.on_workspace_release,
        "hooks": {
            "on_startup": _on_startup,
            "on_message": _on_message,
        },
    }
