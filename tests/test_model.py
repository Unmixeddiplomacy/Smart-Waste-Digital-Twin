import unittest
import numpy as np
import os
import sys
import json
import tempfile
from PIL import Image

# Add project root (parent directory) to sys.path so we can import from ai_model/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

AI_MODEL_DIR = os.path.join(PROJECT_ROOT, "ai_model")
MODEL_KERAS_PATH = os.path.join(AI_MODEL_DIR, "model.keras")
MODEL_H5_PATH = os.path.join(AI_MODEL_DIR, "model.h5")
CLASS_NAMES_PATH = os.path.join(AI_MODEL_DIR, "class_names.json")

MODEL_EXISTS = (
    (os.path.exists(MODEL_KERAS_PATH) or os.path.exists(MODEL_H5_PATH))
    and os.path.exists(CLASS_NAMES_PATH)
)


@unittest.skipIf(
    not MODEL_EXISTS,
    "Trained model (model.keras/model.h5) or class_names.json not found in ai_model/. Run train.py first.",
)
class TestWasteClassifier(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ai_model.inference import WasteClassifier

        cls.classifier = WasteClassifier()

    def _assert_valid_result(self, result):
        self.assertIn("class", result)
        self.assertIn("confidence", result)
        self.assertIn("all_probabilities", result)
        self.assertIsInstance(result["class"], str)
        self.assertGreaterEqual(result["confidence"], 0.0)
        self.assertLessEqual(result["confidence"], 1.0)
        self.assertEqual(len(result["all_probabilities"]), 6)
        prob_sum = sum(result["all_probabilities"].values())
        self.assertAlmostEqual(prob_sum, 1.0, delta=0.01)

    def test_model_loads(self):
        self.assertIsNotNone(self.classifier.model)
        self.assertEqual(len(self.classifier.class_names), 6)

    def test_class_names(self):
        self.assertIn("glass", self.classifier.class_names)
        self.assertIn("metal", self.classifier.class_names)
        self.assertIn("plastic", self.classifier.class_names)

    def test_predict_synthetic_image(self):
        random_img = np.random.randint(0, 256, (224, 224, 3), dtype=np.uint8)
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        temp_path = tmp.name
        tmp.close()

        try:
            Image.fromarray(random_img).save(temp_path)
            result = self.classifier.predict(temp_path)
            self._assert_valid_result(result)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_predict_numpy_array(self):
        random_array = np.random.uniform(0, 255, (224, 224, 3)).astype(np.float32)
        result = self.classifier.predict(random_array)
        self._assert_valid_result(result)

    def test_confidence_sums_to_one(self):
        for _ in range(5):
            random_array = np.random.uniform(0, 255, (224, 224, 3)).astype(np.float32)
            result = self.classifier.predict(random_array)
            prob_sum = sum(result["all_probabilities"].values())
            self.assertAlmostEqual(prob_sum, 1.0, delta=0.01)


if __name__ == "__main__":
    unittest.main()
