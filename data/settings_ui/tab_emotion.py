# settings_ui — вкладки диалога настроек (сплит settings_dialog)
from PyQt5 import QtWidgets, QtGui, QtCore
import os
import config

class TabEmotionMixin:
    def _setup_emotion_tab(self, tab):
        layout = QtWidgets.QVBoxLayout(tab)

        self.show_avatar_cb = QtWidgets.QCheckBox("Показывать аватар на рабочем столе")
        layout.addWidget(self.show_avatar_cb)

        self.nsfw_enabled_cb = QtWidgets.QCheckBox("🔞 Разрешить NSFW анимации")
        self.nsfw_enabled_cb.setStyleSheet("color: #ff6b6b; font-weight: bold;")
        layout.addWidget(self.nsfw_enabled_cb)

        layout.addWidget(QtWidgets.QLabel("Частота NSFW (0-100%):"))
        self.nsfw_frequency_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.nsfw_frequency_slider.setRange(0, 100)
        self.nsfw_frequency_slider.valueChanged.connect(self.update_nsfw_label)
        nsfw_layout = QtWidgets.QHBoxLayout()
        nsfw_layout.addWidget(self.nsfw_frequency_slider)
        self.nsfw_frequency_label = QtWidgets.QLabel("45%")
        nsfw_layout.addWidget(self.nsfw_frequency_label)
        layout.addLayout(nsfw_layout)

        layout.addWidget(QtWidgets.QLabel("Анимация по умолчанию:"))
        self.default_anim_combo = QtWidgets.QComboBox()
        self.default_anim_combo.addItems(["neutral", "happy", "idle", "thinking", "love"])
        layout.addWidget(self.default_anim_combo)

        layout.addStretch()
