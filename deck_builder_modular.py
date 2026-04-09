#!/usr/bin/env python3
"""Direct-run modular Deck entry point.

Architecture for this phase:
- deck_builder_modular.py is both the builder/runtime entry point.
- Optional modules are loaded live from a sibling ``Modules/`` folder.
- Built-in systems are always available and registered internally.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

DECK_VERSION = "0.2.0"


# ----------------------------- Service / Category Core -----------------------------


class ServiceRegistry:
    """Simple named service registry used by built-ins and loaded modules."""

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}

    def register(self, key: str, service: Any) -> None:
        self._services[key] = service

    def get(self, key: str, default: Any = None) -> Any:
        return self._services.get(key, default)

    def require(self, key: str) -> Any:
        if key not in self._services:
            raise KeyError(f"Missing required service: {key}")
        return self._services[key]

    def as_dict(self) -> dict[str, Any]:
        return dict(self._services)


class CategoryManager:
    """Tracks modules grouped by category for display/routing."""

    def __init__(self) -> None:
        self._items: dict[str, list[str]] = {}

    def add(self, category: str, module_name: str) -> None:
        self._items.setdefault(category, [])
        if module_name not in self._items[category]:
            self._items[category].append(module_name)

    def snapshot(self) -> dict[str, list[str]]:
        return {k: sorted(v) for k, v in sorted(self._items.items())}


class Diagnostics:
    """In-memory diagnostics/event logger."""

    def __init__(self) -> None:
        self._entries: list[str] = []

    def log(self, message: str) -> None:
        self._entries.append(message)

    def tail(self, size: int = 20) -> list[str]:
        if size <= 0:
            return []
        return self._entries[-size:]


class PersonaSystem:
    """Persona baseline for this phase (minimal but persistent)."""

    def __init__(self, runtime_root: Path) -> None:
        self._store = runtime_root / ".persona.json"
        self._persona = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._store.exists():
            return {
                "name": "Default",
                "tone": "helpful",
                "guardrails": ["safe", "clear", "concise"],
            }
        try:
            return json.loads(self._store.read_text(encoding="utf-8"))
        except Exception:
            return {
                "name": "Default",
                "tone": "helpful",
                "guardrails": ["safe", "clear", "concise"],
            }

    def get(self) -> dict[str, Any]:
        return dict(self._persona)

    def set(self, payload: dict[str, Any]) -> None:
        self._persona.update(payload)
        self._store.write_text(json.dumps(self._persona, indent=2), encoding="utf-8")


# ----------------------------- Module registration model ----------------------------


@dataclass
class ModuleSpec:
    name: str
    category: str
    source: str
    handler: Callable[[str, "DeckContext"], str] | None = None
    description: str = ""


@dataclass
class DeckContext:
    runtime_root: Path
    modules_dir: Path
    services: ServiceRegistry
    categories: CategoryManager
    diagnostics: Diagnostics
    modules: dict[str, ModuleSpec] = field(default_factory=dict)


class ModuleAPI:
    """API exposed to optional external modules in ./Modules."""

    def __init__(self, context: DeckContext) -> None:
        self._context = context

    def register_module(
        self,
        *,
        name: str,
        category: str,
        handler: Callable[[str, DeckContext], str] | None = None,
        description: str = "",
    ) -> None:
        if name in self._context.modules:
            raise ValueError(f"Module '{name}' already registered")
        spec = ModuleSpec(
            name=name,
            category=category,
            source="external",
            handler=handler,
            description=description,
        )
        self._context.modules[name] = spec
        self._context.categories.add(category, name)
        self._context.diagnostics.log(f"Registered external module: {name}")

    def register_service(self, key: str, service: Any) -> None:
        self._context.services.register(key, service)

    @property
    def context(self) -> DeckContext:
        return self._context


class StartupValidator:
    """Startup validator framework for direct-run architecture."""

    def __init__(self, context: DeckContext) -> None:
        self.context = context

    def validate(self) -> list[str]:
        issues: list[str] = []
        if not self.context.modules_dir.exists():
            issues.append(f"Modules folder missing: {self.context.modules_dir}")
        if not self.context.modules_dir.is_dir():
            issues.append(f"Modules path is not a directory: {self.context.modules_dir}")
        if "persona" not in self.context.services.as_dict():
            issues.append("Persona service is not registered")
        return issues


# ------------------------------- Direct runtime shell -------------------------------


class DeckRuntime:
    def __init__(self, script_path: Path) -> None:
        runtime_root = script_path.resolve().parent
        modules_dir = runtime_root / "Modules"

        services = ServiceRegistry()
        categories = CategoryManager()
        diagnostics = Diagnostics()
        context = DeckContext(
            runtime_root=runtime_root,
            modules_dir=modules_dir,
            services=services,
            categories=categories,
            diagnostics=diagnostics,
        )

        self.context = context
        self.api = ModuleAPI(context)
        self.persona = PersonaSystem(runtime_root)

        self.context.services.register("persona", self.persona)
        self.context.services.register("diagnostics", diagnostics)
        self.context.services.register("module_api", self.api)

        self._register_builtins()

    def _register_builtins(self) -> None:
        builtins = [
            ModuleSpec(
                name="System.Diagnostics",
                category="System",
                source="builtin",
                handler=lambda msg, ctx: "\n".join(ctx.diagnostics.tail(30)) or "No diagnostics yet.",
                description="Shows recent diagnostics entries.",
            ),
            ModuleSpec(
                name="System.Persona",
                category="System",
                source="builtin",
                handler=lambda msg, ctx: json.dumps(ctx.services.require("persona").get(), indent=2),
                description="Displays current persona baseline.",
            ),
            ModuleSpec(
                name="System.Modules",
                category="System",
                source="builtin",
                handler=lambda msg, ctx: json.dumps(ctx.categories.snapshot(), indent=2),
                description="Lists module categories and names.",
            ),
            ModuleSpec(
                name="Prompt.Echo",
                category="Prompt",
                source="builtin",
                handler=lambda msg, ctx: f"Echo: {msg}",
                description="Baseline prompt interface echo responder.",
            ),
        ]

        for spec in builtins:
            self.context.modules[spec.name] = spec
            self.context.categories.add(spec.category, spec.name)
            self.context.diagnostics.log(f"Registered built-in module: {spec.name}")

    def discover_external_modules(self) -> None:
        self.context.modules_dir.mkdir(exist_ok=True)
        for file in sorted(self.context.modules_dir.glob("*.py")):
            if file.name.startswith("_"):
                continue
            self._load_external_module(file)

    def _load_external_module(self, file: Path) -> None:
        module_name = f"deck_module_{file.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, str(file))
            if spec is None or spec.loader is None:
                raise RuntimeError("Could not create module spec")
            py_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(py_module)
            self._register_from_module(py_module, file)
        except Exception as exc:
            self.context.diagnostics.log(
                f"Failed to load module '{file.name}': {exc}\n{traceback.format_exc()}"
            )

    def _register_from_module(self, py_module: ModuleType, file: Path) -> None:
        register = getattr(py_module, "register", None)
        if register is None or not callable(register):
            self.context.diagnostics.log(
                f"Skipped module '{file.name}' (missing callable register(api))"
            )
            return
        register(self.api)
        self.context.diagnostics.log(f"Loaded module file: {file.name}")

    def validate_startup(self) -> list[str]:
        validator = StartupValidator(self.context)
        return validator.validate()

    def run_prompt_interface(self) -> None:
        print("=" * 80)
        print(f"Deck Modular Runtime v{DECK_VERSION}")
        print(f"Entry: {self.context.runtime_root / 'deck_builder_modular.py'}")
        print(f"Modules folder: {self.context.modules_dir}")
        print("Type '/help' for commands. Type '/quit' to exit.")
        print("=" * 80)

        while True:
            raw = input("deck> ").strip()
            if not raw:
                continue
            if raw in {"/quit", "/exit"}:
                print("Goodbye.")
                return
            if raw == "/help":
                self._print_help()
                continue
            if raw == "/list":
                print(json.dumps(self.context.categories.snapshot(), indent=2))
                continue
            if raw.startswith("/use "):
                _, module_name, *message_bits = raw.split(" ")
                message = " ".join(message_bits).strip() or "status"
                print(self.invoke(module_name, message))
                continue
            if raw.startswith("/persona "):
                payload_text = raw.removeprefix("/persona ").strip()
                try:
                    payload = json.loads(payload_text)
                except json.JSONDecodeError as exc:
                    print(f"Invalid JSON payload: {exc}")
                    continue
                self.persona.set(payload)
                print("Persona updated.")
                continue

            # Default route goes to prompt baseline.
            print(self.invoke("Prompt.Echo", raw))

    def _print_help(self) -> None:
        print("Commands:")
        print("  /help                 Show this help")
        print("  /list                 Show discovered modules by category")
        print("  /use <name> [msg]     Invoke a module by exact name")
        print("  /persona <json>       Merge persona baseline with JSON")
        print("  /quit                 Exit")

    def invoke(self, module_name: str, message: str) -> str:
        spec = self.context.modules.get(module_name)
        if spec is None:
            return f"Unknown module '{module_name}'. Use /list to inspect available modules."
        if spec.handler is None:
            return f"Module '{module_name}' has no callable handler."
        try:
            result = spec.handler(message, self.context)
            self.context.diagnostics.log(f"Invoked module {module_name!r} with message {message!r}")
            return str(result)
        except Exception as exc:
            self.context.diagnostics.log(f"Handler error in {module_name}: {exc}")
            return f"Error running '{module_name}': {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Direct-run modular Deck runtime")
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print discovered modules and exit",
    )
    args = parser.parse_args()

    runtime = DeckRuntime(Path(__file__))
    runtime.discover_external_modules()

    issues = runtime.validate_startup()
    if issues:
        print("Startup validator warnings:")
        for issue in issues:
            print(f"- {issue}")

    if args.list:
        print(json.dumps(runtime.context.categories.snapshot(), indent=2))
        return 0

    runtime.run_prompt_interface()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
