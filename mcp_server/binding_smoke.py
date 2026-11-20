#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reproduce a native KEY binding audit through the official stdio client."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import sys

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


async def check(config_path, evidence):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    inputs = evidence / "inputs"
    inputs.mkdir()
    model = inputs / "triangle.3do"
    shutil.copyfile(ROOT / "tests/tv/model/triangle.3do", model)
    base = (ROOT / "tests/tv/key/winding_and_holds.key").read_text(encoding="utf-8")
    base = base.replace("MESH NAME joint", "MESH NAME head")
    original_cases = (
        ("matching", 2, 1, "JKDF2", "consistent", []),
        ("misbound", 2, 0, "MOTS", "review", ["joint_name_differs"]),
        ("missing", 3, 2, "JKDF2", "incompatible", ["declared_joint_count_differs", "missing_model_slot"]),
        ("limit", 65, 1, "MOTS", "incompatible", ["key_target_limit", "declared_joint_count_differs"]),
        ("head_with_a_name_longer_than_the_target", 2, 1, "JKDF2", "incompatible", ["key_target_limit"]),
    )
    cases = []
    for label, joints, index, target, status, codes in original_cases:
        text = base.replace("JOINTS 1", f"JOINTS {joints}").replace("NODE 0", f"NODE {index}")
        cases.append((label, text, target, status, codes, {}))
    matching = base.replace("JOINTS 1", "JOINTS 2").replace("NODE 0", "NODE 1")

    def add(label, text, status, codes, **expected):
        cases.append((label, text, "JKDF2", status, codes, expected))

    def with_markers(kinds):
        section = "SECTION: MARKERS\nMARKERS " + str(len(kinds)) + "\n"
        section += "".join(f"{i} {kind}\n" for i, kind in enumerate(kinds))
        return matching.replace("SECTION: KEYFRAME NODES", section + "SECTION: KEYFRAME NODES")

    add("eight_markers", with_markers([1] * 8), "consistent", [], declared_markers=8, parsed_markers=8, skipped_markers=0)
    add("nine_markers", with_markers([1] * 9), "incompatible", ["key_target_limit"], declared_markers=9, parsed_markers=9)
    add("dropped_ninth_marker", with_markers([1] * 8 + [99]), "incompatible",
        ["key_target_limit", "unrecognized_markers"], declared_markers=9, parsed_markers=8, skipped_markers=1)
    add("unknown_marker", with_markers([99]), "review", ["unrecognized_markers"],
        declared_markers=1, parsed_markers=0, skipped_markers=1)
    add("zero_fps", matching.replace("FPS 29.97002997", "FPS 0"), "incompatible", ["invalid_playback_header"])
    add("negative_fps", matching.replace("FPS 29.97002997", "FPS -1"), "incompatible", ["invalid_playback_header"])
    add("nonfinite_fps", matching.replace("FPS 29.97002997", "FPS -1e999"), "incompatible",
        ["invalid_key_number", "invalid_playback_header"])
    add("zero_frames", matching.replace("FRAMES 21", "FRAMES 0"), "incompatible", ["invalid_playback_header"])
    add("no_tracks", matching.split("SECTION: KEYFRAME NODES")[0] + "SECTION: KEYFRAME NODES\nNODES 0\n",
        "no_tracks", [], populated_tracks=0)
    add("empty_track", matching.split("ENTRIES 3")[0] + "ENTRIES 0\n", "review", ["empty_track"], populated_tracks=0)
    add("negative_frame", matching.replace("0: 0 0x3", "0: -1 0x3"), "incompatible", ["invalid_track_timing"])
    add("reversed_frames", matching.replace("2: 15 0x0", "2: 9 0x0"), "incompatible", ["invalid_track_timing"])
    add("duplicate_frames", matching.replace("2: 15 0x0", "2: 10 0x0"), "incompatible", ["invalid_track_timing"])
    add("n" * 65, matching, "incompatible", ["key_target_limit"])
    add("nonascii_\u00e9", matching, "incompatible", ["key_target_limit"])
    add("casefold_name", matching.replace("MESH NAME head", "MESH NAME HEAD"), "consistent", [], matched_names=1)
    many = matching.split("SECTION: KEYFRAME NODES")[0].replace("JOINTS 2", "JOINTS 40")
    many += "SECTION: KEYFRAME NODES\nNODES 40\n"
    many += "".join(f"NODE {i}\nMESH NAME head\nENTRIES 1\n0: 0 0x0 0 0 0 0 0 0\n0 0 0 0 0 0\n" for i in range(40))
    add("bounded_findings", many, "incompatible", ["declared_joint_count_differs", "joint_name_differs", "missing_model_slot"],
        findings_truncated=True, issue_counts={"declared_joint_count_differs": 1, "joint_name_differs": 1, "missing_model_slot": 38})
    # This disposable config authorizes only the synthetic inputs created here.
    config.update(read_roots=[str(inputs)], job_root=str(evidence / "jobs"))
    scoped = evidence / "config.json"
    scoped.write_text(json.dumps(config), encoding="utf-8")
    params = StdioServerParameters(command=sys.executable,
                                   args=["-B", str(ROOT / "mcp_server/server.py"), "--config", str(scoped)])
    summary = {}
    failures = []
    async with Client(params) as client:
        for label, text, target, status, codes, expected in cases:
            path = inputs / (label + ".key")
            path.write_text(text, encoding="utf-8")
            call = await client.call_tool("audit_model_key", {"model_path": str(model), "key_path": str(path),
                                                               "key_target": target})
            data = call.structured_content or {}
            if call.is_error or data.get("status") != "passed":
                failures.append(f"{label} job failed: {data.get('job_directory', call.content)}")
                summary[label] = {"status": "job_failed", "job": data}
                continue
            binding = data["model"]["binding"]
            if (binding["status"] != status or set(binding["issue_counts"]) != set(codes)
                    or not data["source_unchanged"]
                    or data["input_sha256"] != hashlib.sha256(model.read_bytes()).hexdigest()
                    or data["key_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest()
                    or len(binding["findings"]) > 32
                    or any(binding.get(name) != value for name, value in expected.items())):
                failures.append(f"{label}: unexpected report {binding}")
            if label == "misbound" and binding["findings"] != [
                {"code": "joint_name_differs", "index": 0, "key_name": "head", "model_name": "root"}
            ]:
                failures.append("Missing exact source slot and names")
            if label == "bounded_findings" and len(binding["findings"]) != 32:
                failures.append("Bounded finding detail count is not 32")
            summary[label] = binding
        outside = evidence / "outside.key"
        outside.write_bytes(path.read_bytes())
        denied = await client.call_tool("audit_model_key", {"model_path": str(model), "key_path": str(outside)})
        if not denied.is_error:
            raise AssertionError("Out-of-scope KEY was accepted")
        summary["outside_key_rejected"] = True
    (evidence / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (evidence / "checks.json").write_text(json.dumps({"cases": len(cases), "failed": len(failures), "failures": failures}, indent=2) + "\n", encoding="utf-8")
    for name, result in summary.items():
        print(name, result["status"] if isinstance(result, dict) else result, flush=True)
    if failures:
        raise AssertionError("\n".join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Local config specifying runtime and matching add-on")
    parser.add_argument("--evidence", type=Path, required=True, help="New external directory for fixtures and jobs")
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    if any((p / ".git").exists() for p in (evidence, *evidence.parents)):
        parser.error("Choose an evidence directory outside Git")
    evidence.mkdir(parents=True, exist_ok=False)
    asyncio.run(asyncio.wait_for(check(args.config, evidence), timeout=600))


if __name__ == "__main__":
    main()
