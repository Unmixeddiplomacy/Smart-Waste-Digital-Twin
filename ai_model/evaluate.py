import os
import sys
import json
import numpy as np
import tensorflow as tf
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

# Constants
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(SCRIPT_DIR, "dataset")
IMG_SIZE = (224, 224)
BATCH_SIZE = 32
VALIDATION_SPLIT = 0.2
MODEL_PATH = os.path.join(SCRIPT_DIR, "model.keras")
LEGACY_MODEL_PATH = os.path.join(SCRIPT_DIR, "model.h5")
CLASS_NAMES_PATH = os.path.join(SCRIPT_DIR, "class_names.json")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "evaluation_results")


def load_validation_data(dataset_dir=DATASET_DIR):
    """Load the exact same validation split used in train.py (seed=42, categorical)."""
    if not os.path.isdir(dataset_dir):
        raise FileNotFoundError(
            f"Dataset directory not found: {dataset_dir}."
        )

    val_ds = tf.keras.utils.image_dataset_from_directory(
        dataset_dir,
        validation_split=VALIDATION_SPLIT,
        subset="validation",
        seed=42,
        image_size=IMG_SIZE,
        batch_size=BATCH_SIZE,
        label_mode="categorical",
    )
    return val_ds


def plot_confusion_matrix(cm, class_names, output_dir=OUTPUT_DIR):
    """Plot and save the confusion matrix heatmap to PNG (headless, no plt.show)."""
    os.makedirs(output_dir, exist_ok=True)

    plt.figure(figsize=(10, 8))
    sns.heatmap(
        cm,
        annot=True,
        fmt="d",
        cmap="Blues",
        xticklabels=class_names,
        yticklabels=class_names,
    )
    plt.title("Waste Classification Confusion Matrix")
    plt.xlabel("Predicted")
    plt.ylabel("True")
    plt.tight_layout()

    cm_path = os.path.join(output_dir, "confusion_matrix.png")
    plt.savefig(cm_path, dpi=150)
    plt.close()
    print(f"Confusion matrix saved to {cm_path}")
    return cm_path


def evaluate_model(
    model_path=None,
    class_names_path=CLASS_NAMES_PATH,
    dataset_dir=DATASET_DIR,
    output_dir=OUTPUT_DIR,
):
    """Load trained model, evaluate on validation split, and save report + confusion matrix."""
    os.makedirs(output_dir, exist_ok=True)

    if model_path is None:
        if os.path.exists(MODEL_PATH):
            model_path = MODEL_PATH
        elif os.path.exists(LEGACY_MODEL_PATH):
            model_path = LEGACY_MODEL_PATH
        else:
            raise FileNotFoundError(
                f"Model file not found at {MODEL_PATH} (or {LEGACY_MODEL_PATH}). "
                "Please train the model first by running train.py."
            )
    elif not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found at {model_path}.")

    if not os.path.exists(class_names_path):
        raise FileNotFoundError(
            f"Class names file not found at {class_names_path}. "
            "Please run train.py first to generate class_names.json."
        )

    print(f"Loading model from {model_path}...")
    model = tf.keras.models.load_model(model_path)

    with open(class_names_path, "r", encoding="utf-8") as f:
        class_names = json.load(f)

    val_ds = load_validation_data(dataset_dir)

    # Iterate once so predicted and true labels stay strictly aligned per batch
    y_pred_batches = []
    y_true_batches = []
    for images, labels in val_ds:
        preds = model.predict(images, verbose=0)
        y_pred_batches.append(np.argmax(preds, axis=1))
        y_true_batches.append(np.argmax(labels.numpy(), axis=1))

    y_pred = np.concatenate(y_pred_batches)
    y_true = np.concatenate(y_true_batches)

    label_indices = list(range(len(class_names)))
    acc = accuracy_score(y_true, y_pred)
    report_text = classification_report(
        y_true,
        y_pred,
        labels=label_indices,
        target_names=class_names,
        zero_division=0,
    )
    report_dict = classification_report(
        y_true,
        y_pred,
        labels=label_indices,
        target_names=class_names,
        output_dict=True,
        zero_division=0,
    )
    cm = confusion_matrix(y_true, y_pred, labels=label_indices)

    print(f"\nValidation Accuracy: {acc:.4f}\n")
    print("Classification Report:")
    print(report_text)

    report_path = os.path.join(output_dir, "classification_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2)
    print(f"Classification report saved to {report_path}")

    plot_confusion_matrix(cm, class_names, output_dir=output_dir)

    return report_dict, cm


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    try:
        evaluate_model()
        print("Evaluation complete!")
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
