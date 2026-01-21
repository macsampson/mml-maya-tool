# Mega Man Legends (PSX) File Format Documentation

This document describes the file formats used in Mega Man Legends (Rockman DASH) for PlayStation, based on reverse engineering efforts and analysis of the DashViewer tool by xdaniel.

## Table of Contents

1. [Overview](#overview)
2. [Container Header Format](#container-header-format)
3. [TIM Image Format (MML Variant)](#tim-image-format-mml-variant)
4. [EBD Model Format](#ebd-model-format)
5. [Tools](#tools)
6. [References](#references)

---

## Overview

Mega Man Legends uses a custom container format that wraps standard PlayStation file types (TIM images, model data, etc.) with a 2048-byte (0x800) header containing metadata and the original file path.

### Key Characteristics

- **Byte Order**: Little-endian (standard for PlayStation/x86)
- **Container Header Size**: 2048 bytes (0x800)
- **Alignment**: Files are typically aligned to 2048-byte boundaries
- **PS1 Memory Addresses**: Many offsets are stored as PlayStation RAM addresses (0x80XXXXXX) that must be converted to file offsets

### Address Conversion Formula

To convert a PS1 RAM address to a file offset:

```
file_offset = (ps1_address - ram_base_address) + 0x800
```

Where `ram_base_address` is stored at offset 0x0C in the container header.

---

## Container Header Format

All MML data files share a common 2048-byte container header structure.

### Header Structure (0x000 - 0x0FF active, 0x100 - 0x7FF padding)

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0x00 | 4 | uint32 | File type identifier |
| 0x04 | 4 | uint32 | Data size (excluding header) |
| 0x08 | 4 | uint32 | Type-specific field |
| 0x0C | 4 | uint32 | PS1 RAM base address (for address conversion) |
| 0x10 | 4 | uint32 | Type-specific field |
| 0x14 | 4 | uint32 | Type-specific field (often TIM magic 0x10 for images) |
| 0x18 | 4 | uint32 | Type-specific field (often TIM flags for images) |
| 0x1C | 36 | - | Type-specific fields |
| 0x40 | 64 | string | Original file path (null-terminated, e.g., "..\OBJ\FACE\PL00B01.TIM") |
| 0x80 | 128 | - | Padding (zeros) |
| 0x100 | 1792 | - | Padding (zeros) to reach 0x800 |

### File Type Values

| Value | Type | Description |
|-------|------|-------------|
| 0 | Data | Generic binary data (models, scripts, etc.) |
| 1 | TIM | Full TIM image with CLUT |
| 3 | Font | Font data |
| 4 | CLUT | Separate CLUT palette file |
| 5 | SoundVAB | VAB sound data |
| 8 | SoundSEP | SEP sound data |
| 9 | TIMCLUTOnly | CLUT-only TIM (no image data) |
| 10 | TIMCLUTPatch | CLUT patch data |
| -1 | ArchiveEnd | End of archive marker |

### File Sub-Types (for Type 0 - Data)

Determined by file extension:
- `*P.PBD` - Player model file
- `*.EBD` - Embedded model file (stage objects)
- `*.MSG` - Message/script data
- `*.MDT` - Stage floor map

---

## TIM Image Format (MML Variant)

MML wraps standard PlayStation TIM images in its container format with additional metadata.

### Container Header Fields for TIM

| Offset | Size | Description |
|--------|------|-------------|
| 0x00 | 4 | File type (1 = TIM) |
| 0x04 | 4 | Total data size |
| 0x08 | 4 | Unknown |
| 0x0C | 4 | Image width in pixels |
| 0x10 | 4 | Image height in pixels |
| 0x14 | 4 | TIM magic (0x00000010) |
| 0x18 | 4 | TIM flags |
| 0x1C | 4 | Additional width/size info |
| 0x20 | 4 | Unknown (often 0) |
| 0x24 | 4 | CLUT data offset (relative) |
| 0x28 | 4 | Pixel data offset (relative) |

### TIM Flags (at offset 0x18)

```
Bits 0-2: Pixel mode (pMode)
  0 = 4-bit indexed (16 colors)
  1 = 8-bit indexed (256 colors)
  2 = 16-bit direct color
  3 = 24-bit direct color

Bit 3: Has CLUT flag
  0 = No CLUT
  1 = Has CLUT
```

### Data Layout (4-bit indexed mode example)

| Offset | Size | Description |
|--------|------|-------------|
| 0x000 | 256 | Container header |
| 0x100 | 256 | CLUT data (8 palettes × 16 colors × 2 bytes) |
| 0x200 | 1536 | Padding (zeros) |
| 0x800 | varies | Pixel data (4-bit packed, 2 pixels per byte) |

### CLUT Color Format (16-bit ABGR)

```
Bit 15:    Semi-transparency flag
Bits 10-14: Blue (5 bits)
Bits 5-9:   Green (5 bits)
Bits 0-4:   Red (5 bits)
```

To convert to 8-bit RGB:
```python
r = (color & 0x1F) << 3
g = ((color >> 5) & 0x1F) << 3
b = ((color >> 10) & 0x1F) << 3
```

### Pixel Data (4-bit mode)

Each byte contains two pixels:
```
Low nibble (bits 0-3):  First pixel (left)
High nibble (bits 4-7): Second pixel (right)
```

---

## EBD Model Format

EBD (Embedded Binary Data) files contain 3D model data for stage objects, enemies, and other entities.

### Overall Structure

```
┌─────────────────────────────────────┐
│ Container Header (0x000 - 0x7FF)    │
├─────────────────────────────────────┤
│ Model Count (4 bytes at 0x800)      │
├─────────────────────────────────────┤
│ Model Entry Table (16 bytes each)   │
├─────────────────────────────────────┤
│ Limb Index Data                     │
├─────────────────────────────────────┤
│ LOD Pointers                        │
├─────────────────────────────────────┤
│ Limb Information Entries            │
├─────────────────────────────────────┤
│ Vertex Data                         │
├─────────────────────────────────────┤
│ Triangle Data                       │
├─────────────────────────────────────┤
│ Quad Data                           │
├─────────────────────────────────────┤
│ Animation Data (if present)         │
└─────────────────────────────────────┘
```

### Container Header Fields for EBD

| Offset | Size | Description |
|--------|------|-------------|
| 0x00 | 4 | File type (0 = Data) |
| 0x04 | 4 | Data size |
| 0x08 | 4 | Entry count (number of objects) |
| 0x0C | 4 | PS1 RAM base address |
| 0x40 | 64 | File path string |

### Model Entry (16 bytes each, starting at 0x800 + 4)

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0x00 | 4 | uint32 | Unknown/flags |
| 0x04 | 4 | PS1 addr | Limb information start address |
| 0x08 | 4 | PS1 addr | Hierarchy/animation info start address |
| 0x0C | 4 | PS1 addr | Animation order start address |

### Limb Information Block

Located at the address specified in Model Entry offset 0x04.

| Offset | Size | Description |
|--------|------|-------------|
| 0x00 | 16 | Header data |
| 0x10 | varies | Limb index array (4 bytes each) |
| 0x70 | 12 | LOD model addresses (3 × 4 bytes: high, medium, low detail) |

### Limb Index Entry (4 bytes each)

| Offset | Size | Description |
|--------|------|-------------|
| 0x00 | 1 | Render index (which limb to render) |
| 0x01 | 1 | Parent index (for skeletal hierarchy) |
| 0x02 | 1 | Translation index (bone position) |
| 0x03 | 1 | Padding |

### LOD Model Header

Located at each LOD address from the Limb Information Block.

| Offset | Size | Description |
|--------|------|-------------|
| 0x00 | 3 | Unknown |
| 0x03 | 1 | Limb count for this LOD |
| 0x04 | 16 | Unknown |
| 0x14 | varies | Limb info entries (20 bytes each) |

### Limb Info Entry (20 bytes)

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0x00 | 1 | uint8 | Triangle count |
| 0x01 | 1 | uint8 | Quad count |
| 0x02 | 1 | uint8 | Vertex count |
| 0x03 | 1 | uint8 | Limb number/index |
| 0x04 | 4 | PS1 addr | Triangle data start (valid if byte 0x07 == 0x80) |
| 0x08 | 4 | PS1 addr | Quad data start (valid if byte 0x0B == 0x80) |
| 0x0C | 2 | uint16 | Texture page info |
| 0x0E | 2 | uint16 | CLUT page info |
| 0x10 | 4 | PS1 addr | Vertex data start (valid if byte 0x13 == 0x80) |

### Texture Page Info (16-bit)

```
Bits 0-3:   Texture page X (multiply by 64 for pixel coord)
Bit 4:      Texture page Y (multiply by 256 for pixel coord)
Bits 5-6:   Unknown
Bits 7-8:   Color mode (0=4-bit, 1=8-bit, 2=16-bit)
Bits 9-15:  Unknown
```

### CLUT Page Info (16-bit)

```
Bits 0-5:   CLUT X position (multiply by 16)
Bits 6-15:  CLUT Y position
```

### Vertex Data (8 bytes per vertex)

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0x00 | 2 | int16 | X coordinate (negate for correct orientation) |
| 0x02 | 2 | int16 | Y coordinate (negate for correct orientation) |
| 0x04 | 2 | int16 | Z coordinate (negate for correct orientation) |
| 0x06 | 2 | - | Padding |

**Note**: Coordinates are typically divided by 100 for reasonable scale in modern 3D software.

### Triangle Data (12 bytes per triangle)

| Offset | Size | Description |
|--------|------|-------------|
| 0x00 | 1 | U coordinate for vertex 0 |
| 0x01 | 1 | V coordinate for vertex 0 |
| 0x02 | 1 | U coordinate for vertex 1 |
| 0x03 | 1 | V coordinate for vertex 1 |
| 0x04 | 1 | U coordinate for vertex 2 |
| 0x05 | 1 | V coordinate for vertex 2 |
| 0x06 | 2 | Unknown (possibly normal or color index) |
| 0x08 | 1 | Vertex index 0 |
| 0x09 | 1 | Vertex index 1 |
| 0x0A | 1 | Vertex index 2 |
| 0x0B | 1 | Padding |

### Quad Data (12 bytes per quad)

| Offset | Size | Description |
|--------|------|-------------|
| 0x00 | 1 | U coordinate for vertex 2 |
| 0x01 | 1 | V coordinate for vertex 2 |
| 0x02 | 1 | U coordinate for vertex 3 |
| 0x03 | 1 | V coordinate for vertex 3 |
| 0x04 | 1 | U coordinate for vertex 1 |
| 0x05 | 1 | V coordinate for vertex 1 |
| 0x06 | 1 | U coordinate for vertex 0 |
| 0x07 | 1 | V coordinate for vertex 0 |
| 0x08 | 1 | Vertex index 2 |
| 0x09 | 1 | Vertex index 3 |
| 0x0A | 1 | Vertex index 1 |
| 0x0B | 1 | Vertex index 0 |

**Note**: Quad vertex indices and UVs are stored in a non-sequential order (2, 3, 1, 0) and must be reordered when reading.

### Bone/Translation Data (8 bytes per bone)

Located at the address specified in the hierarchy info.

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0x00 | 2 | int16 | X translation (negate) |
| 0x02 | 2 | int16 | Y translation (negate) |
| 0x04 | 2 | int16 | Z translation (negate) |
| 0x06 | 2 | - | Padding |

---

## Tools

### mml_tim2png.py

Converts MML TIM container files to PNG format.

**Usage:**
```bash
python mml_tim2png.py <input.tim> [output.png]
python mml_tim2png.py -a <input.tim>  # Export all 8 palette variations
```

**Features:**
- Handles MML's custom container format
- Supports 4-bit indexed images with CLUT
- Can export all 8 palette variations (for animated textures)

### mml_ebd2obj.py

Converts MML EBD model files to Wavefront OBJ format.

**Usage:**
```bash
python mml_ebd2obj.py <input.ebd> [output.obj] [model_index]
```

**Arguments:**
- `input.ebd` - Input EBD file path
- `output.obj` - Output OBJ file path (default: same name as input with .obj extension)
- `model_index` - Which model to export if file contains multiple (default: 0)

**Features:**
- Exports vertices, triangles, and quads
- Includes UV texture coordinates
- Groups geometry by limb
- Lists all models in file with vertex/face counts

### Dependencies

Both tools require Python 3.x. The TIM converter additionally requires Pillow:

```bash
pip install Pillow
```

---

## References

### Source Code References

- **DashViewer** by xdaniel - C# model viewer that provided the basis for understanding the EBD format
  - `ModelBase.cs` - Model parsing logic
  - `ArchiveReader.cs` - Container format parsing

### Community Resources

- [DashGL MML Tools](https://megamanlegends.gitlab.io/) - Collection of MML asset extraction tools
- [Mega Man Legends Station Forums](https://mmls.proboards.com/) - Community research and documentation
- [DashEditor](https://github.com/OmbraRD/DashEditor) - Translation toolkit with file format handling

### Related Formats

- **PBD** - Player model files (similar structure to EBD but for player characters)
- **MDT** - Stage floor/map data
- **MSG** - Script/message data
- **Standard PSX TIM** - Sony's TIM format documentation applies to the embedded image data

---

## Changelog

- **2024-01-19** - Initial documentation based on reverse engineering of ST00_00.EBD and PL00B01.TIM

---

## License

This documentation is provided for educational and preservation purposes. Mega Man Legends is © Capcom.
