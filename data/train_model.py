# train_model.py
"""
Скрипт для дообучения модели интентов.
Оптимизирован для большого количества классов.
"""

import json
import os
import torch
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    Trainer,
    TrainingArguments,
    EarlyStoppingCallback
)
from datasets import Dataset
import numpy as np
from sklearn.metrics import accuracy_score, f1_score

# ============================================================
# 1. ЗАГРУЗКА ДАННЫХ
# ============================================================

def load_training_data(filepath: str = "training_data.json") -> list:
    """Загрузка данных для обучения."""
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        print(f"⚠️ Файл {filepath} не найден!")
        return []


# ============================================================
# 2. ПОДГОТОВКА ДАННЫХ
# ============================================================

def prepare_dataset(data: list) -> tuple:
    """Подготовка датасета для обучения."""
    texts = [item['text'] for item in data]
    intents = [item['intent'] for item in data]
    
    # Создаем маппинг интентов
    unique_intents = sorted(list(set(intents)))
    intent_to_id = {intent: i for i, intent in enumerate(unique_intents)}
    id_to_intent = {i: intent for intent, i in intent_to_id.items()}
    
    labels = [intent_to_id[intent] for intent in intents]
    
    print(f"\n📊 Всего примеров: {len(data)}")
    print(f"📋 Интенты: {unique_intents}")
    print(f"📋 Распределение:")
    for intent in unique_intents:
        count = sum(1 for i in intents if i == intent)
        print(f"   {intent}: {count} примеров")
    
    return Dataset.from_dict({
        'text': texts,
        'label': labels
    }), intent_to_id, id_to_intent


# ============================================================
# 3. ТОКЕНИЗАЦИЯ
# ============================================================

def tokenize_function(examples, tokenizer):
    """Токенизация для обучения."""
    return tokenizer(
        examples['text'],
        padding='max_length',
        truncation=True,
        max_length=128,
        return_tensors='pt'
    )


# ============================================================
# 4. МЕТРИКИ
# ============================================================

def compute_metrics(eval_pred):
    """Вычисление метрик."""
    predictions = eval_pred.predictions
    labels = eval_pred.label_ids
    preds = np.argmax(predictions, axis=1)
    
    accuracy = accuracy_score(labels, preds)
    f1 = f1_score(labels, preds, average='weighted')
    
    return {
        'accuracy': accuracy,
        'f1': f1,
    }


# ============================================================
# 5. ОСНОВНАЯ ФУНКЦИЯ ОБУЧЕНИЯ
# ============================================================

def train_intent_model(
    data_file: str = "training_data.json",
    model_name: str = "cointegrated/rubert-tiny",
    output_dir: str = "./models/intent_model",
    epochs: int = 15,
    batch_size: int = 16,
    learning_rate: float = 3e-5,
    test_size: float = 0.1
):
    """
    Дообучение модели интентов.
    """
    print("\n" + "=" * 70)
    print("🦊 ДООБУЧЕНИЕ МОДЕЛИ ИНТЕНТОВ")
    print("=" * 70)
    
    # Загружаем данные
    data = load_training_data(data_file)
    if len(data) < 10:
        print("⚠️ Слишком мало данных для обучения!")
        return
    
    # Подготовка данных
    dataset, intent_to_id, id_to_intent = prepare_dataset(data)
    num_labels = len(intent_to_id)
    
    # Разделяем на train/validation
    dataset = dataset.train_test_split(test_size=test_size)
    train_dataset = dataset['train']
    eval_dataset = dataset['test']
    
    print(f"\n📚 Обучающая выборка: {len(train_dataset)} примеров")
    print(f"📚 Валидационная выборка: {len(eval_dataset)} примеров")
    print(f"📋 Количество классов: {num_labels}")
    
    # Загружаем токенизатор
    print(f"\n📥 Загрузка модели {model_name}...")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    
    # Токенизация
    train_dataset = train_dataset.map(
        lambda x: tokenize_function(x, tokenizer),
        batched=True,
        remove_columns=['text']
    )
    eval_dataset = eval_dataset.map(
        lambda x: tokenize_function(x, tokenizer),
        batched=True,
        remove_columns=['text']
    )
    
    # Загружаем модель с правильным количеством классов
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        num_labels=num_labels,
        ignore_mismatched_sizes=True
    )
    
    # Проверяем наличие GPU
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"💻 Устройство: {device}")
    
    # Настройки обучения (оптимизированные)
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size * 2,
        learning_rate=learning_rate,
        warmup_steps=50,
        weight_decay=0.01,
        logging_steps=20,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="accuracy",
        report_to="none",
        fp16=(device == "cuda"),
        gradient_accumulation_steps=2,
        save_total_limit=2,
        dataloader_num_workers=2,
    )
    
    # Создаем тренер
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=5)],
    )
    
    # Обучение
    print("\n🚀 Начинаем дообучение...")
    print(f"📊 Эпох: {epochs}, Размер батча: {batch_size}")
    trainer.train()
    
    # Сохраняем модель
    print(f"\n💾 Сохраняем модель в {output_dir}...")
    os.makedirs(output_dir, exist_ok=True)
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    
    # Сохраняем маппинг интентов
    with open(f'{output_dir}/intents.json', 'w', encoding='utf-8') as f:
        json.dump({
            'intents': list(intent_to_id.keys()),
            'intent_to_id': intent_to_id,
            'id_to_intent': id_to_intent
        }, f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 70)
    print("✅ ДООБУЧЕНИЕ ЗАВЕРШЕНО!")
    print("=" * 70)
    print(f"📁 Модель сохранена: {output_dir}")
    
    # Тестирование
    test_model(output_dir)


# ============================================================
# 6. ТЕСТИРОВАНИЕ
# ============================================================

def test_model(model_path: str):
    """Тестирование обученной модели."""
    print("\n🧪 ТЕСТИРОВАНИЕ МОДЕЛИ")
    print("=" * 70)
    
    # Загружаем модель
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForSequenceClassification.from_pretrained(model_path)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    model.eval()
    
    # Загружаем интенты
    with open(f'{model_path}/intents.json', 'r', encoding='utf-8') as f:
        intents_data = json.load(f)
        id_to_intent = intents_data['id_to_intent']
    
    # Тестовые фразы
    test_phrases = [
        "запусти калькулятор",
        "найди рецепт пиццы",
        "я тебя люблю",
        "выключи компьютер",
        "сделай громче",
        "как дела?",
        "напомни позвонить",
        "сделай скриншот",
        "открой браузер",
        "запиши идею",
        "ты красивая",
        "разденься",
        "что такое любовь"
    ]
    
    print("\nРезультаты:")
    correct = 0
    expected = {
        "запусти калькулятор": "launch_app",
        "найди рецепт пиццы": "search",
        "я тебя люблю": "love",
        "выключи компьютер": "system_control",
        "сделай громче": "volume_control",
        "как дела?": "chat",
        "напомни позвонить": "reminder",
        "сделай скриншот": "screenshot",
        "открой браузер": "open_browser",
        "запиши идею": "notes",
        "ты красивая": "flirty",
        "разденься": "undress",
        "что такое любовь": "question"
    }
    
    for phrase in test_phrases:
        inputs = tokenizer(
            phrase,
            return_tensors='pt',
            truncation=True,
            padding=True,
            max_length=128
        )
        inputs = {k: v.to(device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = model(**inputs)
            probs = torch.softmax(outputs.logits, dim=1)
            confidence, predicted = torch.max(probs, dim=1)
            
            intent = id_to_intent[str(predicted.item())]
            confidence = confidence.item()
            
            expected_intent = expected.get(phrase, "?")
            is_correct = intent == expected_intent
            if is_correct:
                correct += 1
            
            status = "✅" if is_correct else "❌"
            print(f"  {status} '{phrase}' → {intent} (уверенность: {confidence:.2f}) [ожидалось: {expected_intent}]")
    
    print(f"\n📊 Точность: {correct}/{len(test_phrases)} = {correct/len(test_phrases)*100:.1f}%")
    print("=" * 70)


# ============================================================
# 7. ГЛАВНАЯ ФУНКЦИЯ
# ============================================================

def main():
    """Главная функция с меню."""
    print("\n" + "=" * 70)
    print("🦊 УПРАВЛЕНИЕ ДООБУЧЕНИЕМ МОДЕЛИ")
    print("=" * 70)
    print("\nВыберите действие:")
    print("  1. Дообучить модель (15 эпох, улучшенные параметры)")
    print("  2. Добавить примеры вручную")
    print("  3. Интерактивный сбор данных")
    print("  4. Выход")
    
    choice = input("\nВаш выбор (1-4): ").strip()
    
    if choice == "1":
        train_intent_model(epochs=15, learning_rate=3e-5, batch_size=16)
    elif choice == "2":
        text = input("📝 Фраза: ").strip()
        intent = input("🎯 Интент: ").strip().lower()
        data = load_training_data()
        data.append({"text": text, "intent": intent})
        with open("training_data.json", 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ Добавлено! Всего: {len(data)} примеров")
    elif choice == "3":
        print("Интерактивный режим")
        data = load_training_data()
        while True:
            text = input("\n📝 Фраза (exit для выхода): ").strip()
            if text.lower() == 'exit':
                break
            if not text:
                continue
            intent = input("🎯 Интент: ").strip().lower()
            data.append({"text": text, "intent": intent})
            with open("training_data.json", 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"✅ Добавлено! Всего: {len(data)} примеров")
    elif choice == "4":
        print("До свидания! 🦊")
    else:
        print("Неверный выбор. Запускаем дообучение...")
        train_intent_model(epochs=15, learning_rate=3e-5, batch_size=16)


if __name__ == "__main__":
    main()