#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
exec "${PYTHON:-python3}" "$script_dir/run_regression.py" "$@"
