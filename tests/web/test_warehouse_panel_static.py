import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INDEX_HTML = PROJECT_ROOT / "src" / "web" / "templates" / "index.html"
APP_JS = PROJECT_ROOT / "src" / "web" / "static" / "app.js"
STYLE_CSS = PROJECT_ROOT / "src" / "web" / "static" / "style.css"


class WarehousePanelStaticTests(unittest.TestCase):
    def test_index_contains_manual_warehouse_panel_controls(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")

        for token in (
            'id="warehouse-panel"',
            'id="btn-warehouse-scan"',
            'id="btn-warehouse-stop"',
            'id="warehouse-status"',
            'id="warehouse-category"',
            'id="warehouse-page"',
            'id="warehouse-categories-completed"',
            'id="warehouse-items-found"',
            'id="warehouse-low-confidence"',
            'id="warehouse-message"',
        ):
            self.assertIn(token, html)

    def test_app_js_wires_warehouse_endpoints_and_single_bounded_poll(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        for endpoint in (
            "/api/warehouse/status",
            "/api/warehouse/scan",
            "/api/warehouse/stop",
            "/api/bot/start",
            "/api/bot/stop",
        ):
            self.assertIn(endpoint, source)

        self.assertEqual(source.count("setInterval("), 1)
        self.assertIn("function refreshStatus()", source)
        self.assertIn("const WAREHOUSE_TERMINAL_STATUSES", source)
        self.assertIn("function warehouseButtonState(", source)
        self.assertIn('status === "running"', source)
        self.assertIn('status === "stopping"', source)
        self.assertIn('status === "idle"', source)

        labels_block = re.search(
            r"const WAREHOUSE_STATUS_LABELS = \{(?P<body>.*?)\n\};",
            source,
            re.S,
        )
        self.assertIsNotNone(labels_block)
        body = labels_block.group("body")
        for status in ("idle", "running", "stopping", "success", "partial", "failed", "stopped"):
            self.assertRegex(body, rf"\b{status}\b\s*:")

    def test_existing_runtime_helpers_are_not_inside_block_comments(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        active_source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)

        for helper in (
            "function tasksFingerprint(",
            "function setMsg(",
            "async function api(",
            "async function setTaskOption(",
            "function setWarehouseMsg(",
        ):
            self.assertIn(helper, active_source)

    def test_style_contains_manual_warehouse_panel_classes(self) -> None:
        css = STYLE_CSS.read_text(encoding="utf-8")

        for token in (
            ".warehouse-panel",
            ".warehouse-actions",
            ".warehouse-grid",
            ".warehouse-stat",
            ".warehouse-message",
        ):
            self.assertIn(token, css)


if __name__ == "__main__":
    unittest.main()
