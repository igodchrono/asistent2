# settings_ui/tab_memory.py — долговременная память
from PyQt5 import QtWidgets, QtCore
import config


class MemoryTabMixin:
    """Вкладка 🧠 Память."""

    def _setup_memory_tab(self, tab):
        """Просмотр долговременной памяти (запомни / [REMEMBER])."""
        layout = QtWidgets.QVBoxLayout(tab)

        info = QtWidgets.QLabel(
            "Память <b>выбранного персонажа</b> + общие слои (user/pc/global). "
            "Скоуп <code>character:имя</code> — только этот персонаж. "
            "Ссылки с пометкой «не открывать» хранятся как <code>blocked_url</code>."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(info)

        filt = QtWidgets.QHBoxLayout()
        filt.addWidget(QtWidgets.QLabel("Категория:"))
        self.memory_cat_combo = QtWidgets.QComboBox()
        self.memory_cat_combo.addItem("Все", "")
        self.memory_cat_combo.currentIndexChanged.connect(self._reload_memory_table)
        filt.addWidget(self.memory_cat_combo)
        search_lbl = QtWidgets.QLabel("Поиск:")
        filt.addWidget(search_lbl)
        self.memory_search_edit = QtWidgets.QLineEdit()
        self.memory_search_edit.setPlaceholderText("фрагмент key/value…")
        self.memory_search_edit.textChanged.connect(self._reload_memory_table)
        filt.addWidget(self.memory_search_edit)
        refresh = QtWidgets.QPushButton("🔄")
        refresh.setFixedWidth(36)
        refresh.clicked.connect(self._reload_memory_table)
        filt.addWidget(refresh)
        layout.addLayout(filt)

        self.memory_table = QtWidgets.QTableWidget(0, 6)
        self.memory_table.setHorizontalHeaderLabels(
            ["ID", "Скоуп", "Категория", "Ключ", "Значение", "Обновлено"]
        )
        self.memory_table.horizontalHeader().setStretchLastSection(True)
        self.memory_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.memory_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.memory_table.setAlternatingRowColors(True)
        layout.addWidget(self.memory_table)

        self.memory_stats_label = QtWidgets.QLabel("")
        layout.addWidget(self.memory_stats_label)

        btn = QtWidgets.QHBoxLayout()
        del_btn = QtWidgets.QPushButton("🗑 Удалить выбранное")
        del_btn.clicked.connect(self._delete_selected_memory)
        btn.addWidget(del_btn)
        open_db = QtWidgets.QPushButton("📂 Папка с БД")
        open_db.clicked.connect(self._open_memory_db_folder)
        btn.addWidget(open_db)
        btn.addStretch()
        layout.addLayout(btn)

        how = QtWidgets.QLabel(
            "Как попадает в память:\n"
            "• Ты: «запомни, что меня зовут …» → модель пишет [REMEMBER name: …]\n"
            "• Ассистент сохраняет category/key/value в БД\n"
            "• При следующих репликах куски подмешиваются в промпт (get_context_for_prompt)"
        )
        how.setWordWrap(True)
        how.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(how)

        self._reload_memory_table()

    def _get_pm(self):
        try:
            from persistent_memory import PersistentMemory
            path = getattr(config, "PERSISTENT_MEMORY_DB", "persistent_memory.db")
            return PersistentMemory(path)
        except Exception as e:
            logger_err = getattr(__import__("utils", fromlist=["logger"]), "logger", None)
            if logger_err:
                logger_err.error(f"PM open: {e}")
            return None

    def _reload_memory_table(self, *_):
        if not hasattr(self, "memory_table"):
            return
        pm = self._get_pm()
        if not pm:
            self.memory_stats_label.setText("Не удалось открыть persistent_memory.db")
            return
        try:
            cats = pm.list_categories()
            cur = self.memory_cat_combo.currentData() if self.memory_cat_combo.count() else ""
            self.memory_cat_combo.blockSignals(True)
            self.memory_cat_combo.clear()
            self.memory_cat_combo.addItem("Все", "")
            for c in cats:
                self.memory_cat_combo.addItem(f'{c["category"]} ({c["count"]})', c["category"])
            if cur:
                for i in range(self.memory_cat_combo.count()):
                    if self.memory_cat_combo.itemData(i) == cur:
                        self.memory_cat_combo.setCurrentIndex(i)
                        break
            self.memory_cat_combo.blockSignals(False)

            cat_filter = self.memory_cat_combo.currentData() or None
            # Память выбранного персонажа + общие скоупы (user/pc/global)
            try:
                from memory_scope import ui_memory_scopes, active_character, character_scope
                scopes = ui_memory_scopes()
                who = active_character()
            except Exception:
                scopes = None
                who = getattr(config, "ACTIVE_CHARACTER", "лисичка")
                character_scope = lambda n=None: f"character:{n or who}"

            if scopes is not None:
                rows = []
                seen = set()
                for sc in scopes:
                    part = pm.list_all(scope=sc, category=cat_filter, limit=300) or []
                    for r in part:
                        rid = r.get("id")
                        if rid in seen:
                            continue
                        seen.add(rid)
                        rows.append(r)
                # На случай старых записей без скоупа персонажа
                more = pm.list_all(scope=None, category=cat_filter, limit=500) or []
                for r in more:
                    rid = r.get("id")
                    if rid in seen:
                        continue
                    sc = (r.get("scope") or "")
                    if sc in (scopes or []) or sc.startswith("character:"):
                        seen.add(rid)
                        rows.append(r)
            else:
                rows = pm.list_all(scope=None, category=cat_filter, limit=400) or []

            q = (self.memory_search_edit.text() or "").strip().lower()
            if q:
                rows = [
                    r for r in rows
                    if q in (r.get("key") or "").lower()
                    or q in (r.get("value") or "").lower()
                    or q in (r.get("category") or "").lower()
                    or q in (r.get("scope") or "").lower()
                ]

            # Сортируем: сначала character:текущий, потом user/pc, global
            def _ord(r):
                sc = r.get("scope") or ""
                if sc == character_scope(who):
                    return 0
                if sc == "user":
                    return 1
                if sc in ("pc", "project"):
                    return 2
                if sc == "global":
                    return 3
                return 4
            rows.sort(key=_ord)

            self.memory_table.setRowCount(0)
            for r in rows:
                i = self.memory_table.rowCount()
                self.memory_table.insertRow(i)
                vals = [
                    str(r.get("id", "")),
                    str(r.get("scope", "")),
                    str(r.get("category", "")),
                    str(r.get("key", ""))[:80],
                    str(r.get("value", ""))[:200],
                    str(r.get("updated_at", "") or r.get("created_at", "")),
                ]
                for col, v in enumerate(vals):
                    item = QtWidgets.QTableWidgetItem(v)
                    if col == 0:
                        item.setData(QtCore.Qt.UserRole, r.get("id"))
                    self.memory_table.setItem(i, col, item)

            try:
                st = pm.get_stats()
                self.memory_stats_label.setText(
                    f"Персонаж: {who}  |  показано: {len(rows)}  |  всего в БД: {st}"
                )
            except Exception:
                self.memory_stats_label.setText(f"Персонаж: {who}  |  показано: {len(rows)}")
        except Exception as e:
            self.memory_stats_label.setText(f"Ошибка: {e}")
        finally:
            try:
                pm.close()
            except Exception:
                pass

    def _delete_selected_memory(self):
        rows = self.memory_table.selectionModel().selectedRows()
        if not rows:
            QtWidgets.QMessageBox.information(self, "Память", "Выбери строку")
            return
        ids = []
        for idx in rows:
            item = self.memory_table.item(idx.row(), 0)
            if item:
                mid = item.data(QtCore.Qt.UserRole) or item.text()
                try:
                    ids.append(int(mid))
                except Exception:
                    pass
        if not ids:
            return
        if QtWidgets.QMessageBox.question(
            self, "Удалить", f"Удалить записей: {len(ids)}?"
        ) != QtWidgets.QMessageBox.Yes:
            return
        pm = self._get_pm()
        if not pm:
            return
        try:
            for mid in ids:
                pm.delete_memory(mid)
        finally:
            try:
                pm.close()
            except Exception:
                pass
        self._reload_memory_table()

    def _open_memory_db_folder(self):
        import os, sys, subprocess
        path = getattr(config, "PERSISTENT_MEMORY_DB", "persistent_memory.db")
        folder = os.path.dirname(os.path.abspath(path)) or os.getcwd()
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Память", str(e))

