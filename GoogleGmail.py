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
