# settings_ui.tab_aliases — управление алиасами приложений/команд
from PyQt5 import QtWidgets, QtCore
import os


class TabAliasesMixin:
    """Вкладка «Алиасы»: просмотр / добавление / удаление без SQL."""

    def _get_scanner(self):
        try:
            parent = getattr(self, "parent", None)
            if parent and getattr(parent, "assistant", None):
                ex = getattr(parent.assistant, "executor", None)
                if ex and getattr(ex, "app_scanner", None):
                    return ex.app_scanner
        except Exception:
            pass
        try:
            from app_scanner import AppScanner
            import config
            db = getattr(config, "APP_SCANNER_DB", "apps.db")
            return AppScanner(db)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Алиасы", f"AppScanner недоступен: {e}")
            return None

    def _setup_aliases_tab(self, tab):
        layout = QtWidgets.QVBoxLayout(tab)

        hint = QtWidgets.QLabel(
            "Алиасы: короткое имя → приложение / файл / папка / URL.\n"
            "Тип «command» в SAFE_MODE лучше не использовать (shell)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#aaa; margin-bottom:6px;")
        layout.addWidget(hint)

        self.aliases_table = QtWidgets.QTableWidget(0, 5)
        self.aliases_table.setHorizontalHeaderLabels(
            ["Алиас", "Цель", "Тип", "Использований", "Описание"]
        )
        self.aliases_table.horizontalHeader().setStretchLastSection(True)
        self.aliases_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.aliases_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.aliases_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.aliases_table)

        form = QtWidgets.QFormLayout()
        self.alias_name_edit = QtWidgets.QLineEdit()
        self.alias_name_edit.setPlaceholderText("например: блокнот")
        form.addRow("Имя алиаса:", self.alias_name_edit)

        self.alias_target_edit = QtWidgets.QLineEdit()
        self.alias_target_edit.setPlaceholderText(r"C:\...\app.exe  или  https://...")
        form.addRow("Цель:", self.alias_target_edit)

        self.alias_type_combo = QtWidgets.QComboBox()
        self.alias_type_combo.addItem("app", "app")
        self.alias_type_combo.addItem("file", "file")
        self.alias_type_combo.addItem("folder", "folder")
        self.alias_type_combo.addItem("url", "url")
        # command скрыт по умолчанию — security
        form.addRow("Тип:", self.alias_type_combo)

        self.alias_desc_edit = QtWidgets.QLineEdit()
        self.alias_desc_edit.setPlaceholderText("опционально")
        form.addRow("Описание:", self.alias_desc_edit)
        layout.addLayout(form)

        btn_row = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("Добавить")
        add_btn.clicked.connect(self._aliases_add)
        btn_row.addWidget(add_btn)

        browse_btn = QtWidgets.QPushButton("Обзор…")
        browse_btn.clicked.connect(self._aliases_browse)
        btn_row.addWidget(browse_btn)

        del_btn = QtWidgets.QPushButton("Удалить выбранный")
        del_btn.clicked.connect(self._aliases_delete)
        btn_row.addWidget(del_btn)

        refresh_btn = QtWidgets.QPushButton("Обновить")
        refresh_btn.clicked.connect(self._reload_aliases_table)
        btn_row.addWidget(refresh_btn)

        scan_btn = QtWidgets.QPushButton("Сканировать приложения")
        scan_btn.clicked.connect(self._aliases_scan)
        btn_row.addWidget(scan_btn)
        layout.addLayout(btn_row)

        self._reload_aliases_table()

    def _reload_aliases_table(self, *_):
        table = getattr(self, "aliases_table", None)
        if table is None:
            return
        table.setRowCount(0)
        sc = self._get_scanner()
        if not sc:
            return
        try:
            rows = sc.list_aliases() or []
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Алиасы", str(e))
            return
        for a in rows:
            r = table.rowCount()
            table.insertRow(r)
            vals = [
                a.get("alias", ""),
                a.get("target", ""),
                a.get("type", ""),
                str(a.get("usage_count", 0)),
                a.get("description", "") or "",
            ]
            for c, v in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(str(v))
                if c == 0:
                    item.setData(QtCore.Qt.UserRole, a.get("alias", ""))
                table.setItem(r, c, item)

    def _aliases_browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Выберите exe / файл", "", "Программы (*.exe);;Все (*.*)"
        )
        if path:
            self.alias_target_edit.setText(path)
            if not self.alias_name_edit.text().strip():
                base = os.path.splitext(os.path.basename(path))[0]
                self.alias_name_edit.setText(base.lower())
            self.alias_type_combo.setCurrentIndex(0)

    def _aliases_add(self):
        name = (self.alias_name_edit.text() or "").strip().lower()
        target = (self.alias_target_edit.text() or "").strip()
        type_ = self.alias_type_combo.currentData() or "app"
        desc = (self.alias_desc_edit.text() or "").strip()
        if not name or not target:
            QtWidgets.QMessageBox.information(self, "Алиасы", "Укажи имя и цель")
            return
        sc = self._get_scanner()
        if not sc:
            return
        try:
            ok = sc.add_alias(name, target, type_, desc)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Алиасы", str(e))
            return
        if ok:
            self.alias_name_edit.clear()
            self.alias_target_edit.clear()
            self.alias_desc_edit.clear()
            self._reload_aliases_table()
        else:
            QtWidgets.QMessageBox.warning(self, "Алиасы", "Не удалось добавить (дубликат?)")

    def _aliases_delete(self):
        rows = self.aliases_table.selectionModel().selectedRows()
        if not rows:
            QtWidgets.QMessageBox.information(self, "Алиасы", "Выбери строку")
            return
        item = self.aliases_table.item(rows[0].row(), 0)
        alias = item.data(QtCore.Qt.UserRole) if item else None
        if not alias:
            return
        if QtWidgets.QMessageBox.question(
            self, "Удалить", f"Удалить алиас «{alias}»?"
        ) != QtWidgets.QMessageBox.Yes:
            return
        sc = self._get_scanner()
        if not sc:
            return
        try:
            sc.delete_alias(alias)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Алиасы", str(e))
        self._reload_aliases_table()

    def _aliases_scan(self):
        sc = self._get_scanner()
        if not sc:
            return
        try:
            msg = sc.scan_system(force=True)
            QtWidgets.QMessageBox.information(self, "Сканирование", str(msg))
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Сканирование", str(e))
