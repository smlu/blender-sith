# SPDX-FileCopyrightText: 2026 Crt Vavros
# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve editable material cels and safely publish a model/texture bundle."""
import os
from pathlib import Path, PureWindowsPath
import shutil
import tempfile

import numpy as np

from .cmp import ColorMap
from .mat import kMatCelImagePrefix, kMatMissingPixels
from .matWriter import MatCel, encodeMat


class ExportRollbackError(RuntimeError):
    """Keep the staging directory if an OS error prevents restoring originals."""


def _filename(name):
    if (not name or name in ('.', '..') or any(char in name for char in '/\\\0:<>"|?*')
            or name.endswith((' ', '.')) or PureWindowsPath(name).is_reserved()):
        raise ValueError(f'Unsafe MAT output filename: {name!r}; use a portable filename without folders')


def _images(material):
    import bpy
    from ..model.utils import getMaterialImage

    if isinstance(material, bpy.types.Image):
        return [material]
    if not isinstance(material, bpy.types.Material):
        raise ValueError('Select a material or image to export')
    bound = {}
    for name in material.keys():
        if not name.startswith(kMatCelImagePrefix):
            continue
        suffix = name[len(kMatCelImagePrefix):]
        if not suffix.isdecimal():
            continue
        image = material[name]
        if not isinstance(image, bpy.types.Image):
            raise ValueError(f"Material '{material.name}' has an invalid image binding for cel {suffix}")
        index = int(suffix)
        if index in bound:
            raise ValueError(f"Material '{material.name}' has duplicate cel {index}")
        bound[index] = image
    if 0 not in bound:
        image = getMaterialImage(material)
        if image is None:
            raise ValueError(f"Material '{material.name}' has no exportable texture; bake shaders to an image first")
        bound[0] = image
    if sorted(bound) != list(range(len(bound))):
        raise ValueError(f"Material '{material.name}' has missing cels; cel indices must be consecutive from zero")
    return [bound[index] for index in range(len(bound))]


def prepareMatExports(materials, directory, encoding, palettePath='', *, overwrite=False,
                      generateMipmaps=True, grim=False, warnings=None):
    """Encode material cels or individual images before touching output files."""
    directory = Path(directory)
    if directory.is_symlink() or (getattr(directory, 'is_junction', lambda: False)()):
        raise ValueError('MAT output directory cannot be a symbolic link or junction')
    named = {}
    for name, material in materials:
        _filename(name)
        if name in named and named[name] != material:
            raise ValueError(f"Different Blender materials resolve to '{name}'; rename them before exporting textures")
        named[name] = material
    pending = []
    for name, material in named.items():
        target = directory / name
        if target.is_symlink() or target.is_dir():
            raise ValueError(f'Unsafe MAT output path: {target}')
        if target.exists() and not overwrite:
            if warnings is not None:
                warnings.append(f"Kept existing MAT '{name}' (Overwrite Existing MAT Files is disabled)")
            continue
        pending.append((target, material))
    if not pending:
        return []
    if grim and encoding != 'INDEXED':
        raise ValueError('Grim Fandango textures require Indexed encoding and a CMP palette')
    palette = None
    if encoding == 'INDEXED':
        if not os.fspath(palettePath):
            raise ValueError('Select a CMP palette to export indexed MAT textures')
        palette = ColorMap.load(palettePath)

    result = []
    for target, material in pending:
        cels = []
        for image in _images(material):
            if (image.source not in ('FILE', 'GENERATED') or image.get(kMatMissingPixels)
                    or min(image.size) <= 0):
                raise ValueError(f"Image '{image.name}' has no exportable still-image pixels; load/bake it or reload its MAT with a CMP")
            width, height = image.size
            pixels = np.empty(width * height * 4, dtype=np.float32)
            # FILE images may load lazily: has_data can be false until this read.
            try:
                image.pixels.foreach_get(pixels)
            except RuntimeError as error:
                raise ValueError(f"Cannot read RGBA pixels from image '{image.name}'") from error
            if not np.isfinite(pixels).all():
                raise ValueError(f"Image '{image.name}' contains nonfinite pixels")
            if warnings is not None:
                if np.any(pixels < 0) or np.any(pixels > 1):
                    warnings.append(f"Clamped HDR values in '{image.name}' to the MAT range [0,1]")
                if encoding in ('RGB24', 'RGB565') and np.any(pixels[3::4] < 1):
                    warnings.append(f"Encoding {encoding} discards alpha from '{image.name}'")
            cels.append(MatCel(width, height, pixels))
        result.append((target, encodeMat(cels, encoding, palette,
                                        generateMipmaps=generateMipmaps, grim=grim)))
    return result


def _same_volume(first, second):
    return Path(first).stat().st_dev == Path(second).stat().st_dev


def publishExportFiles(files, staging, *, warnings=None):
    """Publish prepared files and return written paths; roll back on failure."""
    staging = Path(staging)
    completed = []
    created_directories = []
    active_backup = None
    active_target = None
    local_temporaries = []
    keep_recovery = False
    try:
        for number, (target, prepared, overwrite) in enumerate(files):
            target, prepared = Path(target), Path(prepared)
            if not target.parent.exists():
                missing = []
                directory = target.parent
                while not directory.exists():
                    missing.append(directory)
                    directory = directory.parent
                for directory in reversed(missing):
                    try:
                        directory.mkdir()
                    except FileExistsError:
                        if not directory.is_dir():
                            raise
                    else:
                        created_directories.append(directory)
            if target.is_symlink() or target.is_dir():
                raise ValueError(f'Unsafe export destination: {target}')
            if not overwrite:
                # Exclusive creation protects a MAT that appeared since preflight.
                try:
                    destination = target.open('xb')
                except FileExistsError:
                    if warnings is not None:
                        warnings.append(f"Kept MAT '{target.name}' created during export")
                    continue
                try:
                    with destination, prepared.open('rb') as source:
                        shutil.copyfileobj(source, destination)
                except BaseException:
                    target.unlink()
                    raise
                completed.append((target, None))
                continue

            active_target = target
            active_backup = None
            # A custom MAT folder may live on a different drive. Prepare a local
            # copy so the final rename and its rollback stay on one filesystem.
            if not _same_volume(prepared, target.parent):
                descriptor, name = tempfile.mkstemp(prefix='.sith-write-', dir=target.parent)
                os.close(descriptor)
                local = Path(name)
                local_temporaries.append(local)
                shutil.copyfile(prepared, local)
                prepared = local
            if target.exists():
                if _same_volume(staging, target.parent):
                    backup = staging / f'backup-{number}'
                else:
                    descriptor, name = tempfile.mkstemp(prefix='.sith-backup-', dir=target.parent)
                    os.close(descriptor)
                    backup = Path(name)
                    local_temporaries.append(backup)
                os.replace(target, backup)
                active_backup = backup
            os.replace(prepared, target)
            completed.append((target, active_backup))
            active_target = active_backup = None
    except BaseException as error:
        failures = []
        if active_backup is not None:
            try:
                os.replace(active_backup, active_target)
            except OSError as failure:
                failures.append(str(failure))
        for target, backup in reversed(completed):
            try:
                if backup is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(backup, target)
            except OSError as failure:
                failures.append(str(failure))
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        if failures:
            keep_recovery = True
            raise ExportRollbackError(f'Export failed and some originals could not be restored. Keep recovery files in {staging} and {local_temporaries}: {failures}') from error
        raise
    finally:
        if not keep_recovery:
            for path in local_temporaries:
                try:
                    path.unlink(missing_ok=True)
                except OSError as error:
                    if warnings is not None:
                        warnings.append(f'Could not remove export temporary file {path}: {error}')
            for directory in reversed(created_directories):
                try:
                    directory.rmdir()
                except OSError:
                    pass
    return [target for target, _ in completed]


def exportMat(source, path, encoding='RGBA32', palettePath='', *, overwrite=False,
              generateMipmaps=True, grim=False, warnings=None):
    """Export one image or a material's bound cels; return False if kept existing."""
    import bpy

    if not isinstance(source, (bpy.types.Material, bpy.types.Image)):
        raise ValueError('Select a material or image to export')
    # Access the captured ID before any skip/write: a removed datablock must not
    # silently fall back to another active material while the browser is open.
    source.name
    if not os.fspath(path):
        raise ValueError('Select a MAT output file')
    destination = Path(bpy.path.abspath(os.fspath(path))).absolute()
    if destination.suffix.lower() != '.mat':
        raise ValueError('MAT output filename must end with .mat')
    palette = os.fspath(palettePath)
    if palette:
        palette = bpy.path.abspath(palette)
        if not Path(palette).is_absolute():
            palette = str(destination.parent / palette)

    textures = prepareMatExports([(destination.name, source)], destination.parent, encoding,
                                 palette, overwrite=overwrite, generateMipmaps=generateMipmaps,
                                 grim=grim, warnings=warnings)
    if not textures:
        return False
    staging = Path(tempfile.mkdtemp(prefix='sith-mat-export-'))
    keepRecovery = False
    try:
        prepared = staging / 'texture'
        prepared.write_bytes(textures[0][1])
        return bool(publishExportFiles([(destination, prepared, overwrite)], staging, warnings=warnings))
    except ExportRollbackError:
        keepRecovery = True
        raise
    finally:
        if not keepRecovery:
            try:
                shutil.rmtree(staging)
            except OSError as error:
                if warnings is not None:
                    warnings.append(f'Could not remove export temporary directory {staging}: {error}')
