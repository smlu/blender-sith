# Alignment with Blender and Blender Lab MCP

Official-project source review: **2026-11-01**. Blender-Sith is an add-on for
Blender. Blender's general modeling, animation, baking, rendering and scene tools
remain available when the add-on is installed.

## General automation already exists

The official [Blender Lab MCP project](https://www.blender.org/lab/mcp-server/)
is a separate server and Blender add-on requiring Blender 5.1 or newer; it is
not built into Blender core. This review inspected
[`lab/blender_mcp` at `dbbf836ad4b1025f14a2b3b504c43903f39e0b04`](https://projects.blender.org/lab/blender_mcp/commit/dbbf836ad4b1025f14a2b3b504c43903f39e0b04).

Its [tool inventory](https://projects.blender.org/lab/blender_mcp/src/commit/dbbf836ad4b1025f14a2b3b504c43903f39e0b04/readme_tools.rst)
already covers general Python execution, scene/object summaries, missing files
and linked libraries, API/manual search, screenshots, viewport navigation and
rendering. Several summary tools also offer background-process variants.

The Sith companion concentrates on format-specific operations: bounded 3DO
inspection, geometry-only conversion, baseline regression receipts and extension
packaging. It does not duplicate general Python execution or attach to an
artist's existing interactive scene. See [MCP setup](MCP.md).

The servers can be configured as separate host entries. This is an arrangement
of independent services, not an automatic bridge or evidence of tested
coexistence. The Sith companion does not install the official Blender add-on,
open its socket or forward requests to it.

## Separate environments

The inspected official project's
[`mcp/pyproject.toml`](https://projects.blender.org/lab/blender_mcp/src/commit/dbbf836ad4b1025f14a2b3b504c43903f39e0b04/mcp/pyproject.toml)
declares MCP SDK below version 2. The Sith companion pins SDK 2.3.0. Keep each
server in its own external environment and point its host entry at the correct
interpreter. Neither SDK needs to be installed into Blender.

The official project's internal tool discovery is not a stable third-party
plugin API. Its [design discussion](https://projects.blender.org/blender/blender/issues/152011)
also considers separate MCP servers for customizations. A future backend adapter
would need its own implementation and integration tests.

## Reuse Blender's extension and process facilities

Blender already supplies extension build, validation, installation, repository
management and platform-split commands. The [deterministic packager](building.md)
adds explicit membership and byte provenance; it does not redefine Blender's
manifest rules. With a configured Blender executable, the MCP package operation
runs Blender's built-in validator on the exact new ZIP and requires its success.
The Python-plus-bpy route explicitly reports validator `not_run`.

The [official extension command reference](https://docs.blender.org/manual/en/latest/advanced/command_line/extension_arguments.html)
and [manifest instructions](https://docs.blender.org/manual/en/latest/advanced/extensions/getting_started.html)
remain authoritative. Unused optional manifest fields should be omitted rather
than set to empty values. The pure-Python add-on keeps its unrestricted manifest.

Background execution, factory startup, automatic-script controls, thread limits
and offline preference controls are existing Blender capabilities. The companion
adds job isolation, bounded subprocess handling and receipts around them.
`--offline-mode` sets Blender's online-access preference; it is not an OS network
sandbox. See the [Blender CLI reference](https://docs.blender.org/manual/en/latest/advanced/command_line/arguments.html).

Geometry conversion retains the importer restriction to geoset zero and skips
implicit MAT/CMP discovery. JK 2.1 UV normalization needs texture dimensions;
geometry-only output does not establish a textured round trip or game-runtime
compatibility. Runtime, native-platform and coexistence claims require their
own recorded tests.
