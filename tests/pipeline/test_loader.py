from pathlib import Path
import unittest

from src.pipeline.loader import PipelineConfigError, load_pipeline


class PipelineLoaderTests(unittest.TestCase):
    def test_loads_valid_pipeline(self):
        path = Path("tests/pipeline/fixtures/valid.yaml")
        definition = load_pipeline(path)
        self.assertEqual(definition.id, "demo")
        self.assertEqual(definition.start, "main")
        self.assertEqual(definition.nodes["main"].recognize.template, "nav_fief")

    def test_rejects_unknown_next_node(self):
        path = Path("tests/pipeline/fixtures/unknown_next.yaml")
        with self.assertRaises(PipelineConfigError):
            load_pipeline(path)

    def test_rejects_invalid_roi_and_threshold(self):
        path = Path("tests/pipeline/fixtures/invalid_vision.yaml")
        with self.assertRaises(PipelineConfigError):
            load_pipeline(path)

    def test_requires_bounded_deterministic_nodes(self):
        path = Path("tests/pipeline/fixtures/unbounded_wait.yaml")
        with self.assertRaises(PipelineConfigError):
            load_pipeline(path)


if __name__ == "__main__":
    unittest.main()
