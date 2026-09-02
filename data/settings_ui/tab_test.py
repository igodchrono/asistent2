# settings_ui/tab_test.py — unit-тесты безопасности
from PyQt5 import QtWidgets, QtGui, QtCore
import config


class TestTabMixin:
    """Вкладка 🧪 Тест."""

    def _setup_test_tab(self, tab):
        """Вкладка запуска unit-тестов безопасности и парсера."""
        layout = QtWidgets.QVBoxLayout(tab)

        info = QtWidgets.QLabel(
            "Проверка CommandParser, IntentRouter, whitelist RUN, confirm\n"
            "для опасных команд и ALLOWED_DIRS.\n"
            "Файл: test_security_and_parser.py (рядом с main.py)."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #aaa; margin-bottom: 8px;")
        layout.addWidget(info)

        btn_row = QtWidgets.QHBoxLayout()
        self.test_run_btn = QtWidgets.QPushButton("▶ Запустить тесты")
        self.test_run_btn.clicked.connect(self._run_security_tests)
        btn_row.addWidget(self.test_run_btn)

        self.test_clear_btn = QtWidgets.QPushButton("Очистить лог")
        self.test_clear_btn.clicked.connect(lambda: self.test_output.clear())
        btn_row.addWidget(self.test_clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.test_status = QtWidgets.QLabel("Готово к запуску")
        self.test_status.setStyleSheet("color: #8ab; font-weight: 600;")
        layout.addWidget(self.test_status)

        self.test_output = QtWidgets.QPlainTextEdit()
        self.test_output.setReadOnly(True)
        self.test_output.setPlaceholderText("Результат тестов появится здесь…")
        mono = QtGui.QFont("Consolas", 10)
        if not QtGui.QFontInfo(mono).family():
            mono = QtGui.QFont("Courier New", 10)
        self.test_output.setFont(mono)
        self.test_output.setStyleSheet(
            "QPlainTextEdit { background: #1a1d23; color: #d8d8d8; "
            "border: 1px solid #333; border-radius: 6px; padding: 6px; }"
        )
        layout.addWidget(self.test_output)

        hint = QtWidgets.QLabel(
            "Тесты не трогают систему (kill/shutdown только проверяют отказ без confirm)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(hint)

    def _run_security_tests(self):
        """Запуск test_security_and_parser.py в фоне."""
        import os
        import sys
        import subprocess
        from pathlib import Path

        # корень проекта: рядом с config / main
        candidates = [
            Path(getattr(config, "BASE_DIR", "") or ""),
            Path(__file__).resolve().parent,
            Path.cwd(),
        ]
        test_file = None
        for base in candidates:
            if not base:
                continue
            p = base / "test_security_and_parser.py"
            if p.is_file():
                test_file = p
                break

        if not test_file:
            self.test_output.setPlainText(
                "❌ Не найден test_security_and_parser.py\n"
                "Положи файл в корень проекта (рядом с main.py / config.py)."
            )
            self.test_status.setText("Файл тестов не найден")
            self.test_status.setStyleSheet("color: #e66; font-weight: 600;")
            return

        self.test_run_btn.setEnabled(False)
        self.test_status.setText("Выполняется…")
        self.test_status.setStyleSheet("color: #fc6; font-weight: 600;")
        self.test_output.setPlainText(f"▶ {sys.executable} {test_file}\n\n")

        self._test_proc = QtCore.QProcess(self)
        self._test_proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self._test_proc.setWorkingDirectory(str(test_file.parent))
        self._test_proc.readyReadStandardOutput.connect(self._on_test_output)
        self._test_proc.finished.connect(self._on_test_finished)
        self._test_proc.start(sys.executable, [str(test_file)])
        if not self._test_proc.waitForStarted(3000):
            self.test_output.appendPlainText("❌ Не удалось запустить процесс Python")
            self.test_run_btn.setEnabled(True)
            self.test_status.setText("Ошибка запуска")
            self.test_status.setStyleSheet("color: #e66; font-weight: 600;")

    def _on_test_output(self):
        if not hasattr(self, "_test_proc") or self._test_proc is None:
            return
        data = self._test_proc.readAllStandardOutput()
        try:
            text = bytes(data).decode("utf-8", errors="replace")
        except Exception:
            text = str(data)
        # config.py при импорте печатает баннер — оставляем, но можно свернуть
        self.test_output.moveCursor(QtGui.QTextCursor.End)
        self.test_output.insertPlainText(text)
        self.test_output.moveCursor(QtGui.QTextCursor.End)

    def _on_test_finished(self, exit_code, exit_status):
        self.test_run_btn.setEnabled(True)
        if exit_code == 0:
            self.test_status.setText("✅ Все тесты прошли")
            self.test_status.setStyleSheet("color: #6c6; font-weight: 600;")
            self.test_output.appendPlainText("\n——— ГОТОВО (exit 0) ———")
        else:
            self.test_status.setText(f"❌ Есть ошибки (код {exit_code})")
            self.test_status.setStyleSheet("color: #e66; font-weight: 600;")
            self.test_output.appendPlainText(f"\n——— ЗАВЕРШЕНО С ОШИБКОЙ (exit {exit_code}) ———")
