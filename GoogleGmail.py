from __future__ import annotations

# ══════════════════════════════════════════════════════════════════════════════
# GoogleGmail.py  —  Full Gmail client module for Echo Deck
# Section 1 of 10: Imports · MODULE_MANIFEST · Constants · GmailClient wrapper
# ══════════════════════════════════════════════════════════════════════════════

import base64
import hashlib
import json
import mimetypes
import re
import uuid
from datetime import datetime, timezone
from email import encoders as _email_encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
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
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# ─────────────────────────────────────────────────────────────────────────────
# MODULE_MANIFEST
# ─────────────────────────────────────────────────────────────────────────────

MODULE_MANIFEST = {
    "key": "google_gmail",
    "display_name": "Google Gmail",
    "version": "1.0.0",
    "deck_api_version": "1.0",
    "home_category": "Google",
    "entry_function": "register",
    "shared_resource": "google_auth",
    "description": (
        "Full Gmail client module for Echo Deck. Workspace-based email reading, "
        "composing, threading, attachments, AI evaluation, and smart sync."
    ),
    "tab_definitions": [
        {
            "tab_id": "google_gmail_main",
            "tab_name": "Google Gmail",
        }
    ],
    "emits": [
        "gmail.message.received",
        "gmail.message.sent",
        "gmail.message.read",
        "gmail.message.deleted",
        "gmail.message.archived",
        "gmail.rule.suggested",
        "gmail.rule.applied",
    ],
    "listens": [
        "gmail.message.*",
        "gmail.rule.*",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

UTC = timezone.utc

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

# System label IDs → display names (order defines folder tree order)
SYSTEM_LABEL_DEFS: list[tuple[str, str]] = [
    ("INBOX",     "Inbox"),
    ("STARRED",   "Starred"),
    ("_SNOOZED",  "Snoozed"),   # local-only pseudo-label
    ("IMPORTANT", "Important"),
    ("SENT",      "Sent"),
    ("DRAFT",     "Drafts"),
    ("SPAM",      "Spam"),
    ("TRASH",     "Trash"),
]

# Category tabs shown above thread list
CATEGORY_TABS: list[str] = ["Primary", "Promotions", "Social", "Updates", "Forums"]

# Maps category tab name → Gmail label ID used to filter threads
CATEGORY_TAB_LABEL: dict[str, str] = {
    "Primary":    "INBOX",
    "Promotions": "CATEGORY_PROMOTIONS",
    "Social":     "CATEGORY_SOCIAL",
    "Updates":    "CATEGORY_UPDATES",
    "Forums":     "CATEGORY_FORUMS",
}

# Max bytes Gmail API allows per message (25 MB)
GMAIL_MAX_SEND_BYTES = 25 * 1024 * 1024

# Default undo-send delay in milliseconds
UNDO_SEND_DELAY_MS = 5_000

# Avatar colour palette (hash-selected per sender)
AVATAR_COLOURS = [
    "#1a73e8", "#ea4335", "#f9ab00", "#34a853",
    "#ff6d00", "#9c27b0", "#00acc1", "#e91e63",
]

# ─────────────────────────────────────────────────────────────────────────────
# Small utility helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _fingerprint(payload: dict[str, Any], keys: list[str]) -> str:
    material = {k: payload.get(k) for k in keys}
    raw = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _decode_base64url(data: str) -> bytes:
    padded = data.replace("-", "+").replace("_", "/")
    padded += "=" * ((4 - len(padded) % 4) % 4)
    return base64.b64decode(padded)


def _header_value(headers: list[dict], name: str) -> str:
    name_lower = name.lower()
    for h in headers or []:
        if str(h.get("name") or "").lower() == name_lower:
            return str(h.get("value") or "")
    return ""


def _sender_display(from_header: str) -> tuple[str, str]:
    """Return (display_name, email_address) parsed from a From header."""
    m = re.match(r'^"?([^"<]+)"?\s*<([^>]+)>', from_header.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    email_m = re.search(r"[\w.+\-]+@[\w.\-]+", from_header)
    if email_m:
        addr = email_m.group(0)
        return addr, addr
    return from_header.strip(), from_header.strip()


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes // 1024} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _format_timestamp(date_header: str) -> str:
    """Return a short human timestamp: HH:MM if today, else Mon DD."""
    if not date_header:
        return ""
    try:
        # Strip timezone name suffix if present (e.g. "(UTC)")
        cleaned = re.sub(r"\s+\([^)]+\)\s*$", "", date_header.strip())
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(cleaned)
        now = datetime.now(dt.tzinfo or UTC)
        if dt.date() == now.date():
            return dt.strftime("%H:%M")
        if dt.year == now.year:
            return dt.strftime("%b %d")
        return dt.strftime("%b %d %Y")
    except Exception:
        return date_header[:10] if date_header else ""


def _avatar_colour(name: str) -> str:
    idx = sum(ord(c) for c in (name or "?")) % len(AVATAR_COLOURS)
    return AVATAR_COLOURS[idx]


def sanitize_html(raw: str) -> str:
    """Strip dangerous HTML: scripts, event handlers, tracking pixels, external img src."""
    # Remove script and noscript blocks
    raw = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<noscript[^>]*>.*?</noscript>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    # Strip inline event handlers (onclick=, onload=, etc.)
    raw = re.sub(r"""\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|\S+)""", "", raw, flags=re.IGNORECASE)
    # Remove 1×1 tracking pixels (match width=1 height=1 in any order)
    raw = re.sub(
        r'<img[^>]+'
        r'(?:width\s*=\s*["\']?1["\']?[^>]*height\s*=\s*["\']?1["\']?'
        r'|height\s*=\s*["\']?1["\']?[^>]*width\s*=\s*["\']?1["\']?)'
        r'[^>]*/?>',
        "",
        raw,
        flags=re.IGNORECASE,
    )
    # Neutralise external img src so QTextEdit does not load remote resources
    raw = re.sub(
        r'(<img[^>]+)src\s*=\s*["\']https?://[^"\']+["\']',
        r'\1src=""',
        raw,
        flags=re.IGNORECASE,
    )
    return raw


def _extract_body(payload: dict[str, Any]) -> tuple[str, str]:
    """Walk a Gmail message payload and return (html_body, plain_body)."""
    html_body = ""
    plain_body = ""

    def _walk(part: dict[str, Any]) -> None:
        nonlocal html_body, plain_body
        mime = str(part.get("mimeType") or "").lower()
        body_obj = part.get("body") or {}
        data = str(body_obj.get("data") or "")
        if data:
            try:
                decoded = _decode_base64url(data).decode("utf-8", errors="replace")
                if mime == "text/html" and not html_body:
                    html_body = decoded
                elif mime == "text/plain" and not plain_body:
                    plain_body = decoded
            except Exception:
                pass
        for sub in part.get("parts") or []:
            _walk(sub)

    _walk(payload)
    return html_body, plain_body


def _extract_attachments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of attachment metadata dicts from a message payload."""
    attachments: list[dict[str, Any]] = []

    def _walk(part: dict[str, Any]) -> None:
        filename = str(part.get("filename") or "")
        body_obj = part.get("body") or {}
        att_id = str(body_obj.get("attachmentId") or "")
        if filename and att_id:
            attachments.append({
                "filename":      filename,
                "attachment_id": att_id,
                "size":          int(body_obj.get("size") or 0),
                "mime_type":     str(part.get("mimeType") or "application/octet-stream"),
            })
        for sub in part.get("parts") or []:
            _walk(sub)

    _walk(payload)
    return attachments


# ─────────────────────────────────────────────────────────────────────────────
# Lightweight data records (no heavy ORM — plain classes, json-serialisable)
# ─────────────────────────────────────────────────────────────────────────────

class ThreadSummary:
    """Minimal per-thread data needed to render one row in the thread list."""
    __slots__ = (
        "thread_id", "subject", "sender_name", "sender_email",
        "snippet", "timestamp", "is_unread", "is_starred",
        "is_important", "has_attachment", "label_ids", "message_count",
    )

    def __init__(
        self,
        thread_id: str,
        subject: str,
        sender_name: str,
        sender_email: str,
        snippet: str,
        timestamp: str,
        is_unread: bool,
        is_starred: bool,
        is_important: bool,
        has_attachment: bool,
        label_ids: list[str],
        message_count: int,
    ) -> None:
        self.thread_id     = thread_id
        self.subject       = subject
        self.sender_name   = sender_name
        self.sender_email  = sender_email
        self.snippet       = snippet
        self.timestamp     = timestamp
        self.is_unread     = is_unread
        self.is_starred    = is_starred
        self.is_important  = is_important
        self.has_attachment = has_attachment
        self.label_ids     = label_ids
        self.message_count = message_count


class MessageDetail:
    """Full message content for the thread-read view."""
    __slots__ = (
        "message_id", "thread_id", "subject",
        "from_header", "to_header", "cc_header", "date_header",
        "html_body", "plain_body", "label_ids",
        "attachments", "snippet", "is_unread",
    )

    def __init__(
        self,
        message_id: str,
        thread_id: str,
        subject: str,
        from_header: str,
        to_header: str,
        cc_header: str,
        date_header: str,
        html_body: str,
        plain_body: str,
        label_ids: list[str],
        attachments: list[dict[str, Any]],
        snippet: str,
        is_unread: bool,
    ) -> None:
        self.message_id  = message_id
        self.thread_id   = thread_id
        self.subject     = subject
        self.from_header = from_header
        self.to_header   = to_header
        self.cc_header   = cc_header
        self.date_header = date_header
        self.html_body   = html_body
        self.plain_body  = plain_body
        self.label_ids   = label_ids
        self.attachments = attachments
        self.snippet     = snippet
        self.is_unread   = is_unread


# ─────────────────────────────────────────────────────────────────────────────
# GmailClient  —  thin wrapper around the Google Gmail API service
# ─────────────────────────────────────────────────────────────────────────────

class GmailClient:
    """
    Wraps googleapiclient.discovery Gmail v1 service.

    Constructed with a valid google.oauth2.credentials.Credentials object.
    Every public method raises RuntimeError on hard failures; callers should
    catch it and surface the message to the user.
    """

    def __init__(self, credentials: Any) -> None:
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "googleapiclient is not installed. "
                "Run: pip install google-api-python-client"
            ) from exc
        self._svc = build("gmail", "v1", credentials=credentials)

    # ── Profile ───────────────────────────────────────────────────────────────

    def get_profile(self) -> dict[str, Any]:
        """Return users.getProfile response (emailAddress, historyId, …)."""
        return self._svc.users().getProfile(userId="me").execute()

    # ── Threads ───────────────────────────────────────────────────────────────

    def list_threads(
        self,
        label_ids: list[str] | None = None,
        query: str = "",
        page_token: str = "",
        max_results: int = 50,
    ) -> tuple[list[dict[str, Any]], str]:
        """
        Return (thread_stubs, next_page_token).
        Each stub is the raw threads.list item: {"id": …, "snippet": …}.
        """
        params: dict[str, Any] = {"userId": "me", "maxResults": max_results}
        if query:
            params["q"] = query
        elif label_ids:
            params["labelIds"] = label_ids
        if page_token:
            params["pageToken"] = page_token
        resp = self._svc.users().threads().list(**params).execute()
        stubs = list(resp.get("threads") or [])
        next_token = str(resp.get("nextPageToken") or "")
        return stubs, next_token

    def get_thread_metadata(self, thread_id: str) -> dict[str, Any]:
        """Fetch a thread with format=metadata (headers only, fast)."""
        return self._svc.users().threads().get(
            userId="me",
            id=thread_id,
            format="metadata",
            metadataHeaders=["From", "Subject", "Date", "To", "Cc"],
        ).execute()

    def get_thread_full(self, thread_id: str) -> dict[str, Any]:
        """Fetch a thread with format=full (complete bodies)."""
        return self._svc.users().threads().get(
            userId="me", id=thread_id, format="full"
        ).execute()

    def modify_thread(
        self,
        thread_id: str,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if add_label_ids:
            body["addLabelIds"] = add_label_ids
        if remove_label_ids:
            body["removeLabelIds"] = remove_label_ids
        return self._svc.users().threads().modify(
            userId="me", id=thread_id, body=body
        ).execute()

    def trash_thread(self, thread_id: str) -> dict[str, Any]:
        return self._svc.users().threads().trash(
            userId="me", id=thread_id
        ).execute()

    def untrash_thread(self, thread_id: str) -> dict[str, Any]:
        return self._svc.users().threads().untrash(
            userId="me", id=thread_id
        ).execute()

    # ── Messages ──────────────────────────────────────────────────────────────

    def send_message(self, raw_b64: str, thread_id: str = "") -> dict[str, Any]:
        """Send a base64url-encoded raw MIME message."""
        body: dict[str, Any] = {"raw": raw_b64}
        if thread_id:
            body["threadId"] = thread_id
        return self._svc.users().messages().send(
            userId="me", body=body
        ).execute()

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        """Download an attachment; returns raw bytes."""
        resp = self._svc.users().messages().attachments().get(
            userId="me", messageId=message_id, id=attachment_id
        ).execute()
        data = str(resp.get("data") or "")
        if not data:
            raise RuntimeError("Attachment data is empty.")
        return _decode_base64url(data)

    # ── Drafts ────────────────────────────────────────────────────────────────

    def create_draft(self, raw_b64: str, thread_id: str = "") -> dict[str, Any]:
        msg: dict[str, Any] = {"raw": raw_b64}
        if thread_id:
            msg["threadId"] = thread_id
        return self._svc.users().drafts().create(
            userId="me", body={"message": msg}
        ).execute()

    def list_drafts(self) -> list[dict[str, Any]]:
        resp = self._svc.users().drafts().list(userId="me").execute()
        return list(resp.get("drafts") or [])

    # ── Labels ────────────────────────────────────────────────────────────────

    def list_labels(self) -> list[dict[str, Any]]:
        resp = self._svc.users().labels().list(userId="me").execute()
        return list(resp.get("labels") or [])

    def create_label(self, name: str, bg_color: str = "", fg_color: str = "") -> dict[str, Any]:
        body: dict[str, Any] = {"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
        if bg_color and fg_color:
            body["color"] = {"backgroundColor": bg_color, "textColor": fg_color}
        return self._svc.users().labels().create(userId="me", body=body).execute()

    # ── History (incremental sync) ────────────────────────────────────────────

    def list_history(
        self,
        start_history_id: str,
        history_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Return the raw history.list response.
        Raises RuntimeError with status code in message on HTTP error so the
        sync engine can detect 404 (historyId expired) and fall back.
        """
        params: dict[str, Any] = {
            "userId": "me",
            "startHistoryId": start_history_id,
        }
        if history_types:
            params["historyTypes"] = history_types
        try:
            return self._svc.users().history().list(**params).execute()
        except Exception as exc:
            # Preserve the HTTP status code in the exception message so the
            # sync engine can parse it.
            status = int(
                getattr(getattr(exc, "resp", None), "status", 0) or 0
            )
            raise RuntimeError(
                f"history.list failed (status={status}): {exc}"
            ) from exc

    # ── MIME builder helpers ──────────────────────────────────────────────────

    @staticmethod
    def build_raw_message(
        from_addr: str,
        to: str,
        subject: str,
        html_body: str,
        cc: str = "",
        bcc: str = "",
        reply_to_message_id: str = "",
        thread_id: str = "",
        attachments: list[dict[str, Any]] | None = None,
    ) -> tuple[str, int]:
        """
        Build a base64url-encoded MIME message.
        Returns (raw_b64, size_bytes).
        Attachments are dicts with keys: path (str), mime_type (str, optional).
        """
        plain_body = re.sub(r"<[^>]+>", "", html_body)

        if attachments:
            root = MIMEMultipart("mixed")
            alt = MIMEMultipart("alternative")
            alt.attach(MIMEText(plain_body, "plain", "utf-8"))
            alt.attach(MIMEText(html_body, "html", "utf-8"))
            root.attach(alt)
            for att in attachments:
                path = Path(str(att.get("path") or ""))
                if not path.exists():
                    continue
                mime_type = (
                    att.get("mime_type")
                    or mimetypes.guess_type(str(path))[0]
                    or "application/octet-stream"
                )
                main_t, sub_t = (
                    mime_type.split("/", 1)
                    if "/" in mime_type
                    else ("application", "octet-stream")
                )
                part = MIMEBase(main_t, sub_t)
                part.set_payload(path.read_bytes())
                _email_encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition", "attachment", filename=path.name
                )
                root.attach(part)
        else:
            root = MIMEMultipart("alternative")
            root.attach(MIMEText(plain_body, "plain", "utf-8"))
            root.attach(MIMEText(html_body, "html", "utf-8"))

        root["From"]    = from_addr
        root["To"]      = to
        root["Subject"] = subject
        if cc:
            root["Cc"] = cc
        if bcc:
            root["Bcc"] = bcc
        if reply_to_message_id:
            root["In-Reply-To"] = reply_to_message_id
            root["References"]  = reply_to_message_id

        raw_bytes = root.as_bytes()
        raw_b64   = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")
        return raw_b64, len(raw_bytes)

    # ── Convenience: thread list → ThreadSummary objects ─────────────────────

    def fetch_thread_summaries(
        self,
        label_ids: list[str] | None = None,
        query: str = "",
        page_token: str = "",
        max_results: int = 50,
    ) -> tuple[list[ThreadSummary], str]:
        """
        High-level helper: returns (list[ThreadSummary], next_page_token).
        Fetches the thread stub list then makes one metadata call per thread.
        """
        stubs, next_token = self.list_threads(
            label_ids=label_ids,
            query=query,
            page_token=page_token,
            max_results=max_results,
        )
        summaries: list[ThreadSummary] = []
        for stub in stubs:
            tid = str(stub.get("id") or "")
            if not tid:
                continue
            try:
                t = self.get_thread_metadata(tid)
                msgs = t.get("messages") or []
                if not msgs:
                    continue
                # Collect label IDs across all messages in thread
                all_labels: list[str] = []
                for m in msgs:
                    all_labels.extend(m.get("labelIds") or [])
                label_set = set(all_labels)

                # Use last message for sender + timestamp context
                last = msgs[-1]
                hdrs = (last.get("payload") or {}).get("headers") or []
                from_h = _header_value(hdrs, "From")
                sender_name, sender_email = _sender_display(from_h)
                subject = _header_value(hdrs, "Subject") or "(no subject)"
                date_h  = _header_value(hdrs, "Date")

                # Detect attachment flag: any part with a filename in any message
                has_att = False
                for m in msgs:
                    payload = m.get("payload") or {}
                    if _extract_attachments(payload):
                        has_att = True
                        break

                summaries.append(ThreadSummary(
                    thread_id     = tid,
                    subject       = subject,
                    sender_name   = sender_name,
                    sender_email  = sender_email,
                    snippet       = str(last.get("snippet") or ""),
                    timestamp     = _format_timestamp(date_h),
                    is_unread     = "UNREAD" in label_set,
                    is_starred    = "STARRED" in label_set,
                    is_important  = "IMPORTANT" in label_set,
                    has_attachment= has_att,
                    label_ids     = list(label_set),
                    message_count = len(msgs),
                ))
            except Exception:
                continue
        return summaries, next_token

    def fetch_thread_messages(self, thread_id: str) -> list[MessageDetail]:
        """
        Fetch all messages in a thread at full format and return MessageDetail list.
        Also marks the thread UNREAD flag removed (read receipt) after fetch.
        """
        t = self.get_thread_full(thread_id)
        msgs = t.get("messages") or []
        result: list[MessageDetail] = []
        for msg in msgs:
            msg_id   = str(msg.get("id") or "")
            label_ids= list(msg.get("labelIds") or [])
            snippet  = str(msg.get("snippet") or "")
            payload  = msg.get("payload") or {}
            hdrs     = payload.get("headers") or []
            html_b, plain_b = _extract_body(payload)
            if html_b:
                html_b = sanitize_html(html_b)
            atts = _extract_attachments(payload)
            result.append(MessageDetail(
                message_id  = msg_id,
                thread_id   = thread_id,
                subject     = _header_value(hdrs, "Subject") or "(no subject)",
                from_header = _header_value(hdrs, "From"),
                to_header   = _header_value(hdrs, "To"),
                cc_header   = _header_value(hdrs, "Cc"),
                date_header = _header_value(hdrs, "Date"),
                html_body   = html_b,
                plain_body  = plain_b,
                label_ids   = label_ids,
                attachments = atts,
                snippet     = snippet,
                is_unread   = "UNREAD" in label_ids,
            ))
        # Remove UNREAD from entire thread
        try:
            self.modify_thread(thread_id, remove_label_ids=["UNREAD"])
        except Exception:
            pass
        return result


# ══════════════════════════════════════════════════════════════════════════════
# Section 2: EmailClassifier · AI Rule Engine · Local Rules Storage
# ══════════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# Data classes for rules and rule conditions / actions
# ─────────────────────────────────────────────────────────────────────────────

class RuleCondition:
    """One condition inside a Rule: field OP value."""
    __slots__ = ("field", "operator", "value")

    VALID_FIELDS    = {"sender", "subject", "body", "label"}
    VALID_OPERATORS = {"contains", "equals", "starts_with", "regex"}

    def __init__(self, field: str, operator: str, value: str) -> None:
        self.field    = field
        self.operator = operator
        self.value    = value

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "operator": self.operator, "value": self.value}

    @classmethod
    def from_dict(cls, d: dict) -> "RuleCondition":
        return cls(
            field    = str(d.get("field")    or "subject"),
            operator = str(d.get("operator") or "contains"),
            value    = str(d.get("value")    or ""),
        )


class RuleAction:
    """One action to perform when a rule matches."""
    __slots__ = ("action", "label_name")

    VALID_ACTIONS = {
        "add_label", "remove_label", "flag", "archive",
        "mark_spam", "notify_ai",
    }

    def __init__(self, action: str, label_name: str = "") -> None:
        self.action     = action
        self.label_name = label_name

    def to_dict(self) -> dict[str, str]:
        return {"action": self.action, "label_name": self.label_name}

    @classmethod
    def from_dict(cls, d: dict) -> "RuleAction":
        return cls(
            action     = str(d.get("action")     or "flag"),
            label_name = str(d.get("label_name") or ""),
        )


class RuleRecord:
    """A single automation rule with conditions and actions."""

    def __init__(
        self,
        rule_id:    str,
        name:       str,
        conditions: list[dict],
        actions:    list[dict],
        created_by: str,
        created_at: str,
        active:     bool,
    ) -> None:
        self.rule_id    = rule_id
        self.name       = name
        self.conditions = conditions   # list of RuleCondition.to_dict()
        self.actions    = actions      # list of RuleAction.to_dict()
        self.created_by = created_by   # "user" | "ai"
        self.created_at = created_at
        self.active     = active

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id":    self.rule_id,
            "name":       self.name,
            "conditions": self.conditions,
            "actions":    self.actions,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "active":     self.active,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RuleRecord":
        return cls(
            rule_id    = str(d.get("rule_id")    or str(uuid.uuid4())),
            name       = str(d.get("name")       or "Unnamed Rule"),
            conditions = list(d.get("conditions") or []),
            actions    = list(d.get("actions")    or []),
            created_by = str(d.get("created_by") or "user"),
            created_at = str(d.get("created_at") or _now_iso()),
            active     = bool(d.get("active", True)),
        )


# ─────────────────────────────────────────────────────────────────────────────
# EmailClassifier  —  lightweight pattern-based pre-classifier
# ─────────────────────────────────────────────────────────────────────────────

class EmailClassifier:
    """
    Classifies emails into coarse categories using keyword / regex patterns
    before the full AI pipeline is invoked.  Results are advisory; the AI
    layer can override or supplement them.
    """

    # Spam / phishing signal words (case-insensitive)
    _SPAM_SIGNALS = re.compile(
        r"\b("
        r"congratulations.{0,30}(won|winner|prize|lottery)|"
        r"click here to (claim|verify|confirm|unlock)|"
        r"verify your (account|identity|payment)|"
        r"your account (has been|will be) (suspended|locked|closed)|"
        r"update your (payment|billing|credit card)|"
        r"unusual (sign.?in|login|activity) detected|"
        r"we noticed (a|an) (unusual|suspicious)|"
        r"urgent.{0,20}action required|"
        r"100% free|act now|limited time offer|"
        r"dear (valued |lucky )?customer|"
        r"nigerian (prince|banker|official)|"
        r"wire transfer|western union|moneygram"
        r")\b",
        re.IGNORECASE | re.DOTALL,
    )

    _PHISHING_SIGNALS = re.compile(
        r"(password|ssn|social security|bank account|credit card|cvv).{0,60}"
        r"(enter|provide|confirm|verify|update)",
        re.IGNORECASE | re.DOTALL,
    )

    # Job-related patterns
    _JOB_REJECTION = re.compile(
        r"\b("
        r"we (regret|are sorry|unfortunately)|"
        r"not moving forward|"
        r"decided (not to|to not)|"
        r"selected (other|another) candidate|"
        r"position has been filled|"
        r"we won't be proceeding|"
        r"your application was (not|unsuccessful)|"
        r"thank you for (applying|your interest|your time).*consider"
        r")\b",
        re.IGNORECASE | re.DOTALL,
    )

    _JOB_INTERVIEW = re.compile(
        r"\b("
        r"interview|phone (screen|call)|"
        r"would like to (schedule|set up|arrange)|"
        r"invite you (to|for) an? (interview|meeting|call)|"
        r"next (step|round|stage)|"
        r"speak with you|"
        r"available (for|to) (a |an )?(chat|call|interview)"
        r")\b",
        re.IGNORECASE | re.DOTALL,
    )

    _JOB_ACK = re.compile(
        r"\b("
        r"received your application|"
        r"application (has been|was) (received|submitted)|"
        r"we will (review|be in touch)|"
        r"thank you for applying"
        r")\b",
        re.IGNORECASE | re.DOTALL,
    )

    # ── Public API ────────────────────────────────────────────────────────────

    def classify_spam(self, subject: str, body: str) -> dict[str, Any]:
        """
        Return {"is_spam": bool, "is_phishing": bool, "signals": [str]}.
        """
        combined = f"{subject} {body}"
        signals: list[str] = []
        is_spam = bool(self._SPAM_SIGNALS.search(combined))
        is_phishing = bool(self._PHISHING_SIGNALS.search(combined))
        if is_spam:
            signals.append("spam_keyword")
        if is_phishing:
            signals.append("phishing_credential_request")
        return {"is_spam": is_spam, "is_phishing": is_phishing, "signals": signals}

    def classify_job_status(self, subject: str, body: str) -> dict[str, Any]:
        """
        Return {"status": "rejection"|"interview"|"acknowledgement"|"unknown"}.
        """
        combined = f"{subject} {body}"
        if self._JOB_REJECTION.search(combined):
            return {"status": "rejection"}
        if self._JOB_INTERVIEW.search(combined):
            return {"status": "interview"}
        if self._JOB_ACK.search(combined):
            return {"status": "acknowledgement"}
        return {"status": "unknown"}

    def build_spam_ai_prompt(
        self, sender: str, subject: str, body: str
    ) -> str:
        return (
            f"Evaluate this email for spam or phishing indicators.\n"
            f"Sender: {sender}\n"
            f"Subject: {subject}\n"
            f"Body (truncated to 500 chars): {body[:500]}\n\n"
            "Respond with your assessment. If you identify phishing patterns, "
            "suggest a rule to block similar emails using this JSON block "
            "(include it verbatim in your response):\n"
            '{"rule_suggestion": {"name": "...", '
            '"conditions": [{"field": "sender", "operator": "contains", "value": "..."}], '
            '"actions": [{"action": "mark_spam", "label_name": ""}]}}'
        )

    def build_job_ai_prompt(
        self, sender: str, subject: str, body: str
    ) -> str:
        return (
            f"This email may be a response to a job application.\n"
            f"Sender: {sender}\n"
            f"Subject: {subject}\n"
            f"Body (truncated to 500 chars): {body[:500]}\n\n"
            "Evaluate whether it is a rejection, interview request, or "
            "acknowledgement. Suggest a label rule if appropriate using this "
            "JSON block (include it verbatim in your response):\n"
            '{"rule_suggestion": {"name": "...", '
            '"conditions": [{"field": "subject", "operator": "contains", "value": "..."}], '
            '"actions": [{"action": "add_label", "label_name": "Jobs"}]}}'
        )


# ─────────────────────────────────────────────────────────────────────────────
# AIRuleEngine  —  parse suggestions, apply rules against messages
# ─────────────────────────────────────────────────────────────────────────────

class AIRuleEngine:
    """
    Owns local rules.json storage and rule evaluation logic.
    Lives inside GmailRuntime (owns the path).
    """

    def __init__(self, rules_path: Optional[Path], log: Callable[[str], None]) -> None:
        self._path = rules_path
        self._log  = log

    # ── Storage ───────────────────────────────────────────────────────────────

    def load_rules(self) -> list[RuleRecord]:
        if not self._path or not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return [RuleRecord.from_dict(d) for d in (raw if isinstance(raw, list) else [])]
        except Exception as exc:
            self._log(f"GoogleGmail rules load failed: {exc}")
            return []

    def save_rules(self, rules: list[RuleRecord]) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps([r.to_dict() for r in rules], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            self._log(f"GoogleGmail rules save failed: {exc}")

    def add_rule(self, rule: RuleRecord) -> None:
        rules = self.load_rules()
        # Replace if same rule_id exists
        rules = [r for r in rules if r.rule_id != rule.rule_id]
        rules.append(rule)
        self.save_rules(rules)
        self._log(f"GoogleGmail rule added: {rule.name!r} (id={rule.rule_id})")

    def delete_rule(self, rule_id: str) -> None:
        rules = [r for r in self.load_rules() if r.rule_id != rule_id]
        self.save_rules(rules)
        self._log(f"GoogleGmail rule deleted: id={rule_id}")

    def toggle_rule(self, rule_id: str, active: bool) -> None:
        rules = self.load_rules()
        for r in rules:
            if r.rule_id == rule_id:
                r.active = active
        self.save_rules(rules)

    # ── Evaluation ────────────────────────────────────────────────────────────

    def evaluate(
        self,
        sender_name:  str,
        sender_email: str,
        subject:      str,
        body_plain:   str,
        label_ids:    list[str],
    ) -> list[RuleAction]:
        """
        Evaluate all active rules against the given message fields.
        Returns a flat list of RuleAction objects from all matched rules.
        All matching rules apply; first-match-wins is NOT used.
        """
        targets = {
            "sender":  f"{sender_name} {sender_email}".lower(),
            "subject": subject.lower(),
            "body":    body_plain.lower(),
            "label":   " ".join(label_ids).lower(),
        }
        matched: list[RuleAction] = []
        for rule in self.load_rules():
            if not rule.active:
                continue
            if self._all_conditions_match(rule.conditions, targets):
                for ad in rule.actions:
                    matched.append(RuleAction.from_dict(ad))
        return matched

    @staticmethod
    def _all_conditions_match(
        conditions: list[dict], targets: dict[str, str]
    ) -> bool:
        for cond in conditions:
            field    = str(cond.get("field")    or "subject")
            operator = str(cond.get("operator") or "contains")
            value    = str(cond.get("value")    or "").lower()
            target   = targets.get(field, "")
            if operator == "contains":
                ok = value in target
            elif operator == "equals":
                ok = value == target
            elif operator == "starts_with":
                ok = target.startswith(value)
            elif operator == "regex":
                try:
                    ok = bool(re.search(value, target))
                except Exception:
                    ok = False
            else:
                ok = False
            if not ok:
                return False
        return True

    # ── AI response parser ────────────────────────────────────────────────────

    def parse_rule_suggestion(self, ai_response: str) -> Optional[RuleRecord]:
        """
        Scan an AI response for a JSON ``rule_suggestion`` block and, if found,
        return a RuleRecord ready to be offered to the user for acceptance.
        Returns None if no parseable suggestion is found.
        """
        # Try to find the outer JSON object containing "rule_suggestion"
        try:
            # Greedy scan: find the first '{' that leads to valid JSON
            for m in re.finditer(r"\{", ai_response):
                start = m.start()
                # Find balanced closing brace
                depth = 0
                for i, ch in enumerate(ai_response[start:], start=start):
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            candidate = ai_response[start : i + 1]
                            try:
                                data = json.loads(candidate)
                                suggestion = data.get("rule_suggestion")
                                if isinstance(suggestion, dict):
                                    return RuleRecord(
                                        rule_id    = str(uuid.uuid4()),
                                        name       = str(suggestion.get("name") or "AI Rule"),
                                        conditions = list(suggestion.get("conditions") or []),
                                        actions    = list(suggestion.get("actions")    or []),
                                        created_by = "ai",
                                        created_at = _now_iso(),
                                        active     = True,
                                    )
                            except json.JSONDecodeError:
                                pass
                            break
        except Exception:
            pass
        return None

    def offer_suggestion_dialog(
        self, suggestion: RuleRecord, parent_widget: Optional[QWidget] = None
    ) -> bool:
        """
        Show a QMessageBox asking the user whether to accept the AI-suggested
        rule.  Returns True if accepted.
        """
        conditions_text = "\n".join(
            f"  {c.get('field','?')} {c.get('operator','?')} \"{c.get('value','?')}\""
            for c in suggestion.conditions
        ) or "  (none)"
        actions_text = "\n".join(
            f"  {a.get('action','?')}"
            + (f" → {a.get('label_name')}" if a.get("label_name") else "")
            for a in suggestion.actions
        ) or "  (none)"

        msg = QMessageBox(parent_widget)
        msg.setWindowTitle("AI Rule Suggestion")
        msg.setText(f"The AI suggested a new rule: <b>{suggestion.name}</b>")
        msg.setInformativeText(
            f"<b>Conditions:</b><br><pre>{conditions_text}</pre>"
            f"<b>Actions:</b><br><pre>{actions_text}</pre>"
            "<br>Apply this rule?"
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        return msg.exec() == QMessageBox.StandardButton.Yes
