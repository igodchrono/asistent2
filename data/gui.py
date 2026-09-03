# gui.py — совместимость со старым импортом:
#   from gui import AssistantWindow
#
# Реализация окна лежит в пакете ui/.
# Старый gui.py можно сохранить как gui.py.bak

from ui.window import AssistantWindow

__all__ = ["AssistantWindow"]
