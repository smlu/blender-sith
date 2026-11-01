# Blender-Sith MCP companion

This optional local stdio server gives an MCP-capable agent five structured tools. It uses the [background runner](agent-use.md) and [deterministic packager](building.md), which must be present alongside it. It uses the official Python MCP SDK and launches fresh background Blender jobs. Installing the ordinary Blender extension does not start a server, open a port, or add dependencies to Blender.

For general scene interaction, use this format-specific companion alongside the [official Blender Lab MCP server](https://www.blender.org/lab/mcp-server/). Keep the two servers in separate external virtual environments: the audited official server uses the MCP SDK 1.x line while this companion pins SDK 2.3.0. This companion does not duplicate a general Python execution or interactive-scene tool. See [Blender alignment](blender-alignment.md) for the integration boundary. Configuring both servers is not evidence of a tested joint session, native installation, or official Blender endorsement.

| Tool | Behavior |
| --- | --- |
| `server_info` | Read configured roots, resource limits and supported operations without launching Blender. |
| `inspect_3do(path)` | Parse one allowlisted 3DO and return format version, geoset/mesh/vertex/face/hierarchy counts, and up to 100 material names. It does not load referenced files. |
| `convert_3do_to_blend(path)` | Import geoset zero into a new `.blend` in a unique job directory. Geometry and placeholder materials only; no texture/palette lookup. JK 2.1 UV coordinates remain unnormalized without texture dimensions. |
| `run_regression` | Run the bundled five-contract baseline 3DO/KEY/MAT harness with logs and a verified launcher receipt. Focused format-fix regressions remain separate. |
| `build_extension` | Build the **companion checkout's** `sith` directory with the deterministic packager. Return ZIP, SHA-256 and receipt. With a configured Blender executable, also run Blender's built-in extension validator on that exact ZIP. This does not publish or install anything. |

The `addon` configuration selects trusted Python source for parsing/conversion/regression. `build_extension` intentionally packages the companion checkout instead, including its manifest and license. The result identifies that source. Use a matching companion/source tree when you want these operations to target the same version.

`build_extension` reports an explicit `validator` result. With the Blender executable route, it runs `blender --command extension validate ZIP` in a fresh bounded process with separate preferences and logs; a rejected archive or validator process failure makes the top-level status `validation_failed`. With the Python+bpy route, packaging can pass while `validator.status` remains `not_run` with the reason that no Blender CLI executable was configured. Importing `bpy` is not a substitute for official extension validation.

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

Start it through your host after reviewing the configured roots. There is no default account, API key, cloud service or HTTP listener. This repository does not modify your host configuration automatically. The configured timeout applies to each subprocess, not to the entire tool call. Packaging with a Blender executable can use two sequential configured timeouts: one for building and one for validation. Set the host's tool timeout above twice the configured timeout plus cleanup and startup margin when using all tools. Regression cleanup can need up to 45 additional seconds.

## Scope and failure handling

Inputs must be regular `.3do` files beneath an explicit read root, no larger than 64 MiB. Relative paths, parent traversal and symlink/junction routes are rejected. A job snapshots only that input into a unique external directory before parsing. Automatic neighboring MAT/CMP discovery is disabled inside the new Blender process. Outputs never replace the input. Source/add-on hashes are checked after model operations and the regression launcher verifies its own report and source hashes.

Jobs are serialized per server; a concurrent request returns an error instead of launching a second Blender. At a subprocess deadline, the service attempts to terminate its owned process tree and records the cleanup outcome. Cleanup is best effort, not a guarantee that the operating system accepted termination. Blender preferences are isolated, user Python injection/optimization variables are removed, and thread counts default to two. Each outer stdout/stderr log retains at most 1 MiB; structured child reports are limited to 256 KiB. Keep job directories as receipts or remove completed ones yourself; there is no automatic deletion tool or retention policy. Regression creates its own detailed logs inside its result directory.

Controlled Blender CLI invocations (model worker, regression launcher and built-in extension validator) include `--offline-mode`. This sets Blender's online-access preference for the process; it is not an OS network sandbox or a claim that arbitrary installed Python code cannot open sockets. The separate Python+bpy route has no Blender CLI flags.

The four job-producing tools return a `status`. Only `passed` means the requested job completed and its report was accepted. A process exit of zero alone is insufficient. Their results include a job directory for logs, input/output hashes where relevant, and bounded structured results. `server_info` is configuration-only: it does not start a job and does not return a job status or directory. Logs and local receipts may contain input names and absolute local paths; review before publishing them.

This is a local trusted-user service, **not an OS security sandbox**. The configured runtime, add-on, companion source and writable job directory must remain trusted and unchanged by other users during a call. Filesystem checks are not a defense against a hostile user racing filesystem changes. Blender/parsers execute with the server user's permissions; there is no hard memory or disk quota. Cancelled host requests may finish their bounded job before returning. The service exposes no arbitrary Python, shell, scene-editing, network, publishing, blend-file loading or deletion tool.

Geometry-only conversion is a useful starting point, not a textured round trip or retail-game acceptance test. It inherits the upstream importer restriction to geoset zero, and it does not normalize JK 2.1 UVs using absent texture sizes. `inspect_3do` summarizes all parsed geosets. Record the exact runtime version and platform with each test. Native macOS execution and joint operation with Blender Lab MCP require separate validation.

## Verification

Run `python -B -m unittest discover -s tests -p test_mcp_server.py -v` with `TEMP`/`TMP` (Windows) or `TMPDIR` (Unix) set to external scratch storage. These unit tests do not require the SDK or Blender. The companion supplies a real stdio integration check using the official SDK client:

```sh
/srv/blender-sith-env/bin/python -B /src/blender-sith/mcp_server/smoke_test.py \
  --config /srv/blender-sith-config.json \
  --input /srv/authorized-models/synthetic-cube.3do \
  --evidence /srv/blender-sith-smoke.json
```

This lists all five tools, exercises inspection/conversion, independently verifies the produced blend hash, runs the regressions, builds an extension and verifies traversal rejection. It requires an authorized valid synthetic 3DO and creates new jobs. Its evidence file must be new and outside Git. Keep its absolute-path-bearing evidence local or sanitize it before publication.

Protocol documentation: [official Python SDK](https://py.sdk.modelcontextprotocol.io/) and [stdio server guide](https://modelcontextprotocol.io/docs/develop/build-server). The SDK is an optional host dependency with its own MIT license; Blender-Sith and this companion remain GPL-3.0-or-later.
