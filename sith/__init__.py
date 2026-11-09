# SPDX-FileCopyrightText: 2026 Crt Vavros
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sith resources can be used without loading Blender's application layer."""

if 'app' in locals():
    import importlib
    importlib.reload(app)


def register():
    from . import app
    app.register()


def unregister():
    from . import app
    app.unregister()
