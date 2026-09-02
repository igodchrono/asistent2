# test_security_and_parser.py — pytest для CommandParser, IntentRouter, security
"""
Запуск из корня проекта (где config.py):
  pytest test_security_and_parser.py -q

Или без pytest:
  python test_security_and_parser.py
"""
from __future__ import annotations

import os
import sys

# корень проекта = каталог с config.py
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# минимальные stubs, если окружение без PyQt / тяжёлых deps
import types



def _stub_heavy():
    import sys, types, logging
    for name in ("aiohttp", "aiofiles", "psutil", "pyautogui"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    if "utils" not in sys.modules:
        sys.modules["utils"] = types.SimpleNamespace(
            run_in_executor=lambda f: f,
            fs_semaphore=None,
            task_pool=None,
            logger=logging.getLogger("test"),
            api_semaphore=None,
        )
    # light stubs for executor deps
    for mod, cls in (
        ("system_controller", "SystemController"),
        ("app_scanner", "AppScanner"),
        ("notes_manager", "NotesManager"),
        ("persistent_memory", "PersistentMemory"),
        ("reminder_manager", "ReminderManager"),
    ):
        if mod not in sys.modules:
            m = types.ModuleType(mod)
            setattr(m, cls, type(cls, (object,), {"__init__": lambda self, *a, **k: None}))
            sys.modules[mod] = m

_stub_heavy()

def _ensure_config():
    import config
    if not hasattr(config, "SAFE_MODE"):
        config.SAFE_MODE = True
    if not hasattr(config, "RUN_WHITELIST"):
        config.RUN_WHITELIST = [
            "notepad.exe", "explorer.exe", "calc.exe", "cmd.exe", "powershell.exe"
        ]
    if not hasattr(config, "ALLOWED_DIRS"):
        config.ALLOWED_DIRS = [os.path.expanduser("~"), ROOT]
    if not hasattr(config, "INTENT_ACCELERATE_THRESHOLD"):
        config.INTENT_ACCELERATE_THRESHOLD = 0.88
    if not hasattr(config, "ENABLE_PC_CONTROL"):
        config.ENABLE_PC_CONTROL = True
    return config


# ---------- CommandParser ----------

def test_parser_search():
    from command_parser import CommandParser
    cmds = CommandParser.parse("Сейчас найду [SEARCH кошки] 🦊")
    assert any(c["type"] == "SEARCH" and "кошки" in str(c.get("params", "")) for c in cmds)


def test_parser_shutdown_no_confirm():
    from command_parser import CommandParser
    cmds = CommandParser.parse("Выключаю [SHUTDOWN]")
    assert len(cmds) >= 1
    sh = [c for c in cmds if c["type"] == "SHUTDOWN"][0]
    assert sh["params"].get("confirm") is False or not sh["params"].get("confirm")


def test_parser_shutdown_confirm():
    from command_parser import CommandParser
    cmds = CommandParser.parse("[SHUTDOWN confirm]")
    sh = [c for c in cmds if c["type"] == "SHUTDOWN"][0]
    assert sh["params"].get("confirm") is True


def test_parser_kill_confirm():
    from command_parser import CommandParser
    cmds = CommandParser.parse("[KILL notepad.exe confirm]")
    k = [c for c in cmds if c["type"] == "KILL"][0]
    assert k["params"].get("confirm") is True
    assert "notepad" in k["params"].get("name", "").lower()


def test_parser_delete_confirm():
    from command_parser import CommandParser
    cmds = CommandParser.parse(r'[DELETE C:\Users\test\file.txt confirm]')
    d = [c for c in cmds if c["type"] == "DELETE"][0]
    assert d["params"].get("confirm") is True


def test_parser_ignores_anim_only_in_text_mix():
    from command_parser import CommandParser
    cmds = CommandParser.parse("Привет [ANIM:happy] как дела")
    assert all(c["type"] != "SEARCH" for c in cmds)


# ---------- Security helpers (CommandExecutor) ----------

def test_run_whitelist_blocks_unknown():
    _stub_heavy()
    _ensure_config()
    from command_executor import CommandExecutor
    ex = CommandExecutor.__new__(CommandExecutor)
    # не вызываем __init__ (тяжёлые deps) — только методы
    ok, reason = CommandExecutor._run_allowed(ex, "malware.exe /silent")
    assert ok is False
    assert "whitelist" in reason.lower() or "нет в" in reason.lower()


def test_run_deny_format():
    _stub_heavy()
    _ensure_config()
    from command_executor import CommandExecutor
    ex = CommandExecutor.__new__(CommandExecutor)
    ok, reason = CommandExecutor._run_allowed(ex, "format C:")
    assert ok is False


def test_run_allow_notepad():
    _stub_heavy()
    _ensure_config()
    from command_executor import CommandExecutor
    ex = CommandExecutor.__new__(CommandExecutor)
    ok, reason = CommandExecutor._run_allowed(ex, "notepad.exe")
    assert ok is True, reason


def test_shutdown_requires_confirm():
    _stub_heavy()
    _ensure_config()
    from command_executor import CommandExecutor
    ex = CommandExecutor.__new__(CommandExecutor)
    ex.system = types.SimpleNamespace()
    # _check_pc
    import config
    config.ENABLE_PC_CONTROL = True
    msg = CommandExecutor._shutdown(ex, {"confirm": False})
    assert "подтвержд" in msg.lower() or "⚠️" in msg


def test_kill_protected_process():
    _stub_heavy()
    _ensure_config()
    from command_executor import CommandExecutor
    ex = CommandExecutor.__new__(CommandExecutor)
    import config
    config.ENABLE_PC_CONTROL = True
    msg = CommandExecutor._kill(ex, {"name": "csrss.exe", "confirm": True})
    assert "защищ" in msg.lower() or "⛔" in msg


def test_path_allowed():
    _stub_heavy()
    _ensure_config()
    from command_executor import CommandExecutor
    import config
    home = os.path.expanduser("~")
    config.ALLOWED_DIRS = [home]
    ex = CommandExecutor.__new__(CommandExecutor)
    assert CommandExecutor._path_allowed(ex, os.path.join(home, "docs", "a.txt")) is True
    # путь вне whitelist
    outside = "/tmp/lisichka_forbidden_path_xyz/file.txt"
    if outside.startswith(home):
        outside = "/var/lisichka_forbidden_path_xyz/file.txt"
    assert CommandExecutor._path_allowed(ex, outside) is False


def test_intent_router_chat_goes_to_llm():
    from intent_router import IntentRouter

    class FakeAnalyzer:
        def analyze_intent(self, text):
            return {"intent": "chat", "confidence": 0.99, "params": {}, "source": "rule"}

    router = IntentRouter(analyzer=FakeAnalyzer(), intent_to_command=lambda i, p: None)
    d = router.try_accelerate("привет как дела")
    assert d.should_execute is False
    assert d.intent == "chat"


def test_intent_router_low_confidence_no_exec():
    from intent_router import IntentRouter

    class FakeAnalyzer:
        def analyze_intent(self, text):
            return {"intent": "search", "confidence": 0.5, "params": {"query": "кошки"}, "source": "ml"}

    def ito(intent, params):
        return {"type": "SEARCH", "params": params.get("query", "")}

    router = IntentRouter(analyzer=FakeAnalyzer(), intent_to_command=ito, confidence_threshold=0.88)
    d = router.try_accelerate("найди кошек")
    assert d.should_execute is False


def test_intent_router_high_conf_search_exec():
    from intent_router import IntentRouter

    class FakeAnalyzer:
        def analyze_intent(self, text):
            return {"intent": "search", "confidence": 0.95, "params": {"query": "кошки"}, "source": "rule"}

    def ito(intent, params):
        q = (params or {}).get("query") or ""
        if not q:
            return None
        return {"type": "SEARCH", "params": q}

    router = IntentRouter(analyzer=FakeAnalyzer(), intent_to_command=ito, confidence_threshold=0.88)
    d = router.try_accelerate("найди кошек")
    assert d.should_execute is True
    assert d.command["type"] == "SEARCH"


def test_intent_router_shutdown_never_accelerate():
    from intent_router import IntentRouter

    class FakeAnalyzer:
        def analyze_intent(self, text):
            return {
                "intent": "system_control",
                "confidence": 0.99,
                "params": {"action": "shutdown"},
                "source": "rule",
            }

    def ito(intent, params):
        return {"type": "SHUTDOWN", "params": {"confirm": False}}

    router = IntentRouter(analyzer=FakeAnalyzer(), intent_to_command=ito)
    d = router.try_accelerate("выключи компьютер")
    assert d.should_execute is False



def test_run_injection_substring_blocked():
    """Раньше: w_base in low → 'malware notepad.exe' проходил."""
    _stub_heavy()
    _ensure_config()
    from command_executor import CommandExecutor
    ex = CommandExecutor.__new__(CommandExecutor)
    ok, reason = CommandExecutor._run_allowed(ex, "malware.exe notepad.exe")
    assert ok is False, reason
    ok2, _ = CommandExecutor._run_allowed(ex, 'cmd.exe /c "format C:"')
    assert ok2 is False


def test_run_cmd_c_blocked():
    _stub_heavy()
    _ensure_config()
    from command_executor import CommandExecutor
    ex = CommandExecutor.__new__(CommandExecutor)
    ok, reason = CommandExecutor._run_allowed(ex, "cmd.exe /c whoami")
    assert ok is False


def test_path_traversal_realpath():
    _stub_heavy()
    _ensure_config()
    from command_executor import CommandExecutor
    import config
    data = getattr(config, "DATA_DIR", ROOT)
    config.ALLOWED_DIRS = [data]
    config.HARD_SANDBOX = True
    config.SAFE_MODE = True
    ex = CommandExecutor.__new__(CommandExecutor)
    # путь с .. должен резолвиться; если ушёл за ALLOWED — False
    sneaky = os.path.join(data, "..", "..", "Windows", "System32", "cmd.exe")
    assert CommandExecutor._path_allowed(ex, sneaky) is False


def main():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  OK  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f" FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
