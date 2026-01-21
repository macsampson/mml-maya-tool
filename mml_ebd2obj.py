#!/usr/bin/env python3

"""
mml_ebd2obj - Convert Mega Man Legends EBD model files to OBJ format

EBD File Structure (based on DashViewer by xdaniel):
=====================================================

Container Header (0x000-0x7FF):
  0x00: FileType (0 for Data files)
  0x04: Data size
  0x0C: RAM address (PS1 memory base address)
  0x40: File path string
  DataStart = 0x800

Model Data (starts at 0x800):
  - First 4 bytes: Model count
  - Each model entry: 16 bytes
    - 0x00: Unknown
    - 0x04: LimbInfoStart (PS1 address)
    - 0x08: HierarchyAnimInfoStart (PS1 address)
    - 0x0C: AnimOrderStart (PS1 address)

Limb Information:
  - LimbInfoStart + 0x10: Limb indices (4 bytes each)
  - LimbInfoStart + 0x70: LOD addresses (3 x 4 bytes)

Each LOD Model:
  - LODStart + 0x03: Limb count
  - LODStart + 0x14: Limb info entries (20 bytes each)

Limb Info Entry (20 bytes):
  - 0x00: TriangleCount
  - 0x01: QuadCount
  - 0x02: VertexCount
  - 0x03: LimbNumber
  - 0x04: TriangleStart (PS1 addr)
  - 0x08: QuadStart (PS1 addr)
  - 0x0C: TexturePage
  - 0x0E: CLUTPage
  - 0x10: VertexStart (PS1 addr)

Vertex: 8 bytes (X, Y, Z as signed 16-bit, negated, + 2 bytes padding)
Triangle: 12 bytes (6 bytes UV, 2 bytes unknown, 3 bytes indices, 1 byte pad)
Quad: 12 bytes (8 bytes UV, 4 bytes indices in order 2,3,1,0)
"""

__version__ = "1.0"

import struct
import sys
import os


class EBDReader:
    DATA_START = 0x800

    def __init__(self, filepath):
        with open(filepath, "rb") as f:
            self.data = f.read()

        # Read container header
        self.file_type = struct.unpack("<I", self.data[0x00:0x04])[0]
        self.data_size = struct.unpack("<I", self.data[0x04:0x08])[0]
        self.ram_address = struct.unpack("<I", self.data[0x0C:0x10])[0]

        # Read model count
        self.model_count = struct.unpack(
            "<I", self.data[self.DATA_START : self.DATA_START + 4]
        )[0]

        print(f"File type: {self.file_type}")
        print(f"Data size: {self.data_size}")
        print(f"RAM address: 0x{self.ram_address:08X}")
        print(f"Model count: {self.model_count}")

        # Parse models
        self.models = []
        offset = self.DATA_START + 4
        for i in range(self.model_count):
            model = self.parse_model(offset)
            if model:
                self.models.append(model)
            offset += 16

    def ps1_to_file_offset(self, ps1_addr):
        """Convert PS1 memory address to file offset"""
        if ps1_addr == 0 or (ps1_addr >> 24) != 0x80:
            return None
        return (ps1_addr - self.ram_address) + self.DATA_START

    def read_int(self, offset):
        """Read little-endian 32-bit int"""
        return struct.unpack("<I", self.data[offset : offset + 4])[0]

    def read_short(self, offset):
        """Read little-endian signed 16-bit int"""
        return struct.unpack("<h", self.data[offset : offset + 2])[0]

    def read_ushort(self, offset):
        """Read little-endian unsigned 16-bit int"""
        return struct.unpack("<H", self.data[offset : offset + 2])[0]

    def parse_model(self, offset):
        """Parse a model entry"""
        unknown1 = self.read_int(offset)
        limb_info_addr = self.read_int(offset + 4)
        hierarchy_addr = self.read_int(offset + 8)
        anim_order_addr = self.read_int(offset + 12)

        limb_info_start = self.ps1_to_file_offset(limb_info_addr)
        if limb_info_start is None:
            return None

        hierarchy_start = self.ps1_to_file_offset(hierarchy_addr)

        # Read LOD model addresses (at limb_info_start + 0x70)
        lod_offsets = []
        for i in range(3):
            lod_addr = self.read_int(limb_info_start + 0x70 + i * 4)
            lod_offset = self.ps1_to_file_offset(lod_addr)
            if lod_offset:
                lod_offsets.append(lod_offset)

        if not lod_offsets:
            return None

        # Parse LOD 0 (highest detail)
        lod_start = lod_offsets[0]
        limb_count = self.data[lod_start + 3]

        print(f"  LOD 0 at 0x{lod_start:04X}, {limb_count} limbs")

        # Parse limb index entries (at limb_info_start + 0x10)
        # Each entry: render_index, parent_index, translation_index, padding
        limb_indices = []
        print(f"  Limb indices at 0x{limb_info_start + 0x10:04X}:")
        for i in range(limb_count):
            idx_offset = limb_info_start + 0x10 + i * 4
            render_idx = self.data[idx_offset]
            parent_idx = self.data[idx_offset + 1]
            trans_idx = self.data[idx_offset + 2]
            print(f"    [{i}] render={render_idx}, parent={parent_idx}, trans={trans_idx}")
            limb_indices.append({
                "render": render_idx,
                "parent": parent_idx,
                "translation": trans_idx,
            })

        # Parse bone translations from hierarchy address
        # hierarchy_start points to a pointer table:
        #   [0x00] -> pointer to limb translations
        #   [0x04] -> pointer to first animation data
        # Number of translations = (first_anim_ofs - limb_trans_ofs) / 8
        bone_translations = []
        if hierarchy_start and (hierarchy_start >> 24) == 0:
            print(f"  Hierarchy info at 0x{hierarchy_start:04X}")
            limb_trans_addr = self.read_int(hierarchy_start)
            first_anim_addr = self.read_int(hierarchy_start + 4)

            limb_trans_ofs = self.ps1_to_file_offset(limb_trans_addr)
            first_anim_ofs = self.ps1_to_file_offset(first_anim_addr)

            if limb_trans_ofs and first_anim_ofs and (first_anim_ofs >> 24) == 0:
                num_translations = (first_anim_ofs - limb_trans_ofs) // 8
                print(f"  Limb translations at 0x{limb_trans_ofs:04X}, count={num_translations}")

                for i in range(num_translations):
                    t_offset = limb_trans_ofs + i * 8
                    if t_offset + 8 > len(self.data):
                        break
                    tx = -self.read_short(t_offset)
                    ty = -self.read_short(t_offset + 2)
                    tz = -self.read_short(t_offset + 4)
                    bone_translations.append((tx, ty, tz))

                print(f"  Read {len(bone_translations)} bone translations")
                if bone_translations:
                    print(f"  First few: {bone_translations[:min(5, len(bone_translations))]}")

        # Parse limb information entries
        limbs = []
        limb_offset = lod_start + 0x14
        for i in range(limb_count):
            limb = self.parse_limb_info(limb_offset)
            if limb:
                limbs.append(limb)
            limb_offset += 20

        return {
            "limb_info_start": limb_info_start,
            "lod_offsets": lod_offsets,
            "limbs": limbs,
            "limb_indices": limb_indices,
            "bone_translations": bone_translations,
        }

    def parse_limb_info(self, offset):
        """Parse a limb information entry (20 bytes)"""
        tri_count = self.data[offset]
        quad_count = self.data[offset + 1]
        vert_count = self.data[offset + 2]
        limb_number = self.data[offset + 3]

        # Triangle start (check if valid PS1 address)
        tri_start = None
        if self.data[offset + 7] == 0x80:
            tri_start = self.ps1_to_file_offset(self.read_int(offset + 4))

        # Quad start
        quad_start = None
        if self.data[offset + 11] == 0x80:
            quad_start = self.ps1_to_file_offset(self.read_int(offset + 8))

        texture_page = self.read_ushort(offset + 12)
        clut_page = self.read_ushort(offset + 14)

        # Vertex start
        vert_start = None
        if self.data[offset + 19] == 0x80:
            vert_start = self.ps1_to_file_offset(self.read_int(offset + 16))

        # Parse vertices
        vertices = []
        if vert_start and vert_count > 0:
            for i in range(vert_count):
                v_offset = vert_start + i * 8
                x = -self.read_short(v_offset)
                y = -self.read_short(v_offset + 2)
                z = -self.read_short(v_offset + 4)
                vertices.append((x, y, z))

        # Parse triangles
        triangles = []
        if tri_start and tri_count > 0:
            for i in range(tri_count):
                t_offset = tri_start + i * 12
                # UV coords (6 bytes)
                uvs = []
                for j in range(3):
                    u = self.data[t_offset + j * 2]
                    v = self.data[t_offset + j * 2 + 1]
                    uvs.append((u, v))
                # Vertex indices (bytes 8, 9, 10)
                indices = (
                    self.data[t_offset + 8],
                    self.data[t_offset + 9],
                    self.data[t_offset + 10],
                )
                triangles.append({"indices": indices, "uvs": uvs})

        # Parse quads
        quads = []
        if quad_start and quad_count > 0:
            for i in range(quad_count):
                q_offset = quad_start + i * 12
                # UV coords (first 8 bytes, but reordered)
                # Original order in file: 0,1,2,3 -> reorder to: 2,3,1,0
                uvs = []
                uvs.append(
                    (self.data[q_offset + 6], self.data[q_offset + 7])
                )  # UV for vert 0
                uvs.append(
                    (self.data[q_offset + 4], self.data[q_offset + 5])
                )  # UV for vert 1
                uvs.append(
                    (self.data[q_offset + 0], self.data[q_offset + 1])
                )  # UV for vert 2
                uvs.append(
                    (self.data[q_offset + 2], self.data[q_offset + 3])
                )  # UV for vert 3

                # Vertex indices (bytes 8-11, reordered: 2,3,1,0)
                indices = (
                    self.data[q_offset + 11],  # 0
                    self.data[q_offset + 10],  # 1
                    self.data[q_offset + 8],  # 2
                    self.data[q_offset + 9],  # 3
                )
                quads.append({"indices": indices, "uvs": uvs})

        return {
            "number": limb_number,
            "vertices": vertices,
            "triangles": triangles,
            "quads": quads,
            "texture_page": texture_page,
            "clut_page": clut_page,
        }


def compute_bone_world_positions(limb_indices, bone_translations, debug=False):
    """Compute world position for each bone by walking up parent hierarchy"""
    world_positions = []
    num_limbs = len(limb_indices)

    for i in range(num_limbs):
        # Accumulate translations by walking up the parent chain
        wx, wy, wz = 0, 0, 0
        current_idx = i

        # Walk up parent hierarchy (max iterations to prevent infinite loops)
        visited = set()
        while current_idx < num_limbs and current_idx not in visited:
            visited.add(current_idx)
            limb_info = limb_indices[current_idx]
            trans_idx = limb_info["translation"]

            # Add this bone's translation
            if trans_idx < len(bone_translations):
                tx, ty, tz = bone_translations[trans_idx]
                wx += tx
                wy += ty
                wz += tz

            # Move to parent
            parent_idx = limb_info["parent"]
            if parent_idx == current_idx or parent_idx >= num_limbs:
                break  # Root bone or invalid parent
            current_idx = parent_idx

        world_positions.append((wx, wy, wz))
        if debug:
            print(f"  Limb {i} world pos: ({wx}, {wy}, {wz})")

    return world_positions


def export_obj(ebd, output_path, model_index=0, scale=1.0 / 100.0):
    """Export model to OBJ format"""
    if model_index >= len(ebd.models):
        print(f"Error: Model index {model_index} out of range (0-{len(ebd.models)-1})")
        return False

    model = ebd.models[model_index]

    # Compute world positions for bones
    limb_indices = model.get("limb_indices", [])
    bone_translations = model.get("bone_translations", [])
    print(f"\nComputing bone world positions:")
    world_positions = compute_bone_world_positions(limb_indices, bone_translations, debug=True)

    with open(output_path, "w") as f:
        f.write(f"# Mega Man Legends EBD Model Export\n")
        f.write(f"# Exported by mml_ebd2obj v{__version__}\n")
        f.write(f"# Model {model_index}, {len(model['limbs'])} limbs\n\n")

        global_vertex_offset = 1  # OBJ indices start at 1
        global_uv_offset = 1  # OBJ UV indices also start at 1

        for limb_idx, limb in enumerate(model["limbs"]):
            f.write(f"# Limb {limb['number']}\n")
            f.write(f"g limb_{limb['number']}\n")

            # Get bone world position for this limb
            if limb_idx < len(world_positions):
                bone_x, bone_y, bone_z = world_positions[limb_idx]
            else:
                bone_x, bone_y, bone_z = 0, 0, 0

            # Write vertices (transformed by bone position)
            for x, y, z in limb["vertices"]:
                vx = (x + bone_x) * scale
                vy = (y + bone_y) * scale
                vz = (z + bone_z) * scale
                f.write(f"v {vx:.6f} {vy:.6f} {vz:.6f}\n")

            # Write texture coordinates (normalized to 0-1)
            # Collect all UVs from triangles and quads
            all_uvs = []
            for tri in limb["triangles"]:
                for u, v in tri["uvs"]:
                    all_uvs.append((u / 255.0, 1.0 - v / 255.0))  # Flip V
            for quad in limb["quads"]:
                for u, v in quad["uvs"]:
                    all_uvs.append((u / 255.0, 1.0 - v / 255.0))

            for u, v in all_uvs:
                f.write(f"vt {u:.6f} {v:.6f}\n")

            # Write faces
            uv_offset = global_uv_offset

            # Triangles
            for tri in limb["triangles"]:
                i0, i1, i2 = tri["indices"]
                # Convert to global indices
                v0 = global_vertex_offset + i0
                v1 = global_vertex_offset + i1
                v2 = global_vertex_offset + i2
                # UV indices
                t0 = uv_offset
                t1 = uv_offset + 1
                t2 = uv_offset + 2
                f.write(f"f {v0}/{t0} {v1}/{t1} {v2}/{t2}\n")
                uv_offset += 3

            # Quads (split into two triangles)
            for quad in limb["quads"]:
                i0, i1, i2, i3 = quad["indices"]
                v0 = global_vertex_offset + i0
                v1 = global_vertex_offset + i1
                v2 = global_vertex_offset + i2
                v3 = global_vertex_offset + i3
                t0 = uv_offset
                t1 = uv_offset + 1
                t2 = uv_offset + 2
                t3 = uv_offset + 3
                # Triangle 1: 0, 1, 2
                f.write(f"f {v0}/{t0} {v1}/{t1} {v2}/{t2}\n")
                # Triangle 2: 0, 2, 3
                f.write(f"f {v0}/{t0} {v2}/{t2} {v3}/{t3}\n")
                uv_offset += 4

            global_vertex_offset += len(limb["vertices"])
            global_uv_offset += len(all_uvs)
            f.write("\n")

    print(f"Exported to {output_path}")
    return True


def usage():
    print(f"mml_ebd2obj v{__version__} - Convert MML EBD models to OBJ")
    print(f"Usage: {os.path.basename(sys.argv[0])} [options] <input.ebd> [output.obj] [model_index]")
    print(f"")
    print(f"Options:")
    print(f"  -a, --all    Export all models as separate OBJ files")
    print(f"               Output files will be named <base>_model0.obj, <base>_model1.obj, etc.")
    print(f"")
    print(f"Arguments:")
    print(f"  input.ebd    Input EBD file")
    print(f"  output.obj   Output OBJ file (default: input name with .obj extension)")
    print(f"  model_index  Which model to export (default: 0, ignored with -a)")
    sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        usage()

    # Parse arguments
    export_all = False
    args = []
    for arg in sys.argv[1:]:
        if arg in ("-a", "--all"):
            export_all = True
        else:
            args.append(arg)

    if not args:
        usage()

    input_file = args[0]
    base_name = os.path.splitext(input_file)[0]

    try:
        print(f"Reading {input_file}...")
        ebd = EBDReader(input_file)

        print(f"\nFound {len(ebd.models)} models")
        for i, model in enumerate(ebd.models):
            total_verts = sum(len(limb["vertices"]) for limb in model["limbs"])
            total_tris = sum(len(limb["triangles"]) for limb in model["limbs"])
            total_quads = sum(len(limb["quads"]) for limb in model["limbs"])
            print(
                f"  Model {i}: {len(model['limbs'])} limbs, {total_verts} vertices, {total_tris} tris, {total_quads} quads"
            )

        if export_all:
            print(f"\nExporting all {len(ebd.models)} models...")
            for i in range(len(ebd.models)):
                output_file = f"{base_name}_model{i}.obj"
                print(f"\nExporting model {i}...")
                export_obj(ebd, output_file, i)
            print(f"\nDone! Exported {len(ebd.models)} models.")
        else:
            output_file = args[1] if len(args) > 1 else base_name + ".obj"
            model_index = int(args[2]) if len(args) > 2 else 0
            print(f"\nExporting model {model_index}...")
            export_obj(ebd, output_file, model_index)

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
