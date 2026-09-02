# train_emotion_model.py — дообучение модели эмоций (CUDA / CPU)
"""
Запуск:
  cd /d D:\\asistent\\data
  ..\\python\\python.exe train_emotion_model.py

Если нет accelerate:
  ..\\python\\python.exe -m pip install "accelerate>=1.1.0"

Данные: emotion_training_data.json
Результат: models/emotion_model/
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score

try:
    import config
    MODELS_DIR = Path(getattr(config, "MODELS_DIR", Path(__file__).parent / "models"))
    DATA_DIR = Path(getattr(config, "DATA_DIR", Path(__file__).parent))
except Exception:
    MODELS_DIR = Path(__file__).parent / "models"
    DATA_DIR = Path(__file__).parent

BASE_MODEL = "cointegrated/rubert-tiny"
DATA_FILE = DATA_DIR / "emotion_training_data.json"
OUTPUT_DIR = MODELS_DIR / "emotion_model"

EPOCHS = 8
BATCH = 16
LR = 3e-5
MAX_LEN = 128


def load_data(path: Path):
    if not path.exists():
        print(f"❌ Нет файла {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data = [x for x in data if x.get("text") and x.get("emotion")]
    print(f"📥 Загружено примеров: {len(data)}")
    return data


def build_label_maps(data):
    labels = sorted({x["emotion"].strip().lower() for x in data})
    label2id = {l: i for i, l in enumerate(labels)}
    id2label = {i: l for l, i in label2id.items()}
    print(f"📋 Классы ({len(labels)}): {labels}")
    for l in labels:
        n = sum(1 for x in data if x["emotion"].strip().lower() == l)
        print(f"   {l}: {n}")
    return label2id, id2label


def encode_texts(tokenizer, texts):
    enc = tokenizer(
        list(texts),
        truncation=True,
        padding="max_length",
        max_length=MAX_LEN,
        return_tensors="pt",
    )
    return enc["input_ids"], enc["attention_mask"]


def evaluate(model, loader, device):
    model.eval()
    all_preds, all_labels = [], []
    total_loss = 0.0
    crit = nn.CrossEntropyLoss()
    with torch.no_grad():
        for input_ids, attention_mask, labels in loader:
            input_ids = input_ids.to(device)
            attention_mask = attention_mask.to(device)
            labels = labels.to(device)
            out = model(input_ids=input_ids, attention_mask=attention_mask)
            loss = crit(out.logits, labels)
            total_loss += float(loss.item()) * labels.size(0)
            preds = out.logits.argmax(dim=-1)
            all_preds.extend(preds.cpu().numpy().tolist())
            all_labels.extend(labels.cpu().numpy().tolist())
    n = max(len(all_labels), 1)
    acc = float(accuracy_score(all_labels, all_preds))
    f1 = float(f1_score(all_labels, all_preds, average="weighted"))
    return total_loss / n, acc, f1


def train_torch(model, train_loader, val_loader, device, epochs=EPOCHS):
    """Обучение без transformers.Trainer / accelerate."""
    model.to(device)
    optim = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=0.01)
    crit = nn.CrossEntropyLoss()
    best_f1 = -1.0
    best_state = None

    use_cuda = device.type == "cuda"
    scaler = torch.cuda.amp.GradScaler(enabled=use_cuda)

    for epoch in range(1, epochs + 1):
        model.train()
        running = 0.0
        n_seen = 0
        for input_ids, attention_mask, labels in train_loader:
            input_ids = input_ids.to(device, non_blocking=use_cuda)
            attention_mask = attention_mask.to(device, non_blocking=use_cuda)
            labels = labels.to(device, non_blocking=use_cuda)

            optim.zero_grad(set_to_none=True)
            with torch.cuda.amp.autocast(enabled=use_cuda):
                out = model(input_ids=input_ids, attention_mask=attention_mask)
                loss = crit(out.logits, labels)

            scaler.scale(loss).backward()
            scaler.step(optim)
            scaler.update()

            bs = labels.size(0)
            running += float(loss.item()) * bs
            n_seen += bs

        train_loss = running / max(n_seen, 1)
        val_loss, val_acc, val_f1 = evaluate(model, val_loader, device)
        print(
            f"  epoch {epoch}/{epochs}  "
            f"train_loss={train_loss:.4f}  val_loss={val_loss:.4f}  "
            f"val_acc={val_acc:.3f}  val_f1={val_f1:.3f}"
        )
        if val_f1 >= best_f1:
            best_f1 = val_f1
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

    if best_state is not None:
        model.load_state_dict(best_state)
        print(f"⭐ Лучший val_f1={best_f1:.3f} восстановлен")
    return model


def try_train_with_trainer(model, tokenizer, train_texts, train_y, val_texts, val_y, id2label, label2id):
    """Опциональный путь через HF Trainer (нужен accelerate)."""
    try:
        import accelerate  # noqa: F401
        from transformers import Trainer, TrainingArguments
        from datasets import Dataset
    except Exception as e:
        print(f"ℹ️ Trainer недоступен ({e}) — используем PyTorch-цикл")
        return None

    def tok(batch):
        return tokenizer(
            batch["text"], truncation=True, padding="max_length", max_length=MAX_LEN
        )

    train_ds = Dataset.from_dict({"text": train_texts, "label": train_y}).map(tok, batched=True)
    val_ds = Dataset.from_dict({"text": val_texts, "label": val_y}).map(tok, batched=True)
    cols = ["input_ids", "attention_mask", "label"]
    train_ds.set_format("torch", columns=cols)
    val_ds.set_format("torch", columns=cols)

    sig = inspect.signature(TrainingArguments.__init__)
    params = set(sig.parameters.keys())
    ta = {
        "output_dir": str(OUTPUT_DIR / "checkpoints"),
        "num_train_epochs": EPOCHS,
        "per_device_train_batch_size": BATCH,
        "per_device_eval_batch_size": BATCH,
        "learning_rate": LR,
        "logging_steps": 20,
        "save_total_limit": 2,
        "load_best_model_at_end": True,
        "metric_for_best_model": "f1",
        "greater_is_better": True,
        "report_to": [],
    }
    if "eval_strategy" in params:
        ta["eval_strategy"] = "epoch"
        ta["save_strategy"] = "epoch"
    elif "evaluation_strategy" in params:
        ta["evaluation_strategy"] = "epoch"
        ta["save_strategy"] = "epoch"
    if "fp16" in params and torch.cuda.is_available():
        ta["fp16"] = True
    ta = {k: v for k, v in ta.items() if k in params or k == "output_dir"}

    def metrics(eval_pred):
        logits, labels = eval_pred
        preds = np.argmax(logits, axis=-1)
        return {
            "accuracy": float(accuracy_score(labels, preds)),
            "f1": float(f1_score(labels, preds, average="weighted")),
        }

    try:
        args = TrainingArguments(**ta)
        trainer = Trainer(
            model=model,
            args=args,
            train_dataset=train_ds,
            eval_dataset=val_ds,
            compute_metrics=metrics,
        )
        print("🚀 Trainer (accelerate)...")
        trainer.train()
        trainer.save_model(str(OUTPUT_DIR))
        tokenizer.save_pretrained(str(OUTPUT_DIR))
        return model
    except Exception as e:
        print(f"⚠️ Trainer упал: {e}")
        print("   Переключаюсь на PyTorch-цикл...")
        return None


def main():
    print("=" * 70)
    print("🦊 ДООБУЧЕНИЕ МОДЕЛИ ЭМОЦИЙ")
    print("=" * 70)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"🖥️  device: {device}")
    if device.type == "cuda":
        print(f"   GPU: {torch.cuda.get_device_name(0)}")
        print(f"   CUDA: {torch.version.cuda}")

    data = load_data(DATA_FILE)
    label2id, id2label = build_label_maps(data)
    texts = [x["text"] for x in data]
    y = [label2id[x["emotion"].strip().lower()] for x in data]

    try:
        train_texts, val_texts, train_y, val_y = train_test_split(
            texts, y, test_size=0.15, random_state=42, stratify=y
        )
    except ValueError:
        train_texts, val_texts, train_y, val_y = train_test_split(
            texts, y, test_size=0.15, random_state=42
        )

    print(f"📦 train={len(train_texts)} val={len(val_texts)}")
    print(f"📥 Базовая модель: {BASE_MODEL}")

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL,
        num_labels=len(label2id),
        id2label=id2label,
        label2id=label2id,
        ignore_mismatched_sizes=True,
    )
    model.config.id2label = {int(k): v for k, v in id2label.items()}
    model.config.label2id = label2id

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1) попробовать Trainer
    trained = try_train_with_trainer(
        model, tokenizer, train_texts, train_y, val_texts, val_y, id2label, label2id
    )

    # 2) fallback: чистый PyTorch (CUDA)
    if trained is None:
        print("🚀 PyTorch training loop...")
        tr_ids, tr_mask = encode_texts(tokenizer, train_texts)
        va_ids, va_mask = encode_texts(tokenizer, val_texts)
        tr_y = torch.tensor(train_y, dtype=torch.long)
        va_y = torch.tensor(val_y, dtype=torch.long)

        train_loader = DataLoader(
            TensorDataset(tr_ids, tr_mask, tr_y),
            batch_size=BATCH,
            shuffle=True,
            pin_memory=(device.type == "cuda"),
        )
        val_loader = DataLoader(
            TensorDataset(va_ids, va_mask, va_y),
            batch_size=BATCH,
            shuffle=False,
            pin_memory=(device.type == "cuda"),
        )

        model = train_torch(model, train_loader, val_loader, device, epochs=EPOCHS)
        model.save_pretrained(str(OUTPUT_DIR))
        tokenizer.save_pretrained(str(OUTPUT_DIR))

    # id2label в config.json
    cfg_path = OUTPUT_DIR / "config.json"
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["id2label"] = {str(i): lab for i, lab in id2label.items()}
        cfg["label2id"] = label2id
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    (OUTPUT_DIR / "labels.txt").write_text(
        "\n".join(f"{i}\t{lab}" for i, lab in sorted(id2label.items())),
        encoding="utf-8",
    )

    print("\n✅ Модель сохранена:", OUTPUT_DIR)

    # smoke-test
    model.to(device)
    model.eval()
    tests = [
        ("я очень устал, спать хочу", "sleepy"),
        ("я тебя люблю", "love_shy"),
        ("это бесит", "angry"),
        ("мне грустно", "sad"),
        ("ура получилось", "happy"),
        ("привет как дела", "neutral"),
        ("найди информацию", "searching"),
        ("дай подумать", "thinking"),
    ]
    print("\n🧪 Smoke-test:")
    ok = 0
    for phrase, expect in tests:
        inputs = tokenizer(phrase, return_tensors="pt", truncation=True, max_length=MAX_LEN)
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            probs = torch.softmax(model(**inputs).logits, dim=-1)[0]
        pred_i = int(torch.argmax(probs).item())
        pred = id2label[pred_i]
        conf = float(probs[pred_i])
        mark = "✅" if pred == expect else "⚠️"
        if pred == expect:
            ok += 1
        print(f"  {mark} '{phrase}' → {pred} ({conf:.2f}) [ожид. {expect}]")
    print(f"📊 {ok}/{len(tests)}")
    print("=" * 70)
    print("Перезапустите ассистента.")


if __name__ == "__main__":
    main()
