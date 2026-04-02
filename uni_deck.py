#!/usr/bin/env python3
"""Uni Deck: single-file builder seed and generated deck runtime."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

try:
    from PyQt6.QtCore import QDateTime, Qt
    from PyQt6.QtGui import QAction
    from PyQt6.QtWidgets import (
        QApplication,
        QFileDialog,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
    PYQT_OK = True
except Exception:
    PYQT_OK = False

UTC = timezone.utc
APP_VERSION = "0.2.0"
MODEL_BACKENDS = {"local_transformers", "ollama", "openai", "anthropic", "gguf_runner", "custom"}
MEMORY_LANES = {
    "memory": "memory.jsonl",
    "tasks": "tasks.jsonl",
    "messages": "messages.jsonl",
    "topic_index": "topic_index.jsonl",
    "daily_reflections": "daily_reflections.jsonl",
    "project_registry": "project_registry.jsonl",
    "project_nodes": "project_nodes.jsonl",
    "project_artifacts": "project_artifacts.jsonl",
    "project_decisions": "project_decisions.jsonl",
    "project_kpi_snapshots": "project_kpi_snapshots.jsonl",
}
ALLOWED_EXTS = {".txt", ".md", ".pdf", ".doc", ".docx", ".csv", ".xlsx", ".png", ".jpg", ".jpeg", ".svg", ".json", ".yaml", ".yml", ".html"}
REJECTED_EXTS = {".xlsm", ".xlsb", ".exe", ".dll", ".bat", ".cmd", ".sh", ".msi"}


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_slug(v: str) -> str:
    s = "".join(ch.lower() if ch.isalnum() else "-" for ch in v.strip())
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-") or "deck"


def safe_token(v: str) -> str:
    s = "".join(ch if ch.isalnum() else "_" for ch in v.strip())
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_") or "Deck"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def rewrite_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def default_backup_root(deck_name: str) -> Path:
    token = safe_token(deck_name)
    if os.name == "nt":
        return Path(r"C:\AI\Backups") / token
    return (Path.home() / "AI" / "Backups" / token).resolve()


@dataclass
class DeckPaths:
    root: Path
    runtime: Path
    config: Path
    integration_registry: Path
    memory: Path
    projects: Path
    logs: Path
    assets: Path
    integrations_dir: Path
    backups: Path

    @classmethod
    def from_root(cls, root: Path, backups: Optional[Path] = None) -> "DeckPaths":
        return cls(
            root=root,
            runtime=root / "runtime",
            config=root / "deck_config.json",
            integration_registry=root / "integration_registry.json",
            memory=root / "memory",
            projects=root / "projects",
            logs=root / "logs",
            assets=root / "assets",
            integrations_dir=root / "integrations",
            backups=backups or (root / "backups"),
        )


class ModelAdapter(Protocol):
    def generate(self, prompt: str, system_prompt: str = "") -> str: ...


class RuntimeModelAdapter:
    def __init__(self, model_cfg: Dict[str, Any]):
        self.cfg = model_cfg
        self.backend = model_cfg.get("backend", "custom")
        if self.backend not in MODEL_BACKENDS:
            raise ValueError(f"Unsupported backend: {self.backend}")

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if self.backend == "ollama":
            return self._ollama(prompt, system_prompt)
        if self.backend == "openai":
            return self._openai(prompt, system_prompt)
        if self.backend == "anthropic":
            return self._anthropic(prompt, system_prompt)
        if self.backend == "local_transformers":
            return self._local_transformers(prompt, system_prompt)
        if self.backend == "gguf_runner":
            return self._subprocess_backend(prompt)
        return self._custom(prompt, system_prompt)

    def _ollama(self, prompt: str, system_prompt: str) -> str:
        import urllib.request
        body = {
            "model": self.cfg.get("model_id", "llama3"),
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "options": self.cfg.get("params", {}),
        }
        req = urllib.request.Request(
            self.cfg.get("endpoint", "http://localhost:11434/api/generate"),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            payload = json.loads(r.read().decode("utf-8"))
        return payload.get("response", "")

    def _openai(self, prompt: str, system_prompt: str) -> str:
        import urllib.request
        key = os.environ.get(self.cfg.get("api_key_env", "OPENAI_API_KEY"), "")
        if not key:
            raise RuntimeError("Missing OpenAI API key env.")
        body = {
            "model": self.cfg.get("model_id", "gpt-4o-mini"),
            "messages": [{"role": "system", "content": system_prompt or "You are Uni."}, {"role": "user", "content": prompt}],
            **self.cfg.get("params", {}),
        }
        req = urllib.request.Request(
            self.cfg.get("endpoint", "https://api.openai.com/v1/chat/completions"),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            payload = json.loads(r.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]

    def _anthropic(self, prompt: str, system_prompt: str) -> str:
        import urllib.request
        key = os.environ.get(self.cfg.get("api_key_env", "ANTHROPIC_API_KEY"), "")
        if not key:
            raise RuntimeError("Missing Anthropic API key env.")
        body = {
            "model": self.cfg.get("model_id", "claude-3-5-sonnet-latest"),
            "max_tokens": int(self.cfg.get("params", {}).get("max_tokens", 1024)),
            "system": system_prompt or "You are Uni.",
            "messages": [{"role": "user", "content": prompt}],
        }
        req = urllib.request.Request(
            self.cfg.get("endpoint", "https://api.anthropic.com/v1/messages"),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            payload = json.loads(r.read().decode("utf-8"))
        return payload["content"][0]["text"]

    def _local_transformers(self, prompt: str, system_prompt: str) -> str:
        try:
            from transformers import pipeline
        except Exception as exc:
            raise RuntimeError(f"transformers unavailable: {exc}")
        model_id = self.cfg.get("model_id")
        if not model_id:
            raise RuntimeError("model.model_id required for local_transformers backend")
        pipe = pipeline("text-generation", model=model_id)
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        out = pipe(full_prompt, max_new_tokens=int(self.cfg.get("params", {}).get("max_tokens", 256)))
        text = out[0].get("generated_text", "")
        return text[len(full_prompt):].strip() if text.startswith(full_prompt) else text

    def _subprocess_backend(self, prompt: str) -> str:
        cmd = self.cfg.get("command")
        if not cmd:
            raise RuntimeError("gguf_runner requires model.command")
        proc = subprocess.run(cmd, input=prompt.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", errors="replace"))
        return proc.stdout.decode("utf-8", errors="replace").strip()

    def _custom(self, prompt: str, system_prompt: str) -> str:
        mode = self.cfg.get("custom_mode", "subprocess")
        if mode == "http":
            import urllib.request
            endpoint = self.cfg.get("endpoint")
            if not endpoint:
                raise RuntimeError("custom http mode requires model.endpoint")
            body = {"prompt": prompt, "system": system_prompt, "model": self.cfg.get("model_id", "")}
            req = urllib.request.Request(endpoint, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=120) as r:
                payload = json.loads(r.read().decode("utf-8"))
            return payload.get("response") or payload.get("text") or str(payload)
        return self._subprocess_backend(prompt)


class GoogleCalendarAdapter:
    def __init__(self, deck_root: Path, registry: Dict[str, Any]):
        self.deck_root = deck_root
        self.registry = registry

    def create_event_for_task(self, task: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
        gcfg = self.registry.get("google_calendar", {})
        if not gcfg.get("enabled", False):
            return False, "Google Calendar disabled", None
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except Exception as exc:
            return False, f"Google dependencies missing: {exc}", None

        scopes = ["https://www.googleapis.com/auth/calendar.events"]
        auth = gcfg.get("auth", {})
        cred_path = Path(auth.get("credentials_path") or (self.deck_root / "integrations" / "google_credentials.json"))
        token_path = Path(auth.get("token_path") or (self.deck_root / "integrations" / "google_token.json"))
        if not cred_path.exists():
            return False, f"Missing Google credentials file: {cred_path}", None

        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), scopes)
            creds = flow.run_local_server(port=0)
            ensure_dir(token_path.parent)
            token_path.write_text(creds.to_json(), encoding="utf-8")

        service = build("calendar", "v3", credentials=creds)
        due_text = task.get("due_at")
        if not due_text:
            return False, "Task has no due date for calendar sync", None
        due = datetime.fromisoformat(due_text)
        start = due.astimezone().replace(microsecond=0)
        end = start + timedelta(minutes=30)
        payload = {
            "summary": task.get("title", "Task"),
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        created = service.events().insert(calendarId="primary", body=payload).execute()
        return True, "Event created", created.get("id")


class SystemLayer:
    def __init__(self, paths: DeckPaths):
        self.paths = paths
        self.config = read_json(paths.config, {})
        bkp = self.config.get("paths", {}).get("backups")
        if bkp:
            self.paths.backups = Path(bkp)
        self.integration_registry = read_json(paths.integration_registry, default_integration_registry())
        self.model = RuntimeModelAdapter(self.config.get("model", {}))
        self.calendar = GoogleCalendarAdapter(paths.root, self.integration_registry)

    def lane_path(self, lane: str) -> Path:
        return self.paths.memory / MEMORY_LANES[lane]

    def append_lane(self, lane: str, payload: Dict[str, Any]) -> None:
        append_jsonl(self.lane_path(lane), {"id": str(uuid.uuid4()), "ts": now_iso(), **payload})

    def read_lane(self, lane: str) -> List[Dict[str, Any]]:
        return read_jsonl(self.lane_path(lane))

    def rewrite_lane(self, lane: str, rows: List[Dict[str, Any]]) -> None:
        rewrite_jsonl(self.lane_path(lane), rows)

    def log_diag(self, event: str, payload: Dict[str, Any]) -> None:
        append_jsonl(self.paths.logs / "diagnostics.jsonl", {"ts": now_iso(), "event": event, "payload": payload})

    def send_prompt(self, prompt: str) -> Dict[str, Any]:
        msg = {"prompt": prompt, "status": "failed", "response": "", "backend": self.config.get("model", {}).get("backend")}
        self.append_lane("messages", {"role": "user", "content": prompt})
        try:
            resp = self.model.generate(prompt, system_prompt="You are Uni Deck runtime assistant.")
            msg["response"] = resp
            msg["status"] = "ok"
            self.append_lane("messages", {"role": "assistant", "content": resp})
            self.log_diag("adapter_execution", {"ok": True, "backend": msg["backend"]})
        except Exception as exc:
            msg["response"] = f"Adapter failure: {exc}"
            self.log_diag("adapter_execution", {"ok": False, "backend": msg["backend"], "error": str(exc)})
        return msg

    def create_task(self, title: str, due_at: Optional[str]) -> Tuple[bool, str]:
        task = {"task_id": str(uuid.uuid4()), "title": title, "status": "open", "due_at": due_at, "google_event_id": None, "created_at": now_iso()}
        try:
            self.append_lane("tasks", task)
        except Exception as exc:
            self.log_diag("task_persist_failed", {"error": str(exc)})
            return False, f"Persist failed: {exc}"
        self.log_diag("task_created", {"task_id": task["task_id"]})

        ok, note, event_id = self.calendar.create_event_for_task(task)
        self.log_diag("calendar_sync_attempt", {"ok": ok, "note": note, "task_id": task["task_id"], "event_id": event_id})
        if ok and event_id:
            rows = self.read_lane("tasks")
            for r in rows:
                if r.get("task_id") == task["task_id"]:
                    r["google_event_id"] = event_id
                    r["updated_at"] = now_iso()
            self.rewrite_lane("tasks", rows)
        return True, "Task created"

    def create_project(self, name: str) -> Tuple[bool, str]:
        record = {"project_id": str(uuid.uuid4()), "name": name, "status": "active", "created_at": now_iso()}
        try:
            self.append_lane("project_registry", record)
            ensure_dir(self.paths.projects / safe_slug(name))
            return True, record["project_id"]
        except Exception as exc:
            self.log_diag("project_create_failed", {"error": str(exc)})
            return False, str(exc)

    def add_project_node(self, project_id: str, node_type: str, title: str) -> Tuple[bool, str]:
        rec = {"node_id": str(uuid.uuid4()), "project_id": project_id, "node_type": node_type, "title": title, "status": "open", "created_at": now_iso()}
        try:
            self.append_lane("project_nodes", rec)
            return True, rec["node_id"]
        except Exception as exc:
            return False, str(exc)


def default_deck_config(deck_name: str, slug: str, root: Path, backup_root: Path, backend: str, model_id: str) -> Dict[str, Any]:
    return {
        "deck": {"name": deck_name, "slug": slug, "deck_id": str(uuid.uuid4()), "created_at": now_iso(), "version": APP_VERSION},
        "runtime": {"mode": "runtime"},
        "model": {"backend": backend, "model_id": model_id, "endpoint": "", "api_key_env": "", "params": {"temperature": 0.3, "max_tokens": 512}, "custom_mode": "subprocess", "command": ""},
        "reflection": {"initiative_level": 2},
        "paths": {"root": str(root.resolve()), "memory": str((root / "memory").resolve()), "projects": str((root / "projects").resolve()), "assets": str((root / "assets").resolve()), "logs": str((root / "logs").resolve()), "backups": str(backup_root), "runtime": str((root / "runtime").resolve())},
        "integrations": {"google_calendar": {"enabled": False}, "google_drive": {"enabled": False}},
    }


def default_integration_registry() -> Dict[str, Any]:
    return {
        "google_calendar": {"enabled": False, "auth": {"credentials_path": "", "token_path": ""}, "sync": {"mode": "outbound"}},
        "google_drive": {"enabled": False, "auth": {"credentials_path": "", "token_path": ""}, "project_folder_map": {}},
    }


def init_deck(paths: DeckPaths, cfg: Dict[str, Any]) -> None:
    for p in [paths.root, paths.runtime, paths.memory, paths.projects, paths.logs, paths.assets, paths.integrations_dir]:
        ensure_dir(p)
    ensure_dir(paths.backups)
    write_json(paths.config, cfg)
    write_json(paths.integration_registry, default_integration_registry())
    for lane in MEMORY_LANES.values():
        (paths.memory / lane).touch(exist_ok=True)
    write_json(paths.root / "persona_delta.json", {})
    write_json(paths.root / "project_controls.json", {})
    write_json(paths.root / "project_budget.json", {})
    write_json(paths.root / "project_schedule.json", {})


def launcher_base(deck_name: str) -> str:
    return f"{safe_token(deck_name)}_deck"


def create_runtime_entry(deck_root: Path, deck_name: str) -> Path:
    entry = deck_root / f"{launcher_base(deck_name)}.py"
    code = """#!/usr/bin/env python3
import json
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
cfg = ROOT / "deck_config.json"
if not cfg.exists():
    raise SystemExit("Missing deck_config.json")
loaded = json.loads(cfg.read_text(encoding="utf-8"))
if loaded.get("runtime", {}).get("mode") != "runtime":
    raise SystemExit("Deck is not configured for runtime mode.")
runtime = ROOT / "runtime" / "uni_deck.py"
if not runtime.exists():
    raise SystemExit(f"Missing runtime seed at {runtime}")
sys.argv = [str(runtime), "--runtime", "--deck-root", str(ROOT)] + sys.argv[1:]
runpy.run_path(str(runtime), run_name="__main__")
"""
    entry.write_text(code, encoding="utf-8")
    return entry


def create_windows_launcher(deck_root: Path, deck_name: str) -> Path:
    cmd = deck_root / f"{launcher_base(deck_name)}.cmd"
    py = f"{launcher_base(deck_name)}.py"
    cmd.write_text(f"@echo off\ncd /d \"%~dp0\"\npython \"{py}\" %*\n", encoding="utf-8")
    return cmd


def create_deck_instance(seed_file: Path, output_parent: Path, deck_name: str, backend: str, model_id: str) -> Path:
    root = output_parent / safe_slug(deck_name)
    if root.exists():
        raise FileExistsError(f"Deck directory already exists: {root}")
    backup_root = default_backup_root(deck_name)
    paths = DeckPaths.from_root(root, backups=backup_root)
    cfg = default_deck_config(deck_name, safe_slug(deck_name), root, backup_root, backend, model_id)
    init_deck(paths, cfg)
    shutil.copy2(seed_file, paths.runtime / "uni_deck.py")
    create_runtime_entry(root, deck_name)
    create_windows_launcher(root, deck_name)
    return root


def prompt_builder() -> Tuple[str, Path, str, str]:
    print("Uni Deck Builder")
    name = input("Deck name: ").strip() or "Uni Deck"
    out = Path((input("Output parent [./decks]: ").strip() or "./decks")).expanduser().resolve()
    backend = input("Model backend [custom]: ").strip() or "custom"
    model_id = input("Model id [default]: ").strip() or "default"
    if backend not in MODEL_BACKENDS:
        raise ValueError(f"Unsupported backend: {backend}")
    return name, out, backend, model_id


if PYQT_OK:
    class DeckMainWindow(QMainWindow):
        def __init__(self, system: SystemLayer):
            super().__init__()
            self.system = system
            self.setWindowTitle(f"Uni Deck Runtime - {system.config.get('deck', {}).get('name', 'Deck')}")
            self.resize(1180, 780)
            self.tabs = QTabWidget()
            self.setCentralWidget(self.tabs)
            self._build_menu()
            self._build_tabs()
            self.reload_tasks()
            self.reload_diagnostics()
            self.reload_memory_trace()

        def _build_menu(self) -> None:
            m = self.menuBar().addMenu("Deck")
            diag = QAction("Refresh Diagnostics", self)
            diag.triggered.connect(self.reload_diagnostics)
            m.addAction(diag)

        def _build_tabs(self) -> None:
            self.tactical = QWidget(); self.bootup = QWidget(); self.diag = QWidget(); self.memory = QWidget(); self.projects = QWidget()
            self.tabs.addTab(self.tactical, "Tactical Record")
            self.tabs.addTab(self.bootup, "Bootup")
            self.tabs.addTab(self.diag, "Diagnostics")
            self.tabs.addTab(self.memory, "Memory Trace")
            self.tabs.addTab(self.projects, "Projects")
            self._build_tactical()
            self._build_bootup()
            self._build_diagnostics()
            self._build_memory()
            self._build_projects()

        def _build_tactical(self) -> None:
            layout = QVBoxLayout(self.tactical)
            model_box = QGroupBox("Prompt")
            mb = QVBoxLayout(model_box)
            self.prompt_input = QTextEdit()
            self.prompt_send = QPushButton("Send Prompt")
            self.prompt_send.clicked.connect(self.on_send_prompt)
            self.tactical_log = QPlainTextEdit(); self.tactical_log.setReadOnly(True)
            mb.addWidget(self.prompt_input); mb.addWidget(self.prompt_send)
            layout.addWidget(model_box); layout.addWidget(QLabel("Tactical Record")); layout.addWidget(self.tactical_log)

            task_box = QGroupBox("Task Registry")
            tb = QFormLayout(task_box)
            self.task_title = QLineEdit(); self.task_due = QLineEdit(); self.task_due.setPlaceholderText("ISO datetime, optional")
            self.add_task = QPushButton("Create Task")
            self.add_task.clicked.connect(self.on_create_task)
            tb.addRow("Title", self.task_title)
            tb.addRow("Due", self.task_due)
            tb.addRow("", self.add_task)
            layout.addWidget(task_box)

            self.task_table = QTableWidget(0, 5)
            self.task_table.setHorizontalHeaderLabels(["Task ID", "Title", "Status", "Due", "Google Event"]) 
            layout.addWidget(self.task_table)

        def _build_bootup(self) -> None:
            layout = QVBoxLayout(self.bootup)
            txt = QTextEdit(); txt.setReadOnly(True)
            txt.setPlainText(json.dumps({"deck": self.system.config.get("deck", {}), "model": self.system.config.get("model", {}), "runtime": self.system.config.get("runtime", {})}, indent=2))
            layout.addWidget(txt)

        def _build_diagnostics(self) -> None:
            layout = QVBoxLayout(self.diag)
            self.diag_view = QPlainTextEdit(); self.diag_view.setReadOnly(True)
            btn = QPushButton("Refresh Diagnostics"); btn.clicked.connect(self.reload_diagnostics)
            layout.addWidget(self.diag_view); layout.addWidget(btn)

        def _build_memory(self) -> None:
            layout = QVBoxLayout(self.memory)
            self.memory_view = QPlainTextEdit(); self.memory_view.setReadOnly(True)
            btn = QPushButton("Refresh Memory Trace"); btn.clicked.connect(self.reload_memory_trace)
            layout.addWidget(self.memory_view); layout.addWidget(btn)

        def _build_projects(self) -> None:
            layout = QVBoxLayout(self.projects)
            box = QGroupBox("Project Operations")
            g = QGridLayout(box)
            self.project_name = QLineEdit()
            mk = QPushButton("Create Project"); mk.clicked.connect(self.on_create_project)
            add_node = QPushButton("Add Node"); add_node.clicked.connect(self.on_add_project_node)
            g.addWidget(QLabel("Project Name"), 0, 0); g.addWidget(self.project_name, 0, 1); g.addWidget(mk, 0, 2); g.addWidget(add_node, 1, 0)
            self.project_log = QPlainTextEdit(); self.project_log.setReadOnly(True)
            layout.addWidget(box); layout.addWidget(self.project_log)

        def on_send_prompt(self) -> None:
            prompt = self.prompt_input.toPlainText().strip()
            if not prompt:
                return
            self.tactical_log.appendPlainText(f"[USER] {prompt}")
            result = self.system.send_prompt(prompt)
            self.tactical_log.appendPlainText(f"[UNI:{result['status']}] {result['response']}")
            self.prompt_input.clear()
            self.reload_diagnostics()
            self.reload_memory_trace()

        def on_create_task(self) -> None:
            title = self.task_title.text().strip()
            if not title:
                return
            due = self.task_due.text().strip() or None
            ok, msg = self.system.create_task(title, due)
            if ok:
                self.task_title.clear(); self.task_due.clear(); self.reload_tasks(); self.reload_diagnostics();
                self.tactical_log.appendPlainText(f"[TASK] {msg}: {title}")
            else:
                QMessageBox.warning(self, "Task failed", msg)

        def reload_tasks(self) -> None:
            rows = self.system.read_lane("tasks")
            self.task_table.setRowCount(len(rows))
            for i, r in enumerate(rows):
                self.task_table.setItem(i, 0, QTableWidgetItem(r.get("task_id", "")))
                self.task_table.setItem(i, 1, QTableWidgetItem(r.get("title", "")))
                self.task_table.setItem(i, 2, QTableWidgetItem(r.get("status", "")))
                self.task_table.setItem(i, 3, QTableWidgetItem(r.get("due_at") or ""))
                self.task_table.setItem(i, 4, QTableWidgetItem(r.get("google_event_id") or ""))

        def reload_diagnostics(self) -> None:
            events = read_jsonl(self.system.paths.logs / "diagnostics.jsonl")[-50:]
            payload = {
                "time": QDateTime.currentDateTime().toString(Qt.DateFormat.ISODate),
                "model": self.system.config.get("model", {}),
                "integrations": self.system.integration_registry,
                "recent": events,
            }
            self.diag_view.setPlainText(json.dumps(payload, indent=2))

        def reload_memory_trace(self) -> None:
            trace = {lane: self.system.read_lane(lane)[-5:] for lane in MEMORY_LANES.keys()}
            self.memory_view.setPlainText(json.dumps(trace, indent=2))

        def on_create_project(self) -> None:
            name = self.project_name.text().strip()
            if not name:
                return
            ok, data = self.system.create_project(name)
            if ok:
                self.project_log.appendPlainText(f"Created project {data} :: {name}")
            else:
                self.project_log.appendPlainText(f"Project create failed: {data}")

        def _latest_project_id(self) -> Optional[str]:
            rows = self.system.read_lane("project_registry")
            return rows[-1].get("project_id") if rows else None

        def on_add_project_node(self) -> None:
            pid = self._latest_project_id()
            if not pid:
                QMessageBox.warning(self, "No project", "Create project first")
                return
            node_type, ok = QInputDialog.getItem(self, "Node type", "Type", ["project", "phase", "milestone", "task", "blocker", "decision", "note", "dependency"], 0, False)
            if not ok:
                return
            title, ok = QInputDialog.getText(self, "Node title", "Title")
            if not ok or not title.strip():
                return
            ok, rec = self.system.add_project_node(pid, node_type, title.strip())
            self.project_log.appendPlainText(("Created node " + rec) if ok else ("Node create failed: " + rec))
else:
    DeckMainWindow = None


def resolve_runtime_root(this_file: Path, argv: Sequence[str]) -> Optional[Path]:
    if "--deck-root" in argv:
        i = argv.index("--deck-root")
        if i + 1 < len(argv):
            return Path(argv[i + 1]).expanduser().resolve()
    if this_file.parent.name == "runtime":
        return this_file.parent.parent.resolve()
    return None


def has_runtime_config(root: Path) -> bool:
    cfg = read_json(root / "deck_config.json", {})
    return cfg.get("runtime", {}).get("mode") == "runtime" and bool(cfg.get("deck"))


def run_builder(seed_file: Path) -> int:
    try:
        name, out, backend, model_id = prompt_builder()
        ensure_dir(out)
        root = create_deck_instance(seed_file, out, name, backend, model_id)
        print(f"Deck created: {root}")
        print(f"Runtime entrypoint: {root / (launcher_base(name) + '.py')}")
        return 0
    except Exception as exc:
        print(f"Builder failed: {exc}")
        return 1


def run_runtime(deck_root: Path) -> int:
    paths = DeckPaths.from_root(deck_root)
    if not paths.config.exists():
        print("Missing deck_config.json")
        return 2
    system = SystemLayer(paths)
    if not PYQT_OK:
        print("PyQt6 unavailable; runtime loaded in headless mode")
        print(json.dumps({"deck": system.config.get("deck", {}), "model": system.config.get("model", {})}, indent=2))
        return 0
    app = QApplication(sys.argv)
    w = DeckMainWindow(system)
    w.show()
    return app.exec()


def main(argv: Sequence[str]) -> int:
    this_file = Path(__file__).resolve()
    runtime_root = resolve_runtime_root(this_file, argv)
    explicit_runtime = "--runtime" in argv
    explicit_create = "--create-deck" in argv

    if explicit_runtime and runtime_root is not None:
        return run_runtime(runtime_root)
    if runtime_root is not None and has_runtime_config(runtime_root) and not explicit_create:
        return run_runtime(runtime_root)
    return run_builder(this_file)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
