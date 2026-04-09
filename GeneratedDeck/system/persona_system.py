from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Pronouns:
    subject: str = ""
    object: str = ""
    possessive: str = ""
    reflexive: str = ""


@dataclass
class PersonaTheme:
    light_theme_colors: dict[str, str] = field(default_factory=dict)
    dark_theme_colors: dict[str, str] = field(default_factory=dict)
    accent_colors: dict[str, str] = field(default_factory=dict)


@dataclass
class Persona:
    display_name: str
    pronouns: Pronouns
    tone_profile: str
    system_prompt: str
    theme: PersonaTheme


class PersonaManager:
    def __init__(self, settings_manager) -> None:
        self.settings_manager = settings_manager
        self._active_persona = Persona(
            display_name="Neutral",
            pronouns=Pronouns(),
            tone_profile="balanced",
            system_prompt="",
            theme=PersonaTheme(),
        )

    def active_persona(self) -> Persona:
        return self._active_persona

    def switch_persona(self, persona_data: dict) -> Persona:
        self._active_persona = Persona(
            display_name=persona_data.get("display_name", ""),
            pronouns=Pronouns(**persona_data.get("pronouns", {})),
            tone_profile=persona_data.get("tone_profile", ""),
            system_prompt=persona_data.get("system_prompt", ""),
            theme=PersonaTheme(
                light_theme_colors=persona_data.get("light_theme_colors", {}),
                dark_theme_colors=persona_data.get("dark_theme_colors", {}),
                accent_colors=persona_data.get("accent_colors", {}),
            ),
        )
        self.settings_manager.set_value("persona", persona_data)
        return self._active_persona
