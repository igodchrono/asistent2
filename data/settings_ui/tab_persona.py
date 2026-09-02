# settings_ui/tab_persona.py — персонаж / пользователь
from PyQt5 import QtWidgets, QtCore
import os
import config

CHARACTER_GUIDE_HTML = """
<b>Как правильно писать персонажа</b><br>
Файл — обычный Markdown. Модель читает <b>только эти заголовки</b>
(имя можно менять, заголовки лучше не ломать):
<ul>
<li><b>## Кто она</b> — имя, возраст, кто такая, как обращаться к хозяину</li>
<li><b>## Внешность</b> — канон вида. Без этого блока модель выдумает другой образ</li>
<li><b>## Характер</b> — нрав, границы, когда злится / флиртует</li>
<li><b>## Как говорит</b> — манера: «хозяин» или «ты», длина фраз, эмодзи</li>
<li><b>## Примеры тона</b> — 2–4 коротких диалога в её стиле</li>
<li><b>## Блок для system prompt</b> — 2–4 предложения «ты — …» (сжатый канон)</li>
</ul>
Пиши конкретно и коротко. Один персонаж — один файл в
<b>personas/characters/</b>. Смена персонажа: выбери файл выше и сохрани настройки.
"""

CHARACTER_SECTIONS_SNIPPET = """## Кто она
- Имя:
- Возраст:
- Сущность:
- Обращение к пользователю:

## Внешность
- волосы / глаза / отличительные черты
- обычная одежда
Не выдумывай другой вид.

## Характер
- 4–6 пунктов: нрав, что любит, когда злится, границы

## Как говорит
- обращение
- длина фраз
- эмодзи / без эмодзи
- чего в речи не делать

## Примеры тона
**Хозяин:** привет
**Имя:** …

## Блок для system prompt
Ты — … Внешность: … Характер: … Речь: …
"""

USER_GUIDE_HTML = """
<b>Профиль пользователя</b> — не характер ассистента.<br>
Полезные заголовки: <b>## Как обращаться</b>, <b>## Предпочтения</b>,
<b>## Что важно помнить</b>.
"""


class PersonaTabMixin:
    """Вкладка 🎭 Персонаж."""

    def _setup_persona_tab(self, tab):
        """Выбор файлов характера и пользователя (папка personas/)."""
        layout = QtWidgets.QVBoxLayout(tab)

        hint = QtWidgets.QLabel(CHARACTER_GUIDE_HTML)
        hint.setWordWrap(True)
        hint.setTextFormat(QtCore.Qt.RichText)
        hint.setStyleSheet(
            "color: #c8c8c8; font-size: 11px; background: #2a2a2a; "
            "padding: 8px; border-radius: 6px;"
        )
        layout.addWidget(hint)

        layout.addWidget(QtWidgets.QLabel("<b>Персонаж (характер)</b>"))
        self.character_combo = QtWidgets.QComboBox()
        self.character_combo.setMinimumWidth(280)
        self.character_combo.currentIndexChanged.connect(self._on_persona_changed)
        layout.addWidget(self.character_combo)

        layout.addWidget(QtWidgets.QLabel("<b>Пользователь (профиль)</b>"))
        self.user_persona_combo = QtWidgets.QComboBox()
        self.user_persona_combo.setMinimumWidth(280)
        self.user_persona_combo.currentIndexChanged.connect(self._on_persona_changed)
        layout.addWidget(self.user_persona_combo)

        btn_row = QtWidgets.QHBoxLayout()
        refresh_btn = QtWidgets.QPushButton("🔄 Обновить список")
        refresh_btn.setToolTip("Перечитать папку personas без перезапуска.")
        refresh_btn.clicked.connect(self._refresh_persona_lists)
        btn_row.addWidget(refresh_btn)

        open_char_btn = QtWidgets.QPushButton("✏️ Редактировать персонажа")
        open_char_btn.setToolTip("Открыть .md персонажа в блокноте. Значок и запрет анимаций — в этом файле.")
        open_char_btn.clicked.connect(lambda: self._open_persona_file("character"))
        btn_row.addWidget(open_char_btn)

        open_user_btn = QtWidgets.QPushButton("✏️ Редактировать пользователя")
        open_user_btn.setToolTip("Открыть профиль пользователя (как к тебе обращаться).")
        open_user_btn.clicked.connect(lambda: self._open_persona_file("user"))
        btn_row.addWidget(open_user_btn)
        layout.addLayout(btn_row)

        btn_row2 = QtWidgets.QHBoxLayout()
        new_char = QtWidgets.QPushButton("＋ Новый персонаж")
        new_char.setToolTip("Создать personas/characters/<имя>.md из шаблона.")
        new_char.clicked.connect(lambda: self._create_persona("character"))
        btn_row2.addWidget(new_char)
        new_user = QtWidgets.QPushButton("＋ Новый профиль пользователя")
        new_user.setToolTip("Создать новый файл в personas/users/.")
        new_user.clicked.connect(lambda: self._create_persona("user"))
        btn_row2.addWidget(new_user)
        open_folder = QtWidgets.QPushButton("📂 Папка personas")
        open_folder.setToolTip("Открыть папку со всеми карточками персонажей и профилей.")
        open_folder.clicked.connect(self._open_persona_folder)
        btn_row2.addWidget(open_folder)
        layout.addLayout(btn_row2)

        previews = QtWidgets.QHBoxLayout()

        col_c = QtWidgets.QVBoxLayout()
        col_c.addWidget(QtWidgets.QLabel("<b>Превью персонажа</b>"))
        self.character_preview = QtWidgets.QPlainTextEdit()
        self.character_preview.setReadOnly(True)
        self.character_preview.setMinimumHeight(180)
        self.character_preview.setMaximumHeight(280)
        col_c.addWidget(self.character_preview)
        self.character_path_label = QtWidgets.QLabel("")
        self.character_path_label.setStyleSheet("color: #888; font-size: 10px;")
        self.character_path_label.setWordWrap(True)
        col_c.addWidget(self.character_path_label)
        previews.addLayout(col_c)

        col_u = QtWidgets.QVBoxLayout()
        col_u.addWidget(QtWidgets.QLabel("<b>Превью пользователя</b>"))
        self.user_preview = QtWidgets.QPlainTextEdit()
        self.user_preview.setReadOnly(True)
        self.user_preview.setMinimumHeight(180)
        self.user_preview.setMaximumHeight(280)
        col_u.addWidget(self.user_preview)
        self.user_path_label = QtWidgets.QLabel("")
        self.user_path_label.setStyleSheet("color: #888; font-size: 10px;")
        self.user_path_label.setWordWrap(True)
        col_u.addWidget(self.user_path_label)
        previews.addLayout(col_u)

        layout.addLayout(previews)

        self.persona_preview = self.character_preview
        self.persona_path_label = self.character_path_label

        layout.addStretch()
        self._refresh_persona_lists()

    def _refresh_persona_lists(self):
        try:
            import character_manager as cm
            cm.ensure_persona_dirs()
            cm.migrate_legacy_files()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Persona", f"character_manager: {e}")
            return

        import character_manager as cm
        chars = cm.list_characters()
        users = cm.list_users()

        cur_c = getattr(config, "ACTIVE_CHARACTER", "лисичка") or "лисичка"
        cur_u = getattr(config, "ACTIVE_USER", "default") or "default"

        if hasattr(self, "character_combo"):
            self.character_combo.blockSignals(True)
            self.character_combo.clear()
            for c in chars:
                self.character_combo.addItem(c["name"], c["id"])
            for i in range(self.character_combo.count()):
                if self.character_combo.itemData(i) == cur_c:
                    self.character_combo.setCurrentIndex(i)
                    break
            self.character_combo.blockSignals(False)

        if hasattr(self, "user_persona_combo"):
            self.user_persona_combo.blockSignals(True)
            self.user_persona_combo.clear()
            for u in users:
                self.user_persona_combo.addItem(u["name"], u["id"])
            for i in range(self.user_persona_combo.count()):
                if self.user_persona_combo.itemData(i) == cur_u:
                    self.user_persona_combo.setCurrentIndex(i)
                    break
            self.user_persona_combo.blockSignals(False)

        self._on_persona_changed()

    def _on_persona_changed(self, *_):
        """Обновляет оба превью: персонаж + пользователь."""
        try:
            import character_manager as cm
            # --- character ---
            cid = self.character_combo.currentData() if hasattr(self, "character_combo") else None
            cpath = cm._resolve_md("characters", cid) if cid else None
            if hasattr(self, "character_preview"):
                if cpath and cpath.is_file():
                    self.character_preview.setPlainText(cm.read_preview(cpath, max_chars=4000))
                    self.character_path_label.setText(str(cpath))
                else:
                    self.character_preview.setPlainText("(нет файла персонажа)")
                    self.character_path_label.setText("")
            # --- user ---
            uid = self.user_persona_combo.currentData() if hasattr(self, "user_persona_combo") else None
            upath = cm._resolve_md("users", uid) if uid else None
            if hasattr(self, "user_preview"):
                if upath and upath.is_file():
                    self.user_preview.setPlainText(cm.read_preview(upath, max_chars=4000))
                    self.user_path_label.setText(str(upath))
                else:
                    self.user_preview.setPlainText("(нет файла пользователя)")
                    self.user_path_label.setText("")
        except Exception as e:
            msg = f"Ошибка превью: {e}"
            if hasattr(self, "character_preview"):
                self.character_preview.setPlainText(msg)
            if hasattr(self, "user_preview"):
                self.user_preview.setPlainText(msg)

    def _open_persona_file(self, kind: str):
        """
        Редактор .md внутри приложения (не os.startfile — WinError 1155).
        kind: 'character' | 'user'
        """
        try:
            import character_manager as cm
            if kind == "character":
                pid = self.character_combo.currentData() if hasattr(self, "character_combo") else None
                path = cm._resolve_md("characters", pid) if pid else None
                title = "Редактор персонажа"
            else:
                pid = self.user_persona_combo.currentData() if hasattr(self, "user_persona_combo") else None
                path = cm._resolve_md("users", pid) if pid else None
                title = "Редактор профиля пользователя"

            if not path or not path.is_file():
                QtWidgets.QMessageBox.warning(
                    self,
                    "Persona",
                    "Файл не найден для «%s».\nВыберите другой пункт или создайте новый." % (pid,),
                )
                return

            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self, "Persona", "Не удалось прочитать файл:\n%s" % (e,)
                )
                return

            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("%s — %s" % (title, path.name))
            dlg.resize(720, 640)
            v = QtWidgets.QVBoxLayout(dlg)
            info = QtWidgets.QLabel(str(path))
            info.setStyleSheet("color:#888; font-size:10px;")
            info.setWordWrap(True)
            v.addWidget(info)

            guide = QtWidgets.QLabel(
                CHARACTER_GUIDE_HTML if kind == "character" else USER_GUIDE_HTML
            )
            guide.setWordWrap(True)
            guide.setTextFormat(QtCore.Qt.RichText)
            guide.setStyleSheet(
                "color:#c8c8c8; font-size:11px; background:#2a2a2a; "
                "padding:8px; border-radius:6px;"
            )
            v.addWidget(guide)

            editor = QtWidgets.QPlainTextEdit()
            editor.setPlainText(text)
            editor.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
            v.addWidget(editor)

            if kind == "character":
                insert_btn = QtWidgets.QPushButton("Вставить недостающие заголовки")
                def _insert_sections():
                    cur = editor.toPlainText()
                    missing = []
                    for header in (
                        "## Кто она",
                        "## Внешность",
                        "## Характер",
                        "## Как говорит",
                        "## Примеры тона",
                        "## Блок для system prompt",
                    ):
                        if header.lower() not in cur.lower():
                            missing.append(header)
                    if not missing:
                        QtWidgets.QMessageBox.information(
                            dlg, "Persona", "Все нужные заголовки уже есть."
                        )
                        return
                    editor.appendPlainText("\n\n" + CHARACTER_SECTIONS_SNIPPET)
                insert_btn.clicked.connect(_insert_sections)
                v.addWidget(insert_btn)

            buttons = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
            )
            v.addWidget(buttons)

            def _do_save():
                try:
                    path.write_text(editor.toPlainText(), encoding="utf-8")
                    QtWidgets.QMessageBox.information(dlg, "Persona", "Сохранено.")
                    self._on_persona_changed()
                    dlg.accept()
                except Exception as e:
                    QtWidgets.QMessageBox.critical(
                        dlg, "Persona", "Ошибка записи:\n%s" % (e,)
                    )

            buttons.rejected.connect(dlg.reject)
            save_btn = buttons.button(QtWidgets.QDialogButtonBox.Save)
            save_btn.clicked.connect(_do_save)
            dlg.exec_()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Persona", str(e))

    def _create_persona(self, kind: str):
        try:
            import character_manager as cm
            name, ok = QtWidgets.QInputDialog.getText(
                self, "Новый профиль",
                "Имя файла (без .md):",
            )
            if not ok or not name.strip():
                return
            if kind == "character":
                path = cm.create_character(name.strip())
            else:
                path = cm.create_user(name.strip())
            self._refresh_persona_lists()
            QtWidgets.QMessageBox.information(
                self, "Persona", f"Создано:\n{path}\nОтредактируй и нажми Сохранить в настройках."
            )
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Persona", str(e))

    def _open_persona_folder(self):
        try:
            import character_manager as cm
            import subprocess, sys
            root = cm.ensure_persona_dirs()
            if sys.platform == "win32":
                os.startfile(str(root))
            else:
                subprocess.Popen(["xdg-open", str(root)])
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Persona", str(e))

