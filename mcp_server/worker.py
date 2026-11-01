#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixed Blender subprocess worker. Not an arbitrary script execution endpoint."""
import importlib
import importlib.util
import json
from pathlib import Path
import sys


def main():
    sys.dont_write_bytecode = True
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    request = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    if request["bpy_site"]:
        sys.path.insert(0, request["bpy_site"])
    import bpy
    if not bpy.app.background:
        raise RuntimeError("Refusing an interactive Blender process")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.filepaths.use_scripts_auto_execute = False
    for scene in bpy.data.scenes:
        scene.render.threads_mode = "FIXED"
        scene.render.threads = request["threads"]
    root = Path(request["addon"])
    name = "sith_mcp_job"
    spec = importlib.util.spec_from_file_location(name, root / "__init__.py", submodule_search_locations=[str(root)])
    addon = importlib.util.module_from_spec(spec)
    sys.modules[name] = addon
    spec.loader.exec_module(addon)
    addon.register()
    loader = importlib.import_module(name + ".model.model3doLoader")
    model, version = loader.load3do(request["input"])
    # The upstream parser tolerates empty/unknown files. Require actual geometry.
    if not model.geosets or not model.meshHierarchy or not model.geosets[0].meshes:
        raise ValueError("No importable model geometry/hierarchy found")
    meshes = [mesh for geoset in model.geosets for mesh in geoset.meshes]
    report = {"schema": "blender-sith-mcp-model-v1", "blender": bpy.app.version_string,
              "format_version": version.value, "geosets": len(model.geosets), "meshes": len(meshes),
              "vertices": sum(len(m.vertices) for m in meshes), "faces": sum(len(m.faces) for m in meshes),
              "hierarchy_nodes": len(model.meshHierarchy), "material_count": len(model.materials),
              "materials": [str(m)[:256] for m in model.materials[:100]], "materials_truncated": len(model.materials) > 100,
              "scope": "Parsed model counts; no implicit referenced-file reads or game validation"}
    if request["output"]:
        importer = importlib.import_module(name + ".model.model3doImporter")
        # Binding overrides are confined to this new background process. They
        # suppress the upstream importer's automatic neighbor MAT/CMP searches.
        importer.getCmpFileOrDefault = lambda *args: None
        importer.getDefaultMatFolders = lambda *args: []
        importer.importMaterials = lambda *args: None
        obj = importer.import3do(request["input"], mat_dirs=[], cmp_file="", uvAbsolute_2_1=False,
                                 importVertexColors=True, importRadiusObj=False, preserveOrder=True, clearScene=True)
        if obj is None:
            raise ValueError("Importer produced no object")
        bpy.ops.wm.save_as_mainfile(filepath=request["output"], check_existing=False)
        report.update(converted_geoset=0, object_count=len(bpy.data.objects),
                      conversion="Geometry and placeholder materials only; JK 2.1 UVs remain unnormalized without texture dimensions")
    Path(request["report"]).write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
