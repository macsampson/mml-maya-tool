#!/usr/bin/env python3

"""
mml_ebd2gltf - Convert Mega Man Legends EBD model files to glTF format with skeleton

Exports models with proper bone hierarchies. glTF is well-supported by
Blender, Maya (with plugin), 3ds Max, Unity, Unreal, and most 3D software.

Requires: pip install pygltflib numpy
"""

__version__ = "1.0"

import struct
import sys
import os
import json
import base64

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


class EBDReader:
    """Read and parse EBD model files."""

    DATA_START = 0x800

    def __init__(self, filepath):
        with open(filepath, "rb") as f:
            self.data = f.read()

        self.file_type = struct.unpack("<I", self.data[0x00:0x04])[0]
        self.data_size = struct.unpack("<I", self.data[0x04:0x08])[0]
        self.ram_address = struct.unpack("<I", self.data[0x0C:0x10])[0]

        self.model_count = struct.unpack(
            "<I", self.data[self.DATA_START : self.DATA_START + 4]
        )[0]

        self.models = []
        offset = self.DATA_START + 4
        for i in range(self.model_count):
            model = self.parse_model(offset)
            if model:
                self.models.append(model)
            offset += 16

    def ps1_to_file_offset(self, ps1_addr):
        if ps1_addr == 0 or (ps1_addr >> 24) != 0x80:
            return None
        return (ps1_addr - self.ram_address) + self.DATA_START

    def read_int(self, offset):
        return struct.unpack("<I", self.data[offset : offset + 4])[0]

    def read_short(self, offset):
        return struct.unpack("<h", self.data[offset : offset + 2])[0]

    def read_ushort(self, offset):
        return struct.unpack("<H", self.data[offset : offset + 2])[0]

    def parse_model(self, offset):
        limb_info_addr = self.read_int(offset + 4)
        hierarchy_addr = self.read_int(offset + 8)

        limb_info_start = self.ps1_to_file_offset(limb_info_addr)
        if limb_info_start is None:
            return None

        hierarchy_start = self.ps1_to_file_offset(hierarchy_addr)

        lod_offsets = []
        for i in range(3):
            lod_addr = self.read_int(limb_info_start + 0x70 + i * 4)
            lod_offset = self.ps1_to_file_offset(lod_addr)
            if lod_offset:
                lod_offsets.append(lod_offset)

        if not lod_offsets:
            return None

        lod_start = lod_offsets[0]
        limb_count = self.data[lod_start + 3]

        limb_indices = []
        for i in range(limb_count):
            idx_offset = limb_info_start + 0x10 + i * 4
            render_idx = self.data[idx_offset]
            parent_idx = self.data[idx_offset + 1]
            trans_idx = self.data[idx_offset + 2]
            limb_indices.append({
                "render": render_idx,
                "parent": parent_idx,
                "translation": trans_idx,
            })

        bone_translations = []
        if hierarchy_start and (hierarchy_start >> 24) == 0:
            limb_trans_addr = self.read_int(hierarchy_start)
            first_anim_addr = self.read_int(hierarchy_start + 4)

            limb_trans_ofs = self.ps1_to_file_offset(limb_trans_addr)
            first_anim_ofs = self.ps1_to_file_offset(first_anim_addr)

            if limb_trans_ofs and first_anim_ofs and (first_anim_ofs >> 24) == 0:
                num_translations = (first_anim_ofs - limb_trans_ofs) // 8

                for i in range(num_translations):
                    t_offset = limb_trans_ofs + i * 8
                    if t_offset + 8 > len(self.data):
                        break
                    tx = -self.read_short(t_offset)
                    ty = -self.read_short(t_offset + 2)
                    tz = -self.read_short(t_offset + 4)
                    bone_translations.append((tx, ty, tz))

        limbs = []
        limb_offset = lod_start + 0x14
        for i in range(limb_count):
            limb = self.parse_limb_info(limb_offset)
            if limb:
                limbs.append(limb)
            limb_offset += 20

        return {
            "limbs": limbs,
            "limb_indices": limb_indices,
            "bone_translations": bone_translations,
        }

    def parse_limb_info(self, offset):
        tri_count = self.data[offset]
        quad_count = self.data[offset + 1]
        vert_count = self.data[offset + 2]
        limb_number = self.data[offset + 3]

        tri_start = None
        if self.data[offset + 7] == 0x80:
            tri_start = self.ps1_to_file_offset(self.read_int(offset + 4))

        quad_start = None
        if self.data[offset + 11] == 0x80:
            quad_start = self.ps1_to_file_offset(self.read_int(offset + 8))

        vert_start = None
        if self.data[offset + 19] == 0x80:
            vert_start = self.ps1_to_file_offset(self.read_int(offset + 16))

        vertices = []
        if vert_start and vert_count > 0:
            for i in range(vert_count):
                v_offset = vert_start + i * 8
                x = -self.read_short(v_offset)
                y = -self.read_short(v_offset + 2)
                z = -self.read_short(v_offset + 4)
                vertices.append((x, y, z))

        triangles = []
        if tri_start and tri_count > 0:
            for i in range(tri_count):
                t_offset = tri_start + i * 12
                uvs = []
                for j in range(3):
                    u = self.data[t_offset + j * 2]
                    v = self.data[t_offset + j * 2 + 1]
                    uvs.append((u, v))
                indices = (
                    self.data[t_offset + 8],
                    self.data[t_offset + 9],
                    self.data[t_offset + 10],
                )
                triangles.append({"indices": indices, "uvs": uvs})

        quads = []
        if quad_start and quad_count > 0:
            for i in range(quad_count):
                q_offset = quad_start + i * 12
                uvs = []
                uvs.append((self.data[q_offset + 6], self.data[q_offset + 7]))
                uvs.append((self.data[q_offset + 4], self.data[q_offset + 5]))
                uvs.append((self.data[q_offset + 0], self.data[q_offset + 1]))
                uvs.append((self.data[q_offset + 2], self.data[q_offset + 3]))

                indices = (
                    self.data[q_offset + 11],
                    self.data[q_offset + 10],
                    self.data[q_offset + 8],
                    self.data[q_offset + 9],
                )
                quads.append({"indices": indices, "uvs": uvs})

        return {
            "number": limb_number,
            "vertices": vertices,
            "triangles": triangles,
            "quads": quads,
        }


def compute_world_positions(limb_indices, bone_translations, scale=1.0/100.0):
    """Compute world position for each bone."""
    world_positions = []
    num_limbs = len(limb_indices)

    for i in range(num_limbs):
        wx, wy, wz = 0, 0, 0
        current_idx = i
        visited = set()

        while current_idx < num_limbs and current_idx not in visited:
            visited.add(current_idx)
            limb_info = limb_indices[current_idx]
            trans_idx = limb_info["translation"]

            if trans_idx < len(bone_translations):
                tx, ty, tz = bone_translations[trans_idx]
                wx += tx
                wy += ty
                wz += tz

            parent_idx = limb_info["parent"]
            if parent_idx == current_idx or parent_idx >= num_limbs:
                break
            current_idx = parent_idx

        world_positions.append((wx * scale, wy * scale, wz * scale))

    return world_positions


def pack_float32_array(values):
    """Pack float array to bytes."""
    return struct.pack(f'<{len(values)}f', *values)


def pack_uint16_array(values):
    """Pack uint16 array to bytes."""
    return struct.pack(f'<{len(values)}H', *values)


def pack_uint8_array(values):
    """Pack uint8 array to bytes."""
    return struct.pack(f'<{len(values)}B', *values)


def export_gltf(ebd, output_path, model_index=0, scale=1.0/100.0):
    """Export model to glTF format with embedded binary data."""
    if model_index >= len(ebd.models):
        print(f"Error: Model index {model_index} out of range")
        return False

    model = ebd.models[model_index]
    limb_indices = model.get("limb_indices", [])
    bone_translations = model.get("bone_translations", [])

    world_positions = compute_world_positions(limb_indices, bone_translations, scale)
    num_bones = len(limb_indices)

    # Collect geometry
    all_positions = []
    all_uvs = []
    all_indices = []
    all_joints = []  # Bone indices for skinning
    all_weights = []  # Weights (all 1.0 for rigid binding)

    global_vertex_offset = 0

    for limb_idx, limb in enumerate(model["limbs"]):
        if limb_idx < len(world_positions):
            bone_world = world_positions[limb_idx]
        else:
            bone_world = (0, 0, 0)

        # Add vertices
        for vx, vy, vz in limb["vertices"]:
            wx = vx * scale + bone_world[0]
            wy = vy * scale + bone_world[1]
            wz = vz * scale + bone_world[2]
            all_positions.extend([wx, wy, wz])
            # Joint indices (4 per vertex, only first is used)
            all_joints.extend([limb_idx, 0, 0, 0])
            # Weights (4 per vertex, only first is 1.0)
            all_weights.extend([1.0, 0.0, 0.0, 0.0])

        # Add triangles
        for tri in limb["triangles"]:
            i0, i1, i2 = tri["indices"]
            all_indices.extend([
                global_vertex_offset + i0,
                global_vertex_offset + i1,
                global_vertex_offset + i2,
            ])
            for u, v in tri["uvs"]:
                all_uvs.extend([u / 255.0, 1.0 - v / 255.0])

        # Add quads as two triangles
        for quad in limb["quads"]:
            i0, i1, i2, i3 = quad["indices"]
            all_indices.extend([
                global_vertex_offset + i0,
                global_vertex_offset + i1,
                global_vertex_offset + i2,
            ])
            all_indices.extend([
                global_vertex_offset + i0,
                global_vertex_offset + i2,
                global_vertex_offset + i3,
            ])
            u0, v0 = quad["uvs"][0]
            u1, v1 = quad["uvs"][1]
            u2, v2 = quad["uvs"][2]
            u3, v3 = quad["uvs"][3]
            all_uvs.extend([u0 / 255.0, 1.0 - v0 / 255.0])
            all_uvs.extend([u1 / 255.0, 1.0 - v1 / 255.0])
            all_uvs.extend([u2 / 255.0, 1.0 - v2 / 255.0])
            all_uvs.extend([u0 / 255.0, 1.0 - v0 / 255.0])
            all_uvs.extend([u2 / 255.0, 1.0 - v2 / 255.0])
            all_uvs.extend([u3 / 255.0, 1.0 - v3 / 255.0])

        global_vertex_offset += len(limb["vertices"])

    num_vertices = len(all_positions) // 3
    num_indices = len(all_indices)

    # Compute bounding box
    min_pos = [float('inf')] * 3
    max_pos = [float('-inf')] * 3
    for i in range(num_vertices):
        for j in range(3):
            val = all_positions[i * 3 + j]
            min_pos[j] = min(min_pos[j], val)
            max_pos[j] = max(max_pos[j], val)

    # Build binary buffer
    buffer_data = bytearray()

    # Positions
    positions_offset = len(buffer_data)
    positions_bytes = pack_float32_array(all_positions)
    buffer_data.extend(positions_bytes)

    # Pad to 4-byte alignment
    while len(buffer_data) % 4 != 0:
        buffer_data.append(0)

    # UVs (per-vertex, need to expand from per-face)
    # For now, skip UVs in skinned export to simplify
    # We'll add them back properly later

    # Indices
    indices_offset = len(buffer_data)
    indices_bytes = pack_uint16_array(all_indices)
    buffer_data.extend(indices_bytes)

    while len(buffer_data) % 4 != 0:
        buffer_data.append(0)

    # Joints (4 x uint8 per vertex)
    joints_offset = len(buffer_data)
    joints_bytes = pack_uint8_array(all_joints)
    buffer_data.extend(joints_bytes)

    while len(buffer_data) % 4 != 0:
        buffer_data.append(0)

    # Weights (4 x float32 per vertex)
    weights_offset = len(buffer_data)
    weights_bytes = pack_float32_array(all_weights)
    buffer_data.extend(weights_bytes)

    while len(buffer_data) % 4 != 0:
        buffer_data.append(0)

    # Inverse bind matrices (4x4 matrix per bone)
    ibm_offset = len(buffer_data)
    ibm_data = []
    for i in range(num_bones):
        if i < len(world_positions):
            wx, wy, wz = world_positions[i]
        else:
            wx, wy, wz = 0, 0, 0
        # Inverse bind matrix = inverse of bone world transform
        # For translation-only, inverse is just negative translation
        ibm_data.extend([
            1, 0, 0, 0,
            0, 1, 0, 0,
            0, 0, 1, 0,
            -wx, -wy, -wz, 1
        ])
    ibm_bytes = pack_float32_array(ibm_data)
    buffer_data.extend(ibm_bytes)

    # Encode buffer as base64 for embedded glTF
    buffer_b64 = base64.b64encode(bytes(buffer_data)).decode('ascii')

    # Build glTF structure
    gltf = {
        "asset": {
            "version": "2.0",
            "generator": f"mml_ebd2gltf v{__version__}"
        },
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [],
        "meshes": [],
        "skins": [],
        "accessors": [],
        "bufferViews": [],
        "buffers": [{
            "uri": f"data:application/octet-stream;base64,{buffer_b64}",
            "byteLength": len(buffer_data)
        }]
    }

    # Buffer views
    gltf["bufferViews"] = [
        # 0: Positions
        {"buffer": 0, "byteOffset": positions_offset, "byteLength": len(positions_bytes), "target": 34962},
        # 1: Indices
        {"buffer": 0, "byteOffset": indices_offset, "byteLength": len(indices_bytes), "target": 34963},
        # 2: Joints
        {"buffer": 0, "byteOffset": joints_offset, "byteLength": len(joints_bytes)},
        # 3: Weights
        {"buffer": 0, "byteOffset": weights_offset, "byteLength": len(weights_bytes)},
        # 4: Inverse bind matrices
        {"buffer": 0, "byteOffset": ibm_offset, "byteLength": len(ibm_bytes)},
    ]

    # Accessors
    gltf["accessors"] = [
        # 0: Positions
        {
            "bufferView": 0,
            "componentType": 5126,  # FLOAT
            "count": num_vertices,
            "type": "VEC3",
            "min": min_pos,
            "max": max_pos
        },
        # 1: Indices
        {
            "bufferView": 1,
            "componentType": 5123,  # UNSIGNED_SHORT
            "count": num_indices,
            "type": "SCALAR"
        },
        # 2: Joints
        {
            "bufferView": 2,
            "componentType": 5121,  # UNSIGNED_BYTE
            "count": num_vertices,
            "type": "VEC4"
        },
        # 3: Weights
        {
            "bufferView": 3,
            "componentType": 5126,  # FLOAT
            "count": num_vertices,
            "type": "VEC4"
        },
        # 4: Inverse bind matrices
        {
            "bufferView": 4,
            "componentType": 5126,  # FLOAT
            "count": num_bones,
            "type": "MAT4"
        },
    ]

    # Build bone hierarchy nodes
    # Node 0 will be the root armature
    # Nodes 1 to num_bones will be bones
    # Node num_bones+1 will be the mesh

    armature_node = {"name": "Armature", "children": []}
    gltf["nodes"].append(armature_node)

    # Create bone nodes - detect and prevent cycles
    # Use render_index ordering to break cycles (like DashViewer does)
    bone_children = {i: [] for i in range(num_bones)}
    bone_parent = {i: -1 for i in range(num_bones)}
    root_bones = []

    cycles_broken = 0
    for i in range(num_bones):
        limb_info = limb_indices[i]
        parent_idx = limb_info["parent"]
        render_idx = limb_info["render"]

        # Check if this is a root bone
        is_root = (parent_idx == i or parent_idx >= num_bones)

        # Additional cycle check: parent must have lower render index
        # to prevent cycles like 0->18->0
        if not is_root and parent_idx < num_bones:
            parent_render = limb_indices[parent_idx]["render"]
            if parent_render >= render_idx:
                # This would create a cycle, treat as root
                is_root = True
                cycles_broken += 1

        if is_root:
            root_bones.append(i)
            bone_parent[i] = -1
        else:
            bone_children[parent_idx].append(i)
            bone_parent[i] = parent_idx

    if cycles_broken > 0:
        print(f"  Note: Broke {cycles_broken} hierarchy cycles")

    # Add bone nodes
    joint_node_indices = []
    for i in range(num_bones):
        parent_idx = bone_parent[i]  # Use our cycle-safe parent
        is_root = (parent_idx == -1)

        # Compute local translation
        my_world = world_positions[i] if i < len(world_positions) else (0, 0, 0)
        if is_root:
            local_trans = list(my_world)
        else:
            parent_world = world_positions[parent_idx] if parent_idx < len(world_positions) else (0, 0, 0)
            local_trans = [
                my_world[0] - parent_world[0],
                my_world[1] - parent_world[1],
                my_world[2] - parent_world[2],
            ]

        node = {"name": f"Bone_{i:02d}"}
        if local_trans != [0, 0, 0]:
            node["translation"] = local_trans
        if bone_children[i]:
            node["children"] = [j + 1 for j in bone_children[i]]  # +1 because armature is node 0

        node_idx = len(gltf["nodes"])
        joint_node_indices.append(node_idx)
        gltf["nodes"].append(node)

    # Link root bones to armature
    armature_node["children"] = [i + 1 for i in root_bones]

    # Add mesh node
    mesh_node_idx = len(gltf["nodes"])
    gltf["nodes"].append({
        "name": f"MML_Model_{model_index}",
        "mesh": 0,
        "skin": 0
    })
    armature_node["children"].append(mesh_node_idx)

    # Mesh
    gltf["meshes"] = [{
        "name": f"MML_Mesh_{model_index}",
        "primitives": [{
            "attributes": {
                "POSITION": 0,
                "JOINTS_0": 2,
                "WEIGHTS_0": 3
            },
            "indices": 1
        }]
    }]

    # Skin
    gltf["skins"] = [{
        "inverseBindMatrices": 4,
        "joints": joint_node_indices,
        "skeleton": 1  # First bone node
    }]

    # Write glTF file
    with open(output_path, 'w') as f:
        json.dump(gltf, f, indent=2)

    print(f"Exported to {output_path}")
    print(f"  Bones: {num_bones}")
    print(f"  Vertices: {num_vertices}")
    print(f"  Triangles: {num_indices // 3}")
    return True


def usage():
    print(f"mml_ebd2gltf v{__version__} - Convert MML EBD models to glTF with skeleton")
    print(f"Usage: {os.path.basename(sys.argv[0])} [options] <input.ebd> [output.gltf] [model_index]")
    print(f"")
    print(f"Options:")
    print(f"  -a, --all    Export all models as separate glTF files")
    print(f"")
    print(f"Output can be imported into Blender, Maya, Unity, Unreal, etc.")
    sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        usage()

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
            print(f"  Model {i}: {len(model['limbs'])} limbs, {total_verts} verts, {total_tris} tris, {total_quads} quads")

        if export_all:
            print(f"\nExporting all {len(ebd.models)} models...")
            for i in range(len(ebd.models)):
                output_file = f"{base_name}_model{i}.gltf"
                print(f"\nExporting model {i}...")
                export_gltf(ebd, output_file, i)
            print(f"\nDone! Exported {len(ebd.models)} models.")
        else:
            output_file = args[1] if len(args) > 1 else base_name + ".gltf"
            model_index = int(args[2]) if len(args) > 2 else 0
            print(f"\nExporting model {model_index}...")
            export_gltf(ebd, output_file, model_index)

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
