from __future__ import annotations

import json
import os
import tempfile
import csv
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


MODULE_MANIFEST = {
    "key": "meal_prepper",
    "display_name": "Meal Prepper",
    "version": "1.0.0",
    "deck_api_version": "1.0",
    "home_category": "Cooking",
    "entry_function": "register",
    "tab_definitions": [
        {
            "tab_id": "meal_prepper_main",
            "tab_name": "Meal Prep",
        }
    ],
}


DEFAULT_DATA = {
    "recipes": {},
    "batches": {},
    "consumption_log": [],
}

CATEGORY_OPTIONS = [
    "Slow Cooker",
    "Stove Top",
    "Oven",
    "Canning / Jarring",
    "Freezer Meals",
    "Other",
]
SHELF_LIFE_UNITS = ["Days", "Weeks", "Months"]
NOT_ENOUGH_HISTORY = "Not enough history yet"


class FocusWheelComboBox(QComboBox):
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if self.hasFocus():
            super().wheelEvent(event)
            return
        event.ignore()


class CollapsibleSection(QFrame):
    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.toggle = QToolButton(self)
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle.clicked.connect(self._set_expanded)
        layout.addWidget(self.toggle)
        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)

    def _set_expanded(self) -> None:
        expanded = self.toggle.isChecked()
        self.body.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)


class MealPrepperRuntime:
    def __init__(self, deck_api: dict[str, Any]):
        self.deck_api = deck_api
        self.log: Callable[[str], None] = (
            deck_api.get("log") if callable(deck_api.get("log")) else (lambda _msg: None)
        )
        self.cfg_path = deck_api.get("cfg_path") if callable(deck_api.get("cfg_path")) else None
        self.request_ai = (
            deck_api.get("request_ai_interpretation")
            if callable(deck_api.get("request_ai_interpretation"))
            else None
        )

        self.data_path = self._resolve_data_path()
        self.data = self._load_or_initialize_data()
        self.log("Meal Prepper module loaded")

    def _resolve_data_path(self) -> Path:
        if callable(self.cfg_path):
            try:
                path = self.cfg_path("meal_prepper_data.json")
                if path:
                    data_path = Path(path)
                    data_path.parent.mkdir(parents=True, exist_ok=True)
                    return data_path
            except Exception:
                pass
        fallback = Path(__file__).resolve().parent / "meal_prepper_data.json"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        return fallback

    def _safe_now_iso(self) -> str:
        return datetime.utcnow().isoformat()

    def _today_iso(self) -> str:
        return date.today().isoformat()

    def _validate_data_shape(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return dict(DEFAULT_DATA)
        recipes = payload.get("recipes")
        batches = payload.get("batches")
        consumption_log = payload.get("consumption_log")

        sanitized = {
            "recipes": recipes if isinstance(recipes, dict) else {},
            "batches": batches if isinstance(batches, dict) else {},
            "consumption_log": consumption_log if isinstance(consumption_log, list) else [],
        }
        return sanitized

    def _load_or_initialize_data(self) -> dict[str, Any]:
        if not self.data_path.exists():
            data = dict(DEFAULT_DATA)
            self._atomic_save(data)
            self.log("Meal Prepper data file loaded")
            return data
        try:
            payload = json.loads(self.data_path.read_text(encoding="utf-8"))
            data = self._validate_data_shape(payload)
            if payload != data:
                self._atomic_save(data)
            self.log("Meal Prepper data file loaded")
            return data
        except Exception as ex:
            self.log(f"Meal Prepper failed load: {ex}")
            raise RuntimeError("Failed to load meal prep data (corrupted JSON file).")

    def _atomic_save(self, payload: dict[str, Any]) -> None:
        directory = str(self.data_path.parent)
        fd, tmp_name = tempfile.mkstemp(prefix="meal_prepper_", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                json.dump(payload, tmp_file, ensure_ascii=False, indent=2)
            os.replace(tmp_name, self.data_path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except Exception:
                pass
            raise

    def save(self) -> None:
        self._atomic_save(self.data)
        self.log("Meal Prepper data saved")

    def list_recipes(self) -> list[dict[str, Any]]:
        values = list(self.data.get("recipes", {}).values())
        values.sort(key=lambda row: str(row.get("name", "")).lower())
        return values

    def recipe_batches(self, recipe_id: str) -> list[dict[str, Any]]:
        batches = [
            b for b in self.data.get("batches", {}).values() if str(b.get("recipe_id") or "") == recipe_id
        ]
        batches.sort(key=lambda row: str(row.get("batch_date") or ""), reverse=True)
        return batches

    def current_batch_for_recipe(self, recipe_id: str, preferred_batch_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        batches = self.recipe_batches(recipe_id)
        if not batches:
            return None
        chosen = None
        if preferred_batch_id:
            chosen = next((b for b in batches if str(b.get("id") or "") == preferred_batch_id), None)
        if chosen is None:
            active = [b for b in batches if int(b.get("jars_remaining") or 0) > 0 and not b.get("finished_at")]
            chosen = active[0] if active else batches[0]
        chosen["status"] = self.compute_status(chosen)
        return chosen

    def strongest_recipe_status(self, recipe_id: str) -> str:
        priorities = {"Out": 5, "Expired": 4, "Near Best By": 3, "Low Stock": 2, "Fresh": 1}
        batches = [b for b in self.recipe_batches(recipe_id) if not b.get("finished_at")]
        if not batches:
            return "Out"
        statuses = [self.compute_status(b) for b in batches]
        return max(statuses, key=lambda s: priorities.get(s, 0))

    def compute_best_by(self, batch_dt: date, value: int, unit: str) -> date:
        safe_value = max(0, int(value or 0))
        u = str(unit or "Days")
        if u == "Weeks":
            return batch_dt + timedelta(weeks=safe_value)
        if u == "Months":
            return batch_dt + timedelta(days=30 * safe_value)
        return batch_dt + timedelta(days=safe_value)

    def parse_iso_date(self, raw: Any) -> Optional[date]:
        if not raw:
            return None
        try:
            return date.fromisoformat(str(raw)[:10])
        except Exception:
            return None

    def compute_status(self, batch: dict[str, Any]) -> str:
        jars_remaining = int(batch.get("jars_remaining") or 0)
        if jars_remaining == 0:
            return "Out"
        best_by = self.parse_iso_date(batch.get("best_by_date"))
        today = date.today()
        if best_by is not None:
            if today > best_by:
                return "Expired"
            if 0 <= (best_by - today).days <= 14:
                return "Near Best By"
        if 0 < jars_remaining <= 2:
            return "Low Stock"
        return "Fresh"

    def create_or_update_recipe(self, recipe: dict[str, Any]) -> dict[str, Any]:
        now = self._safe_now_iso()
        recipes = self.data["recipes"]
        recipe_id = str(recipe.get("id") or "")
        existing = recipes.get(recipe_id) if recipe_id else None

        if existing is None:
            recipe_id = str(uuid4())
            entry = {
                "id": recipe_id,
                "name": str(recipe.get("name") or "").strip(),
                "category": str(recipe.get("category") or "Other").strip() or "Other",
                "ingredients": str(recipe.get("ingredients") or ""),
                "instructions": str(recipe.get("instructions") or ""),
                "notes": str(recipe.get("notes") or ""),
                "default_shelf_life": {
                    "value": int(recipe.get("default_shelf_life", {}).get("value") or 0),
                    "unit": str(recipe.get("default_shelf_life", {}).get("unit") or "Days"),
                },
                "expected_jars_per_batch": int(recipe.get("expected_jars_per_batch") or 0),
                "tags": str(recipe.get("tags") or ""),
                "created_at": now,
                "updated_at": now,
            }
            recipes[recipe_id] = entry
            self.save()
            self.log("Meal Prepper recipe created")
            return entry

        existing.update(
            {
                "name": str(recipe.get("name") or "").strip(),
                "category": str(recipe.get("category") or "Other").strip() or "Other",
                "ingredients": str(recipe.get("ingredients") or ""),
                "instructions": str(recipe.get("instructions") or ""),
                "notes": str(recipe.get("notes") or ""),
                "default_shelf_life": {
                    "value": int(recipe.get("default_shelf_life", {}).get("value") or 0),
                    "unit": str(recipe.get("default_shelf_life", {}).get("unit") or "Days"),
                },
                "expected_jars_per_batch": int(recipe.get("expected_jars_per_batch") or 0),
                "tags": str(recipe.get("tags") or ""),
                "updated_at": now,
            }
        )
        self.save()
        self.log("Meal Prepper recipe updated")
        return existing

    def delete_recipe(self, recipe_id: str) -> None:
        recipes = self.data["recipes"]
        if recipe_id in recipes:
            del recipes[recipe_id]
        batch_ids = [bid for bid, row in self.data["batches"].items() if str(row.get("recipe_id") or "") == recipe_id]
        for bid in batch_ids:
            del self.data["batches"][bid]
        self.data["consumption_log"] = [
            row for row in self.data["consumption_log"] if str(row.get("recipe_id") or "") != recipe_id
        ]
        self.save()
        self.log("Meal Prepper recipe deleted")

    def create_or_update_batch(self, batch: dict[str, Any]) -> dict[str, Any]:
        now = self._safe_now_iso()
        batches = self.data["batches"]
        batch_id = str(batch.get("id") or "")
        existing = batches.get(batch_id) if batch_id else None

        payload = {
            "recipe_id": str(batch.get("recipe_id") or ""),
            "batch_date": str(batch.get("batch_date") or self._today_iso()),
            "best_by_date": str(batch.get("best_by_date") or self._today_iso()),
            "total_jars": max(0, int(batch.get("total_jars") or 0)),
            "jars_remaining": max(0, int(batch.get("jars_remaining") or 0)),
            "shelf_life": {
                "value": max(0, int(batch.get("shelf_life", {}).get("value") or 0)),
                "unit": str(batch.get("shelf_life", {}).get("unit") or "Days"),
            },
            "notes": str(batch.get("notes") or ""),
            "finished_at": batch.get("finished_at"),
        }

        payload["status"] = self.compute_status(payload)
        if payload["jars_remaining"] == 0 and not payload.get("finished_at"):
            payload["finished_at"] = self._today_iso()

        if existing is None:
            batch_id = str(uuid4())
            entry = {
                "id": batch_id,
                **payload,
                "created_at": now,
                "updated_at": now,
            }
            batches[batch_id] = entry
            self.save()
            self.log("Meal Prepper batch created")
            return entry

        existing.update(payload)
        existing["updated_at"] = now
        self.save()
        if existing.get("jars_remaining") == 0:
            self.log("Meal Prepper batch finished")
        else:
            self.log("Meal Prepper batch updated")
        return existing

    def adjust_batch_remaining(self, batch_id: str, delta: int, log_consumption: bool = False) -> Optional[dict[str, Any]]:
        batch = self.data["batches"].get(batch_id)
        if not batch:
            return None
        old_val = int(batch.get("jars_remaining") or 0)
        new_val = max(0, old_val + int(delta))
        batch["jars_remaining"] = new_val
        batch["status"] = self.compute_status(batch)
        if new_val == 0 and not batch.get("finished_at"):
            batch["finished_at"] = self._today_iso()
        batch["updated_at"] = self._safe_now_iso()
        if log_consumption and delta < 0 and old_val > 0:
            consumed = min(old_val, abs(delta))
            self.data["consumption_log"].append(
                {
                    "id": str(uuid4()),
                    "recipe_id": str(batch.get("recipe_id") or ""),
                    "batch_id": str(batch.get("id") or ""),
                    "event": "ate_one",
                    "quantity": int(consumed),
                    "timestamp": self._safe_now_iso(),
                }
            )
            self.log("Meal Prepper consumption logged")
        self.save()
        if new_val == 0:
            self.log("Meal Prepper batch finished")
        else:
            self.log("Meal Prepper batch updated")
        return batch

    def statistics_for_recipe(self, recipe_id: str, preferred_batch_id: Optional[str] = None) -> dict[str, Any]:
        batches = self.recipe_batches(recipe_id)
        current = self.current_batch_for_recipe(recipe_id, preferred_batch_id=preferred_batch_id)

        stats: dict[str, Any] = {
            "last_made_date": batches[0].get("batch_date") if batches else None,
            "current_batch_best_by": current.get("best_by_date") if current else None,
            "current_total": current.get("total_jars") if current else None,
            "current_remaining": current.get("jars_remaining") if current else None,
            "current_status": self.compute_status(current) if current else None,
            "average_jars_per_batch": None,
            "average_batch_duration_days": None,
            "average_days_per_jar": None,
            "estimated_days_remaining": None,
            "average_days_between_batches": None,
            "projected_next_batch_needed_date": None,
        }

        if batches:
            totals = [max(0, int(b.get("total_jars") or 0)) for b in batches]
            if totals:
                stats["average_jars_per_batch"] = round(sum(totals) / len(totals), 2)

        durations: list[int] = []
        for row in batches:
            start = self.parse_iso_date(row.get("batch_date"))
            finish = self.parse_iso_date(row.get("finished_at"))
            if start and finish and finish >= start:
                durations.append((finish - start).days)
        if durations:
            stats["average_batch_duration_days"] = round(sum(durations) / len(durations), 2)

        recipe_logs = [
            row
            for row in self.data.get("consumption_log", [])
            if str(row.get("recipe_id") or "") == recipe_id and str(row.get("event") or "") == "ate_one"
        ]
        if recipe_logs:
            recipe_logs.sort(key=lambda row: str(row.get("timestamp") or ""))
            first_ts = self.parse_iso_date(recipe_logs[0].get("timestamp"))
            last_ts = self.parse_iso_date(recipe_logs[-1].get("timestamp"))
            qty = sum(max(0, int(row.get("quantity") or 0)) for row in recipe_logs)
            if qty > 0 and first_ts and last_ts:
                window_days = max(1, (last_ts - first_ts).days + 1)
                stats["average_days_per_jar"] = round(window_days / qty, 2)

        if current and stats["average_days_per_jar"] is not None:
            remaining = max(0, int(current.get("jars_remaining") or 0))
            days_per_jar = float(stats["average_days_per_jar"])
            stats["estimated_days_remaining"] = round(remaining * days_per_jar, 2)

        if len(batches) >= 2:
            starts = [self.parse_iso_date(b.get("batch_date")) for b in batches]
            starts = [s for s in starts if s is not None]
            starts.sort()
            intervals: list[int] = []
            for idx in range(1, len(starts)):
                intervals.append((starts[idx] - starts[idx - 1]).days)
            intervals = [x for x in intervals if x >= 0]
            if intervals:
                stats["average_days_between_batches"] = round(sum(intervals) / len(intervals), 2)

        if current and stats["estimated_days_remaining"] is not None:
            stats["projected_next_batch_needed_date"] = (
                date.today() + timedelta(days=int(round(float(stats["estimated_days_remaining"]))))
            ).isoformat()

        return stats

    def send_selection_to_ai(
        self,
        recipe: dict[str, Any],
        selected_batch: Optional[dict[str, Any]],
        active_batches: list[dict[str, Any]],
        stats: dict[str, Any],
    ) -> bool:
        payload = {
            "type": "MealPrepper Recipe",
            "selected_recipe": {
                "id": str(recipe.get("id") or ""),
                "name": str(recipe.get("name") or ""),
                "category": str(recipe.get("category") or ""),
                "ingredients": str(recipe.get("ingredients") or ""),
                "instructions": str(recipe.get("instructions") or ""),
                "notes": str(recipe.get("notes") or ""),
                "default_shelf_life": dict(recipe.get("default_shelf_life") or {"value": 0, "unit": "Days"}),
                "expected_jars_per_batch": int(recipe.get("expected_jars_per_batch") or 0),
                "tags": str(recipe.get("tags") or ""),
            },
            "selected_batch": {
                "id": str((selected_batch or {}).get("id") or ""),
                "batch_date": str((selected_batch or {}).get("batch_date") or ""),
                "best_by_date": str((selected_batch or {}).get("best_by_date") or ""),
                "total_jars": int((selected_batch or {}).get("total_jars") or 0),
                "jars_remaining": int((selected_batch or {}).get("jars_remaining") or 0),
                "status": str((selected_batch or {}).get("status") or ""),
                "notes": str((selected_batch or {}).get("notes") or ""),
            },
            "active_batches": [
                {
                    "id": str(b.get("id") or ""),
                    "batch_date": str(b.get("batch_date") or ""),
                    "best_by_date": str(b.get("best_by_date") or ""),
                    "total_jars": int(b.get("total_jars") or 0),
                    "jars_remaining": int(b.get("jars_remaining") or 0),
                    "status": self.compute_status(b),
                    "notes": str(b.get("notes") or ""),
                }
                for b in active_batches
            ],
            "stats": {
                "average_jars_per_batch": stats.get("average_jars_per_batch")
                if stats.get("average_jars_per_batch") is not None
                else NOT_ENOUGH_HISTORY,
                "average_batch_duration_days": stats.get("average_batch_duration_days")
                if stats.get("average_batch_duration_days") is not None
                else NOT_ENOUGH_HISTORY,
                "average_days_per_jar": stats.get("average_days_per_jar")
                if stats.get("average_days_per_jar") is not None
                else NOT_ENOUGH_HISTORY,
                "estimated_days_remaining": stats.get("estimated_days_remaining")
                if stats.get("estimated_days_remaining") is not None
                else NOT_ENOUGH_HISTORY,
                "projected_next_batch_needed_date": stats.get("projected_next_batch_needed_date")
                if stats.get("projected_next_batch_needed_date") is not None
                else NOT_ENOUGH_HISTORY,
            },
        }

        handlers: list[Callable[..., Any]] = []
        for key in ["send_to_session", "request_ai_interpretation", "module_send_to_session"]:
            fn = self.deck_api.get(key)
            if callable(fn):
                handlers.append(fn)
        if not handlers:
            for key, fn in self.deck_api.items():
                if callable(fn) and ("session" in str(key).lower() or "ai" in str(key).lower()):
                    handlers.append(fn)

        for handler in handlers:
            try:
                result = handler("meal_prepper", payload)
                if result is False:
                    continue
                self.log("Meal Prepper Send To AI sent")
                return True
            except TypeError:
                try:
                    result = handler(payload)
                    if result is False:
                        continue
                    self.log("Meal Prepper Send To AI sent")
                    return True
                except Exception:
                    continue
            except Exception:
                continue

        self.log("Send To AI blocked: no AI handoff available")
        return False


class MealPrepperWidget(QWidget):
    def __init__(self, runtime: MealPrepperRuntime):
        super().__init__()
        self.runtime = runtime
        self.current_recipe_id: Optional[str] = None
        self.current_batch_id: Optional[str] = None

        self._build_ui()
        self.refresh_recipe_list()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.setStyleSheet(
            """
            QWidget { font-size: 10pt; letter-spacing: 0px; }
            QLabel { font-size: 10pt; }
            QLineEdit, QComboBox, QSpinBox, QDateEdit { min-height: 32px; padding: 4px 8px; font-size: 11pt; }
            QPushButton { min-height: 40px; padding: 8px 12px; letter-spacing: 0px; font-size: 10pt; }
            QPlainTextEdit { min-height: 90px; font-size: 11pt; padding: 6px; }
            QListWidget { font-size: 10pt; min-height: 160px; }
            """
        )

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget(scroll)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        content_layout.addWidget(self._build_top_section(content))
        content_layout.addWidget(self._build_recipe_management_section(content))
        content_layout.addWidget(self._build_recipe_section(content))
        content_layout.addWidget(self._build_batch_section(content))
        content_layout.addWidget(self._build_batch_inventory_section(content))
        content_layout.addWidget(self._build_batch_actions_section(content))
        content_layout.addWidget(self._build_send_to_section(content))
        content_layout.addWidget(self._build_stats_section(content))
        content_layout.addStretch(1)

        scroll.setWidget(content)
        root.addWidget(scroll)

    def _configure_form_layout(self, form: QFormLayout) -> None:
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

    def _add_button_rows(self, parent_layout: QVBoxLayout, parent: QWidget, buttons: list[QPushButton]) -> None:
        for idx in range(0, len(buttons), 2):
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(buttons[idx], 1)
            if idx + 1 < len(buttons):
                row.addWidget(buttons[idx + 1], 1)
            parent_layout.addLayout(row)

    def _build_top_section(self, parent: QWidget) -> QWidget:
        panel = CollapsibleSection("1. Search + Recipe Selector", parent)
        layout = panel.body_layout

        self.search_edit = QLineEdit(panel)
        self.search_edit.setPlaceholderText("Search recipes...")
        self.search_edit.textChanged.connect(self.refresh_recipe_list)
        layout.addWidget(self.search_edit)

        self.filter_combo = QComboBox(panel)
        self.filter_combo.addItem("All Categories")
        self.filter_combo.addItems(CATEGORY_OPTIONS)
        self.filter_combo.currentTextChanged.connect(self.refresh_recipe_list)
        layout.addWidget(self.filter_combo)

        self.recipe_list = QListWidget(panel)
        self.recipe_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.recipe_list.itemSelectionChanged.connect(self._on_recipe_selected)
        layout.addWidget(self.recipe_list, 1)
        return panel

    def _build_recipe_management_section(self, parent: QWidget) -> QWidget:
        box = CollapsibleSection("2. Recipe Management", parent)
        layout = box.body_layout

        self.btn_new_recipe = QPushButton("New Recipe", box)
        self.btn_save_recipe = QPushButton("Save Recipe", box)
        self.btn_delete_recipe = QPushButton("Delete Recipe", box)
        self.btn_clear_recipe = QPushButton("Clear Form", box)

        self.btn_new_recipe.clicked.connect(self._new_recipe)
        self.btn_save_recipe.clicked.connect(self._save_recipe)
        self.btn_delete_recipe.clicked.connect(self._delete_recipe)
        self.btn_clear_recipe.clicked.connect(self._clear_recipe_form)

        self._add_button_rows(
            layout,
            box,
            [self.btn_new_recipe, self.btn_save_recipe, self.btn_delete_recipe, self.btn_clear_recipe],
        )
        return box

    def _build_recipe_section(self, parent: QWidget) -> QWidget:
        box = CollapsibleSection("3. Recipe Details", parent)
        layout = box.body_layout

        form = QFormLayout()
        self._configure_form_layout(form)

        self.name_edit = QLineEdit(box)
        self.category_edit = FocusWheelComboBox(box)
        self.category_edit.setEditable(True)
        self.category_edit.addItems(CATEGORY_OPTIONS)
        self.ingredients_edit = QPlainTextEdit(box)
        self.ingredients_edit.setMinimumHeight(110)
        self.instructions_edit = QPlainTextEdit(box)
        self.instructions_edit.setMinimumHeight(130)
        self.notes_edit = QPlainTextEdit(box)
        self.notes_edit.setMinimumHeight(90)
        self.shelf_life_value = QSpinBox(box)
        self.shelf_life_value.setRange(0, 9999)
        self.shelf_life_unit = QComboBox(box)
        self.shelf_life_unit.addItems(SHELF_LIFE_UNITS)
        self.expected_jars = QSpinBox(box)
        self.expected_jars.setRange(0, 9999)
        self.tags_edit = QLineEdit(box)

        form.addRow("Name", self.name_edit)
        form.addRow("Category", self.category_edit)
        form.addRow("Ingredients", self.ingredients_edit)
        form.addRow("Instructions", self.instructions_edit)
        form.addRow("Notes", self.notes_edit)

        shelf_row = QWidget(box)
        shelf_layout = QHBoxLayout(shelf_row)
        shelf_layout.setContentsMargins(0, 0, 0, 0)
        shelf_layout.setSpacing(8)
        shelf_layout.addWidget(self.shelf_life_value)
        shelf_layout.addWidget(self.shelf_life_unit)
        form.addRow("Default shelf life", shelf_row)

        form.addRow("Expected jars/servings per batch", self.expected_jars)
        form.addRow("Tags", self.tags_edit)
        layout.addLayout(form)
        return box

    def _build_stats_section(self, parent: QWidget) -> QWidget:
        box = CollapsibleSection("8. Current Batch + Statistics", parent)
        layout = box.body_layout

        self.stats_form = QFormLayout()
        self._configure_form_layout(self.stats_form)
        self.stats_labels: dict[str, QLabel] = {}

        rows = [
            ("last_made_date", "Last made date"),
            ("current_batch_best_by", "Current batch best-by date"),
            ("current_total", "Total jars/servings in current batch"),
            ("current_remaining", "Jars/servings remaining"),
            ("current_status", "Current status"),
            ("average_jars_per_batch", "Average jars/servings per batch"),
            ("average_batch_duration_days", "Average batch duration for this user"),
            ("average_days_per_jar", "Average consumption rate"),
            ("estimated_days_remaining", "Estimated days remaining"),
            ("average_days_between_batches", "How often user makes this recipe"),
            ("projected_next_batch_needed_date", "Projected next batch needed date"),
        ]
        for key, label in rows:
            value = QLabel(NOT_ENOUGH_HISTORY, box)
            value.setMinimumHeight(30)
            value.setWordWrap(True)
            self.stats_labels[key] = value
            self.stats_form.addRow(label, value)

        layout.addLayout(self.stats_form)
        return box

    def _build_batch_section(self, parent: QWidget) -> QWidget:
        box = CollapsibleSection("4. Batch Tracking", parent)
        layout = box.body_layout

        form = QFormLayout()
        self._configure_form_layout(form)

        self.batch_date = QDateEdit(box)
        self.batch_date.setCalendarPopup(True)
        self.batch_date.setDate(date.today())

        self.total_jars = QSpinBox(box)
        self.total_jars.setRange(0, 9999)
        self.remaining_jars = QSpinBox(box)
        self.remaining_jars.setRange(0, 9999)

        self.batch_shelf_value = QSpinBox(box)
        self.batch_shelf_value.setRange(0, 9999)
        self.batch_shelf_unit = QComboBox(box)
        self.batch_shelf_unit.addItems(SHELF_LIFE_UNITS)

        self.best_by_date = QDateEdit(box)
        self.best_by_date.setCalendarPopup(True)
        self.best_by_date.setDate(date.today())

        self.batch_notes = QPlainTextEdit(box)
        self.batch_notes.setMinimumHeight(100)

        self.batch_date.dateChanged.connect(self._recalculate_best_by)
        self.batch_shelf_value.valueChanged.connect(self._recalculate_best_by)
        self.batch_shelf_unit.currentTextChanged.connect(self._recalculate_best_by)

        form.addRow("Batch date", self.batch_date)
        form.addRow("Total jars/servings made", self.total_jars)
        form.addRow("Jars/servings remaining", self.remaining_jars)

        shelf_row = QWidget(box)
        shelf_layout = QHBoxLayout(shelf_row)
        shelf_layout.setContentsMargins(0, 0, 0, 0)
        shelf_layout.setSpacing(8)
        shelf_layout.addWidget(self.batch_shelf_value)
        shelf_layout.addWidget(self.batch_shelf_unit)
        form.addRow("Shelf life", shelf_row)

        form.addRow("Best-by date", self.best_by_date)
        form.addRow("Batch notes", self.batch_notes)
        layout.addLayout(form)
        return box

    def _build_batch_inventory_section(self, parent: QWidget) -> QWidget:
        box = CollapsibleSection("5. Batch Inventory / Made Batches", parent)
        layout = box.body_layout
        self.batch_inventory_list = QListWidget(box)
        self.batch_inventory_list.itemSelectionChanged.connect(self._on_batch_inventory_selected)
        layout.addWidget(self.batch_inventory_list)
        return box

    def _build_batch_actions_section(self, parent: QWidget) -> QWidget:
        box = CollapsibleSection("6. Batch Actions + Export", parent)
        layout = box.body_layout

        self.btn_new_batch = QPushButton("New Batch", box)
        self.btn_save_batch = QPushButton("Save Batch", box)
        self.btn_ate_one = QPushButton("Ate One", box)
        self.btn_remove_one = QPushButton("Remove One", box)
        self.btn_finish_batch = QPushButton("Mark Finished", box)
        self.btn_delete_batch = QPushButton("Delete Batch", box)

        self.btn_new_batch.clicked.connect(self._new_batch)
        self.btn_save_batch.clicked.connect(self._save_batch)
        self.btn_ate_one.clicked.connect(self._ate_one)
        self.btn_remove_one.clicked.connect(self._remove_one)
        self.btn_finish_batch.clicked.connect(self._mark_batch_finished)
        self.btn_delete_batch.clicked.connect(self._delete_batch)

        self._add_button_rows(
            layout,
            box,
            [self.btn_new_batch, self.btn_save_batch, self.btn_ate_one, self.btn_remove_one, self.btn_finish_batch, self.btn_delete_batch],
        )
        self.export_format = QComboBox(box)
        self.export_format.addItems(["TXT", "CSV", "Excel .xlsx", "PDF"])
        self.btn_export_one = QPushButton("Export This Recipe", box)
        self.btn_export_selected = QPushButton("Export Selected Recipes", box)
        self.btn_export_all = QPushButton("Export All Recipes", box)
        self.btn_export_one.clicked.connect(self._export_this_recipe)
        self.btn_export_selected.clicked.connect(self._export_selected_recipes)
        self.btn_export_all.clicked.connect(self._export_all_recipes)
        layout.addWidget(self.export_format)
        self._add_button_rows(layout, box, [self.btn_export_one, self.btn_export_selected, self.btn_export_all])
        return box

    def _build_send_to_section(self, parent: QWidget) -> QWidget:
        box = CollapsibleSection("7. Send To", parent)
        layout = box.body_layout

        self.btn_send_ai = QPushButton("Send To AI", box)
        self.btn_send_shop = QPushButton("Send To Shopping List", box)
        self.btn_send_recipe_book = QPushButton("Send To Recipe Book", box)

        self.btn_send_ai.clicked.connect(self._send_to_ai)
        self.btn_send_shop.setEnabled(False)
        self.btn_send_recipe_book.setEnabled(False)
        self.btn_send_shop.setToolTip("Coming Soon — Shopping List module not installed.")
        self.btn_send_recipe_book.setToolTip("Coming Soon — Recipe Book module not installed.")

        self._add_button_rows(layout, box, [self.btn_send_ai, self.btn_send_shop, self.btn_send_recipe_book])
        return box

    def _msg_error(self, text: str) -> None:
        QMessageBox.critical(self, "Meal Prepper", text)

    def _msg_warn(self, text: str) -> None:
        QMessageBox.warning(self, "Meal Prepper", text)

    def _safe_int(self, spin: QSpinBox) -> int:
        return max(0, int(spin.value()))

    def refresh_recipe_list(self) -> None:
        selected_before = set()
        for item in self.recipe_list.selectedItems():
            selected_before.add(str(item.data(Qt.ItemDataRole.UserRole) or ""))
        self.recipe_list.clear()

        search = self.search_edit.text().strip().lower() if hasattr(self, "search_edit") else ""
        category = self.filter_combo.currentText() if hasattr(self, "filter_combo") else "All Categories"

        for recipe in self.runtime.list_recipes():
            name = str(recipe.get("name") or "")
            cat = str(recipe.get("category") or "")
            if search and search not in name.lower() and search not in str(recipe.get("tags") or "").lower():
                continue
            if category != "All Categories" and cat != category:
                continue
            status = self.runtime.strongest_recipe_status(str(recipe.get("id") or ""))
            item = QListWidgetItem(f"{name} — {status}")
            item.setData(Qt.ItemDataRole.UserRole, str(recipe.get("id") or ""))
            self.recipe_list.addItem(item)

        if selected_before:
            for idx in range(self.recipe_list.count()):
                item = self.recipe_list.item(idx)
                if str(item.data(Qt.ItemDataRole.UserRole)) in selected_before:
                    item.setSelected(True)

    def _on_recipe_selected(self) -> None:
        items = self.recipe_list.selectedItems()
        if not items:
            self.current_recipe_id = None
            self.current_batch_id = None
            self._clear_recipe_form()
            self._new_batch(clear_only=True)
            self._refresh_batch_inventory()
            self._populate_stats(None)
            return

        recipe_id = str(items[0].data(Qt.ItemDataRole.UserRole) or "")
        recipe = self.runtime.data["recipes"].get(recipe_id)
        if not recipe:
            return
        self.current_recipe_id = recipe_id
        self._load_recipe_into_form(recipe)

        current_batch = self.runtime.current_batch_for_recipe(recipe_id)
        if current_batch:
            self.current_batch_id = str(current_batch.get("id") or "")
            self._load_batch_into_form(current_batch)
        else:
            self.current_batch_id = None
            self._new_batch(clear_only=True)
        self._refresh_batch_inventory()
        self._populate_stats(recipe_id)

    def _refresh_batch_inventory(self) -> None:
        self.batch_inventory_list.clear()
        if not self.current_recipe_id:
            return
        for row in self.runtime.recipe_batches(self.current_recipe_id):
            status = self.runtime.compute_status(row)
            line = (
                f"{row.get('batch_date', '')} | best-by {row.get('best_by_date', '')} | "
                f"total {int(row.get('total_jars') or 0)} | remaining {int(row.get('jars_remaining') or 0)} | {status}"
            )
            item = QListWidgetItem(line)
            item.setData(Qt.ItemDataRole.UserRole, str(row.get("id") or ""))
            self.batch_inventory_list.addItem(item)
            if str(row.get("id") or "") == self.current_batch_id:
                item.setSelected(True)

    def _on_batch_inventory_selected(self) -> None:
        items = self.batch_inventory_list.selectedItems()
        if not items:
            return
        batch_id = str(items[0].data(Qt.ItemDataRole.UserRole) or "")
        batch = self.runtime.data["batches"].get(batch_id)
        if not batch:
            return
        self.current_batch_id = batch_id
        self._load_batch_into_form(batch)
        self._populate_stats(self.current_recipe_id)

    def _load_recipe_into_form(self, recipe: dict[str, Any]) -> None:
        self.name_edit.setText(str(recipe.get("name") or ""))
        self.category_edit.setCurrentText(str(recipe.get("category") or "Other"))
        self.ingredients_edit.setPlainText(str(recipe.get("ingredients") or ""))
        self.instructions_edit.setPlainText(str(recipe.get("instructions") or ""))
        self.notes_edit.setPlainText(str(recipe.get("notes") or ""))
        shelf = recipe.get("default_shelf_life") or {}
        self.shelf_life_value.setValue(max(0, int(shelf.get("value") or 0)))
        self.shelf_life_unit.setCurrentText(str(shelf.get("unit") or "Days"))
        self.expected_jars.setValue(max(0, int(recipe.get("expected_jars_per_batch") or 0)))
        self.tags_edit.setText(str(recipe.get("tags") or ""))

    def _clear_recipe_form(self) -> None:
        self.name_edit.clear()
        self.category_edit.setCurrentText("Other")
        self.ingredients_edit.clear()
        self.instructions_edit.clear()
        self.notes_edit.clear()
        self.shelf_life_value.setValue(0)
        self.shelf_life_unit.setCurrentText("Days")
        self.expected_jars.setValue(0)
        self.tags_edit.clear()

    def _new_recipe(self) -> None:
        self.current_recipe_id = None
        self._clear_recipe_form()

    def _save_recipe(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self._msg_warn("Please provide a recipe name before saving recipe without name.")
            return

        payload = {
            "id": self.current_recipe_id,
            "name": name,
            "category": self.category_edit.currentText().strip() or "Other",
            "ingredients": self.ingredients_edit.toPlainText(),
            "instructions": self.instructions_edit.toPlainText(),
            "notes": self.notes_edit.toPlainText(),
            "default_shelf_life": {
                "value": self._safe_int(self.shelf_life_value),
                "unit": self.shelf_life_unit.currentText(),
            },
            "expected_jars_per_batch": self._safe_int(self.expected_jars),
            "tags": self.tags_edit.text().strip(),
        }
        try:
            saved = self.runtime.create_or_update_recipe(payload)
            self.current_recipe_id = str(saved.get("id") or "")
            self.refresh_recipe_list()
            self._populate_stats(self.current_recipe_id)
        except Exception:
            self._msg_error("Failed save")

    def _delete_recipe(self) -> None:
        if not self.current_recipe_id:
            return
        try:
            self.runtime.delete_recipe(self.current_recipe_id)
            self.current_recipe_id = None
            self.current_batch_id = None
            self._clear_recipe_form()
            self._new_batch(clear_only=True)
            self._refresh_batch_inventory()
            self._populate_stats(None)
            self.refresh_recipe_list()
        except Exception:
            self._msg_error("Failed save")

    def _recalculate_best_by(self) -> None:
        qd = self.batch_date.date().toPython()
        best = self.runtime.compute_best_by(qd, self._safe_int(self.batch_shelf_value), self.batch_shelf_unit.currentText())
        self.best_by_date.setDate(best)

    def _new_batch(self, clear_only: bool = False) -> None:
        self.current_batch_id = None
        today = date.today()
        self.batch_date.setDate(today)
        expected = 0
        shelf_val = self._safe_int(self.shelf_life_value)
        shelf_unit = self.shelf_life_unit.currentText()
        if self.current_recipe_id:
            recipe = self.runtime.data["recipes"].get(self.current_recipe_id) or {}
            expected = max(0, int(recipe.get("expected_jars_per_batch") or 0))
            shelf = recipe.get("default_shelf_life") or {}
            shelf_val = max(0, int(shelf.get("value") or 0))
            shelf_unit = str(shelf.get("unit") or "Days")
        self.total_jars.setValue(expected)
        self.remaining_jars.setValue(expected)
        self.batch_shelf_value.setValue(shelf_val)
        self.batch_shelf_unit.setCurrentText(shelf_unit)
        self.batch_notes.clear()
        self._recalculate_best_by()
        self._refresh_batch_inventory()
        if not clear_only and not self.current_recipe_id:
            self._msg_warn("Please select a recipe first; creating batch without selected recipe is blocked.")

    def _load_batch_into_form(self, batch: dict[str, Any]) -> None:
        bdt = self.runtime.parse_iso_date(batch.get("batch_date")) or date.today()
        bby = self.runtime.parse_iso_date(batch.get("best_by_date")) or date.today()
        self.batch_date.setDate(bdt)
        self.best_by_date.setDate(bby)
        self.total_jars.setValue(max(0, int(batch.get("total_jars") or 0)))
        self.remaining_jars.setValue(max(0, int(batch.get("jars_remaining") or 0)))
        shelf = batch.get("shelf_life") or {}
        self.batch_shelf_value.setValue(max(0, int(shelf.get("value") or 0)))
        self.batch_shelf_unit.setCurrentText(str(shelf.get("unit") or "Days"))
        self.batch_notes.setPlainText(str(batch.get("notes") or ""))

    def _save_batch(self) -> None:
        if not self.current_recipe_id:
            self._msg_warn("Please select a recipe first; creating batch without selected recipe is blocked.")
            return
        total = self._safe_int(self.total_jars)
        remaining = self._safe_int(self.remaining_jars)
        if remaining > total:
            self._msg_warn("Invalid jar count")
            return

        payload = {
            "id": self.current_batch_id,
            "recipe_id": self.current_recipe_id,
            "batch_date": self.batch_date.date().toPython().isoformat(),
            "best_by_date": self.best_by_date.date().toPython().isoformat(),
            "total_jars": total,
            "jars_remaining": remaining,
            "shelf_life": {
                "value": self._safe_int(self.batch_shelf_value),
                "unit": self.batch_shelf_unit.currentText(),
            },
            "notes": self.batch_notes.toPlainText(),
        }
        try:
            saved = self.runtime.create_or_update_batch(payload)
            self.current_batch_id = str(saved.get("id") or "")
            self._load_batch_into_form(saved)
            self.refresh_recipe_list()
            self._refresh_batch_inventory()
            self._populate_stats(self.current_recipe_id)
        except Exception:
            self._msg_error("Failed save")

    def _adjust_current_batch(self, delta: int, log_consumption: bool = False) -> None:
        if not self.current_batch_id:
            self._msg_warn("No batch selected.")
            return
        try:
            updated = self.runtime.adjust_batch_remaining(self.current_batch_id, delta=delta, log_consumption=log_consumption)
            if not updated:
                self._msg_warn("No batch selected.")
                return
            self._load_batch_into_form(updated)
            self.refresh_recipe_list()
            self._refresh_batch_inventory()
            self._populate_stats(self.current_recipe_id)
        except Exception:
            self._msg_error("Failed save")

    def _ate_one(self) -> None:
        if self.remaining_jars.value() <= 0:
            self._msg_warn("Invalid jar count")
            return
        self._adjust_current_batch(delta=-1, log_consumption=True)

    def _remove_one(self) -> None:
        if self.remaining_jars.value() <= 0:
            self._msg_warn("Invalid jar count")
            return
        self._adjust_current_batch(delta=-1, log_consumption=False)

    def _mark_batch_finished(self) -> None:
        if not self.current_batch_id:
            self._msg_warn("No batch selected.")
            return
        try:
            payload = {
                "id": self.current_batch_id,
                "recipe_id": self.current_recipe_id,
                "batch_date": self.batch_date.date().toPython().isoformat(),
                "best_by_date": self.best_by_date.date().toPython().isoformat(),
                "total_jars": self._safe_int(self.total_jars),
                "jars_remaining": 0,
                "shelf_life": {
                    "value": self._safe_int(self.batch_shelf_value),
                    "unit": self.batch_shelf_unit.currentText(),
                },
                "notes": self.batch_notes.toPlainText(),
                "finished_at": date.today().isoformat(),
            }
            saved = self.runtime.create_or_update_batch(payload)
            self.current_batch_id = str(saved.get("id") or "")
            self._load_batch_into_form(saved)
            self.refresh_recipe_list()
            self._refresh_batch_inventory()
            self._populate_stats(self.current_recipe_id)
        except Exception:
            self._msg_error("Failed save")

    def _delete_batch(self) -> None:
        if not self.current_batch_id:
            self._msg_warn("No batch selected.")
            return
        if self.current_batch_id in self.runtime.data["batches"]:
            del self.runtime.data["batches"][self.current_batch_id]
            self.runtime.save()
        self.current_batch_id = None
        self._new_batch(clear_only=True)
        self.refresh_recipe_list()
        self._refresh_batch_inventory()
        self._populate_stats(self.current_recipe_id)

    def _value_or_history(self, value: Any) -> str:
        if value is None or value == "":
            return NOT_ENOUGH_HISTORY
        return str(value)

    def _populate_stats(self, recipe_id: Optional[str]) -> None:
        if not recipe_id:
            for lbl in self.stats_labels.values():
                lbl.setText(NOT_ENOUGH_HISTORY)
            return
        stats = self.runtime.statistics_for_recipe(recipe_id, preferred_batch_id=self.current_batch_id)
        for key, lbl in self.stats_labels.items():
            lbl.setText(self._value_or_history(stats.get(key)))

    def _send_to_ai(self) -> None:
        if not self.current_recipe_id:
            self._msg_warn("Please select a recipe first.")
            return
        recipe = self.runtime.data["recipes"].get(self.current_recipe_id)
        if not recipe:
            self._msg_warn("Please select a recipe first.")
            return
        batch = self.runtime.current_batch_for_recipe(self.current_recipe_id, preferred_batch_id=self.current_batch_id)
        active_batches = [
            b for b in self.runtime.recipe_batches(self.current_recipe_id) if int(b.get("jars_remaining") or 0) > 0
        ]
        stats = self.runtime.statistics_for_recipe(self.current_recipe_id, preferred_batch_id=self.current_batch_id)
        ok = self.runtime.send_selection_to_ai(recipe, batch, active_batches, stats)
        if not ok:
            self._msg_warn("Send To AI is unavailable right now.")

    def _recipes_for_export(self, mode: str) -> list[dict[str, Any]]:
        recipes = self.runtime.list_recipes()
        if mode == "one":
            if not self.current_recipe_id:
                return []
            row = self.runtime.data["recipes"].get(self.current_recipe_id)
            return [row] if row else []
        if mode == "selected":
            ids = [str(i.data(Qt.ItemDataRole.UserRole) or "") for i in self.recipe_list.selectedItems()]
            return [self.runtime.data["recipes"][rid] for rid in ids if rid in self.runtime.data["recipes"]]
        return recipes

    def _format_export_rows(self, recipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for recipe in recipes:
            recipe_id = str(recipe.get("id") or "")
            batches = self.runtime.recipe_batches(recipe_id)
            stats = self.runtime.statistics_for_recipe(recipe_id)
            rows.append(
                {
                    "name": recipe.get("name", ""),
                    "category": recipe.get("category", ""),
                    "ingredients": recipe.get("ingredients", ""),
                    "instructions": recipe.get("instructions", ""),
                    "notes": recipe.get("notes", ""),
                    "batches": json.dumps(batches),
                    "consumption_stats": json.dumps(stats),
                }
            )
        return rows

    def _perform_export(self, mode: str) -> None:
        recipes = self._recipes_for_export(mode)
        if not recipes:
            self._msg_warn("No recipes selected for export.")
            return
        export_type = self.export_format.currentText()
        rows = self._format_export_rows(recipes)
        if export_type in {"Excel .xlsx", "PDF"}:
            self._msg_warn("Export format unavailable: missing dependency")
            return
        ext = "txt" if export_type == "TXT" else "csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export Meal Prep Data", "", f"*.{ext}")
        if not path:
            return
        try:
            if export_type == "TXT":
                with open(path, "w", encoding="utf-8") as f:
                    for row in rows:
                        f.write(f"Recipe: {row['name']}\nCategory: {row['category']}\n")
                        f.write(f"Ingredients:\n{row['ingredients']}\nInstructions:\n{row['instructions']}\n")
                        f.write(f"Notes:\n{row['notes']}\nBatches:\n{row['batches']}\n")
                        f.write(f"Consumption Stats:\n{row['consumption_stats']}\n\n")
            else:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(
                        f,
                        fieldnames=["name", "category", "ingredients", "instructions", "notes", "batches", "consumption_stats"],
                    )
                    writer.writeheader()
                    writer.writerows(rows)
        except Exception:
            self._msg_error("Failed export")

    def _export_this_recipe(self) -> None:
        self._perform_export("one")

    def _export_selected_recipes(self) -> None:
        self._perform_export("selected")

    def _export_all_recipes(self) -> None:
        self._perform_export("all")


class MealPrepperModule:
    def __init__(self, deck_api: dict[str, Any]):
        self.runtime = MealPrepperRuntime(deck_api)

    def build_main_widget(self) -> QWidget:
        return MealPrepperWidget(self.runtime)

    def build_workspace(self) -> QWidget:
        return self.build_main_widget()


def register(deck_api: dict[str, Any]) -> dict[str, Any]:
    deck_api_version = str(deck_api.get("deck_api_version") or "")
    if deck_api_version != "1.0":
        raise RuntimeError(f"Unsupported deck API version: {deck_api_version}")

    module = MealPrepperModule(deck_api)

    def _build_tab() -> QWidget:
        return module.build_main_widget()

    return {
        "deck_api_version": "1.0",
        "module_key": "meal_prepper",
        "display_name": "Meal Prepper",
        "home_category": "Cooking",
        "tabs": [
            {
                "tab_id": "meal_prepper_main",
                "tab_name": "Meal Prep",
                "get_content": _build_tab,
            }
        ],
        "supports_workspaces": True,
        "workspaces": [
            {
                "slot": 1,
                "id": "meal_prep_workspace",
                "label": "Meal Prep",
                "build": module.build_workspace,
            }
        ],
    }
