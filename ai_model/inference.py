import os
import sys
import json
import numpy as np
import tensorflow as tf
from PIL import Image


class WasteClassifier:
    """Single-image and batch waste classifier backed by the trained MobileNetV2 model."""

    def __init__(self, model_path=None, class_names_path=None):
        script_dir = os.path.dirname(os.path.abspath(__file__))

        if model_path is None:
            keras_default = os.path.join(script_dir, "model.keras")
            h5_default = os.path.join(script_dir, "model.h5")
            if os.path.exists(keras_default):
                model_path = keras_default
            elif os.path.exists(h5_default):
                model_path = h5_default
            else:
                raise FileNotFoundError(
                    f"Model file not found at {keras_default} (or {h5_default}). "
                    "Please train the model first by running train.py."
                )
        elif not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found at {model_path}")

        if class_names_path is None:
            class_names_path = os.path.join(script_dir, "class_names.json")
        if not os.path.exists(class_names_path):
            raise FileNotFoundError(
                f"Class names file not found at {class_names_path}. "
                "Please train the model first by running train.py."
            )

        self.model = tf.keras.models.load_model(model_path)
        with open(class_names_path, "r", encoding="utf-8") as f:
            self.class_names = json.load(f)

        self.img_size = (224, 224)
        print(f"WasteClassifier loaded with {len(self.class_names)} classes")

    def predict(self, image_path_or_array):
        """Predict waste class from a file path or numpy array (RGB, 0-255)."""
        if isinstance(image_path_or_array, (str, os.PathLike)):
            if not os.path.exists(image_path_or_array):
                raise FileNotFoundError(f"Image file not found at {image_path_or_array}")
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            with Image.open(image_path_or_array) as img:
                img = img.convert("RGB")
                img = img.resize(self.img_size, resampling)
                img_array = np.asarray(img, dtype=np.float32)
        elif isinstance(image_path_or_array, np.ndarray):
            img_array = image_path_or_array.astype(np.float32)
            if img_array.ndim == 2:
                img_array = np.stack([img_array] * 3, axis=-1)
            elif img_array.ndim == 3 and img_array.shape[-1] == 4:
                img_array = img_array[:, :, :3]
            if img_array.shape[:2] != self.img_size:
                img_array = tf.image.resize(img_array, self.img_size).numpy().astype(np.float32)
        else:
            raise TypeError(
                "image_path_or_array must be a file path (str/PathLike) or numpy.ndarray."
            )

        # Add batch dimension: (1, 224, 224, 3). Do NOT manually rescale;
        # the model's built-in Rescaling(1./127.5, offset=-1) layer handles it.
        batch_input = np.expand_dims(img_array, axis=0)

        predictions = self.model.predict(batch_input, verbose=0)
        probs = predictions[0]

        class_idx = int(np.argmax(probs))
        confidence = float(probs[class_idx])
        class_name = self.class_names[class_idx]

        return {
            "class": class_name,
            "confidence": round(confidence, 4),
            "all_probabilities": {
                name: round(float(prob), 4)
                for name, prob in zip(self.class_names, probs)
            },
        }

    def predict_batch(self, image_paths):
        """Predict waste classes for a list of image file paths."""
        return [self.predict(path) for path in image_paths]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inference.py <image_path>", file=sys.stderr)
        sys.exit(1)

    image_path = sys.argv[1]
    try:
        classifier = WasteClassifier()
        result = classifier.predict(image_path)
        print(json.dumps(result, indent=2))
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
