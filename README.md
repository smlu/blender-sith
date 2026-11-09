<div align="center">

# 🎮 Sith Engine Toolkit for Blender

[![Blender](https://img.shields.io/badge/Blender-5.0+-orange.svg?style=flat&logo=blender)](https://www.blender.org/)
[![Tests](https://github.com/smlu/blender-sith/actions/workflows/tests.yml/badge.svg)](https://github.com/smlu/blender-sith/actions/workflows/tests.yml)
[![License](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg?style=flat)](LICENSE)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-purple.svg?style=flat)

**Import/Export assets for classic LucasArts games**

[<img src="demo/social-preview-painted-scaled.jpg"/>](demo/blsthbn.png)

[🚀 Installation](#-installation) • [📖 Usage Guide](USAGE.md) • [🔧 Troubleshooting](USAGE.md#-troubleshooting)

</div>

---

## 📑 Table of Contents

- [Supported Games](#️-supported-games)
- [Features](#-features)
- [Quick Start](#-quick-start)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [Usage](USAGE.md)
- [Technical Documentation](docs/README.md)
- [Contributing](#-contributing)
- [Tests](#tests)
- [Links](#links)

---

## 🕹️ Supported Games

- Star Wars Jedi Knight: Dark Forces II
- Star Wars Jedi Knight: Mysteries of the Sith
- Star Wars: DroidWorks
- Indiana Jones and the Infernal Machine
- Grim Fandango

---

## ✨ Features
<div align="center">
<img src="demo/gif/in_hat2.gif" width="48%"/>
</div>
<div align="center">
</div>

---

<table>
<tr>
<td width="50%">

### 📦  3DO Models
- ✅ Import/Export 3DO 2.1, 2.2 and 2.3
- ✅ Grim Fandango MODL binary import/export
- 🎨 Mesh hierarchy editing
- 🔧 Edit properties in Blender UI
- 🎯 Vertex colors & UV mapping

### 🎬 KEY Animations
- ✅ Import/Export mesh animations
- ✅ Grim Fandango FYEK binary import/export
- 🛟 KEY recovery & flexible frame starts
- 🎞️  Keyframe markers support
- ⚙️ Node-type priority masks
- 📊 Fractional playback rates

</td>
<td width="50%">

### 🖼️ MAT Textures
- ✅ Import as Blender materials
- 📤 Export materials/textures to MAT
- 🎞️ Animated texture cels
- 🎨 8-bit, 16-bit, 24-bit & 32-bit formats
- 🔧 ColorMap (.cmp) support
- ✅ Grim Fandango indexed MAT variants

### 🛠️ Advanced Editing
- 🎛️ Per-face properties & flags
- 🔦 Lighting & texture modes
- 🎨 Extra light color support
- 💡 Live Extra Light preview
- ⚡ Multi-face batch editing

</td>
</tr>
</table>



## ⚡ Quick Start

1. **Install**: Download from [Releases](https://github.com/smlu/blender-sith/releases) and install via Blender Extensions
2. **Import Model**: `File > Import > Sith Game Engine 3D Model (.3do)`
3. **Import Textures**: Use MAT Directory option or let auto-search find them
4. **Import Animation**: `File > Import > Sith Game Engine Animation (.key)`
5. **Edit Properties**: Use the 3DO Properties panels (see [Usage Guide](USAGE.md))
6. **Export**: `File > Export` to save your modifications

> 📖 **Detailed instructions**: See the [Usage Guide](USAGE.md) for complete documentation.

---

## 📋 Requirements

> **Blender 5.0+** is required for this version of the add-on.

🔗 [Download Blender](https://www.blender.org/download/)

---

## 🚀 Installation

### Method 1: From Release (Recommended)

1. 📥 **Download** the latest ZIP from the [Releases](https://github.com/smlu/blender-sith/releases) page
2. 🔧 **Open Blender** and go to `Edit > Preferences > Add-ons`
3. 📂 **Install**: Click the dropdown menu (▼) at the top-right and select `Install from Disk...`
4. 📁 **Select** the downloaded ZIP file
5. ✅ **Enable** the add-on: Check the box next to **Sith Game Engine Formats (.3do, .mat, .key)**
6. 🎉 **Done!** Import/export options appear in `File > Import` and `File > Export` menus

### Method 2: From Source

```bash
# Clone or download the repository
git clone https://github.com/smlu/blender-sith.git
cd blender-sith

# Build the installable extension archive (Python 3.11+, standard library only)
python scripts/make_addon.py
```

Install the resulting `build/sith.zip` using **Install from Disk...**. The builder
is independent of the working directory and accepts `--output /path/to/sith.zip`.
It packages the current `sith` extension with its manifest at the archive root,
omits development/Blender backup files, and leaves sources untouched. An existing
archive is replaced only after a successful build; an unreadable source directory
aborts the build instead of silently omitting modules. The output must stay outside
the source tree, including physical aliases through alternate namespaces or mounts.
`scripts/make_addon.sh` is a
compatibility wrapper for Bash users; no external `zip` command is required.

Blender's 3DO workflow imports/exports **LOD 0 only**. Extra geosets in a source
model are not retained by the Blender round trip; see the [Usage Guide](USAGE.md).

> 💡 **Note**: In Blender 5.0, add-ons are managed through the Extensions system.

---

## 📖 Usage

For complete documentation on importing, exporting, and editing, see the **[Usage Guide](USAGE.md)**.
For byte layouts, field tables and ASCII structure diagrams, see the
[technical documentation](docs/README.md) and [format reference](docs/formats/README.md).
The [Blender pipeline guide](docs/blender-pipeline.md) explains model/animation
conversion, baked pivots, UV units, hierarchy ordering and mesh-list sync.

### Quick Reference

- **Import 3DO**: `File > Import > Sith Game Engine 3D Model (.3do)`
- **Export 3DO**: `File > Export > Sith Game Engine 3D Model (.3do)`
- **Import KEY**: `File > Import > Sith Game Engine Animation (.key)`
- **Export KEY**: `File > Export > Sith Game Engine Animation (.key)`
- **Import MAT**: `File > Import > Sith Game Engine Texture (.mat)`
- **Export MAT**: `Image Editor > Image > Export to MAT...`, or right-click an image/material in the Outliner or a material row in Material Properties
- **Edit Properties**: `Properties Panel > Object Properties > 3DO Properties`
- **Edit Faces**: `Properties Panel > Data Properties > 3DO Mesh Face Properties` (Edit Mode)

> 📖 See [USAGE.md](USAGE.md) for detailed options, screenshots, and troubleshooting.

---

## 🤝 Contributing

Contributions are welcome! Feel free to:
- 🐛 Report bugs via [Issues](https://github.com/smlu/blender-sith/issues)
- 💡 Suggest features or improvements
- 🔧 Submit pull requests

---

## Tests

Resource codecs run in ordinary Python 3.11+ without Blender:

```sh
python -m pip install -r tests/requirements.txt
python tests/run.py --suite core
```

Blender import/export tests run in a separate Blender 5.0+ process:

```sh
blender --background --factory-startup --python-exit-code 1 --python tests/run.py -- --suite app
```

Both suites use standard-library `unittest` and synthetic fixtures. GitHub Actions
runs the core suite on Windows, macOS and Linux, and the application suite in
headless Blender on Linux. See [tests/README.md](tests/README.md) for coverage,
commands and interpolation limitations.

## Links

- 📦 [Releases](https://github.com/smlu/blender-sith/releases) - Download the latest version
- 🐛 [Issue Tracker](https://github.com/smlu/blender-sith/issues) - Report bugs or request features
- 🌐 [Blender.org](https://www.blender.org/) - Get Blender

---

<div align="center">

**⭐ If you find this project useful, consider giving it a star!**

</div>
