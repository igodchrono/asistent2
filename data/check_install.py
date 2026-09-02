# check_install.py — проверка пакетов Лисички
import importlib
import sys

print("Python:", sys.executable)
print("Ver:", sys.version.replace("\n", " "))
print("=" * 60)

NEED = [
    ("aiohttp", True),
    ("aiosqlite", True),
    ("qasync", True),
    ("PyQt5", True),
    ("PIL", True),
    ("requests", True),
    ("numpy", True),
    ("torch", True),
    ("transformers", True),
    ("sklearn", True),
    ("datasets", False),
    ("pygame", False),
    ("edge_tts", False),
    ("speech_recognition", False),
    ("psutil", True),
    ("pyautogui", False),
    ("rapidocr_onnxruntime", True),
    ("onnxruntime", True),
    ("pytesseract", False),
    ("faiss", False),
    ("docx", False),
    ("openpyxl", False),
]

ok = miss = 0
for name, required in NEED:
    try:
        m = importlib.import_module(name)
        ver = getattr(m, "__version__", "")
        print(f"  OK   {name:24s} {ver}")
        ok += 1
    except Exception as e:
        tag = "NEED" if required else "opt "
        print(f"  {tag} {name:24s} {e.__class__.__name__}")
        if required:
            miss += 1

print("=" * 60)
try:
    import torch
    print("torch cuda:", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")
except Exception as e:
    print("torch:", e)

print("-" * 60)
print("OCR backends:")
for label, fn in (
    ("rapidocr", "rapidocr_onnxruntime"),
    ("onnxruntime", "onnxruntime"),
    ("pytesseract", "pytesseract"),
    ("easyocr", "easyocr"),
):
    try:
        importlib.import_module(fn)
        print("  OK ", label)
    except Exception:
        print("  -- ", label)

print("-" * 60)
print(f"обязательные: не хватает {miss}, найдено {ok}")
if miss:
    print("Доустанови:")
    print(f'  "{sys.executable}" -m pip install -r requirements.txt')
    sys.exit(1)
print("База стоит. OCR: нужен rapidocr-onnxruntime (уже в requirements).")
