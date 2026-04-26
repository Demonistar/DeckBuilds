from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


MODULE_MANIFEST = {
    "key": "meal_prepper",
    "display_name": "Meal Prepper",
    "version": "1.0.0",
    "deck_api_version": "1.0",
    "home_category": "Home / Food / Meal Prep",
    "entry_function": "register",
    "description": "Track jarred and pre-cooked meal recipes, batches, stock, and consumption stats.",
    "tab_definitions": [{"tab_id": "meal_prepper_main", "tab_name": "Meal Prep"}],
}

UTC = timezone.utc
CATEGORIES = ["Slow Cooker", "Stove Top", "Oven", "Canning / Jarring", "Freezer Meals", "Other"]
SHELF_LIFE_UNITS = ["days", "weeks", "months"]
STATUS_PRIORITY = {"out": 5, "expired": 4, "near_best_by": 3, "low_stock": 2, "fresh": 1}
STATUS_LABELS = {
    "fresh": "Fresh",
    "near_best_by": "Near Best By",
    "expired": "Expired",
    "low_stock": "Low Stock",
    "out": "Out",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _today() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_dt(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _to_date_str(dt: datetime) -> str:
    return dt.date().isoformat()


def _add_shelf_life(base_date: datetime, value: int, unit: str) -> datetime:
    if unit == "days":
        return base_date + timedelta(days=value)
    if unit == "weeks":
        return base_date + timedelta(weeks=value)
    if unit == "months":
        return base_date + timedelta(days=value * 30)
    return base_date


class MealPrepperStore:
    def __init__(self, deck_api: dict[str, Any]):
        self._deck_api = deck_api
        self._log: Callable[[str], None] = deck_api.get("log") if callable(deck_api.get("log")) else (lambda _m: None)
        self._cfg_path = deck_api.get("cfg_path") if callable(deck_api.get("cfg_path")) else None
        self.data_path = self._resolve_data_path()
        self.data: dict[str, Any] = {"recipes": {}, "batches": {}, "consumption_log": []}
        self.load()

    def _resolve_data_path(self) -> Path:
        if callable(self._cfg_path):
            try:
                p = self._cfg_path("meal_prepper_data.json")
                if p:
                    path = Path(p)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    return path
            except Exception:
                pass
        return Path(__file__).with_name("meal_prepper_data.json")

    def _seed_data(self) -> dict[str, Any]:
        now = _now_iso()
        rid = _gen_id("recipe")
        recipes: dict[str, Any] = {
            rid: {
                "id": rid,
                "name": "Chicken and Rice Soup",
                "category": "Slow Cooker",
                "ingredients": [
                    "2 cans chunked chicken",
                    "1 cup long grain rice",
                    "1 can sliced carrots",
                    "1 can mushrooms",
                    "2–3 tbsp dehydrated celery",
                    "4 cups chicken broth",
                    "1/2 tsp salt",
                    "1/2 tsp pepper",
                    "1/2 tsp parsley",
                    "pinch thyme",
                    "optional 1 tbsp butter",
                    "optional 1 can cream of chicken",
                ],
                "instructions": "Combine ingredients, simmer until rice is tender, and jar per safe canning process.",
                "notes": "Great freezer fallback meal.",
                "default_shelf_life": {"value": 3, "unit": "months"},
                "expected_jars_per_batch": 8,
                "tags": ["soup", "chicken", "comfort"],
                "created_at": now,
                "updated_at": now,
            }
        }
        for name in [
            "Mexican Meatballs",
            "Vegetable Beef Soup",
            "Chicken and Dumplings",
            "Tailgating Chili with Beans",
        ]:
            pid = _gen_id("recipe")
            recipes[pid] = {
                "id": pid,
                "name": name,
                "category": "Slow Cooker",
                "ingredients": [],
                "instructions": "",
                "notes": "",
                "default_shelf_life": {"value": 3, "unit": "months"},
                "expected_jars_per_batch": 8,
                "tags": [],
                "created_at": now,
                "updated_at": now,
            }
        return {"recipes": recipes, "batches": {}, "consumption_log": []}

    def load(self) -> None:
        if not self.data_path.exists():
            self.data = self._seed_data()
            self.save()
            self._log("MealPrepper data file initialized with starter recipes.")
            return
        try:
            parsed = json.loads(self.data_path.read_text(encoding="utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("Expected dict")
            parsed.setdefault("recipes", {})
            parsed.setdefault("batches", {})
            parsed.setdefault("consumption_log", [])
            self.data = parsed
            self._log("MealPrepper data file loaded.")
        except Exception as ex:
            self._log(f"MealPrepper data load failed, reseeding: {ex}")
            self.data = self._seed_data()
            self.save()

    def save(self) -> None:
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=str(self.data_path.parent)) as tf:
            tf.write(payload)
            tmp_name = tf.name
        os.replace(tmp_name, self.data_path)

    def recipes(self) -> list[dict[str, Any]]:
        rows = [v for v in self.data.get("recipes", {}).values() if isinstance(v, dict)]
        return sorted(rows, key=lambda x: str(x.get("name") or "").lower())

    def recipe_by_id(self, recipe_id: str) -> Optional[dict[str, Any]]:
        row = self.data.get("recipes", {}).get(recipe_id)
        return row if isinstance(row, dict) else None

    def batches_for_recipe(self, recipe_id: str) -> list[dict[str, Any]]:
        rows = []
        for batch in self.data.get("batches", {}).values():
            if isinstance(batch, dict) and str(batch.get("recipe_id") or "") == recipe_id:
                rows.append(batch)
        rows.sort(key=lambda b: str(b.get("batch_date") or ""), reverse=True)
        return rows

    def active_batch_for_recipe(self, recipe_id: str) -> Optional[dict[str, Any]]:
        for batch in self.batches_for_recipe(recipe_id):
            if int(batch.get("jars_remaining") or 0) > 0 and not batch.get("finished_at"):
                return batch
        return self.batches_for_recipe(recipe_id)[0] if self.batches_for_recipe(recipe_id) else None

    def upsert_recipe(self, recipe: dict[str, Any]) -> dict[str, Any]:
        now = _now_iso()
        rid = str(recipe.get("id") or "").strip() or _gen_id("recipe")
        existing = self.recipe_by_id(rid) or {}
        cleaned = {
            "id": rid,
            "name": str(recipe.get("name") or "").strip() or "Untitled Recipe",
            "category": str(recipe.get("category") or "Other").strip() or "Other",
            "ingredients": [s.strip() for s in (recipe.get("ingredients") or []) if str(s).strip()],
            "instructions": str(recipe.get("instructions") or ""),
            "notes": str(recipe.get("notes") or ""),
            "default_shelf_life": {
                "value": max(1, int(((recipe.get("default_shelf_life") or {}).get("value") or 1))),
                "unit": str(((recipe.get("default_shelf_life") or {}).get("unit") or "months")).lower(),
            },
            "expected_jars_per_batch": max(1, int(recipe.get("expected_jars_per_batch") or 1)),
            "tags": [s.strip() for s in (recipe.get("tags") or []) if str(s).strip()],
            "created_at": str(existing.get("created_at") or now),
            "updated_at": now,
        }
        self.data["recipes"][rid] = cleaned
        self.save()
        self._log(f"MealPrepper recipe created/updated: {cleaned['name']}")
        return cleaned

    def delete_recipe(self, recipe_id: str) -> None:
        recipe = self.recipe_by_id(recipe_id)
        if recipe_id in self.data.get("recipes", {}):
            del self.data["recipes"][recipe_id]
        batch_ids = [bid for bid, b in self.data.get("batches", {}).items() if str((b or {}).get("recipe_id") or "") == recipe_id]
        for bid in batch_ids:
            del self.data["batches"][bid]
        self.data["consumption_log"] = [
            e for e in self.data.get("consumption_log", []) if str((e or {}).get("recipe_id") or "") != recipe_id
        ]
        self.save()
        self._log(f"MealPrepper recipe deleted: {str((recipe or {}).get('name') or recipe_id)}")

    def create_or_update_batch(self, batch: dict[str, Any]) -> dict[str, Any]:
        now = _now_iso()
        bid = str(batch.get("id") or "").strip() or _gen_id("batch")
        existing = self.data.get("batches", {}).get(bid) if isinstance(self.data.get("batches", {}), dict) else {}
        shelf = batch.get("shelf_life") if isinstance(batch.get("shelf_life"), dict) else {}
        cleaned = {
            "id": bid,
            "recipe_id": str(batch.get("recipe_id") or ""),
            "batch_date": str(batch.get("batch_date") or _to_date_str(_today())),
            "best_by_date": str(batch.get("best_by_date") or _to_date_str(_today())),
            "total_jars": max(0, int(batch.get("total_jars") or 0)),
            "jars_remaining": max(0, int(batch.get("jars_remaining") or 0)),
            "shelf_life": {"value": max(1, int(shelf.get("value") or 1)), "unit": str(shelf.get("unit") or "months")},
            "notes": str(batch.get("notes") or ""),
            "status": str(batch.get("status") or "fresh"),
            "finished_at": batch.get("finished_at"),
            "created_at": str((existing or {}).get("created_at") or now),
            "updated_at": now,
        }
        self.data["batches"][bid] = cleaned
        self.save()
        self._log(f"MealPrepper batch created/updated: {bid}")
        return cleaned

    def add_consumption(self, recipe_id: str, batch_id: str, quantity: int = 1) -> None:
        event = {
            "id": _gen_id("consume"),
            "recipe_id": recipe_id,
            "batch_id": batch_id,
            "event": "ate_jar",
            "quantity": max(1, int(quantity)),
            "timestamp": _now_iso(),
        }
        self.data.setdefault("consumption_log", []).append(event)
        self.save()
        self._log(f"MealPrepper jar consumption logged: recipe={recipe_id} batch={batch_id} qty={quantity}")


class MealPrepperPanel(QWidget):
    def __init__(self, store: MealPrepperStore, deck_api: dict[str, Any]):
        super().__init__()
        self.store = store
        self.deck_api = deck_api
        self._log: Callable[[str], None] = deck_api.get("log") if callable(deck_api.get("log")) else (lambda _m: None)
        self.selected_recipe_id = ""
        self.selected_batch_id = ""
        self._build_ui()
        self.refresh_tree()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal, self)

        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        self.recipe_tree = QTreeWidget(left)
        self.recipe_tree.setHeaderLabels(["Meal Prep Recipes"])
        self.recipe_tree.itemSelectionChanged.connect(self._on_recipe_selected)
        left_layout.addWidget(self.recipe_tree)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)

        recipe_box = QGroupBox("Recipe Details", right)
        rf = QFormLayout(recipe_box)
        self.recipe_name = QLineEdit(recipe_box)
        self.recipe_category = QComboBox(recipe_box)
        self.recipe_category.addItems(CATEGORIES)
        self.recipe_ingredients = QTextEdit(recipe_box)
        self.recipe_instructions = QTextEdit(recipe_box)
        self.recipe_notes = QTextEdit(recipe_box)
        self.recipe_shelf_value = QSpinBox(recipe_box)
        self.recipe_shelf_value.setRange(1, 3650)
        self.recipe_shelf_unit = QComboBox(recipe_box)
        self.recipe_shelf_unit.addItems(["days", "weeks", "months"])
        self.recipe_expected_jars = QSpinBox(recipe_box)
        self.recipe_expected_jars.setRange(1, 500)
        self.recipe_tags = QLineEdit(recipe_box)
        rf.addRow("Name", self.recipe_name)
        rf.addRow("Category", self.recipe_category)
        rf.addRow("Ingredients (one per line)", self.recipe_ingredients)
        rf.addRow("Instructions", self.recipe_instructions)
        rf.addRow("Notes", self.recipe_notes)

        shelf_wrap = QWidget(recipe_box)
        shelf_layout = QHBoxLayout(shelf_wrap)
        shelf_layout.setContentsMargins(0, 0, 0, 0)
        shelf_layout.addWidget(self.recipe_shelf_value)
        shelf_layout.addWidget(self.recipe_shelf_unit)
        rf.addRow("Default shelf life", shelf_wrap)

        rf.addRow("Expected jars per batch", self.recipe_expected_jars)
        rf.addRow("Tags (comma-separated)", self.recipe_tags)

        stats_box = QGroupBox("Current Batch + Statistics", right)
        self.stats_layout = QGridLayout(stats_box)
        self.stats_labels: dict[str, QLabel] = {}
        stat_fields = [
            "Last made date",
            "Best-by date",
            "Total jars made in current batch",
            "Jars remaining",
            "Status",
            "Average jars made per batch",
            "Average batch duration for this user",
            "Average consumption rate",
            "Estimated days remaining",
            "How often user makes this recipe",
            "Projected next batch needed date",
        ]
        for idx, title in enumerate(stat_fields):
            lbl = QLabel("-", stats_box)
            lbl.setWordWrap(True)
            self.stats_layout.addWidget(QLabel(title, stats_box), idx, 0)
            self.stats_layout.addWidget(lbl, idx, 1)
            self.stats_labels[title] = lbl

        batch_box = QGroupBox("Batch Tracking", right)
        bf = QFormLayout(batch_box)
        self.batch_date = QDateEdit(batch_box)
        self.batch_date.setCalendarPopup(True)
        self.batch_date.setDate(QDate.currentDate())
        self.batch_total = QSpinBox(batch_box)
        self.batch_total.setRange(0, 10000)
        self.batch_remaining = QSpinBox(batch_box)
        self.batch_remaining.setRange(0, 10000)
        self.batch_shelf_value = QSpinBox(batch_box)
        self.batch_shelf_value.setRange(1, 3650)
        self.batch_shelf_unit = QComboBox(batch_box)
        self.batch_shelf_unit.addItems(["days", "weeks", "months"])
        self.batch_best_by = QDateEdit(batch_box)
        self.batch_best_by.setCalendarPopup(True)
        self.batch_best_by.setDate(QDate.currentDate())
        self.batch_notes = QTextEdit(batch_box)
        self.batch_shelf_value.valueChanged.connect(self._recalc_best_by)
        self.batch_shelf_unit.currentTextChanged.connect(self._recalc_best_by)
        self.batch_date.dateChanged.connect(self._recalc_best_by)

        bf.addRow("Jar Date / Batch Date", self.batch_date)
        bf.addRow("Total Jars Made", self.batch_total)
        bf.addRow("Jars Remaining", self.batch_remaining)
        shelf_batch_wrap = QWidget(batch_box)
        sb_layout = QHBoxLayout(shelf_batch_wrap)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.addWidget(self.batch_shelf_value)
        sb_layout.addWidget(self.batch_shelf_unit)
        bf.addRow("Shelf Life", shelf_batch_wrap)
        bf.addRow("Best By Date", self.batch_best_by)
        bf.addRow("Notes", self.batch_notes)

        btn_row1 = QHBoxLayout()
        for label, fn in [
            ("New Recipe", self._new_recipe),
            ("Edit Recipe", self._edit_recipe),
            ("Delete Recipe", self._delete_recipe),
            ("Save Recipe", self._save_recipe),
        ]:
            b = QPushButton(label, self)
            b.clicked.connect(fn)
            btn_row1.addWidget(b)
        right_layout.addWidget(recipe_box)
        right_layout.addLayout(btn_row1)
        right_layout.addWidget(stats_box)
        right_layout.addWidget(batch_box)

        btn_row2 = QHBoxLayout()
        for label, fn in [
            ("New Batch", self._new_batch),
            ("Save Batch", self._save_batch),
            ("Ate One Jar", self._ate_one_jar),
            ("Add Jar", self._add_jar),
            ("Remove Jar", self._remove_jar),
            ("Mark Batch Finished", self._finish_batch),
        ]:
            b = QPushButton(label, self)
            b.clicked.connect(fn)
            btn_row2.addWidget(b)
        right_layout.addLayout(btn_row2)

        send_row = QHBoxLayout()
        send_ai = QPushButton("Send To AI", self)
        send_ai.clicked.connect(self._send_to_ai)
        send_row.addWidget(send_ai)
        send_shop = QPushButton("Send to Shopping List", self)
        send_shop.setEnabled(False)
        send_shop.setToolTip("Coming Soon — Shopping List module not installed.")
        send_row.addWidget(send_shop)
        send_book = QPushButton("Send to Recipe Book", self)
        send_book.setEnabled(False)
        send_book.setToolTip("Coming Soon — Recipe Book module not installed.")
        send_row.addWidget(send_book)
        right_layout.addLayout(send_row)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([280, 900])
        root.addWidget(splitter)

    def refresh_tree(self) -> None:
        self.recipe_tree.clear()
        grouped: dict[str, list[dict[str, Any]]] = {cat: [] for cat in CATEGORIES}
        for recipe in self.store.recipes():
            cat = str(recipe.get("category") or "Other")
            if cat not in grouped:
                grouped["Other"].append(recipe)
            else:
                grouped[cat].append(recipe)
        for cat in CATEGORIES:
            parent = QTreeWidgetItem([cat])
            parent.setExpanded(True)
            self.recipe_tree.addTopLevelItem(parent)
            for recipe in grouped[cat]:
                status = self._status_for_recipe(recipe)
                indicator = "⚠ " if status in {"near_best_by", "expired", "low_stock", "out"} else ""
                child = QTreeWidgetItem([f"{indicator}{recipe.get('name')}"])
                child.setData(0, Qt.UserRole, recipe.get("id"))
                parent.addChild(child)
        self.recipe_tree.expandAll()

    def _status_for_recipe(self, recipe: dict[str, Any]) -> str:
        batch = self.store.active_batch_for_recipe(str(recipe.get("id") or ""))
        if not batch:
            return "fresh"
        return self._compute_status(batch)

    def _compute_status(self, batch: dict[str, Any]) -> str:
        statuses = ["fresh"]
        remaining = int(batch.get("jars_remaining") or 0)
        if remaining == 0:
            statuses.append("out")
        elif remaining <= 2:
            statuses.append("low_stock")
        best_by = _parse_dt(str(batch.get("best_by_date") or ""))
        if best_by is not None:
            today = _today()
            if today.date() > best_by.date():
                statuses.append("expired")
            elif (best_by.date() - today.date()).days <= 14:
                statuses.append("near_best_by")
        return max(statuses, key=lambda s: STATUS_PRIORITY.get(s, 0))

    def _on_recipe_selected(self) -> None:
        items = self.recipe_tree.selectedItems()
        if not items:
            return
        rid = str(items[0].data(0, Qt.UserRole) or "")
        if not rid:
            return
        recipe = self.store.recipe_by_id(rid)
        if not recipe:
            return
        self.selected_recipe_id = rid
        self._load_recipe(recipe)
        self._load_batch_for_recipe(rid)
        self._refresh_stats(recipe)

    def _load_recipe(self, recipe: dict[str, Any]) -> None:
        self.recipe_name.setText(str(recipe.get("name") or ""))
        cat = str(recipe.get("category") or "Other")
        self.recipe_category.setCurrentText(cat if cat in CATEGORIES else "Other")
        self.recipe_ingredients.setPlainText("\n".join(recipe.get("ingredients") or []))
        self.recipe_instructions.setPlainText(str(recipe.get("instructions") or ""))
        self.recipe_notes.setPlainText(str(recipe.get("notes") or ""))
        shelf = recipe.get("default_shelf_life") if isinstance(recipe.get("default_shelf_life"), dict) else {}
        self.recipe_shelf_value.setValue(max(1, int(shelf.get("value") or 1)))
        self.recipe_shelf_unit.setCurrentText(str(shelf.get("unit") or "months"))
        self.recipe_expected_jars.setValue(max(1, int(recipe.get("expected_jars_per_batch") or 1)))
        self.recipe_tags.setText(", ".join(recipe.get("tags") or []))

    def _load_batch_for_recipe(self, recipe_id: str) -> None:
        batch = self.store.active_batch_for_recipe(recipe_id)
        self.selected_batch_id = ""
        if not batch:
            self._new_batch()
            return
        self.selected_batch_id = str(batch.get("id") or "")
        batch_dt = _parse_dt(str(batch.get("batch_date") or "")) or _today()
        best_dt = _parse_dt(str(batch.get("best_by_date") or "")) or batch_dt
        self.batch_date.setDate(QDate(batch_dt.year, batch_dt.month, batch_dt.day))
        self.batch_best_by.setDate(QDate(best_dt.year, best_dt.month, best_dt.day))
        self.batch_total.setValue(int(batch.get("total_jars") or 0))
        self.batch_remaining.setValue(int(batch.get("jars_remaining") or 0))
        shelf = batch.get("shelf_life") if isinstance(batch.get("shelf_life"), dict) else {}
        self.batch_shelf_value.setValue(max(1, int(shelf.get("value") or 1)))
        self.batch_shelf_unit.setCurrentText(str(shelf.get("unit") or "months"))
        self.batch_notes.setPlainText(str(batch.get("notes") or ""))

    def _refresh_stats(self, recipe: dict[str, Any]) -> None:
        stats = self._calc_stats(str(recipe.get("id") or ""))
        batch = self.store.active_batch_for_recipe(str(recipe.get("id") or ""))
        status = self._compute_status(batch) if batch else "fresh"
        self.stats_labels["Last made date"].setText(str(stats.get("last_made") or "Not enough history yet"))
        self.stats_labels["Best-by date"].setText(str((batch or {}).get("best_by_date") or "Not enough history yet"))
        self.stats_labels["Total jars made in current batch"].setText(str((batch or {}).get("total_jars") or "Not enough history yet"))
        self.stats_labels["Jars remaining"].setText(str((batch or {}).get("jars_remaining") or "Not enough history yet"))
        self.stats_labels["Status"].setText(STATUS_LABELS.get(status, "Fresh"))
        self.stats_labels["Average jars made per batch"].setText(str(stats.get("avg_jars") or "Not enough history yet"))
        self.stats_labels["Average batch duration for this user"].setText(str(stats.get("avg_batch_duration") or "Not enough history yet"))
        self.stats_labels["Average consumption rate"].setText(str(stats.get("avg_days_per_jar") or "Not enough history yet"))
        self.stats_labels["Estimated days remaining"].setText(str(stats.get("estimated_days_remaining") or "Not enough history yet"))
        self.stats_labels["How often user makes this recipe"].setText(str(stats.get("cadence") or "Not enough history yet"))
        self.stats_labels["Projected next batch needed date"].setText(str(stats.get("next_batch_date") or "Not enough history yet"))

    def _calc_stats(self, recipe_id: str) -> dict[str, Any]:
        batches = self.store.batches_for_recipe(recipe_id)
        if not batches:
            return {}
        total_jars = [int(b.get("total_jars") or 0) for b in batches]
        avg_jars = round(sum(total_jars) / len(total_jars), 2) if total_jars else None

        durations = []
        for b in batches:
            bdt = _parse_dt(str(b.get("batch_date") or ""))
            fdt = _parse_dt(str(b.get("finished_at") or ""))
            if bdt and fdt:
                durations.append(max(0, (fdt.date() - bdt.date()).days))
        avg_duration = round(sum(durations) / len(durations), 2) if durations else None

        consumption_days = []
        for ev in self.store.data.get("consumption_log", []):
            if str((ev or {}).get("recipe_id") or "") != recipe_id:
                continue
            ts = _parse_dt(str((ev or {}).get("timestamp") or ""))
            batch = self.store.data.get("batches", {}).get(str((ev or {}).get("batch_id") or ""), {})
            bdt = _parse_dt(str((batch or {}).get("batch_date") or ""))
            if ts and bdt:
                consumption_days.append(max(1, (ts.date() - bdt.date()).days))
        avg_days_per_jar = round(sum(consumption_days) / len(consumption_days), 2) if consumption_days else None

        sorted_dates = sorted([_parse_dt(str(b.get("batch_date") or "")) for b in batches if _parse_dt(str(b.get("batch_date") or ""))])
        cadence = None
        if len(sorted_dates) >= 2:
            gaps = [(sorted_dates[i].date() - sorted_dates[i - 1].date()).days for i in range(1, len(sorted_dates))]
            cadence_days = round(sum(gaps) / len(gaps), 2) if gaps else None
            cadence = f"Every {cadence_days} days" if cadence_days else None
        active = self.store.active_batch_for_recipe(recipe_id)
        estimated_days_remaining = None
        next_batch_date = None
        if active and avg_days_per_jar:
            remaining = int(active.get("jars_remaining") or 0)
            estimated_days_remaining = round(remaining * avg_days_per_jar, 2)
            next_batch_date = (_today() + timedelta(days=int(estimated_days_remaining))).date().isoformat()

        return {
            "avg_jars": avg_jars,
            "avg_batch_duration": f"{avg_duration} days" if avg_duration is not None else None,
            "avg_days_per_jar": f"{avg_days_per_jar} days/jar" if avg_days_per_jar is not None else None,
            "estimated_days_remaining": f"{estimated_days_remaining} days" if estimated_days_remaining is not None else None,
            "cadence": cadence,
            "next_batch_date": next_batch_date,
            "last_made": sorted_dates[-1].date().isoformat() if sorted_dates else None,
        }

    def _new_recipe(self) -> None:
        self.selected_recipe_id = ""
        self.recipe_name.setText("")
        self.recipe_category.setCurrentText("Slow Cooker")
        self.recipe_ingredients.setPlainText("")
        self.recipe_instructions.setPlainText("")
        self.recipe_notes.setPlainText("")
        self.recipe_shelf_value.setValue(3)
        self.recipe_shelf_unit.setCurrentText("months")
        self.recipe_expected_jars.setValue(8)
        self.recipe_tags.setText("")

    def _edit_recipe(self) -> None:
        # Fields are always editable; this exists to satisfy required control.
        self.recipe_name.setFocus()

    def _save_recipe(self) -> None:
        recipe = {
            "id": self.selected_recipe_id,
            "name": self.recipe_name.text().strip(),
            "category": self.recipe_category.currentText(),
            "ingredients": [line.strip() for line in self.recipe_ingredients.toPlainText().splitlines() if line.strip()],
            "instructions": self.recipe_instructions.toPlainText().strip(),
            "notes": self.recipe_notes.toPlainText().strip(),
            "default_shelf_life": {
                "value": self.recipe_shelf_value.value(),
                "unit": self.recipe_shelf_unit.currentText(),
            },
            "expected_jars_per_batch": self.recipe_expected_jars.value(),
            "tags": [tag.strip() for tag in self.recipe_tags.text().split(",") if tag.strip()],
        }
        saved = self.store.upsert_recipe(recipe)
        self.selected_recipe_id = str(saved.get("id") or "")
        self.refresh_tree()
        self._refresh_stats(saved)

    def _delete_recipe(self) -> None:
        if not self.selected_recipe_id:
            return
        if QMessageBox.question(self, "Delete Recipe", "Delete recipe and all associated batches?") != QMessageBox.Yes:
            return
        self.store.delete_recipe(self.selected_recipe_id)
        self.selected_recipe_id = ""
        self.selected_batch_id = ""
        self.refresh_tree()
        self._new_recipe()

    def _new_batch(self) -> None:
        recipe = self.store.recipe_by_id(self.selected_recipe_id) if self.selected_recipe_id else None
        self.selected_batch_id = ""
        self.batch_date.setDate(QDate.currentDate())
        default_jars = int((recipe or {}).get("expected_jars_per_batch") or 1)
        self.batch_total.setValue(max(1, default_jars))
        self.batch_remaining.setValue(max(1, default_jars))
        shelf = (recipe or {}).get("default_shelf_life") if isinstance((recipe or {}).get("default_shelf_life"), dict) else {}
        self.batch_shelf_value.setValue(max(1, int((shelf or {}).get("value") or 3)))
        self.batch_shelf_unit.setCurrentText(str((shelf or {}).get("unit") or "months"))
        self._recalc_best_by()
        self.batch_notes.setPlainText("")

    def _recalc_best_by(self) -> None:
        base = self.batch_date.date().toPython()
        base_dt = datetime(base.year, base.month, base.day, tzinfo=UTC)
        best_dt = _add_shelf_life(base_dt, self.batch_shelf_value.value(), self.batch_shelf_unit.currentText())
        self.batch_best_by.setDate(QDate(best_dt.year, best_dt.month, best_dt.day))

    def _save_batch(self) -> None:
        if not self.selected_recipe_id:
            return
        batch = {
            "id": self.selected_batch_id,
            "recipe_id": self.selected_recipe_id,
            "batch_date": self.batch_date.date().toString("yyyy-MM-dd"),
            "best_by_date": self.batch_best_by.date().toString("yyyy-MM-dd"),
            "total_jars": self.batch_total.value(),
            "jars_remaining": self.batch_remaining.value(),
            "shelf_life": {"value": self.batch_shelf_value.value(), "unit": self.batch_shelf_unit.currentText()},
            "notes": self.batch_notes.toPlainText().strip(),
        }
        batch["status"] = self._compute_status(batch)
        if int(batch["jars_remaining"]) == 0:
            batch["finished_at"] = _now_iso()
            self._log(f"MealPrepper batch finished: {batch.get('id') or 'new'}")
        saved = self.store.create_or_update_batch(batch)
        self.selected_batch_id = str(saved.get("id") or "")
        recipe = self.store.recipe_by_id(self.selected_recipe_id)
        if recipe:
            self._refresh_stats(recipe)
            self.refresh_tree()

    def _ate_one_jar(self) -> None:
        if not self.selected_recipe_id:
            return
        if not self.selected_batch_id:
            self._save_batch()
        if self.batch_remaining.value() <= 0:
            return
        self.batch_remaining.setValue(self.batch_remaining.value() - 1)
        self._save_batch()
        if self.selected_batch_id:
            self.store.add_consumption(self.selected_recipe_id, self.selected_batch_id, quantity=1)
        if self.batch_remaining.value() == 0:
            self._finish_batch()

    def _add_jar(self) -> None:
        self.batch_remaining.setValue(self.batch_remaining.value() + 1)
        if self.batch_remaining.value() > self.batch_total.value():
            self.batch_total.setValue(self.batch_remaining.value())
        self._save_batch()

    def _remove_jar(self) -> None:
        self.batch_remaining.setValue(max(0, self.batch_remaining.value() - 1))
        self._save_batch()

    def _finish_batch(self) -> None:
        self.batch_remaining.setValue(0)
        self._save_batch()

    def _send_to_ai(self) -> None:
        if not self.selected_recipe_id:
            return
        recipe = self.store.recipe_by_id(self.selected_recipe_id)
        batch = self.store.active_batch_for_recipe(self.selected_recipe_id) or {}
        stats = self._calc_stats(self.selected_recipe_id)
        payload = {
            "type": "MealPrepper Recipe",
            "recipe_name": str((recipe or {}).get("name") or ""),
            "category": str((recipe or {}).get("category") or ""),
            "ingredients": list((recipe or {}).get("ingredients") or []),
            "instructions": str((recipe or {}).get("instructions") or ""),
            "notes": str((recipe or {}).get("notes") or ""),
            "current_batch": {
                "batch_date": str(batch.get("batch_date") or ""),
                "best_by_date": str(batch.get("best_by_date") or ""),
                "total_jars": int(batch.get("total_jars") or 0),
                "jars_remaining": int(batch.get("jars_remaining") or 0),
                "status": STATUS_LABELS.get(self._compute_status(batch), "Fresh") if batch else "Fresh",
            },
            "stats": {
                "average_jars_per_batch": stats.get("avg_jars"),
                "average_days_per_jar": stats.get("avg_days_per_jar"),
                "average_batch_duration": stats.get("avg_batch_duration"),
                "projected_next_batch_date": stats.get("next_batch_date"),
            },
        }
        handoff = self.deck_api.get("handoff_workspace_context")
        request_ai = self.deck_api.get("request_ai_interpretation")
        sent = False
        if callable(handoff):
            try:
                sent = bool(handoff("meal_prepper", payload, True))
            except Exception as ex:
                self._log(f"MealPrepper Send To AI blocked (handoff error): {ex}")
        elif callable(request_ai):
            try:
                sent = bool(request_ai("meal_prepper", payload))
            except Exception as ex:
                self._log(f"MealPrepper Send To AI blocked (request error): {ex}")
        if sent:
            self._log("MealPrepper Send To AI payload sent.")
        else:
            self._log("MealPrepper Send To AI blocked: host handoff unavailable.")


class MealPrepperRuntime:
    def __init__(self, deck_api: dict[str, Any]):
        self.deck_api = deck_api
        self._log: Callable[[str], None] = deck_api.get("log") if callable(deck_api.get("log")) else (lambda _m: None)
        self.store = MealPrepperStore(deck_api)
        self.panel: Optional[MealPrepperPanel] = None
        self._claim_workspaces = deck_api.get("claim_workspaces") if callable(deck_api.get("claim_workspaces")) else None
        self._log("MealPrepper module loaded.")

    def build_panel(self) -> QWidget:
        if self.panel is None:
            self.panel = MealPrepperPanel(self.store, self.deck_api)
        return self.panel

    def get_workspace_spec(self) -> dict[str, Any]:
        return {
            "tabs": [
                {
                    "slot": 1,
                    "id": "meal_prep_workspace",
                    "label": "Meal Prep",
                    "build": self.build_panel,
                }
            ]
        }

    def on_startup(self) -> None:
        if callable(self._claim_workspaces):
            try:
                self._claim_workspaces("meal_prepper")
            except Exception:
                pass


def register(deck_api: dict) -> dict:
    if str(deck_api.get("deck_api_version") or "") != "1.0":
        raise RuntimeError(f"Unsupported deck API version: {deck_api.get('deck_api_version')}")

    runtime = MealPrepperRuntime(deck_api)

    return {
        "deck_api_version": "1.0",
        "module_key": "meal_prepper",
        "display_name": "Meal Prepper",
        "home_category": "Home / Food / Meal Prep",
        "tabs": [
            {
                "tab_id": "meal_prepper_main",
                "tab_name": "Meal Prep",
                "get_content": runtime.build_panel,
            }
        ],
        "workspace": runtime.get_workspace_spec(),
        "supports_workspaces": True,
        "workspace_tabs": runtime.get_workspace_spec()["tabs"],
        "get_workspace_spec": runtime.get_workspace_spec,
        "hooks": {
            "on_startup": runtime.on_startup,
        },
    }
