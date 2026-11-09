# SPDX-License-Identifier: GPL-3.0-or-later
$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'run_regression.py') @args
exit $LASTEXITCODE
