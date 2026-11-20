# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise native binding findings in the ordinary core suite without Blender or MCP."""
from pathlib import Path
import tempfile
import unittest

from fixtures import TV
from sith.key.keyLoader import loadKey
from sith.key.modelBinding import auditModelKey
from sith.model.model3doLoader import load3do


class ModelKeyBindingTests(unittest.TestCase):
    def setUp(self):
        self.model, _ = load3do(TV / "model/triangle.3do")
        self.key = loadKey(TV / "key/winding_and_holds.key")
        self.key.numJoints = 2
        self.track = self.key.nodes[0]
        self.track.meshName = "head"

    def test_sparse_model_match(self):
        self.track.idx = 1
        report = auditModelKey(self.model, self.key, "MOTS")
        self.assertEqual(report["status"], "consistent")
        self.assertEqual(report["matched_names"], 1)

    def test_misnamed_slot_and_missing_slot_have_different_verdicts(self):
        self.track.idx = 0
        report = auditModelKey(self.model, self.key)
        self.assertEqual(report["status"], "review")
        self.assertEqual(report["findings"], [
            {"code": "joint_name_differs", "index": 0, "key_name": "head", "model_name": "root"}])
        self.key.numJoints = 3
        self.track.idx = 2
        report = auditModelKey(self.model, self.key)
        self.assertEqual(report["status"], "incompatible")
        self.assertEqual(report["issue_counts"]["missing_model_slot"], 1)

    def test_marker_limit_uses_declared_source_count(self):
        source = (TV / "key/winding_and_holds.key").read_text(encoding="utf-8")
        markers = "SECTION: MARKERS\nMARKERS 9\n" + "0 1\n" * 8 + "0 99\n"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "markers.key"
            path.write_text(source.replace("SECTION: KEYFRAME NODES", markers + "SECTION: KEYFRAME NODES"),
                            encoding="utf-8")
            key = loadKey(path)
        report = auditModelKey(self.model, key)
        self.assertEqual((report["declared_markers"], report["parsed_markers"], report["skipped_markers"]), (9, 8, 1))
        self.assertEqual(report["status"], "incompatible")
        self.assertEqual(report["issue_counts"]["key_target_limit"], 1)
