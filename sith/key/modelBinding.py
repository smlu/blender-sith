# SPDX-License-Identifier: GPL-3.0-or-later
"""Index-based comparison of a native 3DO hierarchy and a parsed text KEY."""

from .keyValidation import kKeyTargetLimits, validateKeyForTarget, validateKeyNumericData

DETAIL_LIMIT = 32


def auditModelKey(model, key, key_target="JKDF2"):
    """Compare parsed slots, basic track integrity and native KEY target limits.

    This does not evaluate poses or duplicate the Blender importer's sampling,
    first-frame policy, timeline bounds or animation-channel checks. Marker
    provenance describes the loaded source, even if its editable list changes.
    """
    if key_target not in {"JKDF2", "MOTS"}:
        raise ValueError("Choose JKDF2 or MOTS for the KEY binding audit")
    report = {"key_target": key_target, "declared_joints": key.numJoints,
              "model_joints": len(model.meshHierarchy), "tracks": len(key.nodes),
              "populated_tracks": sum(bool(node.keyframes) for node in key.nodes),
              "frames": key.numFrames, "declared_markers": key.sourceMarkerCount,
              "parsed_markers": len(key.markers), "skipped_markers": key.sourceSkippedMarkers,
              "matched_names": 0, "issue_counts": {}, "findings": []}
    severity = 0

    def finding(level, code, **details):
        nonlocal severity
        severity = max(severity, level)
        counts = report["issue_counts"]
        counts[code] = counts.get(code, 0) + 1
        if len(report["findings"]) < DETAIL_LIMIT:
            report["findings"].append({"code": code, **details})

    if key.fileFormat.value != "text":
        finding(2, "non_text_key")
    for validator, args, code in ((validateKeyNumericData, (key,), "invalid_key_number"),
                                  (validateKeyForTarget, (key, key_target), "key_target_limit")):
        try:
            validator(*args)
        except (AssertionError, ValueError) as exc:
            finding(2, code, detail=str(exc)[:256])
    # The loader deliberately omits unknown marker types. Its retained list
    # alone cannot establish the declared source's fixed engine-buffer bound.
    marker_limit = kKeyTargetLimits[key_target][1]
    if (key.sourceMarkerCount is not None and key.sourceMarkerCount > marker_limit
            and len(key.markers) <= marker_limit):
        finding(2, "key_target_limit", detail=f"{key_target} supports at most {marker_limit} KEY markers; source declares {key.sourceMarkerCount}")
    if key.sourceSkippedMarkers:
        finding(1, "unrecognized_markers", count=key.sourceSkippedMarkers)
    if key.numFrames < 1 or key.fps <= 0:
        finding(2, "invalid_playback_header", detail="KEY frame count and FPS must be positive")

    if key.numJoints != len(model.meshHierarchy):
        finding(1, "declared_joint_count_differs")
    aligned = all(node.idx == slot for slot, node in enumerate(model.meshHierarchy))
    if not aligned:
        finding(2, "nonsequential_model_indices")
    for track in key.nodes:
        if not track.keyframes:
            finding(1, "empty_track", index=track.idx)
        elif (any(entry.frame < 0 for entry in track.keyframes)
              or any(current.frame <= previous.frame
                     for previous, current in zip(track.keyframes, track.keyframes[1:]))):
            finding(2, "invalid_track_timing", index=track.idx)
        if not 0 <= track.idx < len(model.meshHierarchy):
            finding(2, "missing_model_slot", index=track.idx, key_name=track.meshName[:128])
            continue
        joint = model.meshHierarchy[track.idx]
        if joint.idx != track.idx:
            continue  # This model does not identify the slot unambiguously.
        if joint.name.casefold() == track.meshName.casefold():
            report["matched_names"] += 1
        else:
            finding(1, "joint_name_differs", index=track.idx, key_name=track.meshName[:128],
                    model_name=joint.name[:128])
    report["findings_truncated"] = sum(report["issue_counts"].values()) > len(report["findings"])
    report["status"] = ("incompatible" if severity == 2 else "review" if severity == 1
                        else "consistent" if key.nodes else "no_tracks")
    return report
