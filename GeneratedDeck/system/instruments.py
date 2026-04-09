from __future__ import annotations

from dataclasses import dataclass


@dataclass
class InstrumentReading:
    name: str
    value: str


class Instruments:
    def __init__(self) -> None:
        self.readings: dict[str, InstrumentReading] = {}

    def set_reading(self, name: str, value: str) -> None:
        self.readings[name] = InstrumentReading(name=name, value=value)

    def get_reading(self, name: str) -> InstrumentReading | None:
        return self.readings.get(name)
