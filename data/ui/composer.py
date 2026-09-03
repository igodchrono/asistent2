# ui/composer.py — поле ввода и кнопки
from PyQt5 import QtWidgets, QtGui


class ComposerBar(QtWidgets.QWidget):
    """Нижняя панель: статус + поле + кнопки. Логика остаётся в окне."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout_ = QtWidgets.QHBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)

        self.status_indicator = QtWidgets.QLabel("●")
        self.status_indicator.setStyleSheet("color: #0f0; font-size: 16px;")
        self.status_indicator.setToolTip("Соединение с API установлено")
        self.layout_.addWidget(self.status_indicator)

        self.status_label = QtWidgets.QLabel("готово")
        self.status_label.setStyleSheet(
            "color:#9ab; font-size:12px; padding:0 8px; min-width:90px;"
        )
        self.status_label.setToolTip("Статус ассистента")
        self.layout_.addWidget(self.status_label)

        self.input_field = QtWidgets.QLineEdit()
        self.input_field.setPlaceholderText("Введите сообщение...")
        self.layout_.addWidget(self.input_field)

        self.send_btn = QtWidgets.QPushButton("Отправить")
        self.layout_.addWidget(self.send_btn)

        self.attach_btn = QtWidgets.QPushButton("📎")
        self.attach_btn.setToolTip("Прикрепить файл")
        self.layout_.addWidget(self.attach_btn)

        self.voice_btn = None

        self.sound_btn = QtWidgets.QPushButton()
        self.layout_.addWidget(self.sound_btn)

        self.clear_btn = QtWidgets.QPushButton("🗑️")
        self.clear_btn.setToolTip("Очистить историю")
        self.layout_.addWidget(self.clear_btn)

        self.settings_btn = QtWidgets.QPushButton("⚙️")
        self.settings_btn.setToolTip("Настройки")
        self.layout_.addWidget(self.settings_btn)

    def add_voice_button(self):
        self.voice_btn = QtWidgets.QPushButton("🎤")
        self.voice_btn.setToolTip("Голосовой ввод")
        # перед кнопкой звука
        idx = self.layout_.indexOf(self.sound_btn)
        self.layout_.insertWidget(idx, self.voice_btn)
        return self.voice_btn

    def set_controls_enabled(self, enabled: bool):
        self.send_btn.setEnabled(enabled)
        self.attach_btn.setEnabled(enabled)
        if self.voice_btn is not None:
            self.voice_btn.setEnabled(enabled)
        self.clear_btn.setEnabled(enabled)
        self.settings_btn.setEnabled(enabled)
        self.input_field.setEnabled(enabled)
