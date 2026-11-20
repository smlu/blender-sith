# Isolated Application Tests

The optional launcher runs the existing [`tests/run.py`](../tests/run.py)
application suite in a separate Blender 5.0+ process:

```sh
python scripts/run_regression.py --blender /path/to/blender --timeout 600
```

On Windows, an installed Blender executable or its Microsoft Store alias can be
supplied directly, including paths containing spaces:

```powershell
python scripts/run_regression.py --blender "$env:LOCALAPPDATA\Microsoft\WindowsApps\blender-launcher.exe" --timeout 600
```

The launcher uses background/factory-startup mode, disables automatic script
execution, enables offline mode, and limits Blender and common numeric libraries
to two threads. It creates fresh temporary `BLENDER_USER_CONFIG`,
`BLENDER_USER_SCRIPTS`, `BLENDER_USER_DATAFILES` and `BLENDER_USER_EXTENSIONS`
directories, removes ambient Python path/home/optimization overrides, and runs
with a temporary working directory outside the checkout. These settings isolate
normal preferences; they are not a sandbox for untrusted code.

Standard output and errors are relayed directly, including the existing suite's
test count and failures. The launcher returns Blender's exit status. A timeout
stops the launched process and its descendants and returns 124; an interrupted
run returns 130; a failed launch returns 127. Temporary settings are removed when
the process ends. Redirect logs to a location outside the checkout when needed.

The test runner and fixtures remain the ones documented in
[`tests/README.md`](../tests/README.md): this adds no separate format tests,
private-codec assertions, registration path, or receipt format. Run core tests
with `python tests/run.py --suite core`; direct Blender commands and CI remain
available as documented there.
