# Background regression checks

The command-line launcher runs Blender-Sith checks in a fresh background process.
It requires an existing Blender executable or a Python interpreter with compatible
`bpy`; it does not install dependencies, modify desktop preferences, or download
runtimes. Keep runtimes, environments and generated results outside Git checkouts.

```sh
python3 scripts/run_regression.py --blender /opt/blender/blender \
  --output /external/sith-check-001 --threads 2 --timeout 300
```

Shell and PowerShell wrappers forward the same arguments, including paths with
spaces. The Python-plus-`bpy` alternative is:

```powershell
python scripts/run_regression.py --python C:\Python313\python.exe `
  --bpy-site C:\runtimes\bpy-site --output C:\builds\sith-check-001
```

The output must be a new directory outside the source and every Git checkout.
Lexical and resolved routes are checked so a checkout junction cannot hide the
output's location. A separate extracted extension can be selected with `--addon`.

Each job uses isolated Blender user directories, factory startup, disabled
automatic script execution, two threads by default and a 300-second default
deadline. The Blender executable route also sets `--offline-mode`, which is a
Blender preference rather than an operating-system network sandbox. The real
harness also disables automatic-script execution through the bpy preference,
asserts that it is disabled and records its final value in the report; this covers
the Python-plus-bpy route. User Python
injection and optimization environment variables are removed. Timeout cleanup
targets the owned process group/tree and records its best-effort outcome.

## Baseline contracts

The bundled harness tests five established upstream behaviors:

- Smooth-cube vertex normals and unchanged source geometry.
- UV seams, absolute UV scaling, materials, linear-light vertex colors (including
  byte-color attributes) and face properties.
- Parent/child hierarchy, local positions and model offset.
- Linear animated KEY frames for the JKDF2 target and canonical hexadecimal
  metadata through the current exporter modules.
- Indexed MAT cels and mip levels with an explicitly supplied CMP palette,
  including transparency and imported image dimensions.

These baseline checks are independent of proposed corner-normal, hexadecimal
normalization, material-delimiter and palette-free MAT fixes. Focused regression
scripts supplied with those changes should also be run when reviewing them.
The baseline harness does not imply those separate behaviors have been repaired.

A successful launcher exit requires a complete nonempty report, consistent test
counts, matching harness/add-on hashes, all assertions passing, and unchanged
source. Process exit zero alone is insufficient. Logs and portable `receipt.json`
remain beside `results/regression.json` and synthetic exported fixtures.

The harness can also run directly in a fresh background process:

```sh
blender --background --factory-startup --offline-mode --disable-autoexec \
  --python-exit-code 1 --python tests/background_regression.py -- \
  --output /external/sith-direct-001
```

Direct execution requires the caller to arrange preference isolation and a
process deadline. The harness rejects an interactive Blender process, optimized
Python assertions, reused output and output inside a source/Git tree.

## Full upstream suites

The five-contract baseline is a quick runtime check with launcher receipts.
Upstream also supplies broader resource and application suites; run those when
validating changes to the formats or Blender integration:

```sh
python -B tests/run.py --suite core
blender --background --factory-startup --offline-mode --disable-autoexec \
  --python-exit-code 1 --python tests/run.py -- --suite app
```

Use a separate process and external temporary storage for these suites. The
application suite enables the add-on through Blender's restricted registration
path. The baseline calls the explicit exporter modules after registering its
chosen add-on; it does not depend on package-level export aliases.

## Launcher tests

The standard-library unit suite does not need Blender. Set `TEMP`/`TMP` on Windows
or `TMPDIR` on Unix to external scratch storage, then run:

```sh
python -B -m unittest discover -s tests -p 'test_run_regression.py' -v
python -B -m unittest discover -s tests -p 'test_regression_entrypoint.py' -v
```

These tests exercise report validation, failure receipts, source changes, output
restrictions, environment isolation, wrappers and process-tree timeout cleanup.
Host-specific wrapper and filesystem fixtures report explicit capability skips.

This is local process orchestration, not an OS security sandbox. Thread limits
are resource controls, not measured speed improvements. Synthetic format checks
do not establish interactive installation, retail rendering or multiplayer
compatibility. No game assets or network access are required for the fixtures.
