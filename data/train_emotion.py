# train_emotion.py — обучение emotion_model (не интенты)
import json
import os
import numpy as np
import torch
from datasets import Dataset
from sklearn.metrics import accuracy_score, f1_score
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    EarlyStoppingCallback,
    Trainer,
    TrainingArguments,
)

DATA_CANDIDATES = [
    "emotion_training_data_merged.json",
    "emotion_training_data.json",
]
OUTPUT_DIR = os.path.join("models", "emotion_model")
BASE_MODEL = "cointegrated/rubert-tiny"


def load_data():
    for name in DATA_CANDIDATES:
        if os.path.isfile(name):
            with open(name, encoding="utf-8") as f:
                data = json.load(f)
            print(f"📄 Данные: {name} ({len(data)} фраз)")
            return data, name
    raise SystemExit(
        "Нет emotion_training_data_merged.json и emotion_training_data.json "
        "в папке data"
    )


def compute_metrics(eval_pred):
    preds = np.argmax(eval_pred.predictions, axis=1)
    return {
        "accuracy": accuracy_score(eval_pred.label_ids, preds),
        "f1": f1_score(eval_pred.label_ids, preds, average="weighted"),
    }


def main():
    print("=" * 70)
    print("🦊 ОБУЧЕНИЕ МОДЕЛИ ЭМОЦИЙ")
    print("=" * 70)
    data, _ = load_data()
    rows = []
    for item in data:
        text = " ".join(str(item.get("text", "")).split()).strip()
        emo = str(item.get("emotion") or item.get("intent") or "").strip().lower()
        if text and emo:
            rows.append((text, emo))
    if len(rows) < 20:
        raise SystemExit("Слишком мало строк")

    labels = sorted({e for _, e in rows})
    lab2id = {e: i for i, e in enumerate(labels)}
    id2lab = {i: e for e, i in lab2id.items()}
    print(f"Классов: {len(labels)}")
    for e in labels:
        print(f"  {e}: {sum(1 for _, x in rows if x == e)}")

    ds = Dataset.from_dict({
        "text": [t for t, _ in rows],
        "label": [lab2id[e] for _, e in rows],
    }).train_test_split(test_size=0.1, seed=42)

    tok = AutoTokenizer.from_pretrained(BASE_MODEL)

    def tokenize(batch):
        return tok(batch["text"], padding="max_length", truncation=True, max_length=128)

    train_ds = ds["train"].map(tokenize, batched=True, remove_columns=["text"])
    eval_ds = ds["test"].map(tokenize, batched=True, remove_columns=["text"])

    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL,
        num_labels=len(labels),
        id2label={str(i): e for i, e in id2lab.items()},
        label2id=lab2id,
        ignore_mismatched_sizes=True,
    )
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("Устройство:", device)

    common = dict(
        output_dir=OUTPUT_DIR + "_runs",
        num_train_epochs=8,
        per_device_train_batch_size=16,
        per_device_eval_batch_size=32,
        learning_rate=3e-5,
        warmup_steps=80,
        weight_decay=0.01,
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        report_to="none",
        fp16=(device == "cuda"),
        save_total_limit=2,
    )
    try:
        args = TrainingArguments(eval_strategy="epoch", save_strategy="epoch", **common)
    except TypeError:
        args = TrainingArguments(evaluation_strategy="epoch", save_strategy="epoch", **common)
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=3)],
    )
    trainer.train()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    trainer.save_model(OUTPUT_DIR)
    tok.save_pretrained(OUTPUT_DIR)
    with open(os.path.join(OUTPUT_DIR, "emotions.json"), "w", encoding="utf-8") as f:
        json.dump({"labels": labels, "label_to_id": lab2id, "id_to_label": {str(k): v for k, v in id2lab.items()}}, f, ensure_ascii=False, indent=2)
    print("Сохранено в", os.path.abspath(OUTPUT_DIR))
    probes = [
        "поплачь", "поспи", "найди котиков", "найди хентай",
        "найди как платить налог", "я тебя люблю", "бесит",
    ]
    model.eval()
    model.to(device)
    print("Пробы:")
    for phrase in probes:
        inputs = tok(phrase, return_tensors="pt", truncation=True, max_length=128)
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            logits = model(**inputs).logits
            prob = torch.softmax(logits, dim=1)[0]
            i = int(prob.argmax())
            print(f"  {phrase!r:30s} -> {id2lab[i]:15s} {float(prob[i]):.2f}")


if __name__ == "__main__":
    main()
