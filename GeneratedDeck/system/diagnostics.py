from __future__ import annotations

from datetime import datetime, timezone


class Diagnostics:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def _log(self, level: str, message: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = f"[{timestamp}] [{level}] {message}"
        self.records.append((level, entry))
        print(entry)

    def info(self, message: str) -> None:
        self._log("INFO", message)

    def warning(self, message: str) -> None:
        self._log("WARN", message)

    def error(self, message: str) -> None:
        self._log("ERROR", message)
