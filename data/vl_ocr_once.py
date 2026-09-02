# один кадр + 8B VL, без GUI
# D:\asistent\python\python.exe D:\asistent\data\vl_ocr_once.py
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from screen_watch import capture_jpeg, ocr_via_vl

path = capture_jpeg(text="центральный монитор")
print("jpeg:", path)
if not path:
    raise SystemExit("нет кадра")
txt = ocr_via_vl(path)
print("--- VL ---")
print(txt or "(пусто)")
