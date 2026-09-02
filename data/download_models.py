# download_models.py
"""
Скрипт для скачивания моделей для Лисички.
Запустите один раз для загрузки всех необходимых моделей.
Модели займут ~30 МБ на диске.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

def get_data_dir():
    """Определяет правильную папку data."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Если мы уже в папке data
    if os.path.basename(script_dir) == "data":
        data_dir = script_dir
    else:
        # Ищем папку data рядом
        possible_data = os.path.join(script_dir, "data")
        if os.path.exists(possible_data) and os.path.isdir(possible_data):
            data_dir = possible_data
        else:
            # Создаем data рядом
            data_dir = os.path.join(script_dir, "data")
    
    # Проверяем, нет ли внутри data/data
    inner_data = os.path.join(data_dir, "data")
    if os.path.exists(inner_data) and os.path.isdir(inner_data):
        data_dir = inner_data
    
    os.makedirs(data_dir, exist_ok=True)
    return data_dir

def download_models():
    """Скачивание всех необходимых моделей."""
    
    print("=" * 70)
    print("🦊 СКАЧИВАНИЕ МОДЕЛЕЙ ДЛЯ ЛИСИЧКИ")
    print("=" * 70)
    
    # Определяем пути
    data_dir = get_data_dir()
    models_dir = os.path.join(data_dir, "models")
    intent_path = os.path.join(models_dir, "intent_model")
    emotion_path = os.path.join(models_dir, "emotion_model")
    
    # Создаем папки
    os.makedirs(models_dir, exist_ok=True)
    os.makedirs(intent_path, exist_ok=True)
    os.makedirs(emotion_path, exist_ok=True)
    
    print(f"\n📁 DATA_DIR: {data_dir}")
    print(f"📁 MODELS_DIR: {models_dir}")
    print(f"📁 Python: {sys.executable}")
    print("=" * 70)
    
    # Проверяем установленные пакеты
    print("\n🔍 Проверка зависимостей...")
    
    try:
        import transformers
        print(f"   ✅ transformers: {transformers.__version__}")
    except ImportError:
        print("   ❌ transformers не установлен")
        print("   Установите: pip install transformers")
        return False
    
    try:
        import torch
        print(f"   ✅ torch: {torch.__version__}")
        print(f"   ✅ CUDA доступна: {torch.cuda.is_available()}")
    except ImportError:
        print("   ❌ torch не установлен")
        print("   Установите: pip install torch")
        return False
    
    print("\n" + "=" * 70)
    
    # ===== МОДЕЛЬ 1: ИНТЕНТЫ =====
    print("\n📥 [1/2] Скачивание модели для интентов (cointegrated/rubert-tiny)...")
    print(f"   📁 Сохранение в: {intent_path}")
    
    try:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        
        print("   ⏳ Загрузка из Hugging Face... (может занять 1-2 минуты)")
        tokenizer = AutoTokenizer.from_pretrained("cointegrated/rubert-tiny")
        model = AutoModelForSequenceClassification.from_pretrained(
            "cointegrated/rubert-tiny",
            num_labels=10
        )
        
        print("   💾 Сохранение на диск...")
        tokenizer.save_pretrained(intent_path)
        model.save_pretrained(intent_path)
        
        files = os.listdir(intent_path)
        print(f"   ✅ Модель интентов сохранена! ({len(files)} файлов)")
        for f in files:
            size = os.path.getsize(os.path.join(intent_path, f))
            if size > 1024 * 1024:
                print(f"      📄 {f} ({size // (1024 * 1024)} MB)")
            elif size > 1024:
                print(f"      📄 {f} ({size // 1024} KB)")
            else:
                print(f"      📄 {f} ({size} B)")
                
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        print("   Попробуйте скачать вручную с huggingface.co")
        return False
    
    # ===== МОДЕЛЬ 2: ЭМОЦИИ =====
    print("\n📥 [2/2] Скачивание модели для эмоций (cointegrated/rubert-tiny-toxicity)...")
    print(f"   📁 Сохранение в: {emotion_path}")
    
    try:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        
        print("   ⏳ Загрузка из Hugging Face... (может занять 1-2 минуты)")
        tokenizer = AutoTokenizer.from_pretrained("cointegrated/rubert-tiny-toxicity")
        model = AutoModelForSequenceClassification.from_pretrained(
            "cointegrated/rubert-tiny-toxicity"
        )
        
        print("   💾 Сохранение на диск...")
        tokenizer.save_pretrained(emotion_path)
        model.save_pretrained(emotion_path)
        
        files = os.listdir(emotion_path)
        print(f"   ✅ Модель эмоций сохранена! ({len(files)} файлов)")
        for f in files:
            size = os.path.getsize(os.path.join(emotion_path, f))
            if size > 1024 * 1024:
                print(f"      📄 {f} ({size // (1024 * 1024)} MB)")
            elif size > 1024:
                print(f"      📄 {f} ({size // 1024} KB)")
            else:
                print(f"      📄 {f} ({size} B)")
                
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        print("   Попробуйте скачать вручную с huggingface.co")
        return False
    
    # ===== СОЗДАЕМ ФАЙЛ INTENTS =====
    print("\n📝 Создание файла intents.json...")
    try:
        import json
        intents_data = {
            "intents": [
                "search",
                "launch_app",
                "open_browser",
                "file_operation",
                "system_control",
                "reminder",
                "notes",
                "chat",
                "love",
                "question",
                "screenshot",
                "volume_control"
            ]
        }
        intents_file = os.path.join(intent_path, "intents.json")
        with open(intents_file, 'w', encoding='utf-8') as f:
            json.dump(intents_data, f, ensure_ascii=False, indent=2)
        print(f"   ✅ Создан {intents_file}")
    except Exception as e:
        print(f"   ⚠️ Не удалось создать intents.json: {e}")
    
    # ===== РЕЗУЛЬТАТ =====
    print("\n" + "=" * 70)
    print("✅ ВСЕ МОДЕЛИ СКАЧАНЫ!")
    print("=" * 70)
    print(f"\n📁 Модели сохранены в: {models_dir}")
    print("\n📊 ИТОГО:")
    print(f"   • Модель интентов: {intent_path}")
    print(f"   • Модель эмоций: {emotion_path}")
    print(f"   • Общий размер: ~30 МБ")
    print("\n🚀 Теперь можно запускать ассистента:")
    print("   python main.py")
    print("=" * 70)
    
    return True

def check_models():
    """Проверка наличия моделей."""
    print("\n" + "=" * 70)
    print("🔍 ПРОВЕРКА НАЛИЧИЯ МОДЕЛЕЙ")
    print("=" * 70)
    
    data_dir = get_data_dir()
    models_dir = os.path.join(data_dir, "models")
    intent_path = os.path.join(models_dir, "intent_model")
    emotion_path = os.path.join(models_dir, "emotion_model")
    
    print(f"\n📁 DATA_DIR: {data_dir}")
    print(f"📁 MODELS_DIR: {models_dir}")
    
    all_ok = True
    
    for name, path in [("Intent", intent_path), ("Emotion", emotion_path)]:
        print(f"\n📂 {name} модель: {path}")
        if os.path.exists(path):
            files = os.listdir(path)
            print(f"   ✅ Папка существует ({len(files)} файлов)")
            
            required = ["config.json", "tokenizer_config.json", "vocab.txt"]
            model_files = ["model.safetensors", "pytorch_model.bin"]
            
            for req in required:
                if os.path.exists(os.path.join(path, req)):
                    print(f"      ✅ {req}")
                else:
                    print(f"      ❌ {req} отсутствует")
                    all_ok = False
            
            has_model = False
            for mf in model_files:
                if os.path.exists(os.path.join(path, mf)):
                    size = os.path.getsize(os.path.join(path, mf))
                    if size > 1024 * 1024:
                        print(f"      ✅ {mf} ({size // (1024 * 1024)} MB)")
                    elif size > 1024:
                        print(f"      ✅ {mf} ({size // 1024} KB)")
                    else:
                        print(f"      ✅ {mf} ({size} B)")
                    has_model = True
                    break
            if not has_model:
                print(f"      ❌ model.safetensors или pytorch_model.bin отсутствует")
                all_ok = False
                
        else:
            print(f"   ❌ Папка не существует")
            all_ok = False
    
    print("\n" + "=" * 70)
    if all_ok:
        print("✅ Все модели на месте!")
    else:
        print("❌ Некоторые модели отсутствуют!")
        print("   Запустите: python download_models.py")
    print("=" * 70)
    
    return all_ok

def main():
    """Главная функция с меню."""
    print("\n" + "=" * 70)
    print("🦊 УПРАВЛЕНИЕ МОДЕЛЯМИ ЛИСИЧКИ")
    print("=" * 70)
    print("\nВыберите действие:")
    print("  1. Скачать/обновить модели (рекомендуется)")
    print("  2. Проверить наличие моделей")
    print("  3. Выход")
    
    choice = input("\nВаш выбор (1-3): ").strip()
    
    if choice == "1":
        download_models()
    elif choice == "2":
        check_models()
    elif choice == "3":
        print("До свидания! 🦊")
    else:
        print("Неверный выбор. Запускаем скачивание...")
        download_models()

if __name__ == "__main__":
    main()