# Blender-Sith MCP companion

This optional local stdio server gives an MCP-capable agent four format-specific tools. It uses the official Python MCP SDK and launches fresh background Blender jobs. Installing the ordinary Blender extension does not start a server, open a port, or add dependencies to Blender.

The native `auditModelKey` API can also be called directly from a Python script or a [Blender Lab MCP](https://www.blender.org/lab/mcp-server/) session. Keep separate MCP servers in separate external virtual environments, with the dependency versions each requires. This companion does not duplicate a general Python execution or interactive-scene tool. See [Blender alignment](blender-alignment.md) for the integration boundary. Publishing both configurations is not evidence of a tested joint session, native installation, or official Blender endorsement.

| Tool | Behavior |
| --- | --- |
| `server_info` | Read configured roots, resource limits and supported operations without launching Blender. |
| `inspect_3do(path)` | Parse one allowlisted 3DO and return format version, geoset/mesh/vertex/face/hierarchy counts, and up to 100 material names. The first 32 geosets also report native triangles, quads, n-gons and triangle equivalents. It does not load referenced files. |
| `audit_model_key(model_path, key_path, key_target)` | Compare a 3DO hierarchy with one text KEY. Return track-index/name discrepancies, source and skipped marker counts, JKDF2 or MOTS KEY export-limit findings and hashes of both inputs. |
| `convert_3do_to_blend(path)` | Import geoset zero into a new `.blend` in a unique job directory. Geometry and placeholder materials only; no texture/palette lookup. JK 2.1 UV coordinates remain unnormalized without texture dimensions. |

The `addon` setting selects the source for parsing, binding audits and conversion. Use matching source for the native binding API and geometry-only import option.

## Will this KEY animate the intended joint?

A replacement 3DO has `root` at hierarchy slot 0 and `head` at slot 1. Two KEY files both call their single track `head`. Before opening a scene, the modeller can ask `audit_model_key` which slot each file addresses.

```json
{"model_path":"/srv/authorized-models/triangle.3do","key_path":"/srv/authorized-models/head.key","key_target":"MOTS"}
```

Read `model.binding` in the result. These outcomes use the repository's synthetic two-joint model.

| KEY entry | Binding status | What the modeller learns |
| --- | --- | --- |
| `NODE 1`, `MESH NAME head` | `consistent` | The indexed slot exists and its model name matches. A sparse KEY can animate just one joint. |
| `NODE 0`, `MESH NAME head` | `review` | Slot 0 belongs to `root`. Check the intended destination. A name discrepancy can be intentional. |
| `NODE 2` with three declared KEY joints | `incompatible` | This model has no slot 2. Changing the label alone cannot supply it. |

The check reads both native files and applies the selected KEY target's numeric and export-limit checks. A completed job can contain an incompatible pair. An empty track list has its own `no_tracks` status when there are no other findings. The report shows at most 32 findings plus totals for every issue. Pose quality and in-game playback still require testing.

The same comparison works in an existing Blender Python script or Blender Lab session with this add-on loaded. Import `auditModelKey` from the add-on's `key.modelBinding` module and pass the objects returned by `load3do(path)[0]` and `loadKey(path)`. The companion handles isolated file reads, input hashes and structured results for MCP clients.

## Installation

Use Python 3.11+ for the server, with the official `mcp==2.3.0` SDK. Keep the virtual environment and jobs physically outside every Git checkout. The Blender runtime is a separate explicit executable, or a Python interpreter with a compatible `bpy` distribution. Blender itself does not need the MCP SDK.

`mcp_server/requirements-windows-py313.lock.txt` records every installed dependency version from the verified Windows Python 3.13 environment. It is a platform-specific reproducibility record; use `requirements.txt` when resolving dependencies for Linux or macOS.

```sh
python3 -m venv /srv/blender-sith-env
/srv/blender-sith-env/bin/python -m pip install -r /src/blender-sith/mcp_server/requirements.txt
```

Create an explicit configuration outside the checkout, for example `/srv/blender-sith-config.json`:

```json
{
  "addon": "/src/blender-sith/sith",
  "blender": "/opt/blender/blender",
  "read_roots": ["/srv/authorized-models"],
  "job_root": "/srv/blender-sith-jobs",
  "timeout": 120,
  "threads": 2
}
```

The Blender executable setting also accepts a Microsoft Store App Execution Alias named `blender.exe` or `blender-launcher.exe` directly under `%LOCALAPPDATA%/Microsoft/WindowsApps`. Other reparse routes retain the ordinary checks.

Use absolute existing paths for `addon`, the runtime, and `read_roots`. The job root is created if needed. On Windows use ordinary drive paths and JSON backslash escaping (or forward slashes); UNC/device/alternate-data-stream paths are intentionally unsupported. For the Python+bpy route, replace `blender` with `python` and optionally set `bpy_site` to an existing compatible dependency directory. Do not configure both runtimes. On macOS use the executable inside Blender.app; native macOS execution must be validated separately.

An MCP host entry uses the server environment's Python and this command (adapt the host's enclosing configuration syntax):

```json
{
  "mcpServers": {
    "blender-sith": {
      "command": "/srv/blender-sith-env/bin/python",
      "args": ["-B", "/src/blender-sith/mcp_server/server.py", "--config", "/srv/blender-sith-config.json"]
    }
  }
}
```

Start it through your host after reviewing the configured roots. There is no default account, API key, cloud service or HTTP listener. This repository does not modify your host configuration automatically. Set the host's tool timeout above the configured job timeout; process-tree cleanup can need up to 30 additional seconds.

## Scope and failure handling

Inputs must be regular `.3do` files (and a named `.key` for the binding audit) beneath an explicit read root, no larger than 64 MiB. Relative paths, parent traversal and symlink/junction routes are rejected. A job snapshots only its named inputs into a unique external directory before parsing. Geometry-only conversion passes `loadExternalMaterials=False` to the public importer. Interactive imports retain material discovery by default. Outputs never replace the input. Add-on source hashes are checked after each operation. The result also records the SHA-256 of each snapshotted input and of a produced blend file.

Jobs are serialized per server; a concurrent request returns an error instead of launching a second Blender. The configured deadline terminates the owned subprocess tree. Blender preferences are isolated, user Python injection/optimization variables are removed, and thread counts default to two. Each outer stdout/stderr log retains at most 1 MiB; structured child reports are limited to 256 KiB. Keep job directories as receipts or remove completed ones yourself; there is no automatic deletion tool or retention policy.

The fixed Blender worker invocation includes `--offline-mode`. This sets Blender's online-access preference for the process; it is not an OS network sandbox or a claim that arbitrary installed Python code cannot open sockets. The separate Python+bpy route has no Blender CLI flags.

Tool results contain a `status`. Only `passed` means the requested operation completed and its report was accepted. A process exit of zero alone is insufficient. The result includes a job directory for logs, input/output hashes where relevant, and bounded structured results. Logs and local receipts may contain input names and absolute local paths; review before publishing them.

This is a local trusted-user service, **not an OS security sandbox**. The configured runtime, add-on, companion source and writable job directory must remain trusted and unchanged by other users during a call. Filesystem checks are not a defense against a hostile user racing filesystem changes. Blender/parsers execute with the server user's permissions; there is no hard memory or disk quota. Cancelled host requests may finish their bounded job before returning. The service exposes no arbitrary Python, shell, scene-editing, network, publishing, blend-file loading or deletion tool.

Geometry-only conversion is a useful starting point, not a textured round trip or retail-game acceptance test. It inherits the upstream importer restriction to geoset zero, and it does not normalize JK 2.1 UVs using absent texture sizes. `inspect_3do` summarizes all parsed geosets. A successful file audit does not establish in-game animation or native-platform validation.

## Verification

Run `python -B -m unittest discover -s tests/core -p test_mcp_server.py -v` with `TEMP`/`TMP` (Windows) or `TMPDIR` (Unix) set to external scratch storage. These tests are also included in `python tests/run.py --suite core` and require neither the SDK nor Blender. The companion supplies a real stdio integration check using the official SDK client:

```sh
/srv/blender-sith-env/bin/python -B /src/blender-sith/mcp_server/smoke_test.py \
  --config /srv/blender-sith-config.json \
  --input /srv/authorized-models/synthetic-cube.3do \
  --evidence /srv/blender-sith-smoke.json
```

This verifies the four-tool catalog, exercises inspection/conversion, independently verifies the produced blend hash and checks traversal rejection. It requires an authorized valid synthetic 3DO and creates new jobs. Its evidence file must be new and outside Git. Keep its absolute-path-bearing evidence local or sanitize it before publication.

Exercise the paired-file audit separately with the same SDK environment and config:

```sh
/srv/blender-sith-env/bin/python -B /src/blender-sith/mcp_server/binding_smoke.py \
  --config /srv/blender-sith-config.json --evidence /srv/new-binding-proof
```

The script creates a disposable config allowing only its synthetic inputs, exercises 22 cases including absent joints, sparse tracks, source marker counts, invalid timing and target limits, verifies both hashes and checks rejection of an out-of-scope KEY. The findings are in `summary.json`. Topology counts use native surface corners before Blender conversion. A quad contributes two triangle equivalents and a five-corner polygon contributes three.

Protocol documentation: [official Python SDK](https://py.sdk.modelcontextprotocol.io/) and [stdio server guide](https://modelcontextprotocol.io/docs/develop/build-server). The SDK is an optional host dependency with its own MIT license; Blender-Sith and this companion remain GPL-3.0-or-later.
