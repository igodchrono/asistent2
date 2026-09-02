# settings_ui — вкладки SettingsDialog (mixins)
from .tab_main import MainTabMixin
from .tab_voice import VoiceTabMixin
from .tab_memory import MemoryTabMixin
from .tab_persona import PersonaTabMixin
from .tab_greeting import GreetingTabMixin
from .tab_test import TestTabMixin

__all__ = [
    "MainTabMixin", "VoiceTabMixin", "MemoryTabMixin",
    "PersonaTabMixin", "GreetingTabMixin", "TestTabMixin",
]
