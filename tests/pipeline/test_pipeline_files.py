from pathlib import Path
import unittest

from src.pipeline.loader import load_pipeline


class PipelineFileTests(unittest.TestCase):
    def test_auto_mail_pipeline_is_valid(self):
        definition = load_pipeline(Path("config/pipelines/auto_mail.yaml"))

        self.assertEqual(definition.id, "auto_mail")
        self.assertEqual(definition.start, "main_city")
        self.assertIn("success", definition.nodes)


if __name__ == "__main__":
    unittest.main()
