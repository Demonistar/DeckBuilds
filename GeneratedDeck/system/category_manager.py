from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CategoryModule:
    module_id: str
    module_name: str
    widget: Any


class CategoryManager:
    def __init__(self) -> None:
        self._categories: dict[str, list[CategoryModule]] = {}
        self._module_to_category: dict[str, str] = {}

    def register_module(self, module_id: str, module_name: str, primary_category: str, widget: Any) -> None:
        self._categories.setdefault(primary_category, []).append(
            CategoryModule(module_id=module_id, module_name=module_name, widget=widget)
        )
        self._module_to_category[module_id] = primary_category

    def remove_module(self, module_id: str) -> None:
        category = self._module_to_category.pop(module_id, None)
        if not category:
            return
        modules = self._categories.get(category, [])
        self._categories[category] = [m for m in modules if m.module_id != module_id]
        if not self._categories[category]:
            del self._categories[category]

    def widgets_for_category(self, category: str) -> list[tuple[str, Any]]:
        return [(m.module_name, m.widget) for m in self._categories.get(category, [])]

    def category_names(self) -> list[str]:
        return list(self._categories.keys())

    def first_category(self) -> str | None:
        return next(iter(self._categories.keys()), None)
