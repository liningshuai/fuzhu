import unittest

import numpy as np

from src.pipeline.models import (
    ActionSpec,
    PipelineDefinition,
    PipelineNode,
    RecognizerSpec,
)
from src.pipeline.result import PipelineStatus
from src.pipeline.runner import PipelineRunner
from src.vision.match import MatchResult


class FakeDevice:
    def __init__(self):
        self.calls = []

    def tap(self, x, y, jitter=True):
        self.calls.append(("tap", x, y, jitter))


class FakeMatcher:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def find(self, screen, name, threshold=None, region=None):
        self.calls.append((screen, name, threshold, region))
        return self.hits.get(name)


class FakeContext:
    def __init__(self, hits):
        self.device = FakeDevice()
        self.matcher = FakeMatcher(hits)
        self.screens = []

    def screenshot(self):
        screen = np.full((1920, 1080, 3), len(self.screens), dtype=np.uint8)
        self.screens.append(screen)
        return screen


def template(name, x=200, y=300):
    return MatchResult(name=name, x=x, y=y, score=0.95, w=40, h=20)


def node(node_id, *, recognize=None, action="none", next=(), error_next=(), max_times=1):
    return PipelineNode(
        id=node_id,
        recognize=recognize,
        action=ActionSpec(type=action),
        next=tuple(next),
        error_next=tuple(error_next),
        max_times=max_times,
    )


class PipelineRunnerTests(unittest.TestCase):
    def setUp(self):
        self.ctx = FakeContext({"main": template("main")})
        self.runner = PipelineRunner(self.ctx)

        self.valid_definition = PipelineDefinition(
            id="valid",
            start="main",
            coordinate_base=(1080, 1920),
            nodes={
                "main": node(
                    "main",
                    recognize=RecognizerSpec(type="template", template="main"),
                    action="tap_self",
                    next=("finish",),
                ),
                "finish": node("finish", action="success"),
            },
        )

    def test_success_path_records_trace(self):
        result = self.runner.run(self.valid_definition)

        self.assertIs(result.status, PipelineStatus.SUCCESS)
        self.assertEqual([step.node_id for step in result.trace], ["main", "finish"])
        self.assertEqual(self.ctx.device.calls, [("tap", 200, 300, True)])

    def test_primary_next_miss_uses_error_next(self):
        definition = PipelineDefinition(
            id="fallback",
            start="main",
            coordinate_base=(1080, 1920),
            nodes={
                "main": node(
                    "main",
                    recognize=RecognizerSpec(type="template", template="main"),
                    next=("missing",),
                    error_next=("fallback_success",),
                ),
                "missing": node(
                    "missing",
                    recognize=RecognizerSpec(type="template", template="not_here"),
                    error_next=("wrong_fail",),
                ),
                "fallback_success": node("fallback_success", action="success"),
                "wrong_fail": node("wrong_fail", action="fail"),
            },
        )

        result = self.runner.run(definition)

        self.assertIs(result.status, PipelineStatus.SUCCESS)
        self.assertEqual(result.trace[-1].node_id, "fallback_success")

    def test_node_max_times_prevents_loop(self):
        definition = PipelineDefinition(
            id="loop",
            start="loop",
            coordinate_base=(1080, 1920),
            nodes={
                "loop": node(
                    "loop",
                    recognize=RecognizerSpec(type="template", template="main"),
                    next=("loop",),
                    max_times=1,
                ),
            },
        )

        result = self.runner.run(definition)

        self.assertIs(result.status, PipelineStatus.FAILED)
        self.assertIn("max_times", result.message)

    def test_global_step_limit_prevents_unbounded_graph(self):
        definition = PipelineDefinition(
            id="loop",
            start="loop",
            coordinate_base=(1080, 1920),
            nodes={
                "loop": node(
                    "loop",
                    recognize=RecognizerSpec(type="template", template="main"),
                    next=("loop",),
                    max_times=99,
                ),
            },
        )

        result = PipelineRunner(self.ctx, max_steps=3).run(definition)

        self.assertIs(result.status, PipelineStatus.STEP_LIMIT)

    def test_candidate_nodes_reuse_one_screenshot(self):
        self.ctx = FakeContext({"candidate_b": template("candidate_b")})
        definition = PipelineDefinition(
            id="candidate",
            start="main",
            coordinate_base=(1080, 1920),
            nodes={
                "main": node(
                    "main",
                    recognize=RecognizerSpec(type="template", template="candidate_b"),
                    next=("candidate_a", "candidate_b"),
                ),
                "candidate_a": node(
                    "candidate_a",
                    recognize=RecognizerSpec(type="template", template="candidate_a"),
                ),
                "candidate_b": node(
                    "candidate_b",
                    recognize=RecognizerSpec(type="template", template="candidate_b"),
                    action="success",
                ),
            },
        )

        result = PipelineRunner(self.ctx).run(definition)

        self.assertIs(result.status, PipelineStatus.SUCCESS)
        self.assertEqual(len(self.ctx.screens), 2)
        self.assertIs(
            self.ctx.matcher.calls[1][0], self.ctx.matcher.calls[2][0]
        )


if __name__ == "__main__":
    unittest.main()
