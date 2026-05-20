from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 01 — MANIFEST / CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

import json
import math
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

MODULE_MANIFEST = {
    "key": "Finance",
    "display_name": "Finance",
    "description": "KPI-first finance planning with budget, vision, retirement, append-only ledger, and AI queue dispatch.",
    "version": "1.0.0",
    "deck_api_version": "1.0",
    "home_category": "Professional",
    "secondary_categories": ["Planning", "Analytics"],
    "entry_function": "register",
    "tab_definitions": [
        {"tab_id": "finance_budget", "tab_name": "Budget"},
        {"tab_id": "finance_vision", "tab_name": "Vision"},
        {"tab_id": "finance_retirement", "tab_name": "Retirement"},
    ],
}
MODULE_KEY = "Finance"
SCHEMA_TARGET = 1

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 02 — IMPORTS / DEPENDENCY GUARDS
# ═══════════════════════════════════════════════════════════════════════════════

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea,
    QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit,
    QTimeEdit, QToolButton, QVBoxLayout, QWidget
)
from PySide6.QtCharts import QChart, QChartView, QPieSeries, QBarSeries, QBarSet, QBarCategoryAxis, QValueAxis, QLineSeries

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 03 — DATABASE SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════

SCHEMA_SQL = [
"""CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)""",
"""CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY,event_time TEXT NOT NULL,recorded_at TEXT NOT NULL,entry_type TEXT,direction TEXT NOT NULL,amount REAL NOT NULL,category_id INTEGER,subcategory TEXT,merchant TEXT,description TEXT,account_id INTEGER,tier TEXT,recurrence_id INTEGER,linked_to_id INTEGER,source TEXT,supersedes_id INTEGER,voided INTEGER NOT NULL DEFAULT 0,voided_at TEXT,void_reason TEXT,notes TEXT)""",
"""CREATE TABLE IF NOT EXISTS settings_history(id INTEGER PRIMARY KEY,effective_from TEXT,recorded_at TEXT,setting_scope TEXT,setting_key TEXT,setting_value TEXT,changed_by TEXT,notes TEXT)""",
"""CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY,name TEXT,account_type TEXT,institution TEXT,created_at TEXT,active INTEGER DEFAULT 1,opening_balance REAL,opening_date TEXT,credit_limit REAL,interest_rate REAL,min_payment REAL,notes TEXT)""",
"""CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY,name TEXT UNIQUE,parent_id INTEGER,default_tier TEXT,color TEXT,icon TEXT,sort_order INTEGER,active INTEGER DEFAULT 1,is_system INTEGER DEFAULT 0,created_at TEXT)""",
"""CREATE TABLE IF NOT EXISTS recurring_schedule(id INTEGER PRIMARY KEY,created_at TEXT,event_type TEXT,name TEXT,category_id INTEGER,amount REAL,frequency TEXT,next_due_date TEXT,day_of_month INTEGER,account_id INTEGER,tier TEXT,active INTEGER DEFAULT 1,auto_post INTEGER DEFAULT 0,superseded_by INTEGER,notes TEXT)""",
"""CREATE TABLE IF NOT EXISTS vision_categories(id INTEGER PRIMARY KEY,name TEXT UNIQUE,sort_order INTEGER,is_system INTEGER DEFAULT 1,created_at TEXT)""",
"""CREATE TABLE IF NOT EXISTS savings_goals(id INTEGER PRIMARY KEY,name TEXT,total_to_save REAL,save_monthly REAL,start_date TEXT,target_date TEXT,completed_date TEXT,linked_account INTEGER,auto_log_on_complete INTEGER DEFAULT 0,superseded_by INTEGER,voided INTEGER DEFAULT 0,notes TEXT,created_at TEXT)""",
"""CREATE TABLE IF NOT EXISTS retirement_inputs(id INTEGER PRIMARY KEY CHECK(id=1),current_age REAL,retirement_age REAL,current_salary REAL,salary_growth REAL,current_balance REAL,annual_contribution REAL,contribution_growth REAL,expected_return REAL,inflation REAL,drawdown_rate REAL,desired_income REAL,pension_income REAL,social_security REAL,tax_rate REAL,under_return_delta REAL,over_return_delta REAL,uncertainty_factor REAL,last_reviewed_at TEXT,updated_at TEXT)""",
"""CREATE TABLE IF NOT EXISTS retirement_projection(id INTEGER PRIMARY KEY,computed_at TEXT,scenario TEXT,age INTEGER,salary REAL,balance REAL,interest REAL,yearly_savings REAL,desired_income REAL,pension_income REAL,end_balance REAL)""",
"""CREATE TABLE IF NOT EXISTS emergency_fund(id INTEGER PRIMARY KEY CHECK(id=1),target_months REAL,linked_account_id INTEGER,last_reviewed_at TEXT,updated_at TEXT)""",
"""CREATE TABLE IF NOT EXISTS budget_periods(id INTEGER PRIMARY KEY,effective_from TEXT,period_type TEXT,category_id INTEGER,amount REAL,threshold_pct REAL,threshold_amt REAL,warning_mode TEXT,superseded_by INTEGER,created_by TEXT,notes TEXT)""",
"""CREATE TABLE IF NOT EXISTS planned_to_actual_links(id INTEGER PRIMARY KEY,planned_ledger_id INTEGER,actual_ledger_id INTEGER,linked_at TEXT,linked_by TEXT,variance_amount REAL)""",
"""CREATE TABLE IF NOT EXISTS ledger_edits(id INTEGER PRIMARY KEY,original_ledger_id INTEGER,supersede_ledger_id INTEGER,edited_at TEXT,edit_reason TEXT,edited_field TEXT,old_value TEXT,new_value TEXT,edited_by TEXT)""",
"""CREATE TABLE IF NOT EXISTS ai_help_sessions(id INTEGER PRIMARY KEY,topic_key TEXT,scope TEXT,opened_at TEXT,last_activity_at TEXT,closed_at TEXT,close_reason TEXT,context_snapshot TEXT,related_session_ids TEXT,state TEXT)""",
"""CREATE TABLE IF NOT EXISTS ai_help_messages(id INTEGER PRIMARY KEY,session_id INTEGER,sent_at TEXT,sender TEXT,message_text TEXT,ui_context TEXT,follow_up_buttons TEXT,user_clicked_followup TEXT)""",
"""CREATE TABLE IF NOT EXISTS ai_nudges(id INTEGER PRIMARY KEY,triggered_at TEXT,trigger_type TEXT,trigger_payload TEXT,drill_path TEXT,ai_message TEXT,follow_up_qs TEXT,user_action TEXT,acted_at TEXT,snooze_until TEXT,cooldown_key TEXT)""",
"""CREATE TABLE IF NOT EXISTS plan_snapshots(id INTEGER PRIMARY KEY,snapshot_at TEXT,snapshot_name TEXT,scope TEXT,data_blob TEXT,created_by TEXT,notes TEXT)""",
"""CREATE TABLE IF NOT EXISTS help_topics(topic_key TEXT PRIMARY KEY,title TEXT,short_explanation TEXT,detailed_explanation TEXT,worked_example TEXT,ai_prompt_template TEXT,follow_up_buttons TEXT,related_topic_keys TEXT)""",
"""CREATE TABLE IF NOT EXISTS workspace_preferences(workspace_key TEXT,subtab_key TEXT,view_mode TEXT,remember_last INTEGER DEFAULT 1,drill_state TEXT,updated_at TEXT,PRIMARY KEY(workspace_key,subtab_key))""",
"""CREATE TABLE IF NOT EXISTS kpi_cache(id INTEGER PRIMARY KEY,kpi_key TEXT,workspace TEXT,subtab TEXT,period_start TEXT,period_end TEXT,drill_scope TEXT,computed_at TEXT,cache_value TEXT,is_dirty INTEGER DEFAULT 0)""",
"""CREATE TABLE IF NOT EXISTS category_tier_defaults(category_id INTEGER PRIMARY KEY,default_tier TEXT)""",
"""CREATE TABLE IF NOT EXISTS debt_metadata(account_id INTEGER PRIMARY KEY,payoff_strategy TEXT,target_payoff_date TEXT,notes TEXT,updated_at TEXT)""",
"""CREATE TABLE IF NOT EXISTS weekly_reconciliations(id INTEGER PRIMARY KEY,week_starting TEXT UNIQUE,reconciled_at TEXT,variance_total REAL,notes TEXT)""",
"""CREATE TABLE IF NOT EXISTS backup_log(id INTEGER PRIMARY KEY,backup_at TEXT,backup_path TEXT,backup_type TEXT,row_count INTEGER,file_size_bytes INTEGER)""",
]

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 04 — DATABASE MIGRATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _utc_now() -> str:
    return datetime.now(UTC).isoformat()

def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 05 — SEED DATA
# ═══════════════════════════════════════════════════════════════════════════════

SEEDED_CATEGORIES = ["Income","Housing","Utilities","Transportation","Food","Healthcare","Insurance","Debt","Savings","Investments","Entertainment","Education","Childcare","Travel","Personal Care","Gifts","Taxes","Misc"]
VISION_CATEGORIES = ["Income","Home","Transportation","Food","Entertainment","Misc","Savings"]

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 06 — FINANCEDB CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class FinanceDB:
    def __init__(self, deck_api: dict[str, Any]):
        self.deck_api = deck_api
        self.root = self._resolve_root()
        self.fin_dir = _ensure_dir(self.root / "Finances")
        self.backup_dir = _ensure_dir(self.fin_dir / "backups")
        self.path = self.fin_dir / "finance.db"
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _resolve_root(self) -> Path:
        cfg = self.deck_api.get("cfg_path")
        if callable(cfg):
            try:
                return Path(str(cfg(""))).resolve()
            except Exception:
                pass
        home = self.deck_api.get("deck_home")
        if home:
            return Path(str(home)).resolve()
        return Path.cwd()

    def _init(self):
        cur = self.conn.cursor()
        for sql in SCHEMA_SQL:
            cur.execute(sql)
        cur.execute("INSERT OR IGNORE INTO schema_version(version,applied_at,description) VALUES(?,?,?)", (SCHEMA_TARGET, _utc_now(), "initial"))
        self.seed_if_needed()
        self.daily_backup()
        self.conn.commit()

    def seed_if_needed(self):
        cur = self.conn.cursor()
        if cur.execute("SELECT COUNT(1) FROM categories").fetchone()[0] == 0:
            for i, n in enumerate(SEEDED_CATEGORIES):
                cur.execute("INSERT INTO categories(name,sort_order,is_system,created_at) VALUES(?,?,1,?)", (n, i, _utc_now()))
        if cur.execute("SELECT COUNT(1) FROM vision_categories").fetchone()[0] == 0:
            for i, n in enumerate(VISION_CATEGORIES):
                cur.execute("INSERT INTO vision_categories(name,sort_order,is_system,created_at) VALUES(?,?,1,?)", (n, i, _utc_now()))
        if cur.execute("SELECT COUNT(1) FROM help_topics").fetchone()[0] == 0:
            for k in ["budgeting_methods","retirement_inputs","emergency_fund","debt_strategies","needs_vs_wants","gross_vs_net_income","planned_vs_actual","thresholds","investment_return","inflation","retirement_uncertainty"]:
                cur.execute("INSERT INTO help_topics(topic_key,title,short_explanation,detailed_explanation,worked_example,ai_prompt_template,follow_up_buttons,related_topic_keys) VALUES(?,?,?,?,?,?,?,?)", (k,k.replace("_"," ").title(),"Short","Detailed","Example","Help me with {topic}",json.dumps(["Why?","How?"]),""))
        if cur.execute("SELECT COUNT(1) FROM settings_history WHERE setting_scope='budget_method' AND setting_key='active'").fetchone()[0] == 0:
            cur.execute("INSERT INTO settings_history(effective_from,recorded_at,setting_scope,setting_key,setting_value,changed_by,notes) VALUES(?,?,?,?,?,?,?)", (_utc_now(), _utc_now(), "budget_method", "active", "none", "system", "default"))

    def daily_backup(self):
        stamp = date.today().isoformat()
        target = self.backup_dir / f"finance_{stamp}.db"
        if not target.exists() and self.path.exists():
            self.conn.commit()
            shutil.copy2(self.path, target)
            sz = target.stat().st_size
            self.conn.execute("INSERT INTO backup_log(backup_at,backup_path,backup_type,row_count,file_size_bytes) VALUES(?,?,?,?,?)", (_utc_now(), str(target), "daily", 0, sz))

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 07 — LEDGER HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def append_ledger(db: FinanceDB, payload: dict[str, Any]) -> int:
    cur = db.conn.cursor()
    cur.execute("""INSERT INTO ledger(event_time,recorded_at,entry_type,direction,amount,category_id,subcategory,merchant,description,account_id,tier,recurrence_id,linked_to_id,source,supersedes_id,voided,voided_at,void_reason,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        payload.get("event_time", _utc_now()), _utc_now(), payload.get("entry_type"), payload.get("direction", "expense"), abs(float(payload.get("amount", 0.0))), payload.get("category_id"), payload.get("subcategory"), payload.get("merchant"), payload.get("description"), payload.get("account_id"), payload.get("tier"), payload.get("recurrence_id"), payload.get("linked_to_id"), payload.get("source", "ui"), payload.get("supersedes_id"), 0, None, None, payload.get("notes")
    ))
    db.conn.commit()
    return int(cur.lastrowid)

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 08 — KPI CACHE HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def cache_kpi(db: FinanceDB, key: str, workspace: str, subtab: str, value: dict[str, Any]):
    db.conn.execute("INSERT INTO kpi_cache(kpi_key,workspace,subtab,period_start,period_end,drill_scope,computed_at,cache_value,is_dirty) VALUES(?,?,?,?,?,?,?,?,0)", (key, workspace, subtab, "", "", "", _utc_now(), json.dumps(value)))
    db.conn.commit()

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 09 — AI SESSION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def queue_ai(deck_api: dict[str, Any], topic: str, context: dict[str, Any]) -> None:
    root = Path(str(deck_api.get("deck_home", Path.cwd())))
    q = root / "memories" / "ai_queue.db"
    if not q.exists():
        return
    conn = sqlite3.connect(str(q))
    conn.execute("CREATE TABLE IF NOT EXISTS queue(id INTEGER PRIMARY KEY, created_at TEXT, topic TEXT, payload TEXT, status TEXT)")
    conn.execute("INSERT INTO queue(created_at,topic,payload,status) VALUES(?,?,?,?)", (_utc_now(), topic, json.dumps(context), "pending"))
    conn.commit(); conn.close()

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — RESPONSIVE LAYOUT HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

class VScrollWidget(QWidget):
    def __init__(self, inner: QWidget):
        super().__init__()
        l = QVBoxLayout(self)
        s = QScrollArea(); s.setWidgetResizable(True); s.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        s.setWidget(inner); l.addWidget(s)

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 11 — REUSABLE WIDGETS
# ═══════════════════════════════════════════════════════════════════════════════

class KPIFrame(QFrame):
    def __init__(self, title: str, value: str):
        super().__init__(); self.setFrameShape(QFrame.StyledPanel)
        l = QVBoxLayout(self); l.addWidget(QLabel(title)); l.addWidget(QLabel(value))

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 12 — DRILLABLE CHART SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

class DrillState(QObject):
    changed = Signal()
    def __init__(self):
        super().__init__(); self.path = ["Budget Overview"]
    def drill(self, node: str): self.path.append(node); self.changed.emit()
    def back(self):
        if len(self.path) > 1: self.path.pop(); self.changed.emit()
    def home(self): self.path = ["Budget Overview"]; self.changed.emit()

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 13 — BUDGET WORKSPACE
# ═══════════════════════════════════════════════════════════════════════════════

class BudgetWorkspace(QWidget):
    def __init__(self, db: FinanceDB, deck_api: dict[str, Any]):
        super().__init__(); self.db=db; self.deck_api=deck_api; self.drill=DrillState()
        root=QVBoxLayout(self); self.tabs=QTabWidget(); root.addWidget(self.tabs)
        self.tabs.addTab(self._weekly(), "Weekly"); self.tabs.addTab(self._monthly(), "Monthly"); self.tabs.addTab(self._annual(), "Annual"); self.tabs.addTab(self._ledger(), "Ledger")

    def _weekly(self):
        w=QWidget(); l=QVBoxLayout(w); row=QHBoxLayout()
        for t,v in [("Income This Week","$0"),("Spent So Far","$0"),("Remaining","$0")]: row.addWidget(KPIFrame(t,v))
        l.addLayout(row); l.addWidget(QLabel("On-pace gauge / donut / planned-vs-actual / velocity")); l.addWidget(QLabel("Threshold status list + weekly reconciliation panel")); return VScrollWidget(w)
    def _monthly(self):
        w=QWidget(); l=QVBoxLayout(w); m=QComboBox(); m.addItems(["50/30/20","50/20/30","zero-based","pay-yourself-first","envelope","none/freeform"]); l.addWidget(m); l.addWidget(QLabel("Method-specific KPI rendering")); l.addWidget(QLabel("Category breakdown + recent transactions")); return VScrollWidget(w)
    def _annual(self):
        w=QWidget(); l=QVBoxLayout(w); l.addWidget(QLabel("Retirement contribution banner")); l.addWidget(QLabel("Emergency fund banner")); l.addWidget(QLabel("Income vs spending + YoY overlay + projection + heatmap + merchant analysis")); return VScrollWidget(w)
    def _ledger(self):
        w=QWidget(); l=QVBoxLayout(w); l.addWidget(QLabel("Data view only")); self.tbl=QTableWidget(0,8); self.tbl.setHorizontalHeaderLabels(["Time","Type","Direction","Amount","Category","Merchant","Account","Actions"]); l.addWidget(self.tbl); return VScrollWidget(w)

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 14 — FINANCIAL VISION WORKSPACE
# ═══════════════════════════════════════════════════════════════════════════════

class VisionWorkspace(QWidget):
    def __init__(self, db: FinanceDB):
        super().__init__(); l=QVBoxLayout(self)
        l.addWidget(QLabel("Current vs Goal KPI bars")); l.addWidget(QLabel("Emergency fund panel")); l.addWidget(QLabel("Savings goals tracker + ETA")); l.addWidget(QLabel("Debt panel with avalanche/snowball + shortcuts"));

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 15 — RETIREMENT WORKSPACE
# ═══════════════════════════════════════════════════════════════════════════════

class RetirementWorkspace(QWidget):
    def __init__(self, db: FinanceDB):
        super().__init__(); self.db=db; l=QVBoxLayout(self)
        self.form = QFormLayout(); self.current_age=QSpinBox(); self.current_age.setRange(18,100); self.current_age.setValue(35)
        self.retire_age=QSpinBox(); self.retire_age.setRange(40,85); self.retire_age.setValue(65)
        self.form.addRow("Current age", self.current_age); self.form.addRow("Retirement age", self.retire_age); l.addLayout(self.form)
        b=QPushButton("Run 45-year projection"); b.clicked.connect(self.compute); l.addWidget(b); self.out=QLabel("Verdict KPI"); l.addWidget(self.out)

    def compute(self):
        ca=self.current_age.value(); ra=self.retire_age.value(); bal=100000.0; salary=90000.0
        self.db.conn.execute("DELETE FROM retirement_projection")
        for scenario,delta in [("base",0.0),("under",-0.02),("over",0.02)]:
            b=bal; s=salary
            for age in range(ca, ca+46):
                r=0.06+delta
                if age < ra:
                    contrib=s*0.12; interest=b*r; end=b+interest+contrib; s*=1.03
                else:
                    desired=70000.0; pension=22000.0; draw=max(desired-pension,0); interest=b*r; end=b+interest-draw; contrib=0
                self.db.conn.execute("INSERT INTO retirement_projection(computed_at,scenario,age,salary,balance,interest,yearly_savings,desired_income,pension_income,end_balance) VALUES(?,?,?,?,?,?,?,?,?,?)", (_utc_now(), scenario, age, s, b, interest, contrib, 70000.0, 22000.0, end))
                b=end
        self.db.conn.commit(); self.out.setText("Projection computed")

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 16 — RIGHT-SIDE MODULE PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class FinancePanel(QWidget):
    def __init__(self, db: FinanceDB, deck_api: dict[str, Any]):
        super().__init__(); self.db=db; self.deck_api=deck_api
        l=QVBoxLayout(self); strip=QFrame(); fl=QFormLayout(strip)
        self.entry_type=QComboBox(); self.entry_type.addItems(["expense","income","savings","check"])
        self.category=QLineEdit(); self.merchant=QLineEdit(); self.date=QDateEdit(); self.time=QTimeEdit(); self.amount=QLineEdit(); self.account=QLineEdit(); self.notes=QTextEdit(); self.tier=QComboBox(); self.tier.addItems(["Need","Want","Growth"])
        for n,w in [("Type",self.entry_type),("Category",self.category),("Merchant/Source",self.merchant),("Date",self.date),("Time",self.time),("Amount",self.amount),("Account",self.account),("Notes",self.notes),("Tier",self.tier)]: fl.addRow(n,w)
        btns=QHBoxLayout(); s=QPushButton("Save"); c=QPushButton("Cancel"); a=QPushButton("Add Another"); btns.addWidget(s); btns.addWidget(c); btns.addWidget(a); fl.addRow(btns)
        s.clicked.connect(self.save); c.clicked.connect(self.clear); a.clicked.connect(self.clear)
        l.addWidget(strip); tabs=QTabWidget(); tabs.addTab(QLabel("Budget panel"),"Budget"); tabs.addTab(QLabel("Vision panel"),"Vision"); tabs.addTab(QLabel("Retirement panel"),"Retirement"); l.addWidget(tabs)

    def save(self):
        append_ledger(self.db, {"entry_type": self.entry_type.currentText(), "direction": self.entry_type.currentText(), "amount": float(self.amount.text() or 0), "merchant": self.merchant.text(), "notes": self.notes.toPlainText()})
        queue_ai(self.deck_api, "transaction_saved", {"merchant": self.merchant.text(), "amount": self.amount.text()})

    def clear(self):
        self.category.clear(); self.merchant.clear(); self.amount.clear(); self.account.clear(); self.notes.clear()

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 17 — FINANCEMODULE LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════════════

class FinanceModule(QObject):
    def __init__(self, deck_api: dict[str, Any]):
        super().__init__(); self.deck_api=deck_api; self.db=FinanceDB(deck_api)
        self.timers: list[QTimer] = []
        self.budget_widget=None; self.vision_widget=None; self.retire_widget=None; self.panel_widget=None

    def build_budget(self):
        if self.budget_widget is None: self.budget_widget=BudgetWorkspace(self.db, self.deck_api)
        return self.budget_widget
    def build_vision(self):
        if self.vision_widget is None: self.vision_widget=VisionWorkspace(self.db)
        return self.vision_widget
    def build_retirement(self):
        if self.retire_widget is None: self.retire_widget=RetirementWorkspace(self.db)
        return self.retire_widget
    def panel_budget(self):
        if self.panel_widget is None: self.panel_widget=FinancePanel(self.db, self.deck_api)
        return self.panel_widget
    panel_vision = panel_budget
    panel_retirement = panel_budget

    def release(self):
        for t in self.timers:
            try: t.stop(); t.timeout.disconnect()
            except Exception: pass
        self.timers.clear()
        for n in ["budget_widget","vision_widget","retire_widget","panel_widget"]:
            w=getattr(self,n)
            if w is not None:
                try: w.hide(); w.deleteLater()
                except Exception: pass
                setattr(self,n,None)
        if self.db and self.db.conn:
            self.db.conn.commit(); self.db.conn.close(); self.db.conn=None
        self.db=None

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 18 — REGISTER(DECK_API)
# ═══════════════════════════════════════════════════════════════════════════════

def register(deck_api: dict) -> dict:
    if str(deck_api.get("deck_api_version", "1.0")) != "1.0":
        raise RuntimeError("Finance module requires deck_api_version 1.0")
    mod = FinanceModule(deck_api)
    return {
        "manifest": MODULE_MANIFEST,
        "tabs": [
            {"tab_id": "finance_budget", "tab_name": "Budget", "get_content": mod.panel_budget},
            {"tab_id": "finance_vision", "tab_name": "Vision", "get_content": mod.panel_vision},
            {"tab_id": "finance_retirement", "tab_name": "Retirement", "get_content": mod.panel_retirement},
        ],
        "workspace": {
            "tabs": [
                {"slot": 1, "id": "budget", "label": "Budget", "build": mod.build_budget},
                {"slot": 2, "id": "financial_vision", "label": "Financial Vision", "build": mod.build_vision},
                {"slot": 3, "id": "retirement_planning", "label": "Retirement Planning", "build": mod.build_retirement},
            ],
            "on_release": mod.release,
            "on_deactivate": mod.release,
        },
    }
