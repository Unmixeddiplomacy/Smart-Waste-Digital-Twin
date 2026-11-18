import os
import json
import numpy as np
import tensorflow as tf
import keras
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import sklearn

# Constants
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(SCRIPT_DIR, "dataset")
IMG_SIZE = (224, 224)
BATCH_SIZE = 32
EPOCHS = 20
VALIDATION_SPLIT = 0.2
CLASS_NAMES = ["cardboard", "glass", "metal", "paper", "plastic", "trash"]
NUM_CLASSES = 6
MODEL_SAVE_PATH = os.path.join(SCRIPT_DIR, "model.keras")

# Data augmentation layer (to be integrated into the model)
data_augmentation = tf.keras.Sequential(
    [
        tf.keras.layers.RandomFlip("horizontal"),
        tf.keras.layers.RandomRotation(0.15),
        tf.keras.layers.RandomZoom(0.1),
        tf.keras.layers.RandomBrightness(0.1),
    ],
    name="data_augmentation",
)


def load_dataset(dataset_dir=DATASET_DIR):
    """Load TrashNet training and validation datasets with prefetching."""
    if not os.path.isdir(dataset_dir):
        raise FileNotFoundError(
            f"Dataset directory not found: {dataset_dir}. "
            "Please place the TrashNet dataset folders "
            "(cardboard, glass, metal, paper, plastic, trash) in this directory."
        )

    train_ds = tf.keras.utils.image_dataset_from_directory(
        dataset_dir,
        validation_split=VALIDATION_SPLIT,
        subset="training",
        seed=42,
        image_size=IMG_SIZE,
        batch_size=BATCH_SIZE,
        label_mode="categorical",
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

    class_names = train_ds.class_names

    # Prefetch optimization
    AUTOTUNE = tf.data.AUTOTUNE
    train_ds = train_ds.prefetch(buffer_size=AUTOTUNE)
    val_ds = val_ds.prefetch(buffer_size=AUTOTUNE)

    return train_ds, val_ds, class_names


def build_model():
    """Build and compile the MobileNetV2 transfer learning model."""
    base_model = tf.keras.applications.MobileNetV2(
        input_shape=(224, 224, 3),
        include_top=False,
        weights="imagenet",
    )
    base_model.trainable = False

    model = tf.keras.Sequential(
        [
            data_augmentation,
            tf.keras.layers.Rescaling(1.0 / 127.5, offset=-1),
            base_model,
            tf.keras.layers.GlobalAveragePooling2D(),
            tf.keras.layers.Dense(128, activation="relu"),
            tf.keras.layers.Dropout(0.3),
            tf.keras.layers.Dense(NUM_CLASSES, activation="softmax"),
        ]
    )

    model.build((None, 224, 224, 3))

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=0.0001),
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )

    model.summary()
    return model


def train_model(model, train_ds, val_ds):
    """Train the model with EarlyStopping, ModelCheckpoint, and ReduceLROnPlateau."""
    early_stop = tf.keras.callbacks.EarlyStopping(
        monitor="val_loss",
        patience=5,
        restore_best_weights=True,
        verbose=1,
    )

    checkpoint = tf.keras.callbacks.ModelCheckpoint(
        filepath=MODEL_SAVE_PATH,
        monitor="val_accuracy",
        save_best_only=True,
        verbose=1,
    )

    reduce_lr = tf.keras.callbacks.ReduceLROnPlateau(
        monitor="val_loss",
        factor=0.5,
        patience=3,
        min_lr=1e-7,
        verbose=1,
    )

    history = model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=EPOCHS,
        callbacks=[early_stop, checkpoint, reduce_lr],
    )

    return history


def plot_training_history(history):
    """Plot and save training & validation accuracy and loss curves."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # Left subplot: Accuracy
    ax1.plot(
        history.history["accuracy"],
        color="blue",
        linestyle="-",
        label="Train Accuracy",
    )
    ax1.plot(
        history.history["val_accuracy"],
        color="orange",
        linestyle="--",
        label="Val Accuracy",
    )
    ax1.set_title("Model Accuracy")
    ax1.set_xlabel("Epoch")
    ax1.set_ylabel("Accuracy")
    ax1.legend()
    ax1.grid(True)

    # Right subplot: Loss
    ax2.plot(
        history.history["loss"],
        color="blue",
        linestyle="-",
        label="Train Loss",
    )
    ax2.plot(
        history.history["val_loss"],
        color="orange",
        linestyle="--",
        label="Val Loss",
    )
    ax2.set_title("Model Loss")
    ax2.set_xlabel("Epoch")
    ax2.set_ylabel("Loss")
    ax2.legend()
    ax2.grid(True)

    plt.tight_layout()

    output_dir = os.path.join(SCRIPT_DIR, "evaluation_results")
    os.makedirs(output_dir, exist_ok=True)
    save_path = os.path.join(output_dir, "training_history.png")
    plt.savefig(save_path, dpi=150)
    plt.close(fig)
    print("Training history plot saved")
    return save_path


def export_to_onnx(model_path):
    """Optionally export the saved Keras model to ONNX format."""
    import importlib

    try:
        tf2onnx = importlib.import_module("tf2onnx")
    except ImportError:
        print("Skipping ONNX export (tf2onnx not installed)")
        return None

    model = tf.keras.models.load_model(model_path)
    onnx_path = os.path.join(os.path.dirname(os.path.abspath(model_path)), "model.onnx")
    input_signature = [tf.TensorSpec((None, *IMG_SIZE, 3), tf.float32, name="input")]

    tf2onnx.convert.from_keras(
        model,
        input_signature=input_signature,
        output_path=onnx_path,
    )

    size_mb = os.path.getsize(onnx_path) / (1024 * 1024)
    print(f"ONNX model saved to: {onnx_path} ({size_mb:.2f} MB)")
    print("ONNX export complete")
    return onnx_path


if __name__ == "__main__":
    train_ds, val_ds, class_names = load_dataset()
    print(f"Number of training batches: {len(train_ds)}")
    print(f"Number of validation batches: {len(val_ds)}")
    print(f"Class names found: {class_names}")
    print("Dataset loaded successfully")

    model = build_model()
    history = train_model(model, train_ds, val_ds)

    print("Training complete!")
    final_val_acc = history.history["val_accuracy"][-1]
    best_val_acc = max(history.history["val_accuracy"])
    print(f"Final val_accuracy: {final_val_acc:.4f} (Best val_accuracy: {best_val_acc:.4f})")

    class_names_path = os.path.join(SCRIPT_DIR, "class_names.json")
    with open(class_names_path, "w", encoding="utf-8") as f:
        json.dump(class_names, f, indent=2)
    print(f"Class names saved to: {class_names_path}")

    plot_training_history(history)

    try:
        export_to_onnx(MODEL_SAVE_PATH)
    except Exception as e:
        print(f"Skipping ONNX export (conversion failed: {e})")
