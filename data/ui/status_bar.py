# ui/status_bar.py
from PyQt5 import QtWidgets

from .theme import STATUS_STYLES


class StatusController:
    """Точка и подпись статуса. Не знает про LLM."""

    def __init__(self, indicator: QtWidgets.QLabel, label: QtWidgets.QLabel):
        self.indicator = indicator
        self.label = label

    def set(self, kind: str, detail: str = ""):
        color, text = STATUS_STYLES.get(kind, ("#9ab", kind or "…"))
        if detail:
            text = f"{text} {detail}".strip()
        if self.indicator is not None:
            self.indicator.setStyleSheet(f"color: {color}; font-size: 16px;")
            self.indicator.setToolTip(text)
        if self.label is not None:
            self.label.setText(text)
            self.label.setStyleSheet(
                f"color:{color}; font-size:12px; padding:0 8px; min-width:90px;"
            )
