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


# ══════════════════════════════════════════════════════════════════════════════
# Section 3: Sync Engine — QThread with history API, interval, battery config
# ══════════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# SyncConfig  —  persisted sync settings
# ─────────────────────────────────────────────────────────────────────────────

class SyncConfig:
    """Sync interval and battery-detection settings, JSON-serialisable."""

    DEFAULT_INTERVAL_VALUE = 5
    DEFAULT_INTERVAL_UNIT  = "minutes"
    DEFAULT_BATTERY_DETECT = True
    DEFAULT_BATTERY_INTERVAL_VALUE = 10
    DEFAULT_BATTERY_INTERVAL_UNIT  = "minutes"

    def __init__(
        self,
        fetch_mode:             str  = "new_only",
        interval_value:         int  = DEFAULT_INTERVAL_VALUE,
        interval_unit:          str  = DEFAULT_INTERVAL_UNIT,
        battery_detection:      bool = DEFAULT_BATTERY_DETECT,
        battery_interval_value: int  = DEFAULT_BATTERY_INTERVAL_VALUE,
        battery_interval_unit:  str  = DEFAULT_BATTERY_INTERVAL_UNIT,
        battery_override_disabled: bool = False,
    ) -> None:
        self.fetch_mode              = fetch_mode            # "new_only" | "full"
        self.interval_value          = interval_value
        self.interval_unit           = interval_unit         # "seconds" | "minutes" | "hours"
        self.battery_detection       = battery_detection
        self.battery_interval_value  = battery_interval_value
        self.battery_interval_unit   = battery_interval_unit
        self.battery_override_disabled = battery_override_disabled

    # ── Unit conversion ───────────────────────────────────────────────────────

    @staticmethod
    def _to_ms(value: int, unit: str) -> int:
        multipliers = {"seconds": 1_000, "minutes": 60_000, "hours": 3_600_000}
        return max(30_000, value * multipliers.get(unit, 60_000))

    def normal_interval_ms(self) -> int:
        return self._to_ms(self.interval_value, self.interval_unit)

    def battery_interval_ms(self) -> int:
        return self._to_ms(self.battery_interval_value, self.battery_interval_unit)

    def effective_interval_ms(self, on_battery: bool) -> int:
        if self.battery_override_disabled:
            return self.normal_interval_ms()
        if on_battery and self.battery_detection:
            return self.battery_interval_ms()
        return self.normal_interval_ms()

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetch_mode":                self.fetch_mode,
            "interval_value":            self.interval_value,
            "interval_unit":             self.interval_unit,
            "battery_detection":         self.battery_detection,
            "battery_interval_value":    self.battery_interval_value,
            "battery_interval_unit":     self.battery_interval_unit,
            "battery_override_disabled": self.battery_override_disabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SyncConfig":
        return cls(
            fetch_mode              = str(d.get("fetch_mode")             or "new_only"),
            interval_value          = int(d.get("interval_value")         or cls.DEFAULT_INTERVAL_VALUE),
            interval_unit           = str(d.get("interval_unit")          or cls.DEFAULT_INTERVAL_UNIT),
            battery_detection       = bool(d.get("battery_detection",      cls.DEFAULT_BATTERY_DETECT)),
            battery_interval_value  = int(d.get("battery_interval_value") or cls.DEFAULT_BATTERY_INTERVAL_VALUE),
            battery_interval_unit   = str(d.get("battery_interval_unit")  or cls.DEFAULT_BATTERY_INTERVAL_UNIT),
            battery_override_disabled = bool(d.get("battery_override_disabled", False)),
        )


# ─────────────────────────────────────────────────────────────────────────────
# GmailRuntime  —  auth, state, API orchestration, rule/signature/snooze mgmt
# ─────────────────────────────────────────────────────────────────────────────

class GmailRuntime:
    """
    Owns all backend state for the Gmail module:
    - Shared google_auth consumption (no independent OAuth ownership)
    - GmailClient construction and credential refresh
    - Sync state persistence (historyId, last sync time, auth status)
    - SyncConfig persistence
    - AIRuleEngine delegation
    - Signature storage
    - Snooze storage
    """

    def __init__(self, deck_api: dict[str, Any]) -> None:
        self._deck_api  = deck_api
        self._log: Callable[[str], None] = (
            deck_api.get("log") if callable(deck_api.get("log"))
            else (lambda _m: None)
        )
        self._cfg_get = (
            deck_api.get("cfg_get") if callable(deck_api.get("cfg_get"))
            else (lambda _k, d=None: d)
        )
        self._cfg_set = (
            deck_api.get("cfg_set") if callable(deck_api.get("cfg_set"))
            else (lambda _k, _v: None)
        )
        self._cfg_path = (
            deck_api.get("cfg_path") if callable(deck_api.get("cfg_path"))
            else None
        )
        self._broadcast = (
            deck_api.get("broadcast") if callable(deck_api.get("broadcast"))
            else None
        )

        self.sync_state: dict[str, Any] = {
            "mode":        "local_only",
            "auth_status": "unknown",
            "last_sync_at": "",
            "last_error":  "",
            "history_id":  "",
            "user_email":  "",
        }
        self.sync_config = SyncConfig()

        self._storage_path        = self._resolve_storage_path()
        self._google_storage_dir  = self._resolve_google_storage_dir()
        self._token_path          = (
            self._google_storage_dir / "token.json"
            if self._google_storage_dir else None
        )
        self._credentials_path    = (
            self._google_storage_dir / "google_credentials.json"
            if self._google_storage_dir else None
        )
        self._gmail_dir = self._resolve_gmail_dir()

        # Sub-systems
        self.rule_engine = AIRuleEngine(
            rules_path = self._gmail_dir / "rules.json" if self._gmail_dir else None,
            log        = self._log,
        )
        self.classifier  = EmailClassifier()

        self._load_state()

    # ── Path resolution ───────────────────────────────────────────────────────

    def _resolve_storage_path(self) -> Optional[Path]:
        if not callable(self._cfg_path):
            return None
        try:
            p = self._cfg_path("google_gmail_module_state.json")
            if not p:
                return None
            path = Path(p)
            path.parent.mkdir(parents=True, exist_ok=True)
            return path
        except Exception as exc:
            self._log(f"GoogleGmail storage path unavailable: {exc}")
            return None

    def _resolve_google_storage_dir(self) -> Optional[Path]:
        if not callable(self._cfg_path):
            return None
        try:
            candidate = self._cfg_path("google_auth/token.json")
            if candidate:
                d = Path(candidate).parent
                d.mkdir(parents=True, exist_ok=True)
                return d
        except Exception as exc:
            self._log(f"GoogleGmail google_auth dir unavailable: {exc}")
        return None

    def _resolve_gmail_dir(self) -> Optional[Path]:
        if not callable(self._cfg_path):
            return None
        try:
            p = self._cfg_path("Gmail/placeholder")
            if not p:
                return None
            d = Path(p).parent
            d.mkdir(parents=True, exist_ok=True)
            return d
        except Exception as exc:
            self._log(f"GoogleGmail Gmail dir unavailable: {exc}")
            return None

    # ── State persistence ─────────────────────────────────────────────────────

    def _load_state(self) -> None:
        if self._storage_path and self._storage_path.exists():
            try:
                data = json.loads(
                    self._storage_path.read_text(encoding="utf-8")
                )
                state = data.get("sync_state")
                if isinstance(state, dict):
                    self.sync_state.update(state)
                cfg_raw = data.get("sync_config")
                if isinstance(cfg_raw, dict):
                    self.sync_config = SyncConfig.from_dict(cfg_raw)
            except Exception as exc:
                self._log(f"GoogleGmail state load failed: {exc}")

    def _save_state(self) -> None:
        payload = {
            "sync_state":  dict(self.sync_state),
            "sync_config": self.sync_config.to_dict(),
            "updated_at":  _now_iso(),
        }
        if self._storage_path:
            try:
                self._storage_path.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception as exc:
                self._log(f"GoogleGmail state save failed: {exc}")
        try:
            self._cfg_set("module_google_gmail_state", payload)
        except Exception:
            pass

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if not callable(self._broadcast):
            return
        envelope = {
            "event_type":    event_type,
            "domain":        "gmail",
            "origin_module": "google_gmail",
            "payload":       payload,
        }
        try:
            self._broadcast(envelope)
        except Exception:
            pass

    # ── Shared google_auth ────────────────────────────────────────────────────

    def _google_auth_snapshot(self) -> dict[str, Any]:
        shared = self._cfg_get("modules.shared_resources.google_auth", {})
        if not isinstance(shared, dict):
            shared = {}
        local_token = bool(self._token_path and self._token_path.exists())
        local_creds = bool(self._credentials_path and self._credentials_path.exists())
        token_present = bool(
            shared.get("token_present") or shared.get("token_path") or local_token
        )
        creds_present = bool(
            shared.get("credentials_present") or shared.get("credentials_path") or local_creds
        )
        valid = bool(shared.get("token_valid", token_present))
        return {
            "token_present":    token_present,
            "credentials_present": creds_present,
            "token_valid":      valid,
        }

    def _set_shared_auth_state(
        self,
        token_valid:         bool,
        token_present:       bool,
        credentials_present: bool,
        credentials_path:    str = "",
    ) -> None:
        payload = {
            "token_valid":         bool(token_valid),
            "token_present":       bool(token_present),
            "credentials_present": bool(credentials_present),
            "refreshable":         True,
            "token_path": (
                str(self._token_path) if token_present and self._token_path else ""
            ),
            "credentials_path": (
                credentials_path if credentials_path
                else (
                    str(self._credentials_path)
                    if credentials_present and self._credentials_path else ""
                )
            ),
        }
        try:
            self._cfg_set("modules.shared_resources.google_auth", payload)
        except Exception:
            pass

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
        return str(self.sync_state["auth_status"])

    # ── Auth flow ─────────────────────────────────────────────────────────────

    def authenticate_google(self, selected_credentials_path: str) -> tuple[bool, str]:
        """
        Run the OAuth flow using the supplied credentials JSON file.
        Writes token.json to the shared Google storage dir.
        """
        if not self._google_storage_dir or not self._token_path or not self._credentials_path:
            return False, "Google auth storage location is unavailable."
        if not selected_credentials_path:
            return False, "No credentials file selected."
        sp = Path(selected_credentials_path)
        if not sp.exists():
            return False, "Selected credentials file does not exist."

        # Copy credentials file into shared storage
        try:
            self._credentials_path.write_text(
                sp.read_text(encoding="utf-8"), encoding="utf-8"
            )
        except Exception as exc:
            return False, f"Failed to store credentials: {exc}"

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except Exception as exc:
            self.sync_state["auth_status"] = "missing"
            self.sync_state["mode"]        = "local_only"
            self.sync_state["last_error"]  = f"Google dependencies unavailable: {exc}"
            self._save_state()
            return False, self.sync_state["last_error"]

        creds = None
        try:
            # Reuse existing token if present and covers required scopes
            if self._token_path.exists():
                try:
                    creds = Credentials.from_authorized_user_file(
                        str(self._token_path), GOOGLE_SCOPES
                    )
                except Exception:
                    creds = None

            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())

            if not creds or not creds.valid:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._credentials_path), GOOGLE_SCOPES
                )
                creds = flow.run_local_server(port=0)

            self._token_path.write_text(creds.to_json(), encoding="utf-8")

            # Validate by fetching profile
            client = GmailClient(creds)
            profile = client.get_profile()
            self.sync_state["user_email"] = str(profile.get("emailAddress") or "")
            self.sync_state["history_id"] = str(profile.get("historyId")    or "")
            self.sync_state["auth_status"] = "authenticated"
            self.sync_state["mode"]        = "google_connected"
            self.sync_state["last_error"]  = ""
            self._set_shared_auth_state(
                token_valid=True, token_present=True, credentials_present=True,
                credentials_path=str(self._credentials_path),
            )
            self._save_state()
            self._log("GoogleGmail authentication successful; token.json written.")
            return True, "Authentication successful."

        except Exception as exc:
            self.sync_state["mode"]        = "local_only"
            self.sync_state["auth_status"] = "missing"
            self.sync_state["last_error"]  = f"Google authentication failed: {exc}"
            self._set_shared_auth_state(
                token_valid=False,
                token_present=bool(self._token_path and self._token_path.exists()),
                credentials_present=bool(self._credentials_path and self._credentials_path.exists()),
            )
            self._save_state()
            self._log(self.sync_state["last_error"])
            return False, self.sync_state["last_error"]

    def _make_client(self) -> GmailClient:
        """Build a GmailClient from the stored token, refreshing if needed."""
        if not self._token_path or not self._token_path.exists():
            raise RuntimeError(
                "No Gmail token found. Please authenticate via the module panel."
            )
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
        except ImportError as exc:
            raise RuntimeError(
                "google-auth is not installed. "
                "Run: pip install google-auth google-auth-oauthlib google-auth-httplib2"
            ) from exc

        creds = Credentials.from_authorized_user_file(
            str(self._token_path), GOOGLE_SCOPES
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self._token_path.write_text(creds.to_json(), encoding="utf-8")
        if not creds.valid:
            raise RuntimeError(
                "Gmail credentials are invalid. Please re-authenticate."
            )
        return GmailClient(creds)

    # ── Sync orchestration ────────────────────────────────────────────────────

    def run_sync(self, force_full: bool = False) -> dict[str, Any]:
        """
        Entry point called by GmailSyncWorker.run().
        Returns {"new_ids": [...], "history_id": "..."}.
        """
        self.evaluate_auth_status()
        if self.sync_state.get("mode") != "google_connected":
            return {"new_ids": [], "history_id": ""}

        history_id = str(self.sync_state.get("history_id") or "")
        if (
            history_id
            and not force_full
            and self.sync_config.fetch_mode == "new_only"
        ):
            return self._incremental_sync(history_id)
        return self._full_sync_bootstrap()

    def _incremental_sync(self, history_id: str) -> dict[str, Any]:
        try:
            client = self._make_client()
            resp = client.list_history(
                start_history_id=history_id,
                history_types=[
                    "messageAdded", "messageDeleted",
                    "labelAdded",   "labelRemoved",
                ],
            )
            new_ids: list[str] = []
            for record in resp.get("history") or []:
                for added in record.get("messagesAdded") or []:
                    msg   = added.get("message") or {}
                    mid   = str(msg.get("id") or "")
                    lbls  = msg.get("labelIds") or []
                    if mid and "INBOX" in lbls:
                        new_ids.append(mid)

            new_hid = str(resp.get("historyId") or history_id)
            self.sync_state["history_id"]  = new_hid
            self.sync_state["last_sync_at"] = _now_iso()
            self.sync_state["last_error"]  = ""
            self._save_state()

            if new_ids:
                self._emit("gmail.message.received", {
                    "count": len(new_ids), "message_ids": new_ids
                })
            self._log(
                f"GoogleGmail incremental sync: {len(new_ids)} new, "
                f"historyId={new_hid}"
            )
            return {"new_ids": new_ids, "history_id": new_hid}

        except RuntimeError as exc:
            # Detect expired historyId (HTTP 404) and fall back to full sync
            if "404" in str(exc) or "status=404" in str(exc):
                self._log(
                    "GoogleGmail historyId expired (404); "
                    "falling back to full sync bootstrap."
                )
                self.sync_state["history_id"] = ""
                return self._full_sync_bootstrap()
            self.sync_state["last_error"] = str(exc)
            self._save_state()
            self._log(f"GoogleGmail incremental sync failed: {exc}")
            return {"new_ids": [], "history_id": history_id}

        except Exception as exc:
            self.sync_state["last_error"] = f"Incremental sync error: {exc}"
            self._save_state()
            self._log(self.sync_state["last_error"])
            return {"new_ids": [], "history_id": history_id}

    def _full_sync_bootstrap(self) -> dict[str, Any]:
        try:
            client  = self._make_client()
            profile = client.get_profile()
            new_hid = str(profile.get("historyId")    or "")
            email   = str(profile.get("emailAddress") or "")
            if email:
                self.sync_state["user_email"] = email
            self.sync_state["history_id"]   = new_hid
            self.sync_state["last_sync_at"] = _now_iso()
            self.sync_state["last_error"]   = ""
            self._save_state()
            self._log(
                f"GoogleGmail full sync bootstrap: "
                f"historyId={new_hid}, user={email}"
            )
            return {"new_ids": [], "history_id": new_hid}
        except Exception as exc:
            self.sync_state["last_error"] = f"Full sync error: {exc}"
            self._save_state()
            self._log(self.sync_state["last_error"])
            return {"new_ids": [], "history_id": ""}

    # ── Snooze storage (local-only; Gmail API has no native snooze) ───────────

    def _snooze_path(self) -> Optional[Path]:
        return (self._gmail_dir / "snooze_data.json") if self._gmail_dir else None

    def load_snoozed(self) -> dict[str, str]:
        p = self._snooze_path()
        if not p or not p.exists():
            return {}
        try:
            return dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return {}

    def snooze_thread(self, thread_id: str, until_iso: str) -> None:
        data = self.load_snoozed()
        data[thread_id] = until_iso
        p = self._snooze_path()
        if p:
            try:
                p.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                pass

    def unsnooze_thread(self, thread_id: str) -> None:
        data = self.load_snoozed()
        data.pop(thread_id, None)
        p = self._snooze_path()
        if p:
            try:
                p.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                pass

    def get_due_snoozed(self) -> list[str]:
        """Return thread_ids whose snooze-until time has passed."""
        now  = datetime.now(UTC)
        data = self.load_snoozed()
        due: list[str] = []
        for tid, until_iso in data.items():
            try:
                until = datetime.fromisoformat(until_iso.replace("Z", "+00:00"))
                if now >= until:
                    due.append(tid)
            except Exception:
                continue
        return due


# ─────────────────────────────────────────────────────────────────────────────
# GmailSyncWorker  —  background QThread
# ─────────────────────────────────────────────────────────────────────────────

class GmailSyncWorker(QThread):
    """
    Runs GmailRuntime.run_sync() on a background thread.

    Interval respects SyncConfig (normal vs battery override).
    Battery state is queried from the deck_api "battery_on_battery" key if
    available; otherwise assumed False (plugged-in).

    Signals
    -------
    sync_complete(new_ids: list, history_id: str)
        Emitted after every successful sync pass.
    sync_error(message: str)
        Emitted when a sync pass raises an unhandled exception.
    """

    sync_complete = Signal(list, str)
    sync_error    = Signal(str)

    def __init__(
        self,
        runtime:  GmailRuntime,
        deck_api: dict[str, Any],
        parent:   Optional[QThread] = None,
    ) -> None:
        super().__init__(parent)
        self._runtime   = runtime
        self._deck_api  = deck_api
        self._stop_flag = False
        self._manual_trigger = False

    # ── Control ───────────────────────────────────────────────────────────────

    def trigger_now(self) -> None:
        """Wake up and run sync immediately, regardless of the current interval."""
        self._manual_trigger = True

    def stop(self) -> None:
        self._stop_flag = True

    # ── Battery detection ─────────────────────────────────────────────────────

    def _on_battery(self) -> bool:
        cfg = self._runtime.sync_config
        if cfg.battery_override_disabled or not cfg.battery_detection:
            return False
        on_batt = self._deck_api.get("battery_on_battery")
        if callable(on_batt):
            try:
                return bool(on_batt())
            except Exception:
                return False
        if isinstance(on_batt, bool):
            return on_batt
        return False

    # ── Thread body ───────────────────────────────────────────────────────────

    def run(self) -> None:
        self._stop_flag      = False
        self._manual_trigger = False

        while not self._stop_flag:
            # ── Run one sync pass ─────────────────────────────────────────────
            try:
                result = self._runtime.run_sync()
                self.sync_complete.emit(
                    result.get("new_ids", []),
                    result.get("history_id", ""),
                )
            except Exception as exc:
                self.sync_error.emit(str(exc))

            # ── Sleep in 500 ms increments so we can react to stop/trigger ───
            interval_ms = self._runtime.sync_config.effective_interval_ms(
                on_battery=self._on_battery()
            )
            elapsed = 0
            while (
                elapsed < interval_ms
                and not self._stop_flag
                and not self._manual_trigger
            ):
                self.msleep(500)
                elapsed += 500

            self._manual_trigger = False


# ══════════════════════════════════════════════════════════════════════════════
# Section 4: Signature System and Local Storage
# ══════════════════════════════════════════════════════════════════════════════

class SignatureRecord:
    """One stored email signature."""

    def __init__(
        self,
        sig_id:     str,
        name:       str,
        content:    str,       # rich-text HTML
        is_default: bool,
        created_at: str,
        updated_at: str,
    ) -> None:
        self.sig_id     = sig_id
        self.name       = name
        self.content    = content
        self.is_default = is_default
        self.created_at = created_at
        self.updated_at = updated_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "sig_id":     self.sig_id,
            "name":       self.name,
            "content":    self.content,
            "is_default": self.is_default,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SignatureRecord":
        return cls(
            sig_id     = str(d.get("sig_id")     or str(uuid.uuid4())),
            name       = str(d.get("name")       or "Signature"),
            content    = str(d.get("content")    or ""),
            is_default = bool(d.get("is_default", False)),
            created_at = str(d.get("created_at") or _now_iso()),
            updated_at = str(d.get("updated_at") or _now_iso()),
        )


class SignatureManager:
    """
    Loads and saves signatures to Gmail/signatures/signatures.json.
    Provides CRUD and default-signature lookup used by compose.
    """

    def __init__(self, gmail_dir: Optional[Path], log: Callable[[str], None]) -> None:
        self._dir = gmail_dir
        self._log = log

    def _path(self) -> Optional[Path]:
        if not self._dir:
            return None
        p = self._dir / "signatures"
        p.mkdir(parents=True, exist_ok=True)
        return p / "signatures.json"

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def load_all(self) -> list[SignatureRecord]:
        p = self._path()
        if not p or not p.exists():
            return []
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            return [SignatureRecord.from_dict(d) for d in (raw if isinstance(raw, list) else [])]
        except Exception as exc:
            self._log(f"GoogleGmail signatures load failed: {exc}")
            return []

    def save_all(self, sigs: list[SignatureRecord]) -> None:
        p = self._path()
        if not p:
            return
        try:
            p.write_text(
                json.dumps([s.to_dict() for s in sigs], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            self._log(f"GoogleGmail signatures save failed: {exc}")

    def upsert(
        self,
        sig_id:     str,
        name:       str,
        content:    str,
        is_default: bool,
    ) -> SignatureRecord:
        sigs = self.load_all()
        if is_default:
            for s in sigs:
                s.is_default = False
        existing = next((s for s in sigs if s.sig_id == sig_id), None)
        now = _now_iso()
        if existing:
            existing.name       = name
            existing.content    = content
            existing.is_default = is_default
            existing.updated_at = now
            self.save_all(sigs)
            return existing
        new_sig = SignatureRecord(
            sig_id=sig_id, name=name, content=content,
            is_default=is_default, created_at=now, updated_at=now,
        )
        sigs.append(new_sig)
        self.save_all(sigs)
        return new_sig

    def delete(self, sig_id: str) -> None:
        self.save_all([s for s in self.load_all() if s.sig_id != sig_id])

    def get_default(self) -> Optional[SignatureRecord]:
        sigs = self.load_all()
        for s in sigs:
            if s.is_default:
                return s
        return sigs[0] if sigs else None

    # ── Signature manager dialog ──────────────────────────────────────────────

    def open_manager_dialog(self, parent: Optional[QWidget] = None) -> None:
        """
        Show a modal dialog for managing signatures:
        list on the left, rich-text editor on the right.
        """
        dlg = QDialog(parent)
        dlg.setWindowTitle("Signature Manager")
        dlg.setMinimumSize(700, 480)
        root = QHBoxLayout(dlg)

        # Left: list + buttons
        left = QWidget(dlg)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        sig_list = QListWidget(left)
        sig_list.setMinimumWidth(180)
        left_layout.addWidget(sig_list)
        btn_row = QHBoxLayout()
        new_btn = QPushButton("New", left)
        del_btn = QPushButton("Delete", left)
        def_btn = QPushButton("Set Default", left)
        for b in (new_btn, del_btn, def_btn):
            btn_row.addWidget(b)
        left_layout.addLayout(btn_row)
        root.addWidget(left)

        # Right: editor
        right = QWidget(dlg)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        name_edit = QLineEdit(right)
        name_edit.setPlaceholderText("Signature name…")
        content_edit = QTextEdit(right)
        content_edit.setAcceptRichText(True)
        content_edit.setPlaceholderText("Signature content (supports rich text)…")
        save_btn = QPushButton("Save Signature", right)
        right_layout.addWidget(QLabel("Name:", right))
        right_layout.addWidget(name_edit)
        right_layout.addWidget(QLabel("Content:", right))
        right_layout.addWidget(content_edit, stretch=1)
        right_layout.addWidget(save_btn)
        root.addWidget(right, stretch=1)

        _state: dict[str, Any] = {"current_id": ""}

        def _reload_list() -> None:
            sig_list.clear()
            for s in self.load_all():
                label = f"{'★ ' if s.is_default else ''}{s.name}"
                item  = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, s.sig_id)
                sig_list.addItem(item)

        def _on_select() -> None:
            item = sig_list.currentItem()
            if not item:
                return
            sid = str(item.data(Qt.ItemDataRole.UserRole) or "")
            sigs = self.load_all()
            sig  = next((s for s in sigs if s.sig_id == sid), None)
            if sig:
                _state["current_id"] = sig.sig_id
                name_edit.setText(sig.name)
                content_edit.setHtml(sig.content)

        def _on_new() -> None:
            _state["current_id"] = str(uuid.uuid4())
            name_edit.clear()
            content_edit.clear()

        def _on_save() -> None:
            name    = name_edit.text().strip()
            content = content_edit.toHtml()
            if not name:
                QMessageBox.warning(dlg, "Signature", "Please enter a name.")
                return
            sid = _state["current_id"] or str(uuid.uuid4())
            self.upsert(sig_id=sid, name=name, content=content, is_default=False)
            _state["current_id"] = sid
            _reload_list()

        def _on_delete() -> None:
            item = sig_list.currentItem()
            if not item:
                return
            sid = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if sid:
                self.delete(sid)
                _state["current_id"] = ""
                name_edit.clear()
                content_edit.clear()
                _reload_list()

        def _on_set_default() -> None:
            item = sig_list.currentItem()
            if not item:
                return
            sid  = str(item.data(Qt.ItemDataRole.UserRole) or "")
            sigs = self.load_all()
            sig  = next((s for s in sigs if s.sig_id == sid), None)
            if sig:
                self.upsert(
                    sig_id=sid, name=sig.name,
                    content=sig.content, is_default=True,
                )
                _reload_list()

        sig_list.itemSelectionChanged.connect(_on_select)
        new_btn.clicked.connect(_on_new)
        save_btn.clicked.connect(_on_save)
        del_btn.clicked.connect(_on_delete)
        def_btn.clicked.connect(_on_set_default)

        _reload_list()
        dlg.exec()


# ══════════════════════════════════════════════════════════════════════════════
# Section 5: Module Panel Widget
# (folder / label tree · compose button · sync status · auth controls)
# ══════════════════════════════════════════════════════════════════════════════

class GmailModulePanel(QWidget):
    """
    Always-visible control surface shown in the Gmail module tab.

    Signals
    -------
    compose_requested()
        User clicked the Compose button.
    folder_selected(label_id: str, display_name: str)
        User selected a folder / label in the tree.
    fetch_now_requested()
        User clicked Fetch Now.
    auth_requested()
        User clicked Authenticate Google.
    settings_requested()
        User clicked Settings.
    """

    compose_requested  = Signal()
    folder_selected    = Signal(str, str)
    fetch_now_requested= Signal()
    auth_requested     = Signal()
    settings_requested = Signal()

    # ── Section-header item flag ──────────────────────────────────────────────
    _SECTION_ROLE = Qt.ItemDataRole.UserRole + 10

    def __init__(
        self,
        runtime: GmailRuntime,
        parent:  Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._runtime = runtime

        # Current label selection (label_id, display_name)
        self._active_label: tuple[str, str] = ("INBOX", "Inbox")

        self._build_ui()
        self.refresh_sync_status()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Compose button ────────────────────────────────────────────────────
        self._compose_btn = QPushButton("✏  Compose", self)
        self._compose_btn.setMinimumHeight(36)
        self._compose_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        font = self._compose_btn.font()
        font.setBold(True)
        self._compose_btn.setFont(font)
        root.addWidget(self._compose_btn)

        # ── Folder / label tree ───────────────────────────────────────────────
        self._folder_list = QListWidget(self)
        self._folder_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._folder_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self._folder_list, stretch=1)

        # ── Auth / Settings row ───────────────────────────────────────────────
        auth_row = QHBoxLayout()
        self._auth_btn     = QPushButton("Authenticate", self)
        self._settings_btn = QPushButton("⚙", self)
        self._settings_btn.setFixedWidth(32)
        auth_row.addWidget(self._auth_btn, stretch=1)
        auth_row.addWidget(self._settings_btn)
        root.addLayout(auth_row)

        # ── Sync status ───────────────────────────────────────────────────────
        sync_box = QGroupBox("Sync", self)
        sync_layout = QVBoxLayout(sync_box)
        sync_layout.setContentsMargins(6, 6, 6, 6)
        sync_layout.setSpacing(4)

        self._sync_status_lbl  = QLabel("Not synced yet.", sync_box)
        self._sync_status_lbl.setWordWrap(True)
        self._sync_mode_lbl    = QLabel("Mode: —", sync_box)
        self._last_synced_lbl  = QLabel("Last synced: —", sync_box)
        self._fetch_now_btn    = QPushButton("Fetch Now", sync_box)

        for lbl in (self._sync_status_lbl, self._sync_mode_lbl, self._last_synced_lbl):
            lbl.setWordWrap(True)
            sync_layout.addWidget(lbl)
        sync_layout.addWidget(self._fetch_now_btn)
        root.addWidget(sync_box)

        # ── Connections ───────────────────────────────────────────────────────
        self._compose_btn.clicked.connect(self.compose_requested)
        self._fetch_now_btn.clicked.connect(self.fetch_now_requested)
        self._auth_btn.clicked.connect(self.auth_requested)
        self._settings_btn.clicked.connect(self.settings_requested)
        self._folder_list.itemClicked.connect(self._on_item_clicked)

        # Populate static folder tree
        self._populate_folder_tree([])

    # ── Folder tree population ────────────────────────────────────────────────

    def _add_section_header(self, title: str) -> None:
        item = QListWidgetItem(title)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setData(self._SECTION_ROLE, True)
        font = item.font()
        font.setBold(True)
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1))
        item.setFont(font)
        item.setForeground(QColor("#888888"))
        self._folder_list.addItem(item)

    def _add_folder_item(
        self,
        label_id:     str,
        display_name: str,
        unread_count: int = 0,
        color:        str = "",
    ) -> None:
        text = display_name
        if unread_count > 0:
            text = f"{display_name}  ({unread_count})"
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, label_id)
        item.setData(self._SECTION_ROLE, False)
        if color:
            item.setForeground(QColor(color))
        # Bold if this is the active selection
        if label_id == self._active_label[0]:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        self._folder_list.addItem(item)

    def _populate_folder_tree(
        self,
        user_labels: list[dict[str, Any]],
        unread_counts: dict[str, int] | None = None,
    ) -> None:
        """
        Rebuild the folder list.
        user_labels — list of raw Gmail label dicts (from labels.list).
        unread_counts — {label_id: unread_count}.
        """
        counts = unread_counts or {}
        self._folder_list.clear()

        # ── System folders ────────────────────────────────────────────────────
        self._add_section_header("FOLDERS")
        for lid, dname in SYSTEM_LABEL_DEFS:
            self._add_folder_item(lid, dname, counts.get(lid, 0))

        # ── User labels ───────────────────────────────────────────────────────
        user_only = [
            lbl for lbl in user_labels
            if str(lbl.get("type") or "") == "user"
        ]
        if user_only:
            self._add_section_header("LABELS")
            for lbl in sorted(user_only, key=lambda x: str(x.get("name") or "")):
                lid   = str(lbl.get("id")   or "")
                dname = str(lbl.get("name") or lid)
                color_info = lbl.get("color") or {}
                color = str(color_info.get("textColor") or "") if isinstance(color_info, dict) else ""
                self._add_folder_item(lid, dname, counts.get(lid, 0), color)

        # Re-apply bold to active label after rebuild
        self._highlight_active()

    def _highlight_active(self) -> None:
        active_id = self._active_label[0]
        for i in range(self._folder_list.count()):
            item = self._folder_list.item(i)
            if not item:
                continue
            lid = str(item.data(Qt.ItemDataRole.UserRole) or "")
            font = item.font()
            font.setBold(lid == active_id)
            item.setFont(font)
            if lid == active_id:
                self._folder_list.setCurrentItem(item)

    # ── Font scaling ──────────────────────────────────────────────────────────

    def _fit_label(self, widget: QWidget, text: str) -> None:
        """Shrink widget font until text fits horizontally within the widget."""
        if not text or widget.width() < 20:
            return
        fm = widget.fontMetrics()
        available = max(10, widget.width() - 12)
        pt = widget.font().pointSizeF() or 9.0
        while pt > 6.5 and fm.horizontalAdvance(text) > available:
            pt -= 0.5
            f = widget.font()
            f.setPointSizeF(pt)
            widget.setFont(f)
            fm = widget.fontMetrics()

    def _apply_font_scaling(self) -> None:
        for w in self.findChildren((QLabel, QPushButton, QToolButton)):
            if hasattr(w, "text"):
                self._fit_label(w, str(w.text()))

    def resizeEvent(self, event: Any) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_font_scaling()

    def showEvent(self, event: Any) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._apply_font_scaling()

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        is_header = bool(item.data(self._SECTION_ROLE))
        if is_header:
            return
        label_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not label_id:
            return
        # Derive display name from item text (strip unread count suffix)
        display_name = item.text().split("  (")[0].strip()
        self._active_label = (label_id, display_name)
        self._highlight_active()
        self.folder_selected.emit(label_id, display_name)

    # ── Public refresh API ────────────────────────────────────────────────────

    def refresh_sync_status(self) -> None:
        """Update sync-status labels from runtime state."""
        state = self._runtime.sync_state
        auth  = state.get("auth_status", "unknown")
        mode  = state.get("mode", "local_only")
        err   = str(state.get("last_error") or "")
        last  = str(state.get("last_sync_at") or "")
        hid   = str(state.get("history_id")  or "")

        if err:
            status_text = f"⚠ {err[:80]}"
        elif mode == "google_connected":
            status_text = "● Connected"
        elif auth in {"token_ready", "authenticated"}:
            status_text = "● Token ready"
        elif auth == "credentials_only":
            status_text = "○ Credentials present — run auth"
        else:
            status_text = "○ Not authenticated"

        self._sync_status_lbl.setText(status_text)
        self._sync_mode_lbl.setText(
            f"Mode: {self._runtime.sync_config.fetch_mode}"
        )
        if last:
            try:
                dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                last_str = dt.strftime("%H:%M:%S")
            except Exception:
                last_str = last[:19]
        else:
            last_str = "—"
        self._last_synced_lbl.setText(f"Last synced: {last_str}")
        self._apply_font_scaling()

    def update_user_labels(
        self,
        user_labels:   list[dict[str, Any]],
        unread_counts: dict[str, int] | None = None,
    ) -> None:
        """Refresh the folder tree with fresh label data from the API."""
        self._populate_folder_tree(user_labels, unread_counts)

    def set_active_label(self, label_id: str, display_name: str) -> None:
        self._active_label = (label_id, display_name)
        self._highlight_active()

    # ── Settings dialog ───────────────────────────────────────────────────────

    def open_settings_dialog(
        self,
        sig_manager: SignatureManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        """
        Modal dialog with two tabs: Sync Settings and Signature Manager.
        Changes take effect immediately on Save.
        """
        dlg = QDialog(parent or self)
        dlg.setWindowTitle("Gmail Settings")
        dlg.setMinimumSize(520, 420)
        dlg_root = QVBoxLayout(dlg)

        from PySide6.QtWidgets import QTabWidget, QSpinBox
        tabs = QTabWidget(dlg)

        # ── Tab 1: Sync Settings ──────────────────────────────────────────────
        sync_tab = QWidget()
        sync_form = QVBoxLayout(sync_tab)
        cfg = self._runtime.sync_config

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Fetch mode:", sync_tab))
        mode_combo = QComboBox(sync_tab)
        mode_combo.addItems(["new_only", "full"])
        mode_combo.setCurrentText(cfg.fetch_mode)
        mode_row.addWidget(mode_combo)
        sync_form.addLayout(mode_row)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("Interval:", sync_tab))
        interval_spin = QSpinBox(sync_tab)
        interval_spin.setRange(1, 9999)
        interval_spin.setValue(cfg.interval_value)
        interval_unit = QComboBox(sync_tab)
        interval_unit.addItems(["seconds", "minutes", "hours"])
        interval_unit.setCurrentText(cfg.interval_unit)
        interval_row.addWidget(interval_spin)
        interval_row.addWidget(interval_unit)
        sync_form.addLayout(interval_row)

        batt_chk = QCheckBox("Slow sync on battery (use battery interval)", sync_tab)
        batt_chk.setChecked(cfg.battery_detection)
        sync_form.addWidget(batt_chk)

        batt_row = QHBoxLayout()
        batt_row.addWidget(QLabel("Battery interval:", sync_tab))
        batt_spin = QSpinBox(sync_tab)
        batt_spin.setRange(1, 9999)
        batt_spin.setValue(cfg.battery_interval_value)
        batt_unit = QComboBox(sync_tab)
        batt_unit.addItems(["seconds", "minutes", "hours"])
        batt_unit.setCurrentText(cfg.battery_interval_unit)
        batt_row.addWidget(batt_spin)
        batt_row.addWidget(batt_unit)
        sync_form.addLayout(batt_row)

        override_chk = QCheckBox("Always use my interval (ignore battery state)", sync_tab)
        override_chk.setChecked(cfg.battery_override_disabled)
        sync_form.addWidget(override_chk)
        sync_form.addStretch(1)
        tabs.addTab(sync_tab, "Sync")

        # ── Tab 2: Signatures (delegates to SignatureManager) ─────────────────
        sig_tab = QWidget()
        sig_tab_layout = QVBoxLayout(sig_tab)
        open_sig_btn = QPushButton("Open Signature Manager…", sig_tab)
        sig_tab_layout.addWidget(open_sig_btn)
        sig_tab_layout.addStretch(1)
        open_sig_btn.clicked.connect(
            lambda: sig_manager.open_manager_dialog(dlg)
        )
        tabs.addTab(sig_tab, "Signatures")

        dlg_root.addWidget(tabs)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            dlg,
        )
        dlg_root.addWidget(btn_box)

        def _on_save() -> None:
            self._runtime.sync_config.fetch_mode             = mode_combo.currentText()
            self._runtime.sync_config.interval_value         = interval_spin.value()
            self._runtime.sync_config.interval_unit          = interval_unit.currentText()
            self._runtime.sync_config.battery_detection      = batt_chk.isChecked()
            self._runtime.sync_config.battery_interval_value = batt_spin.value()
            self._runtime.sync_config.battery_interval_unit  = batt_unit.currentText()
            self._runtime.sync_config.battery_override_disabled = override_chk.isChecked()
            self._runtime._save_state()
            dlg.accept()

        btn_box.accepted.connect(_on_save)
        btn_box.rejected.connect(dlg.reject)
        dlg.exec()


# ══════════════════════════════════════════════════════════════════════════════
# Section 6: Workspace Thread List View (Mode 1)
# ══════════════════════════════════════════════════════════════════════════════

class ThreadListView(QWidget):
    """
    Mode 1 workspace widget — shows Gmail thread list for a label.

    Signals
    -------
    thread_opened(thread_id: str)
    compose_requested()
    """

    thread_opened     = Signal(str)
    compose_requested = Signal()

    # Thread-table column indices
    _COL_CHECK  = 0
    _COL_STAR   = 1
    _COL_IMP    = 2
    _COL_SENDER = 3
    _COL_SUBJ   = 4
    _COL_ATT    = 5
    _COL_TIME   = 6
    _COL_COUNT  = 7

    def __init__(
        self,
        runtime: GmailRuntime,
        parent:  Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._runtime        = runtime
        self._current_label: tuple[str, str] = ("INBOX", "Inbox")
        self._current_query  = ""
        self._page_token     = ""
        self._prev_tokens:   list[str] = []      # stack for Back navigation
        self._total_hint     = 0
        self._page_size      = 50
        self._threads:       list[ThreadSummary] = []
        self._selected_ids:  set[str] = set()
        self._build_ui()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Category tab strip ────────────────────────────────────────────────
        tab_bar = QWidget(self)
        tab_row = QHBoxLayout(tab_bar)
        tab_row.setContentsMargins(6, 4, 6, 4)
        tab_row.setSpacing(2)
        self._cat_btns: dict[str, QPushButton] = {}
        for tab_name in CATEGORY_TABS:
            btn = QPushButton(tab_name, tab_bar)
            btn.setCheckable(True)
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            btn.setMinimumHeight(28)
            btn.clicked.connect(lambda checked, tn=tab_name: self._on_category_tab(tn))
            self._cat_btns[tab_name] = btn
            tab_row.addWidget(btn)
        tab_row.addStretch(1)
        # Pagination label
        self._pagination_lbl = QLabel("", tab_bar)
        self._pagination_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        prev_btn = QPushButton("◀", tab_bar)
        next_btn = QPushButton("▶", tab_bar)
        prev_btn.setFixedWidth(28)
        next_btn.setFixedWidth(28)
        prev_btn.clicked.connect(self._on_prev_page)
        next_btn.clicked.connect(self._on_next_page)
        self._prev_page_btn = prev_btn
        self._next_page_btn = next_btn
        tab_row.addWidget(self._pagination_lbl)
        tab_row.addWidget(prev_btn)
        tab_row.addWidget(next_btn)
        root.addWidget(tab_bar)

        # ── Search bar ────────────────────────────────────────────────────────
        search_bar = QWidget(self)
        search_row = QHBoxLayout(search_bar)
        search_row.setContentsMargins(6, 4, 6, 4)
        self._search_edit = QLineEdit(search_bar)
        self._search_edit.setPlaceholderText(
            "Search mail  (from:, to:, subject:, has:attachment, is:unread, label:, before:, after:…)"
        )
        self._search_edit.returnPressed.connect(self._on_search)
        search_btn = QPushButton("Search", search_bar)
        search_btn.clicked.connect(self._on_search)
        clear_btn  = QPushButton("✕", search_bar)
        clear_btn.setFixedWidth(28)
        clear_btn.clicked.connect(self._on_clear_search)
        search_row.addWidget(self._search_edit, stretch=1)
        search_row.addWidget(search_btn)
        search_row.addWidget(clear_btn)
        root.addWidget(search_bar)

        # ── Batch toolbar (hidden until rows are checked) ─────────────────────
        self._batch_bar = QWidget(self)
        batch_row = QHBoxLayout(self._batch_bar)
        batch_row.setContentsMargins(6, 2, 6, 2)
        self._batch_lbl         = QLabel("0 selected", self._batch_bar)
        batch_archive_btn       = QPushButton("Archive",       self._batch_bar)
        batch_delete_btn        = QPushButton("Delete",        self._batch_bar)
        batch_read_btn          = QPushButton("Mark read",     self._batch_bar)
        batch_unread_btn        = QPushButton("Mark unread",   self._batch_bar)
        batch_row.addWidget(self._batch_lbl)
        batch_row.addWidget(batch_archive_btn)
        batch_row.addWidget(batch_delete_btn)
        batch_row.addWidget(batch_read_btn)
        batch_row.addWidget(batch_unread_btn)
        batch_row.addStretch(1)
        self._batch_bar.setVisible(False)
        batch_archive_btn.clicked.connect(self._on_batch_archive)
        batch_delete_btn.clicked.connect(self._on_batch_delete)
        batch_read_btn.clicked.connect(lambda: self._on_batch_label([], ["UNREAD"]))
        batch_unread_btn.clicked.connect(lambda: self._on_batch_label(["UNREAD"], []))
        root.addWidget(self._batch_bar)

        # ── Thread table ──────────────────────────────────────────────────────
        self._table = QTableWidget(self)
        self._table.setColumnCount(self._COL_COUNT)
        self._table.setHorizontalHeaderLabels(
            ["", "★", "!", "From", "Subject", "📎", "Date"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(False)
        self._table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)

        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(self._COL_CHECK,  QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(self._COL_STAR,   QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(self._COL_IMP,    QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(self._COL_SENDER, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(self._COL_SUBJ,   QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(self._COL_ATT,    QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(self._COL_TIME,   QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(self._COL_CHECK,  28)
        self._table.setColumnWidth(self._COL_STAR,   28)
        self._table.setColumnWidth(self._COL_IMP,    24)
        self._table.setColumnWidth(self._COL_ATT,    28)
        self._table.setColumnWidth(self._COL_SENDER, 160)

        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.itemChanged.connect(self._on_item_changed)
        root.addWidget(self._table, stretch=1)

        # ── Loading indicator ─────────────────────────────────────────────────
        self._loading_lbl = QLabel("Loading…", self)
        self._loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_lbl.setVisible(False)
        root.addWidget(self._loading_lbl)

        # Set Primary tab active by default
        self._set_category_active("Primary")

    # ── Category tabs ─────────────────────────────────────────────────────────

    def _set_category_active(self, tab_name: str) -> None:
        for name, btn in self._cat_btns.items():
            btn.blockSignals(True)
            btn.setChecked(name == tab_name)
            font = btn.font()
            font.setBold(name == tab_name)
            btn.setFont(font)
            btn.blockSignals(False)

    def _on_category_tab(self, tab_name: str) -> None:
        self._set_category_active(tab_name)
        label_id = CATEGORY_TAB_LABEL.get(tab_name, "INBOX")
        self._current_query = ""
        self._search_edit.clear()
        self._page_token   = ""
        self._prev_tokens  = []
        self._current_label = (label_id, tab_name)
        self._load_threads()

    # ── Search ────────────────────────────────────────────────────────────────

    def _on_search(self) -> None:
        query = self._search_edit.text().strip()
        self._current_query = query
        self._page_token    = ""
        self._prev_tokens   = []
        self._set_category_active("")
        self._load_threads()

    def _on_clear_search(self) -> None:
        self._search_edit.clear()
        self._current_query = ""
        self._page_token    = ""
        self._prev_tokens   = []
        self._set_category_active("Primary")
        self._current_label = ("INBOX", "Inbox")
        self._load_threads()

    # ── Pagination ────────────────────────────────────────────────────────────

    def _on_next_page(self) -> None:
        if not self._page_token:
            return
        self._prev_tokens.append(self._page_token)
        self._load_threads()

    def _on_prev_page(self) -> None:
        if not self._prev_tokens:
            self._page_token = ""
        else:
            self._page_token = self._prev_tokens.pop()
        self._load_threads()

    def _update_pagination(self, next_token: str) -> None:
        page_num  = len(self._prev_tokens) + 1
        start_row = (page_num - 1) * self._page_size + 1
        end_row   = start_row + len(self._threads) - 1
        if self._threads:
            self._pagination_lbl.setText(f"{start_row}–{end_row}")
        else:
            self._pagination_lbl.setText("No results")
        self._next_page_btn.setEnabled(bool(next_token))
        self._prev_page_btn.setEnabled(bool(self._prev_tokens))

    # ── Load threads ──────────────────────────────────────────────────────────

    def load_for_label(self, label_id: str, display_name: str) -> None:
        """External call: switch to label and load threads."""
        self._current_label = (label_id, display_name)
        self._current_query = ""
        self._page_token    = ""
        self._prev_tokens   = []
        self._search_edit.clear()
        self._set_category_active("")
        self._load_threads()

    def _load_threads(self) -> None:
        self._loading_lbl.setVisible(True)
        self._table.setVisible(False)
        self._selected_ids.clear()
        self._batch_bar.setVisible(False)

        label_id = self._current_label[0]
        query    = self._current_query

        try:
            client = self._runtime._make_client()
            # Local snooze pseudo-label: show snoozed threads
            if label_id == "_SNOOZED":
                snoozed = self._runtime.load_snoozed()
                threads: list[ThreadSummary] = []
                next_token = ""
                for tid in list(snoozed.keys()):
                    try:
                        msgs = client.fetch_thread_messages(tid)
                        if msgs:
                            m = msgs[-1]
                            sn, se = _sender_display(m.from_header)
                            threads.append(ThreadSummary(
                                thread_id      = tid,
                                subject        = m.subject,
                                sender_name    = sn,
                                sender_email   = se,
                                snippet        = m.snippet,
                                timestamp      = _format_timestamp(m.date_header),
                                is_unread      = m.is_unread,
                                is_starred     = "STARRED" in m.label_ids,
                                is_important   = "IMPORTANT" in m.label_ids,
                                has_attachment = bool(m.attachments),
                                label_ids      = m.label_ids,
                                message_count  = len(msgs),
                            ))
                    except Exception:
                        continue
            else:
                label_ids = [label_id] if label_id and not query else None
                threads, next_token = client.fetch_thread_summaries(
                    label_ids   = label_ids,
                    query       = query,
                    page_token  = self._page_token,
                    max_results = self._page_size,
                )
        except RuntimeError as exc:
            threads    = []
            next_token = ""
            self._loading_lbl.setText(f"⚠ {exc}")
            self._loading_lbl.setVisible(True)

        self._threads   = threads
        self._page_token = next_token
        self._populate_table(threads)
        self._update_pagination(next_token)
        self._loading_lbl.setVisible(False)
        self._table.setVisible(True)
        self._apply_font_scaling()

    # ── Table population ──────────────────────────────────────────────────────

    def _populate_table(self, threads: list[ThreadSummary]) -> None:
        self._table.setUpdatesEnabled(False)
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        self._table.setRowCount(len(threads))

        for row, t in enumerate(threads):
            self._table.setRowHeight(row, 26)

            # Col 0: checkbox
            chk_item = QTableWidgetItem()
            chk_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
            )
            chk_item.setCheckState(Qt.CheckState.Unchecked)
            chk_item.setData(Qt.ItemDataRole.UserRole, t.thread_id)
            self._table.setItem(row, self._COL_CHECK, chk_item)

            # Col 1: star
            star_item = QTableWidgetItem("★" if t.is_starred else "☆")
            star_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            star_item.setData(Qt.ItemDataRole.UserRole, t.thread_id)
            if t.is_starred:
                star_item.setForeground(QColor("#f9ab00"))
            self._table.setItem(row, self._COL_STAR, star_item)

            # Col 2: important
            imp_item = QTableWidgetItem("›" if t.is_important else "")
            imp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            imp_item.setData(Qt.ItemDataRole.UserRole, t.thread_id)
            if t.is_important:
                imp_item.setForeground(QColor("#f9ab00"))
            self._table.setItem(row, self._COL_IMP, imp_item)

            # Col 3: sender
            sender_item = QTableWidgetItem(t.sender_name or t.sender_email)
            sender_item.setData(Qt.ItemDataRole.UserRole, t.thread_id)
            if t.is_unread:
                font = sender_item.font()
                font.setBold(True)
                sender_item.setFont(font)
            self._table.setItem(row, self._COL_SENDER, sender_item)

            # Col 4: subject + snippet (truncated — expected in list rows)
            subj_text = t.subject
            if t.snippet:
                subj_text = f"{t.subject}  ·  {t.snippet}"
            subj_item = QTableWidgetItem(subj_text)
            subj_item.setData(Qt.ItemDataRole.UserRole, t.thread_id)
            if t.is_unread:
                font = subj_item.font()
                font.setBold(True)
                subj_item.setFont(font)
            self._table.setItem(row, self._COL_SUBJ, subj_item)

            # Col 5: attachment
            att_item = QTableWidgetItem("📎" if t.has_attachment else "")
            att_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            att_item.setData(Qt.ItemDataRole.UserRole, t.thread_id)
            self._table.setItem(row, self._COL_ATT, att_item)

            # Col 6: timestamp
            time_item = QTableWidgetItem(t.timestamp)
            time_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            time_item.setData(Qt.ItemDataRole.UserRole, t.thread_id)
            self._table.setItem(row, self._COL_TIME, time_item)

        self._table.blockSignals(False)
        self._table.setUpdatesEnabled(True)

    # ── Cell click handling ───────────────────────────────────────────────────

    def _on_cell_clicked(self, row: int, col: int) -> None:
        item = self._table.item(row, self._COL_CHECK)
        if not item:
            return
        thread_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not thread_id:
            return

        # Star toggle
        if col == self._COL_STAR:
            self._toggle_star(row, thread_id)
            return
        # Important toggle
        if col == self._COL_IMP:
            self._toggle_important(row, thread_id)
            return
        # Checkbox column — toggled by itemChanged; ignore here
        if col == self._COL_CHECK:
            return
        # Any other column — open thread
        self.thread_opened.emit(thread_id)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != self._COL_CHECK:
            return
        thread_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not thread_id:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._selected_ids.add(thread_id)
        else:
            self._selected_ids.discard(thread_id)
        count = len(self._selected_ids)
        self._batch_bar.setVisible(count > 0)
        self._batch_lbl.setText(f"{count} selected")

    # ── Star / important toggles ──────────────────────────────────────────────

    def _toggle_star(self, row: int, thread_id: str) -> None:
        star_item = self._table.item(row, self._COL_STAR)
        if not star_item:
            return
        currently_starred = star_item.text() == "★"
        try:
            client = self._runtime._make_client()
            if currently_starred:
                client.modify_thread(thread_id, remove_label_ids=["STARRED"])
                star_item.setText("☆")
                star_item.setForeground(QColor("#888888"))
            else:
                client.modify_thread(thread_id, add_label_ids=["STARRED"])
                star_item.setText("★")
                star_item.setForeground(QColor("#f9ab00"))
        except Exception:
            pass

    def _toggle_important(self, row: int, thread_id: str) -> None:
        imp_item = self._table.item(row, self._COL_IMP)
        if not imp_item:
            return
        currently_imp = imp_item.text() == "›"
        try:
            client = self._runtime._make_client()
            if currently_imp:
                client.modify_thread(thread_id, remove_label_ids=["IMPORTANT"])
                imp_item.setText("")
            else:
                client.modify_thread(thread_id, add_label_ids=["IMPORTANT"])
                imp_item.setText("›")
                imp_item.setForeground(QColor("#f9ab00"))
        except Exception:
            pass

    # ── Batch operations ──────────────────────────────────────────────────────

    def _on_batch_archive(self) -> None:
        try:
            client = self._runtime._make_client()
            for tid in list(self._selected_ids):
                client.modify_thread(tid, remove_label_ids=["INBOX"])
                self._runtime._emit("gmail.message.archived", {"thread_id": tid})
        except Exception:
            pass
        self._selected_ids.clear()
        self._load_threads()

    def _on_batch_delete(self) -> None:
        try:
            client = self._runtime._make_client()
            for tid in list(self._selected_ids):
                client.trash_thread(tid)
                self._runtime._emit("gmail.message.deleted", {"thread_id": tid})
        except Exception:
            pass
        self._selected_ids.clear()
        self._load_threads()

    def _on_batch_label(
        self, add_ids: list[str], remove_ids: list[str]
    ) -> None:
        try:
            client = self._runtime._make_client()
            for tid in list(self._selected_ids):
                client.modify_thread(tid, add_label_ids=add_ids or None,
                                     remove_label_ids=remove_ids or None)
        except Exception:
            pass
        self._selected_ids.clear()
        self._load_threads()

    # ── Font scaling ──────────────────────────────────────────────────────────

    def _fit_widget(self, widget: QWidget, text: str) -> None:
        if not text or widget.width() < 20:
            return
        fm        = widget.fontMetrics()
        available = max(10, widget.width() - 10)
        pt        = widget.font().pointSizeF() or 9.0
        while pt > 6.5 and fm.horizontalAdvance(text) > available:
            pt -= 0.5
            f  = widget.font()
            f.setPointSizeF(pt)
            widget.setFont(f)
            fm = widget.fontMetrics()

    def _apply_font_scaling(self) -> None:
        for w in self.findChildren((QLabel, QPushButton, QToolButton)):
            if hasattr(w, "text"):
                self._fit_widget(w, str(w.text()))
        # Scale header labels
        hh = self._table.horizontalHeader()
        for col in range(self._table.columnCount()):
            hi = self._table.horizontalHeaderItem(col)
            if hi:
                self._fit_widget(hh, hi.text())

    def resizeEvent(self, event: Any) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_font_scaling()

    def showEvent(self, event: Any) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._apply_font_scaling()


# ══════════════════════════════════════════════════════════════════════════════
# Section 7: Workspace Compose View (Mode 2)
# ══════════════════════════════════════════════════════════════════════════════

class ComposeView(QWidget):
    """
    Mode 2 workspace widget — full compose / reply / forward surface.

    Signals
    -------
    send_complete()    — message sent, return to thread list
    discard_complete() — user discarded, return to thread list
    """

    send_complete    = Signal()
    discard_complete = Signal()

    def __init__(
        self,
        runtime:     GmailRuntime,
        sig_manager: SignatureManager,
        parent:      Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._runtime     = runtime
        self._sig_manager = sig_manager

        self._compose_mode        = "new"
        self._reply_thread_id     = ""
        self._reply_message_id    = ""
        self._attached_files:     list[dict[str, Any]] = []
        self._undo_timer:         Optional[QTimer] = None
        self._undo_countdown      = 0
        self._pending_send_args:  Optional[dict]   = None
        self._ribbon_ref: Optional["GmailRibbon"]  = None

        self._build_ui()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(4)

        # From (read-only)
        from_row = QHBoxLayout()
        from_lbl = QLabel("From:", self)
        from_lbl.setFixedWidth(56)
        self._from_lbl = QLabel(self._runtime.sync_state.get("user_email") or "—", self)
        from_row.addWidget(from_lbl)
        from_row.addWidget(self._from_lbl, stretch=1)
        root.addLayout(from_row)

        # To
        to_row = QHBoxLayout()
        to_lbl = QLabel("To:", self)
        to_lbl.setFixedWidth(56)
        self._to_edit = QLineEdit(self)
        self._to_edit.setPlaceholderText("recipient@example.com, …")
        cc_btn  = QPushButton("Cc", self)
        bcc_btn = QPushButton("Bcc", self)
        cc_btn.setFixedWidth(36)
        bcc_btn.setFixedWidth(40)
        cc_btn.clicked.connect(self._toggle_cc)
        bcc_btn.clicked.connect(self._toggle_bcc)
        to_row.addWidget(to_lbl)
        to_row.addWidget(self._to_edit, stretch=1)
        to_row.addWidget(cc_btn)
        to_row.addWidget(bcc_btn)
        root.addLayout(to_row)

        # CC (collapsed)
        self._cc_row_widget = QWidget(self)
        cc_row = QHBoxLayout(self._cc_row_widget)
        cc_row.setContentsMargins(0, 0, 0, 0)
        cc_lbl = QLabel("Cc:", self._cc_row_widget)
        cc_lbl.setFixedWidth(56)
        self._cc_edit = QLineEdit(self._cc_row_widget)
        self._cc_edit.setPlaceholderText("cc@example.com, …")
        cc_row.addWidget(cc_lbl)
        cc_row.addWidget(self._cc_edit, stretch=1)
        self._cc_row_widget.setVisible(False)
        root.addWidget(self._cc_row_widget)

        # BCC (collapsed)
        self._bcc_row_widget = QWidget(self)
        bcc_row = QHBoxLayout(self._bcc_row_widget)
        bcc_row.setContentsMargins(0, 0, 0, 0)
        bcc_lbl = QLabel("Bcc:", self._bcc_row_widget)
        bcc_lbl.setFixedWidth(56)
        self._bcc_edit = QLineEdit(self._bcc_row_widget)
        self._bcc_edit.setPlaceholderText("bcc@example.com")
        bcc_row.addWidget(bcc_lbl)
        bcc_row.addWidget(self._bcc_edit, stretch=1)
        self._bcc_row_widget.setVisible(False)
        root.addWidget(self._bcc_row_widget)

        # Subject
        subj_row = QHBoxLayout()
        subj_lbl = QLabel("Subject:", self)
        subj_lbl.setFixedWidth(56)
        self._subject_edit = QLineEdit(self)
        self._subject_edit.setPlaceholderText("Subject…")
        subj_row.addWidget(subj_lbl)
        subj_row.addWidget(self._subject_edit, stretch=1)
        root.addLayout(subj_row)

        # Body
        self._body_edit = QTextEdit(self)
        self._body_edit.setAcceptRichText(True)
        self._body_edit.setPlaceholderText("Compose your message…")
        root.addWidget(self._body_edit, stretch=1)

        # Attachment chips area
        self._att_scroll = QScrollArea(self)
        self._att_scroll.setWidgetResizable(True)
        self._att_scroll.setMaximumHeight(60)
        self._att_scroll.setVisible(False)
        self._att_container = QWidget()
        self._att_layout    = QHBoxLayout(self._att_container)
        self._att_layout.setContentsMargins(4, 2, 4, 2)
        self._att_layout.setSpacing(4)
        self._att_layout.addStretch(1)
        self._att_scroll.setWidget(self._att_container)
        root.addWidget(self._att_scroll)

        # Formatting toolbar
        fmt_bar = QWidget(self)
        fmt_row = QHBoxLayout(fmt_bar)
        fmt_row.setContentsMargins(0, 0, 0, 0)
        fmt_row.setSpacing(3)

        self._font_combo = QComboBox(fmt_bar)
        self._font_combo.addItems(["Arial", "Georgia", "Courier New", "Times New Roman", "Verdana"])
        self._font_combo.setFixedWidth(110)
        self._font_combo.currentTextChanged.connect(self._on_font_family)

        self._size_combo = QComboBox(fmt_bar)
        self._size_combo.addItems(["8", "9", "10", "11", "12", "14", "16", "18", "24", "36"])
        self._size_combo.setCurrentText("11")
        self._size_combo.setFixedWidth(52)
        self._size_combo.currentTextChanged.connect(self._on_font_size)

        self._bold_btn      = QToolButton(fmt_bar)
        self._bold_btn.setText("B")
        self._bold_btn.setCheckable(True)
        self._bold_btn.setToolTip("Bold")
        self._bold_btn.clicked.connect(self._on_bold)

        self._italic_btn    = QToolButton(fmt_bar)
        self._italic_btn.setText("I")
        self._italic_btn.setCheckable(True)
        self._italic_btn.setToolTip("Italic")
        self._italic_btn.clicked.connect(self._on_italic)

        self._underline_btn = QToolButton(fmt_bar)
        self._underline_btn.setText("U")
        self._underline_btn.setCheckable(True)
        self._underline_btn.setToolTip("Underline")
        self._underline_btn.clicked.connect(self._on_underline)

        txt_color_btn = QPushButton("A▾", fmt_bar)
        txt_color_btn.setToolTip("Text colour")
        txt_color_btn.setFixedWidth(32)
        txt_color_btn.clicked.connect(self._on_text_color)

        hi_color_btn = QPushButton("H▾", fmt_bar)
        hi_color_btn.setToolTip("Highlight colour")
        hi_color_btn.setFixedWidth(32)
        hi_color_btn.clicked.connect(self._on_highlight_color)

        attach_btn = QPushButton("📎 Attach", fmt_bar)
        attach_btn.clicked.connect(self._on_attach_file)

        img_btn = QPushButton("🖼 Image", fmt_bar)
        img_btn.clicked.connect(self._on_attach_image)

        self._sig_combo = QComboBox(fmt_bar)
        self._sig_combo.setToolTip("Insert signature")
        self._sig_combo.setFixedWidth(120)
        self._sig_combo.currentIndexChanged.connect(self._on_sig_selected)

        for w in (self._font_combo, self._size_combo,
                  self._bold_btn, self._italic_btn, self._underline_btn,
                  txt_color_btn, hi_color_btn, attach_btn, img_btn,
                  self._sig_combo):
            fmt_row.addWidget(w)
        fmt_row.addStretch(1)
        root.addWidget(fmt_bar)

        # Action buttons
        action_bar = QWidget(self)
        act_row    = QHBoxLayout(action_bar)
        act_row.setContentsMargins(0, 0, 0, 0)
        self._send_btn  = QPushButton("Send", action_bar)
        self._draft_btn = QPushButton("Save Draft", action_bar)
        discard_btn     = QPushButton("🗑", action_bar)
        discard_btn.setToolTip("Discard draft")
        discard_btn.setFixedWidth(36)
        font = self._send_btn.font()
        font.setBold(True)
        self._send_btn.setFont(font)
        act_row.addWidget(self._send_btn)
        act_row.addWidget(self._draft_btn)
        act_row.addStretch(1)
        act_row.addWidget(discard_btn)
        root.addWidget(action_bar)

        # Undo-send banner
        self._undo_bar  = QWidget(self)
        undo_row        = QHBoxLayout(self._undo_bar)
        undo_row.setContentsMargins(6, 4, 6, 4)
        self._undo_lbl  = QLabel("Sending in 5 s…", self._undo_bar)
        undo_cancel_btn = QPushButton("Undo", self._undo_bar)
        undo_row.addWidget(self._undo_lbl)
        undo_row.addStretch(1)
        undo_row.addWidget(undo_cancel_btn)
        self._undo_bar.setVisible(False)
        root.addWidget(self._undo_bar)

        self._send_btn.clicked.connect(self._on_send_clicked)
        self._draft_btn.clicked.connect(self._on_save_draft)
        discard_btn.clicked.connect(self._on_discard)
        undo_cancel_btn.clicked.connect(self._on_undo_send)

        self._refresh_sig_combo()

    # ── Public open modes ─────────────────────────────────────────────────────

    def open_new(self) -> None:
        self._compose_mode     = "new"
        self._reply_thread_id  = ""
        self._reply_message_id = ""
        self._attached_files   = []
        self._to_edit.clear()
        self._cc_edit.clear()
        self._bcc_edit.clear()
        self._subject_edit.clear()
        self._body_edit.clear()
        self._cc_row_widget.setVisible(False)
        self._bcc_row_widget.setVisible(False)
        self._from_lbl.setText(self._runtime.sync_state.get("user_email") or "—")
        self._rebuild_att_chips()
        self._insert_default_signature()
        self._refresh_sig_combo()
        self._cancel_undo_timer()

    def open_reply(self, msg: MessageDetail, reply_all: bool = False) -> None:
        self._compose_mode     = "reply_all" if reply_all else "reply"
        self._reply_thread_id  = msg.thread_id
        self._reply_message_id = msg.message_id
        self._attached_files   = []
        self._cc_edit.clear()
        self._bcc_edit.clear()
        self._cc_row_widget.setVisible(False)
        self._bcc_row_widget.setVisible(False)
        self._from_lbl.setText(self._runtime.sync_state.get("user_email") or "—")
        _, se = _sender_display(msg.from_header)
        self._to_edit.setText(se)
        if reply_all:
            self_email = self._runtime.sync_state.get("user_email") or ""
            others = [a.strip() for a in (msg.to_header or "").split(",")
                      if a.strip() and a.strip().lower() != self_email.lower()]
            if others:
                self._to_edit.setText(", ".join([se] + others))
            if msg.cc_header:
                self._cc_edit.setText(msg.cc_header)
                self._cc_row_widget.setVisible(True)
        subj = msg.subject or ""
        if not subj.lower().startswith("re:"):
            subj = f"Re: {subj}"
        self._subject_edit.setText(subj)
        quoted   = self._build_quoted_block(msg)
        sig      = self._sig_manager.get_default()
        sig_html = f"<br>-- <br>{sig.content}" if sig else ""
        self._body_edit.setHtml(f"<br>{sig_html}<br><br>{quoted}")
        cursor = self._body_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self._body_edit.setTextCursor(cursor)
        self._rebuild_att_chips()
        self._refresh_sig_combo()
        self._cancel_undo_timer()

    def open_forward(self, msg: MessageDetail) -> None:
        self._compose_mode     = "forward"
        self._reply_thread_id  = ""
        self._reply_message_id = ""
        self._attached_files   = []
        self._to_edit.clear()
        self._cc_edit.clear()
        self._bcc_edit.clear()
        self._cc_row_widget.setVisible(False)
        self._bcc_row_widget.setVisible(False)
        self._from_lbl.setText(self._runtime.sync_state.get("user_email") or "—")
        subj = msg.subject or ""
        if not subj.lower().startswith("fwd:"):
            subj = f"Fwd: {subj}"
        self._subject_edit.setText(subj)
        fwd      = self._build_forward_block(msg)
        sig      = self._sig_manager.get_default()
        sig_html = f"<br>-- <br>{sig.content}" if sig else ""
        self._body_edit.setHtml(f"<br>{sig_html}<br><br>{fwd}")
        cursor = self._body_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self._body_edit.setTextCursor(cursor)
        self._rebuild_att_chips()
        self._refresh_sig_combo()
        self._cancel_undo_timer()

    # ── Quoted / forwarded block builders ────────────────────────────────────

    @staticmethod
    def _build_quoted_block(msg: MessageDetail) -> str:
        sn, se = _sender_display(msg.from_header)
        body   = msg.html_body or (f"<pre>{msg.plain_body}</pre>" if msg.plain_body else "")
        return (
            f"<div style='color:#555;border-left:3px solid #ccc;padding-left:8px;'>"
            f"On {msg.date_header}, {sn} &lt;{se}&gt; wrote:<br>{body}</div>"
        )

    @staticmethod
    def _build_forward_block(msg: MessageDetail) -> str:
        sn, se = _sender_display(msg.from_header)
        body   = msg.html_body or (f"<pre>{msg.plain_body}</pre>" if msg.plain_body else "")
        return (
            f"<div style='border-top:1px solid #ccc;padding-top:8px;'>"
            f"<b>---------- Forwarded message ----------</b><br>"
            f"From: {sn} &lt;{se}&gt;<br>"
            f"Date: {msg.date_header}<br>"
            f"Subject: {msg.subject}<br>"
            f"To: {msg.to_header}<br><br>{body}</div>"
        )

    # ── Signature helpers ─────────────────────────────────────────────────────

    def _insert_default_signature(self) -> None:
        sig = self._sig_manager.get_default()
        if not sig:
            return
        self._body_edit.setHtml(f"<br><br>-- <br>{sig.content}")
        cursor = self._body_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self._body_edit.setTextCursor(cursor)

    def _refresh_sig_combo(self) -> None:
        self._sig_combo.blockSignals(True)
        self._sig_combo.clear()
        self._sig_combo.addItem("— Signature —")
        for s in self._sig_manager.load_all():
            self._sig_combo.addItem(s.name, s.sig_id)
        self._sig_combo.blockSignals(False)

    def _on_sig_selected(self, index: int) -> None:
        if index <= 0:
            return
        sig_id = self._sig_combo.itemData(index)
        sig    = next((s for s in self._sig_manager.load_all() if s.sig_id == sig_id), None)
        if not sig:
            return
        html    = self._body_edit.toHtml()
        div_idx = html.rfind("-- <br>")
        if div_idx != -1:
            new_html = html[:div_idx] + f"-- <br>{sig.content}"
        else:
            new_html = html + f"<br>-- <br>{sig.content}"
        self._body_edit.setHtml(new_html)
        self._sig_combo.blockSignals(True)
        self._sig_combo.setCurrentIndex(0)
        self._sig_combo.blockSignals(False)

    # ── CC / BCC toggles ──────────────────────────────────────────────────────

    def _toggle_cc(self) -> None:
        self._cc_row_widget.setVisible(not self._cc_row_widget.isVisible())

    def _toggle_bcc(self) -> None:
        self._bcc_row_widget.setVisible(not self._bcc_row_widget.isVisible())

    # ── Formatting ────────────────────────────────────────────────────────────

    def _on_font_family(self, family: str) -> None:
        self._body_edit.setFontFamily(family)
        self._body_edit.setFocus()

    def _on_font_size(self, size_str: str) -> None:
        try:
            self._body_edit.setFontPointSize(float(size_str))
        except ValueError:
            pass
        self._body_edit.setFocus()

    def _on_bold(self) -> None:
        fmt = self._body_edit.currentCharFormat()
        w   = (QFont.Weight.Normal if fmt.fontWeight() >= QFont.Weight.Bold
               else QFont.Weight.Bold)
        self._body_edit.setFontWeight(w)
        self._bold_btn.setChecked(w == QFont.Weight.Bold)
        self._body_edit.setFocus()

    def _on_italic(self) -> None:
        cur = self._body_edit.fontItalic()
        self._body_edit.setFontItalic(not cur)
        self._italic_btn.setChecked(not cur)
        self._body_edit.setFocus()

    def _on_underline(self) -> None:
        cur = self._body_edit.fontUnderline()
        self._body_edit.setFontUnderline(not cur)
        self._underline_btn.setChecked(not cur)
        self._body_edit.setFocus()

    def _on_text_color(self) -> None:
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            self._body_edit.setTextColor(color)
        self._body_edit.setFocus()

    def _on_highlight_color(self) -> None:
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            fmt = QTextCharFormat()
            fmt.setBackground(color)
            cursor = self._body_edit.textCursor()
            cursor.mergeCharFormat(fmt)
            self._body_edit.setTextCursor(cursor)
        self._body_edit.setFocus()

    # ── Attachments ───────────────────────────────────────────────────────────

    def _on_attach_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Attach Files", "", "All files (*)")
        for p in paths:
            if p:
                mt = mimetypes.guess_type(p)[0] or "application/octet-stream"
                self._attached_files.append({"path": p, "mime_type": mt, "inline": False})
        self._rebuild_att_chips()

    def _on_attach_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach Image", "",
            "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"
        )
        if not path:
            return
        reply = QMessageBox.question(
            self, "Image insert", "Insert image inline in body?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                import base64 as _b64
                mt   = mimetypes.guess_type(path)[0] or "image/png"
                data = _b64.b64encode(Path(path).read_bytes()).decode("utf-8")
                self._body_edit.insertHtml(
                    f'<img src="data:{mt};base64,{data}" style="max-width:100%;" />'
                )
            except Exception as exc:
                QMessageBox.warning(self, "Inline image", f"Could not insert: {exc}")
        else:
            mt = mimetypes.guess_type(path)[0] or "image/png"
            self._attached_files.append({"path": path, "mime_type": mt, "inline": False})
            self._rebuild_att_chips()

    def _rebuild_att_chips(self) -> None:
        while self._att_layout.count() > 1:
            item = self._att_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        for i, att in enumerate(self._attached_files):
            p    = Path(str(att.get("path") or ""))
            size = p.stat().st_size if p.exists() else 0
            chip = QPushButton(
                f"  {p.name}  ({_format_size(size)})  ✕",
                self._att_container
            )
            chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            chip.clicked.connect(lambda _, ix=i: self._remove_attachment(ix))
            self._att_layout.insertWidget(self._att_layout.count() - 1, chip)
        self._att_scroll.setVisible(bool(self._attached_files))
        self._apply_font_scaling()

    def _remove_attachment(self, index: int) -> None:
        if 0 <= index < len(self._attached_files):
            self._attached_files.pop(index)
        self._rebuild_att_chips()

    # ── Send / Draft / Discard ────────────────────────────────────────────────

    def _on_send_clicked(self) -> None:
        to      = self._to_edit.text().strip()
        subject = self._subject_edit.text().strip()
        if not to:
            QMessageBox.warning(self, "Send", "Please enter at least one recipient.")
            return
        if not subject:
            if QMessageBox.question(
                self, "Send", "Subject is empty — send anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return
        try:
            _, size = GmailClient.build_raw_message(
                from_addr   = self._runtime.sync_state.get("user_email") or "",
                to          = to,
                subject     = subject,
                html_body   = self._body_edit.toHtml(),
                cc          = self._cc_edit.text().strip(),
                bcc         = self._bcc_edit.text().strip(),
                attachments = [a for a in self._attached_files if not a.get("inline")],
            )
        except Exception:
            size = 0
        if size > GMAIL_MAX_SEND_BYTES:
            QMessageBox.warning(
                self, "Send",
                f"Message size ({_format_size(size)}) exceeds the Gmail 25 MB limit. "
                "Please remove some attachments."
            )
            return
        self._pending_send_args = {
            "to":        to,
            "subject":   subject,
            "html_body": self._body_edit.toHtml(),
            "cc":        self._cc_edit.text().strip(),
            "bcc":       self._bcc_edit.text().strip(),
            "thread_id": self._reply_thread_id,
            "reply_mid": self._reply_message_id,
            "atts":      [a for a in self._attached_files if not a.get("inline")],
        }
        self._send_btn.setEnabled(False)
        self._undo_bar.setVisible(True)
        self._undo_countdown = UNDO_SEND_DELAY_MS // 1000
        self._undo_lbl.setText(f"Sending in {self._undo_countdown} s…")
        self._undo_timer = QTimer(self)
        self._undo_timer.setInterval(1000)
        self._undo_timer.timeout.connect(self._undo_tick)
        self._undo_timer.start()

    def _undo_tick(self) -> None:
        self._undo_countdown -= 1
        if self._undo_countdown > 0:
            self._undo_lbl.setText(f"Sending in {self._undo_countdown} s…")
        else:
            self._cancel_undo_timer()
            self._execute_send()

    def _on_undo_send(self) -> None:
        self._cancel_undo_timer()
        self._pending_send_args = None
        self._send_btn.setEnabled(True)

    def _cancel_undo_timer(self) -> None:
        if self._undo_timer:
            self._undo_timer.stop()
            self._undo_timer = None
        self._undo_bar.setVisible(False)

    def _execute_send(self) -> None:
        args = self._pending_send_args
        if not args:
            return
        self._pending_send_args = None
        try:
            client     = self._runtime._make_client()
            raw_b64, _ = GmailClient.build_raw_message(
                from_addr           = self._runtime.sync_state.get("user_email") or "",
                to                  = args["to"],
                subject             = args["subject"],
                html_body           = args["html_body"],
                cc                  = args.get("cc", ""),
                bcc                 = args.get("bcc", ""),
                reply_to_message_id = args.get("reply_mid", ""),
                thread_id           = args.get("thread_id", ""),
                attachments         = args.get("atts", []),
            )
            client.send_message(raw_b64, thread_id=args.get("thread_id", ""))
            self._runtime._emit("gmail.message.sent", {
                "to": args["to"], "subject": args["subject"]
            })
            self.send_complete.emit()
        except Exception as exc:
            self._send_btn.setEnabled(True)
            QMessageBox.critical(self, "Send failed", str(exc))

    def _on_save_draft(self) -> None:
        try:
            client     = self._runtime._make_client()
            raw_b64, _ = GmailClient.build_raw_message(
                from_addr   = self._runtime.sync_state.get("user_email") or "",
                to          = self._to_edit.text().strip() or "",
                subject     = self._subject_edit.text().strip() or "",
                html_body   = self._body_edit.toHtml(),
                cc          = self._cc_edit.text().strip(),
                bcc         = self._bcc_edit.text().strip(),
                thread_id   = self._reply_thread_id,
                attachments = [a for a in self._attached_files if not a.get("inline")],
            )
            client.create_draft(raw_b64, thread_id=self._reply_thread_id)
            QMessageBox.information(self, "Draft", "Draft saved.")
        except Exception as exc:
            QMessageBox.warning(self, "Draft", f"Could not save draft: {exc}")

    def _on_discard(self) -> None:
        self._cancel_undo_timer()
        if QMessageBox.question(
            self, "Discard", "Discard this draft?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            self.discard_complete.emit()

    # ── Ribbon integration ────────────────────────────────────────────────────

    def notify_ribbon_active(self, ribbon: "GmailRibbon") -> None:
        self._ribbon_ref = ribbon
        ribbon.set_compose_active(True)

    def notify_ribbon_inactive(self, ribbon: "GmailRibbon") -> None:
        if self._ribbon_ref:
            self._ribbon_ref.set_compose_active(False)
        self._ribbon_ref = None

    # ── Font scaling ──────────────────────────────────────────────────────────

    def _fit_widget(self, widget: QWidget, text: str) -> None:
        if not text or widget.width() < 20:
            return
        fm        = widget.fontMetrics()
        available = max(10, widget.width() - 10)
        pt        = widget.font().pointSizeF() or 9.0
        while pt > 6.5 and fm.horizontalAdvance(text) > available:
            pt -= 0.5
            f  = widget.font()
            f.setPointSizeF(pt)
            widget.setFont(f)
            fm = widget.fontMetrics()

    def _apply_font_scaling(self) -> None:
        for w in self.findChildren((QLabel, QPushButton, QToolButton)):
            if hasattr(w, "text"):
                self._fit_widget(w, str(w.text()))

    def resizeEvent(self, event: Any) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_font_scaling()

    def showEvent(self, event: Any) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._apply_font_scaling()
