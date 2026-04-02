#!/usr/bin/env python3
"""
Uni Deck - single-file seed builder and runtime template.

Design goals:
- Clean top-down architecture.
- Local-first storage (JSONL/JSON) and self-contained generated decks.
- Builder mode when invoked directly from seed context.
- Runtime mode when executed from generated deck launcher.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

try:
    from PyQt6.QtCore import QDateTime, QTimer, Qt
    from PyQt6.QtGui import QAction
    from PyQt6.QtWidgets import (
        QApplication,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QPlainTextEdit,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
        QFileDialog,
        QInputDialog,
    )

    PYQT_AVAILABLE = True
except Exception:
    PYQT_AVAILABLE = False


# ---------------------------------------------------------------------------
# Constants and versioning
# ---------------------------------------------------------------------------

APP_NAME = "Uni Deck"
APP_VERSION = "0.1.0"
DEFAULT_INITIATIVE_LEVEL = 2
BACKUP_RETENTION_DEFAULT = 10
UTC = timezone.utc

MODEL_BACKENDS = {
    "local_transformers",
    "ollama",
    "openai",
    "anthropic",
    "gguf_runner",
    "custom",
}

PROJECT_NODE_TYPES = {
    "project",
    "phase",
    "milestone",
    "task",
    "blocker",
    "decision",
    "note",
    "dependency",
}

ARTIFACT_TYPES = {
    "document",
    "dataset",
    "diagram",
    "decision_record",
    "specification",
    "reference_file",
    "generated_report",
    "work_module_ref",
}

TRUTH_MODES = {"ignore", "reference", "authoritative"}
PROJECT_SOT_MODES = {"none", "reference", "authoritative"}
DECISION_STATUSES = {"proposed", "accepted", "rejected", "deferred", "superseded"}
KPI_STATUSES = {"stable", "watch", "at_risk", "unknown"}
WORK_MEMORY_STATUSES = {"draft", "tested", "validated", "canonical", "deprecated"}
TOPIC_TEMPERATURES = {"active", "warm", "cool", "dormant"}

MEMORY_LANES = {
    "memory": "memory.jsonl",
    "tasks": "tasks.jsonl",
    "daily_reflections": "daily_reflections.jsonl",
    "followup_candidates": "followup_candidates.jsonl",
    "argument_memory": "argument_memory.jsonl",
    "work_memory": "work_memory.jsonl",
    "rules_memory": "rules_memory.jsonl",
    "lessons_memory": "lessons_memory.jsonl",
    "topic_index": "topic_index.jsonl",
    "project_registry": "project_registry.jsonl",
    "project_nodes": "project_nodes.jsonl",
    "project_artifacts": "project_artifacts.jsonl",
    "project_decisions": "project_decisions.jsonl",
    "project_kpi_snapshots": "project_kpi_snapshots.jsonl",
}

JSON_STORES = {
    "project_controls": "project_controls.json",
    "project_budget": "project_budget.json",
    "project_schedule": "project_schedule.json",
    "persona_delta": "persona_delta.json",
    "integration_registry": "integration_registry.json",
}

ALLOWED_ARTIFACT_EXTENSIONS = {
    ".txt",
    ".md",
    ".pdf",
    ".doc",
    ".docx",
    ".csv",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".json",
    ".yaml",
    ".yml",
    ".html",
}

REJECTED_ARTIFACT_EXTENSIONS = {
    ".xlsm",
    ".xlsb",
    ".exe",
    ".bat",
    ".cmd",
    ".sh",
    ".msi",
    ".dll",
    ".so",
    ".dylib",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


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
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def rewrite_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def safe_slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "deck"


def safe_name_token(value: str) -> str:
    token = "".join(ch if ch.isalnum() else "_" for ch in value.strip())
    while "__" in token:
        token = token.replace("__", "_")
    token = token.strip("_")
    return token or "Deck"


def default_backup_root(deck_name: str) -> Path:
    deck_token = safe_name_token(deck_name)
    if os.name == "nt":
        return Path(r"C:\AI\Backups") / deck_token
    return (Path.home() / "AI" / "Backups" / deck_token).resolve()


# ---------------------------------------------------------------------------
# Paths + configuration
# ---------------------------------------------------------------------------


@dataclass
class DeckPaths:
    root: Path
    runtime: Path
    config: Path
    integrations: Path
    integrations_dir: Path
    memory: Path
    projects: Path
    assets: Path
    backups: Path
    logs: Path

    @classmethod
    def from_root(cls, root: Path, backups: Optional[Path] = None) -> "DeckPaths":
        runtime = root / "runtime"
        return cls(
            root=root,
            runtime=runtime,
            config=root / "deck_config.json",
            integrations=root / "integration_registry.json",
            integrations_dir=root / "integrations",
            memory=root / "memory",
            projects=root / "projects",
            assets=root / "assets",
            backups=backups or (root / "backups"),
            logs=root / "logs",
        )


def default_deck_config(deck_name: str, deck_slug: str, root: Path, backup_root: Path) -> Dict[str, Any]:
    return {
        "deck": {
            "name": deck_name,
            "slug": deck_slug,
            "deck_id": str(uuid.uuid4()),
            "created_at": utc_now_iso(),
            "version": APP_VERSION,
        },
        "model": {
            "backend": "custom",
            "model_id": "dolphin",
            "endpoint": "",
            "api_key_env": "",
            "params": {"temperature": 0.3, "max_tokens": 800},
        },
        "persona": {
            "enabled": False,
            "display_name": "",
            "tone": "neutral",
            "status_overrides": {},
            "purge_flavor": [],
            "startup_flavor": [],
            "idle_flavor": [],
        },
        "memory": {
            "base_dir": str((root / "memory").resolve()),
            "lanes": MEMORY_LANES,
            "work_memory_promotion": {
                "allowed_statuses": sorted(WORK_MEMORY_STATUSES),
                "default_status": "draft",
            },
        },
        "reflection": {
            "initiative_level": DEFAULT_INITIATIVE_LEVEL,
            "micro_reflection_enabled": True,
            "idle_contemplation_enabled": True,
            "daily_review_enabled": True,
            "weekly_persona_review_enabled": True,
            "topic_weighting": {
                "recency": 0.25,
                "frequency": 0.2,
                "unresolved": 0.2,
                "linkage": 0.15,
                "importance": 0.1,
                "friction": 0.1,
                "staleness_penalty": 0.15,
            },
        },
        "projects": {
            "source_of_truth_mode": "reference",
            "default_artifact_truth_mode": "reference",
            "budget_enabled": True,
            "schedule_enabled": True,
            "node_types": sorted(PROJECT_NODE_TYPES),
            "artifact_types": sorted(ARTIFACT_TYPES),
        },
        "integrations": {
            "google_calendar": {"enabled": False},
            "google_drive": {"enabled": False},
        },
        "ui": {
            "theme": "dark",
            "core_tabs": ["Tactical Record", "Bootup", "Diagnostics", "Memory Trace"],
            "optional_tabs": ["Projects", "Calendar", "Drive", "Work Library", "Insights"],
        },
        "runtime": {
            "mode": "runtime",
            "auto_backup": False,
            "backup_retention": BACKUP_RETENTION_DEFAULT,
            "idle_reflection_seconds": 600,
            "daily_review_hour": 20,
            "weekly_review_weekday": 6,
        },
        "paths": {
            "root": str(root.resolve()),
            "memory": str((root / "memory").resolve()),
            "projects": str((root / "projects").resolve()),
            "assets": str((root / "assets").resolve()),
            "backups": str(backup_root),
            "logs": str((root / "logs").resolve()),
            "runtime": str((root / "runtime").resolve()),
        },
    }


def default_integration_registry() -> Dict[str, Any]:
    return {
        "google_calendar": {
            "enabled": False,
            "auth": {"token_path": "", "credentials_path": ""},
            "sync": {"mode": "both", "poll_seconds": 180},
        },
        "google_drive": {
            "enabled": False,
            "auth": {"token_path": "", "credentials_path": ""},
            "project_folder_map": {},
            "sync": {"mode": "manual"},
        },
    }


# ---------------------------------------------------------------------------
# Model adapter contract
# ---------------------------------------------------------------------------


class ModelAdapter(Protocol):
    backend: str

    def generate(self, prompt: str, system: Optional[str] = None, **kwargs: Any) -> str:
        ...

    def health(self) -> Dict[str, Any]:
        ...


@dataclass
class GenericModelAdapter:
    backend: str
    model_id: str
    endpoint: str = ""
    api_key_env: str = ""
    params: Dict[str, Any] = field(default_factory=dict)

    def generate(self, prompt: str, system: Optional[str] = None, **kwargs: Any) -> str:
        # Routing contract intentionally backend-agnostic in phase skeleton.
        return f"[{self.backend}:{self.model_id}] generation stub: {prompt[:200]}"

    def health(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "model_id": self.model_id,
            "endpoint": self.endpoint,
            "api_key_env": self.api_key_env,
            "status": "configured" if self.backend in MODEL_BACKENDS else "invalid_backend",
        }


# ---------------------------------------------------------------------------
# Persistence managers
# ---------------------------------------------------------------------------


class MemoryLaneStore:
    def __init__(self, paths: DeckPaths):
        self.paths = paths

    def lane_path(self, lane_name: str) -> Path:
        filename = MEMORY_LANES[lane_name]
        return self.paths.memory / filename

    def append(self, lane_name: str, payload: Dict[str, Any]) -> None:
        entry = {"id": str(uuid.uuid4()), "ts": utc_now_iso(), **payload}
        append_jsonl(self.lane_path(lane_name), entry)

    def read(self, lane_name: str) -> List[Dict[str, Any]]:
        return read_jsonl(self.lane_path(lane_name))

    def rewrite(self, lane_name: str, rows: Sequence[Dict[str, Any]]) -> None:
        rewrite_jsonl(self.lane_path(lane_name), rows)


class ProjectStore:
    def __init__(self, lanes: MemoryLaneStore, paths: DeckPaths):
        self.lanes = lanes
        self.paths = paths

    def register_project(self, name: str, source_of_truth_mode: str = "reference") -> Dict[str, Any]:
        if source_of_truth_mode not in PROJECT_SOT_MODES:
            raise ValueError(f"invalid source_of_truth_mode: {source_of_truth_mode}")
        project = {
            "project_id": str(uuid.uuid4()),
            "name": name,
            "source_of_truth_mode": source_of_truth_mode,
            "status": "active",
            "created_at": utc_now_iso(),
        }
        self.lanes.append("project_registry", project)
        return project

    def add_node(self, project_id: str, node_type: str, title: str, status: str = "open") -> Dict[str, Any]:
        if node_type not in PROJECT_NODE_TYPES:
            raise ValueError(f"invalid node_type: {node_type}")
        node = {
            "node_id": str(uuid.uuid4()),
            "project_id": project_id,
            "node_type": node_type,
            "title": title,
            "status": status,
            "created_at": utc_now_iso(),
        }
        self.lanes.append("project_nodes", node)
        return node

    def add_decision(self, project_id: str, summary: str, status: str = "proposed") -> Dict[str, Any]:
        if status not in DECISION_STATUSES:
            raise ValueError(f"invalid decision status: {status}")
        decision = {
            "decision_id": str(uuid.uuid4()),
            "project_id": project_id,
            "summary": summary,
            "status": status,
            "created_at": utc_now_iso(),
        }
        self.lanes.append("project_decisions", decision)
        return decision

    def ingest_artifact(
        self,
        project_id: str,
        src_file: Path,
        artifact_type: str = "reference_file",
        truth_mode: str = "reference",
    ) -> Dict[str, Any]:
        ext = src_file.suffix.lower()
        if ext in REJECTED_ARTIFACT_EXTENSIONS or ext not in ALLOWED_ARTIFACT_EXTENSIONS:
            raise ValueError(f"artifact extension rejected: {ext}")
        if artifact_type not in ARTIFACT_TYPES:
            raise ValueError(f"invalid artifact_type: {artifact_type}")
        if truth_mode not in TRUTH_MODES:
            raise ValueError(f"invalid truth mode: {truth_mode}")

        project_artifact_dir = ensure_dir(self.paths.assets / project_id)
        artifact_id = str(uuid.uuid4())
        dest = project_artifact_dir / f"{artifact_id}{ext}"
        shutil.copy2(src_file, dest)

        record = {
            "artifact_id": artifact_id,
            "project_id": project_id,
            "artifact_type": artifact_type,
            "truth_mode": truth_mode,
            "source_filename": src_file.name,
            "stored_path": str(dest.resolve()),
            "format": ext.lstrip("."),
            "created_at": utc_now_iso(),
        }
        self.lanes.append("project_artifacts", record)
        return record


class KPIEngine:
    @staticmethod
    def generate(project_id: str, lanes: MemoryLaneStore) -> Dict[str, Any]:
        nodes = [n for n in lanes.read("project_nodes") if n.get("project_id") == project_id]
        decisions = [d for d in lanes.read("project_decisions") if d.get("project_id") == project_id]

        open_nodes = sum(1 for n in nodes if n.get("status") not in {"done", "closed"})
        deferred_decisions = sum(1 for d in decisions if d.get("status") == "deferred")

        raw = {
            "flow_stability": max(0, 100 - open_nodes * 3),
            "scope_stability": max(0, 100 - len(nodes) * 2),
            "schedule_health": max(0, 100 - deferred_decisions * 10),
            "effort_accuracy": 50,
            "complexity_growth": len(nodes),
            "continuity_load": open_nodes + deferred_decisions,
        }

        status = "stable"
        if raw["flow_stability"] < 60 or raw["schedule_health"] < 60:
            status = "at_risk"
        elif raw["flow_stability"] < 75:
            status = "watch"

        snapshot = {
            "snapshot_id": str(uuid.uuid4()),
            "project_id": project_id,
            "captured_at": utc_now_iso(),
            "raw_values": raw,
            "normalized_values": {k: min(max(v / 100 if isinstance(v, (int, float)) else 0, 0), 1) for k, v in raw.items()},
            "trend": "flat",
            "status": status if status in KPI_STATUSES else "unknown",
            "short_note": "Provisional KPI from local lane data.",
            "top_risks": [
                "Unresolved project nodes increasing continuity load." if open_nodes > 5 else "No significant structural risk detected."
            ],
            "recommended_focus": [
                "Close or decompose high-friction nodes.",
                "Resolve deferred decisions to improve schedule health.",
            ],
        }
        lanes.append("project_kpi_snapshots", snapshot)
        return snapshot


# ---------------------------------------------------------------------------
# Scheduler shell
# ---------------------------------------------------------------------------


class SchedulerShell:
    def __init__(self) -> None:
        self.jobs: Dict[str, Dict[str, Any]] = {}

    def register_job(self, name: str, every_seconds: int, enabled: bool = True) -> None:
        self.jobs[name] = {
            "name": name,
            "every_seconds": every_seconds,
            "enabled": enabled,
            "last_run": None,
        }

    def mark_run(self, name: str) -> None:
        if name in self.jobs:
            self.jobs[name]["last_run"] = utc_now_iso()

    def diagnostics(self) -> List[Dict[str, Any]]:
        return list(self.jobs.values())


# ---------------------------------------------------------------------------
# Persona layer
# ---------------------------------------------------------------------------


@dataclass
class PersonaLayer:
    enabled: bool
    display_name: str
    tone: str
    status_overrides: Dict[str, str]
    purge_flavor: List[str]

    @classmethod
    def from_config(cls, cfg: Dict[str, Any], delta_payload: Dict[str, Any]) -> "PersonaLayer":
        merged = dict(cfg)
        for key, value in delta_payload.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        return cls(
            enabled=bool(merged.get("enabled", False)),
            display_name=merged.get("display_name", ""),
            tone=merged.get("tone", "neutral"),
            status_overrides=merged.get("status_overrides", {}),
            purge_flavor=merged.get("purge_flavor", []),
        )


# ---------------------------------------------------------------------------
# System layer
# ---------------------------------------------------------------------------


class SystemLayer:
    def __init__(self, paths: DeckPaths):
        self.config = read_json(paths.config, {})
        config_paths = self.config.get("paths", {})
        backup_path_cfg = config_paths.get("backups")
        backups_root = Path(backup_path_cfg).expanduser() if backup_path_cfg else paths.backups
        self.paths = DeckPaths.from_root(paths.root, backups=backups_root)
        self.integration_registry = read_json(self.paths.integrations, default_integration_registry())
        self.lanes = MemoryLaneStore(self.paths)
        self.projects = ProjectStore(self.lanes, self.paths)
        self.scheduler = SchedulerShell()
        self.scheduler.register_job("idle_contemplation", self.config.get("runtime", {}).get("idle_reflection_seconds", 600))
        self.scheduler.register_job("daily_review", 24 * 3600)
        self.scheduler.register_job("weekly_persona_review", 7 * 24 * 3600)

        model_cfg = self.config.get("model", {})
        self.model: ModelAdapter = GenericModelAdapter(
            backend=model_cfg.get("backend", "custom"),
            model_id=model_cfg.get("model_id", ""),
            endpoint=model_cfg.get("endpoint", ""),
            api_key_env=model_cfg.get("api_key_env", ""),
            params=model_cfg.get("params", {}),
        )

        persona_delta = read_json(self.paths.root / JSON_STORES["persona_delta"], {})
        self.persona = PersonaLayer.from_config(self.config.get("persona", {}), persona_delta)

    def log_diagnostic(self, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
        log_file = ensure_dir(self.paths.logs) / "diagnostics.jsonl"
        append_jsonl(log_file, {"ts": utc_now_iso(), "event": event, "payload": payload or {}})

    def save_task(self, title: str, due_at: Optional[str] = None) -> Dict[str, Any]:
        task = {
            "task_id": str(uuid.uuid4()),
            "title": title,
            "status": "open",
            "due_at": due_at,
            "google_event_id": None,
            "created_at": utc_now_iso(),
        }
        self.lanes.append("tasks", task)
        self.log_diagnostic("task_created", {"task_id": task["task_id"]})
        return task

    def update_task_status(self, task_id: str, status: str) -> bool:
        rows = self.lanes.read("tasks")
        changed = False
        for row in rows:
            if row.get("task_id") == task_id:
                row["status"] = status
                row["updated_at"] = utc_now_iso()
                changed = True
                break
        if changed:
            self.lanes.rewrite("tasks", rows)
            self.log_diagnostic("task_status_updated", {"task_id": task_id, "status": status})
        return changed

    def compute_topic_index(self, topic: str, unresolved_count: int = 0, linkage: int = 0, importance: float = 0.5, friction: float = 0.5) -> Dict[str, Any]:
        all_topics = [r for r in self.lanes.read("topic_index") if r.get("topic") == topic]
        frequency = len(all_topics) + 1
        recency_score = 1.0
        staleness_penalty = max(0.0, min((frequency - 1) * 0.02, 0.25))
        score = (
            recency_score * 0.25
            + min(frequency / 10.0, 1.0) * 0.2
            + min(unresolved_count / 10.0, 1.0) * 0.2
            + min(linkage / 10.0, 1.0) * 0.15
            + max(0, min(importance, 1)) * 0.1
            + max(0, min(friction, 1)) * 0.1
            - staleness_penalty
        )

        if score >= 0.75:
            temp = "active"
        elif score >= 0.55:
            temp = "warm"
        elif score >= 0.35:
            temp = "cool"
        else:
            temp = "dormant"

        record = {
            "topic": topic,
            "score": round(score, 4),
            "temperature": temp,
            "weights": {
                "recency": recency_score,
                "frequency": frequency,
                "unresolved_count": unresolved_count,
                "linkage": linkage,
                "user_importance_weight": importance,
                "friction_weight": friction,
                "staleness_penalty": staleness_penalty,
            },
        }
        self.lanes.append("topic_index", record)
        return record

    def backup(self, label: Optional[str] = None) -> Path:
        stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        suffix = f"_{safe_slug(label)}" if label else ""
        target = ensure_dir(self.paths.backups) / f"backup_{stamp}{suffix}"
        ensure_dir(target)

        for item in self.paths.root.iterdir():
            dest = target / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        self.log_diagnostic("backup_created", {"path": str(target)})
        self._enforce_backup_retention()
        return target

    def _enforce_backup_retention(self) -> None:
        retention = int(self.config.get("runtime", {}).get("backup_retention", BACKUP_RETENTION_DEFAULT))
        backups = sorted([p for p in self.paths.backups.glob("backup_*") if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[retention:]:
            shutil.rmtree(old, ignore_errors=True)

    def soft_purge(self) -> None:
        transient = {
            "memory",
            "daily_reflections",
            "followup_candidates",
            "argument_memory",
        }
        for lane in transient:
            rewrite_jsonl(self.lanes.lane_path(lane), [])
        self.log_diagnostic("soft_purge_completed")

    def restore(self, backup_path: Path) -> None:
        if not backup_path.exists() or not backup_path.is_dir():
            raise ValueError("Backup path is invalid.")
        self.soft_purge()
        for child in backup_path.iterdir():
            dest = self.paths.root / child.name
            if child.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(child, dest)
            else:
                shutil.copy2(child, dest)
        self.log_diagnostic("restore_completed", {"backup": str(backup_path)})

    def full_purge(self) -> None:
        self.log_diagnostic("full_purge_requested")
        root = self.paths.root
        shutil.rmtree(root)


# ---------------------------------------------------------------------------
# Builder mode / deck creation
# ---------------------------------------------------------------------------


def initialize_deck_files(paths: DeckPaths, cfg: Dict[str, Any]) -> None:
    for p in [paths.root, paths.runtime, paths.memory, paths.projects, paths.assets, paths.logs, paths.integrations_dir]:
        ensure_dir(p)
    ensure_dir(paths.backups)

    write_json(paths.config, cfg)
    write_json(paths.integrations, default_integration_registry())

    for lane_file in MEMORY_LANES.values():
        lane_path = paths.memory / lane_file
        ensure_dir(lane_path.parent)
        lane_path.touch(exist_ok=True)

    for store_file in [JSON_STORES["project_controls"], JSON_STORES["project_budget"], JSON_STORES["project_schedule"], JSON_STORES["persona_delta"]]:
        store_path = paths.root / store_file
        if not store_path.exists():
            write_json(store_path, {})


def deck_launcher_basename(deck_name: str) -> str:
    return f"{safe_name_token(deck_name)}_deck"


def create_runtime_python_launcher(deck_root: Path, deck_name: str) -> Path:
    launcher = deck_root / f"{deck_launcher_basename(deck_name)}.py"
    content = """#!/usr/bin/env python3
from pathlib import Path
import json
import runpy
import sys

ROOT = Path(__file__).resolve().parent
RUNTIME_ENTRY = ROOT / "runtime" / "uni_deck.py"
if not RUNTIME_ENTRY.exists():
    raise SystemExit(f"Missing runtime entrypoint: {RUNTIME_ENTRY}")

config_path = ROOT / "deck_config.json"
try:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
except Exception as exc:
    raise SystemExit(f"Invalid or missing deck_config.json: {exc}")

if cfg.get("runtime", {}).get("mode") != "runtime":
    raise SystemExit("Deck is not initialized for runtime mode.")

sys.argv = [str(RUNTIME_ENTRY), "--runtime", "--deck-root", str(ROOT)] + sys.argv[1:]
runpy.run_path(str(RUNTIME_ENTRY), run_name="__main__")
"""
    launcher.write_text(content, encoding="utf-8")
    return launcher


def create_windows_launcher(deck_root: Path, deck_name: str) -> Path:
    launcher_name = f"{deck_launcher_basename(deck_name)}.py"
    launcher = deck_root / f"{deck_launcher_basename(deck_name)}.cmd"
    content = f"""@echo off
setlocal
cd /d "%~dp0"
python "{launcher_name}" %*
"""
    launcher.write_text(content, encoding="utf-8")
    return launcher


def create_deck_instance(seed_file: Path, output_dir: Path, deck_name: str, model_backend: str, model_id: str) -> Path:
    deck_slug = safe_slug(deck_name)
    deck_root = output_dir / deck_slug
    if deck_root.exists():
        raise FileExistsError(f"Deck directory already exists: {deck_root}")

    backup_root = default_backup_root(deck_name)
    paths = DeckPaths.from_root(deck_root, backups=backup_root)
    cfg = default_deck_config(deck_name=deck_name, deck_slug=deck_slug, root=deck_root, backup_root=backup_root)
    cfg["model"]["backend"] = model_backend
    cfg["model"]["model_id"] = model_id

    initialize_deck_files(paths, cfg)

    runtime_file = paths.runtime / "uni_deck.py"
    shutil.copy2(seed_file, runtime_file)

    create_runtime_python_launcher(deck_root, deck_name)
    create_windows_launcher(deck_root, deck_name)
    return deck_root


def prompt_builder_inputs() -> Tuple[str, Path, str, str]:
    print(f"\n{APP_NAME} Builder v{APP_VERSION}")
    print("Create a new standalone deck instance.\n")

    deck_name = input("Deck name: ").strip() or "Uni Deck"
    output_raw = input("Output parent directory [./decks]: ").strip() or "./decks"
    backend = input("Model backend [custom]: ").strip() or "custom"
    model_id = input("Default model id [dolphin]: ").strip() or "dolphin"

    if backend not in MODEL_BACKENDS:
        raise ValueError(f"Unsupported backend '{backend}'. Allowed: {sorted(MODEL_BACKENDS)}")

    return deck_name, Path(output_raw).expanduser().resolve(), backend, model_id


# ---------------------------------------------------------------------------
# UI shell
# ---------------------------------------------------------------------------


if PYQT_AVAILABLE:
    class DeckMainWindow(QMainWindow):
        def __init__(self, system: SystemLayer):
            super().__init__()
            self.system = system
            self.setWindowTitle(f"{APP_NAME} — {self.system.config.get('deck', {}).get('name', 'Deck')}")
            self.resize(1200, 780)
            self.tabs = QTabWidget()
            self.setCentralWidget(self.tabs)

            self._init_menu()
            self._build_tabs()
            self._load_tasks_table()
            self._start_idle_timer()

        def _init_menu(self) -> None:
            menu = self.menuBar().addMenu("Deck")

            backup_action = QAction("Backup Now", self)
            backup_action.triggered.connect(self._on_backup)
            menu.addAction(backup_action)

            restore_action = QAction("Restore From Backup", self)
            restore_action.triggered.connect(self._on_restore)
            menu.addAction(restore_action)

            soft_purge_action = QAction("Soft Purge", self)
            soft_purge_action.triggered.connect(self._on_soft_purge)
            menu.addAction(soft_purge_action)

            full_purge_action = QAction("Full Purge", self)
            full_purge_action.triggered.connect(self._on_full_purge)
            menu.addAction(full_purge_action)

        def _build_tabs(self) -> None:
            self.tactical_tab = QWidget()
            self.bootup_tab = QWidget()
            self.diag_tab = QWidget()
            self.memory_trace_tab = QWidget()
            self.projects_tab = QWidget()

            self.tabs.addTab(self.tactical_tab, "Tactical Record")
            self.tabs.addTab(self.bootup_tab, "Bootup")
            self.tabs.addTab(self.diag_tab, "Diagnostics")
            self.tabs.addTab(self.memory_trace_tab, "Memory Trace")
            self.tabs.addTab(self.projects_tab, "Projects")

            self._build_tactical_tab()
            self._build_bootup_tab()
            self._build_diagnostics_tab()
            self._build_memory_trace_tab()
            self._build_projects_tab()

        def _build_tactical_tab(self) -> None:
            layout = QVBoxLayout(self.tactical_tab)
            self.task_title = QLineEdit()
            self.task_due = QLineEdit()
            self.task_due.setPlaceholderText("ISO datetime optional")
            add_btn = QPushButton("Add Task")
            add_btn.clicked.connect(self._on_add_task)

            form = QFormLayout()
            form.addRow("Title", self.task_title)
            form.addRow("Due", self.task_due)
            form.addRow("", add_btn)
            layout.addLayout(form)

            self.tasks_table = QTableWidget(0, 4)
            self.tasks_table.setHorizontalHeaderLabels(["Task ID", "Title", "Status", "Due"])
            layout.addWidget(self.tasks_table)

        def _build_bootup_tab(self) -> None:
            layout = QVBoxLayout(self.bootup_tab)
            cfg = self.system.config
            summary = QTextEdit()
            summary.setReadOnly(True)
            summary.setPlainText(json.dumps({
                "deck": cfg.get("deck", {}),
                "model": cfg.get("model", {}),
                "persona_enabled": cfg.get("persona", {}).get("enabled", False),
                "initiative_level": cfg.get("reflection", {}).get("initiative_level", DEFAULT_INITIATIVE_LEVEL),
            }, indent=2))
            layout.addWidget(summary)

        def _build_diagnostics_tab(self) -> None:
            layout = QVBoxLayout(self.diag_tab)
            self.diag_output = QPlainTextEdit()
            self.diag_output.setReadOnly(True)
            layout.addWidget(self.diag_output)
            refresh = QPushButton("Refresh Diagnostics")
            refresh.clicked.connect(self._refresh_diagnostics)
            layout.addWidget(refresh)
            self._refresh_diagnostics()

        def _build_memory_trace_tab(self) -> None:
            layout = QVBoxLayout(self.memory_trace_tab)
            self.memory_trace = QPlainTextEdit()
            self.memory_trace.setReadOnly(True)
            layout.addWidget(self.memory_trace)
            refresh = QPushButton("Refresh Memory Trace")
            refresh.clicked.connect(self._refresh_memory_trace)
            layout.addWidget(refresh)
            self._refresh_memory_trace()

        def _build_projects_tab(self) -> None:
            layout = QVBoxLayout(self.projects_tab)

            project_box = QGroupBox("Project Operations")
            p_layout = QGridLayout(project_box)
            self.project_name_input = QLineEdit()
            create_project = QPushButton("Create Project")
            create_project.clicked.connect(self._on_create_project)

            create_node = QPushButton("Add Node")
            create_node.clicked.connect(self._on_create_node)

            ingest_artifact = QPushButton("Ingest Artifact")
            ingest_artifact.clicked.connect(self._on_ingest_artifact)

            kpi_btn = QPushButton("Generate KPI Snapshot")
            kpi_btn.clicked.connect(self._on_generate_kpi)

            p_layout.addWidget(QLabel("Project Name"), 0, 0)
            p_layout.addWidget(self.project_name_input, 0, 1)
            p_layout.addWidget(create_project, 0, 2)
            p_layout.addWidget(create_node, 1, 0)
            p_layout.addWidget(ingest_artifact, 1, 1)
            p_layout.addWidget(kpi_btn, 1, 2)

            layout.addWidget(project_box)

            self.project_log = QPlainTextEdit()
            self.project_log.setReadOnly(True)
            layout.addWidget(self.project_log)

        def _on_add_task(self) -> None:
            title = self.task_title.text().strip()
            if not title:
                return
            due = self.task_due.text().strip() or None
            self.system.save_task(title, due)
            self.task_title.clear()
            self.task_due.clear()
            self._load_tasks_table()
            self._refresh_diagnostics()

        def _load_tasks_table(self) -> None:
            rows = self.system.lanes.read("tasks")
            self.tasks_table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                self.tasks_table.setItem(i, 0, QTableWidgetItem(row.get("task_id", "")))
                self.tasks_table.setItem(i, 1, QTableWidgetItem(row.get("title", "")))
                self.tasks_table.setItem(i, 2, QTableWidgetItem(row.get("status", "")))
                self.tasks_table.setItem(i, 3, QTableWidgetItem(row.get("due_at") or ""))

        def _refresh_diagnostics(self) -> None:
            payload = {
                "time": QDateTime.currentDateTime().toString(Qt.DateFormat.ISODate),
                "model": self.system.model.health(),
                "scheduler": self.system.scheduler.diagnostics(),
                "integration_registry": self.system.integration_registry,
            }
            self.diag_output.setPlainText(json.dumps(payload, indent=2))

        def _refresh_memory_trace(self) -> None:
            trace = {
                lane: self.system.lanes.read(lane)[-5:] for lane in MEMORY_LANES.keys()
            }
            self.memory_trace.setPlainText(json.dumps(trace, indent=2))

        def _on_create_project(self) -> None:
            name = self.project_name_input.text().strip()
            if not name:
                return
            project = self.system.projects.register_project(name)
            self.project_log.appendPlainText(f"Created project {project['project_id']} :: {name}")

        def _latest_project_id(self) -> Optional[str]:
            projects = self.system.lanes.read("project_registry")
            if not projects:
                return None
            return projects[-1].get("project_id")

        def _on_create_node(self) -> None:
            project_id = self._latest_project_id()
            if not project_id:
                QMessageBox.warning(self, "No project", "Create a project first.")
                return
            node_type, ok = QInputDialog.getItem(self, "Node Type", "Select node type", sorted(PROJECT_NODE_TYPES), 0, False)
            if not ok:
                return
            title, ok = QInputDialog.getText(self, "Node Title", "Node title")
            if not ok or not title.strip():
                return
            node = self.system.projects.add_node(project_id=project_id, node_type=node_type, title=title.strip())
            self.project_log.appendPlainText(f"Node added {node['node_id']} ({node_type})")

        def _on_ingest_artifact(self) -> None:
            project_id = self._latest_project_id()
            if not project_id:
                QMessageBox.warning(self, "No project", "Create a project first.")
                return
            files, _ = QFileDialog.getOpenFileNames(self, "Select artifacts")
            for fp in files:
                try:
                    rec = self.system.projects.ingest_artifact(project_id=project_id, src_file=Path(fp))
                    self.project_log.appendPlainText(f"Artifact ingested: {rec['source_filename']} -> {rec['artifact_id']}")
                except Exception as exc:
                    self.project_log.appendPlainText(f"Ingest failed for {fp}: {exc}")

        def _on_generate_kpi(self) -> None:
            project_id = self._latest_project_id()
            if not project_id:
                QMessageBox.warning(self, "No project", "Create a project first.")
                return
            snap = KPIEngine.generate(project_id, self.system.lanes)
            self.project_log.appendPlainText(f"KPI snapshot: {snap['snapshot_id']} status={snap['status']}")

        def _on_backup(self) -> None:
            target = self.system.backup(label="manual")
            QMessageBox.information(self, "Backup complete", str(target))

        def _on_restore(self) -> None:
            backup_dir = QFileDialog.getExistingDirectory(self, "Select backup folder", str(self.system.paths.backups))
            if not backup_dir:
                return
            self.system.restore(Path(backup_dir))
            QMessageBox.information(self, "Restore complete", backup_dir)

        def _on_soft_purge(self) -> None:
            confirm = QMessageBox.question(self, "Soft purge", "Clear transient lanes?")
            if confirm == QMessageBox.StandardButton.Yes:
                self.system.soft_purge()
                QMessageBox.information(self, "Done", "Soft purge complete.")

        def _on_full_purge(self) -> None:
            confirm = QMessageBox.question(self, "Full purge", "Delete entire deck folder? This is destructive.")
            if confirm == QMessageBox.StandardButton.Yes:
                self.system.full_purge()

        def _start_idle_timer(self) -> None:
            self.idle_timer = QTimer(self)
            self.idle_timer.timeout.connect(self._on_idle_tick)
            interval_ms = int(self.system.config.get("runtime", {}).get("idle_reflection_seconds", 600)) * 1000
            self.idle_timer.start(max(10_000, interval_ms))

        def _on_idle_tick(self) -> None:
            self.system.scheduler.mark_run("idle_contemplation")
            self.system.lanes.append("daily_reflections", {
                "reflection_type": "idle_contemplation",
                "note": "Idle contemplation trigger fired.",
            })
            self._refresh_diagnostics()
else:
    DeckMainWindow = None


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def run_runtime(deck_root: Path) -> int:
    paths = DeckPaths.from_root(deck_root)
    if not paths.config.exists():
        print(f"deck_config.json not found at {paths.config}")
        return 2

    system = SystemLayer(paths)

    if not PYQT_AVAILABLE:
        print("PyQt6 unavailable. Runtime loaded in headless mode.")
        print(json.dumps({
            "deck": system.config.get("deck", {}),
            "model_health": system.model.health(),
            "scheduler": system.scheduler.diagnostics(),
        }, indent=2))
        return 0

    app = QApplication(sys.argv)
    window = DeckMainWindow(system)
    window.show()
    return app.exec()


def resolve_runtime_root(this_file: Path, argv: Sequence[str]) -> Optional[Path]:
    if "--deck-root" in argv:
        idx = argv.index("--deck-root")
        if idx + 1 < len(argv):
            return Path(argv[idx + 1]).expanduser().resolve()
    if this_file.parent.name == "runtime":
        return this_file.parent.parent.resolve()
    return None


def has_valid_runtime_config(deck_root: Path) -> bool:
    cfg = read_json(deck_root / "deck_config.json", {})
    runtime_mode = cfg.get("runtime", {}).get("mode")
    return bool(cfg.get("deck")) and runtime_mode == "runtime"


def run_builder(seed_file: Path) -> int:
    try:
        deck_name, output_parent, model_backend, model_id = prompt_builder_inputs()
        ensure_dir(output_parent)
        deck_root = create_deck_instance(
            seed_file=seed_file,
            output_dir=output_parent,
            deck_name=deck_name,
            model_backend=model_backend,
            model_id=model_id,
        )
        print(f"\nDeck created at: {deck_root}")
        launcher = deck_root / f"{deck_launcher_basename(deck_name)}.py"
        print(f"Launcher: {launcher}")
        return 0
    except Exception as exc:
        print(f"Builder failed: {exc}")
        return 1


def main(argv: Sequence[str]) -> int:
    this_file = Path(__file__).resolve()
    explicit_create = "--create-deck" in argv
    explicit_runtime = "--runtime" in argv
    runtime_root = resolve_runtime_root(this_file, argv)

    if explicit_runtime and runtime_root is not None:
        return run_runtime(runtime_root)

    if runtime_root is not None and has_valid_runtime_config(runtime_root) and not explicit_create:
        return run_runtime(runtime_root)

    # Seed / explicit creation invocation stays in builder mode.
    return run_builder(this_file)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
