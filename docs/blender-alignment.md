# Native Format Checks and Blender Automation

Blender-Sith adds native Sith-format import/export behavior to Blender. General
scene editing, rendering and interactive inspection remain Blender tasks. The
[official Blender Lab MCP project](https://www.blender.org/lab/mcp-server/) is an
existing route for interactive MCP use; its
[tool inventory](https://projects.blender.org/lab/blender_mcp/src/commit/dbbf836ad4b1025f14a2b3b504c43903f39e0b04/readme_tools.rst)
was reviewed at that pinned revision on 2026-11-01.

The native `auditModelKey(model, key, target)` API compares a decoded 3DO hierarchy
with one decoded KEY. Call it directly from ordinary Python with the resource
modules available, from a Blender script, or through an existing Blender Lab
session. The optional companion is a fixed four-tool adapter around this format
work, with explicit input roots and structured results:

| Need | Entry point |
| --- | --- |
| Read the configured scope and limits | `server_info` |
| Summarize native 3DO counts and polygon budgets | `inspect_3do` |
| Check hierarchy-slot binding, names and KEY target limits | `audit_model_key` |
| Create a new geometry-only blend from one 3DO | `convert_3do_to_blend` |

The companion has no general Python execution, shell or live-scene tool. It
creates fresh bounded jobs and does not attach to an existing interactive scene.
Configuring it and Blender Lab as separate host entries does not prove a tested
joint session, an automatic bridge or official Blender endorsement. Keep their
server dependencies in separate environments. This companion pins SDK 2.3.0;
that is independent of the Blender-Sith add-on version.

Use the repository's existing `tests/run.py` and `scripts/make_addon.py` for
regression and packaging tasks. Blender's own
[extension commands](https://docs.blender.org/manual/en/5.2/advanced/command_line/extension_arguments.html)
remain available for building and validating an installable extension. Those
operations are outside this companion's tool catalog.

Background/factory-startup mode, automatic-script controls, thread limits and
[offline preference controls](https://docs.blender.org/manual/en/5.1/advanced/command_line/arguments.html)
are existing Blender facilities. The companion adds input snapshots, bounded
reports, hashes and serialized jobs around its fixed worker. These are local
trusted-user controls, not an operating-system sandbox.

Geometry-only conversion imports geoset zero, omits external MAT/CMP discovery,
and leaves JK 2.1 UV coordinates unnormalized without texture dimensions.
Inspection summarizes all parsed geosets. A binding result describes native file
relationships and selected export limits; pose quality and in-game playback
remain separate validation tasks. See [configuration and limits](MCP.md).
