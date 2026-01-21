#!/usr/bin/env python3

"""
mml_ebd2fbx - Convert Mega Man Legends EBD model files to FBX format with skeleton

Exports models with proper bone hierarchies for use in 3D software.
Uses ASCII FBX format (FBX 7.4) which doesn't require the Autodesk SDK.
"""

__version__ = "1.0"

import struct
import sys
import os
import time


class EBDReader:
    """Read and parse EBD model files."""

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
        return struct.unpack("<I", self.data[offset : offset + 4])[0]

    def read_short(self, offset):
        return struct.unpack("<h", self.data[offset : offset + 2])[0]

    def read_ushort(self, offset):
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

        # Parse limb index entries (at limb_info_start + 0x10)
        limb_indices = []
        for i in range(limb_count):
            idx_offset = limb_info_start + 0x10 + i * 4
            render_idx = self.data[idx_offset]
            parent_idx = self.data[idx_offset + 1]
            trans_idx = self.data[idx_offset + 2]
            limb_indices.append(
                {
                    "render": render_idx,
                    "parent": parent_idx,
                    "translation": trans_idx,
                }
            )

        # Parse bone translations from hierarchy address
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

        tri_start = None
        if self.data[offset + 7] == 0x80:
            tri_start = self.ps1_to_file_offset(self.read_int(offset + 4))

        quad_start = None
        if self.data[offset + 11] == 0x80:
            quad_start = self.ps1_to_file_offset(self.read_int(offset + 8))

        texture_page = self.read_ushort(offset + 12)
        clut_page = self.read_ushort(offset + 14)

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

        # Parse quads
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
            "texture_page": texture_page,
            "clut_page": clut_page,
        }


class FBXExporter:
    """Export model data to ASCII FBX format."""

    def __init__(self):
        self.object_id = 1000000000
        self.objects = []
        self.connections = []

    def get_id(self):
        """Generate unique object ID."""
        self.object_id += 1
        return self.object_id

    def compute_world_positions(
        self, limb_indices, bone_translations, scale=1.0 / 100.0
    ):
        """Compute world position for each bone by walking up parent hierarchy.

        This matches the logic from the working OBJ exporter.
        """
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

                # Move to parent (parent_idx is used as array index)
                parent_idx = limb_info["parent"]
                if parent_idx == current_idx or parent_idx >= num_limbs:
                    break  # Root bone or invalid parent
                current_idx = parent_idx

            world_positions.append((wx * scale, wy * scale, wz * scale))

        return world_positions

    def build_skeleton(
        self, limb_indices, bone_translations, world_positions, scale=1.0 / 100.0
    ):
        """Build bone hierarchy from model data."""
        bones = []
        num_limbs = len(limb_indices)
        cycles_broken = 0

        for i in range(num_limbs):
            limb_info = limb_indices[i]
            parent_idx = limb_info["parent"]
            render_idx = limb_info["render"]

            # Determine if this is a root bone
            is_root = parent_idx == i or parent_idx >= num_limbs

            # Additional cycle check: parent must have lower render index
            # to prevent cycles like 0->18->0 (DashViewer uses this check)
            if not is_root and parent_idx < num_limbs:
                parent_render = limb_indices[parent_idx]["render"]
                if parent_render >= render_idx:
                    # This would create a cycle, treat as root
                    is_root = True
                    cycles_broken += 1

            # Compute local translation (relative to parent)
            my_world = world_positions[i] if i < len(world_positions) else (0, 0, 0)
            if is_root:
                # Root bone: local = world
                local_trans = my_world
                actual_parent = -1
            else:
                # Child bone: local = world - parent_world
                parent_world = (
                    world_positions[parent_idx]
                    if parent_idx < len(world_positions)
                    else (0, 0, 0)
                )
                local_trans = (
                    my_world[0] - parent_world[0],
                    my_world[1] - parent_world[1],
                    my_world[2] - parent_world[2],
                )
                actual_parent = parent_idx

            bones.append(
                {
                    "index": i,
                    "name": f"Bone_{i:02d}",
                    "parent": actual_parent,
                    "local_translation": local_trans,
                    "world_position": my_world,
                    "render_index": render_idx,
                }
            )

        if cycles_broken > 0:
            print(f"  Note: Broke {cycles_broken} hierarchy cycles")

        return bones

    def export(self, ebd, output_path, model_index=0, scale=1.0 / 100.0):
        """Export model to FBX format."""
        if model_index >= len(ebd.models):
            print(f"Error: Model index {model_index} out of range")
            return False

        model = ebd.models[model_index]

        # Get hierarchy data
        limb_indices = model.get("limb_indices", [])
        bone_translations = model.get("bone_translations", [])

        # Compute world positions (same logic as working OBJ exporter)
        world_positions = self.compute_world_positions(
            limb_indices, bone_translations, scale
        )

        # Build skeleton with proper local translations
        bones = self.build_skeleton(
            limb_indices, bone_translations, world_positions, scale
        )

        # Collect all geometry
        all_vertices = []
        all_uvs = []
        all_indices = []
        vertex_bone_assignments = []  # Which bone each vertex belongs to

        global_vertex_offset = 0

        for bone_idx, limb_info in enumerate(limb_indices):

            # Get the specific mesh meant for this bone
            render_idx = limb_info["render"]

            # Safety check
            if render_idx >= len(model["limbs"]):
                continue

            limb = model["limbs"][render_idx]

            # Get bone world position
            if bone_idx < len(world_positions):
                # CRITICAL FIX: Scale the bone position!
                # The previous error was adding Raw Bone Position (Huge) to Scaled Vertex (Small).
                # We must scale both to ensure they exist in the same coordinate space.
                raw_pos = world_positions[bone_idx]
                bx = raw_pos[0] * scale
                by = raw_pos[1] * scale
                bz = raw_pos[2] * scale
            else:
                bx, by, bz = 0.0, 0.0, 0.0

            # Add vertices
            # We take the local vertex, scale it, and add the SCALED bone world position.
            for vx, vy, vz in limb["vertices"]:
                wx = vx * scale + bx
                wy = vy * scale + by
                wz = vz * scale + bz

                all_vertices.append((wx, wy, wz))
                vertex_bone_assignments.append(bone_idx)

            # Add triangles
            for tri in limb["triangles"]:
                i0, i1, i2 = tri["indices"]
                all_indices.append(
                    (
                        global_vertex_offset + i0,
                        global_vertex_offset + i1,
                        global_vertex_offset + i2,
                    )
                )
                for u, v in tri["uvs"]:
                    all_uvs.append((u / 255.0, 1.0 - v / 255.0))

            # Add quads
            for quad in limb["quads"]:
                i0, i1, i2, i3 = quad["indices"]
                all_indices.append(
                    (
                        global_vertex_offset + i0,
                        global_vertex_offset + i1,
                        global_vertex_offset + i2,
                    )
                )
                all_indices.append(
                    (
                        global_vertex_offset + i0,
                        global_vertex_offset + i2,
                        global_vertex_offset + i3,
                    )
                )

                # UVs processing
                u0, v0 = quad["uvs"][0]
                u1, v1 = quad["uvs"][1]
                u2, v2 = quad["uvs"][2]
                u3, v3 = quad["uvs"][3]
                all_uvs.extend(
                    [
                        (u0 / 255.0, 1.0 - v0 / 255.0),
                        (u1 / 255.0, 1.0 - v1 / 255.0),
                        (u2 / 255.0, 1.0 - v2 / 255.0),
                    ]
                )
                all_uvs.extend(
                    [
                        (u0 / 255.0, 1.0 - v0 / 255.0),
                        (u2 / 255.0, 1.0 - v2 / 255.0),
                        (u3 / 255.0, 1.0 - v3 / 255.0),
                    ]
                )

            global_vertex_offset += len(limb["vertices"])

        # Write FBX file
        self._write_fbx(
            output_path,
            bones,
            all_vertices,
            all_indices,
            all_uvs,
            vertex_bone_assignments,
            world_positions,
            model_index,
        )

        print(f"Exported to {output_path}")
        print(f"  Bones: {len(bones)}")
        print(f"  Vertices: {len(all_vertices)}")
        print(f"  Triangles: {len(all_indices)}")
        return True

    def _write_fbx(
        self,
        output_path,
        bones,
        vertices,
        indices,
        uvs,
        bone_assignments,
        world_positions,
        model_index,
    ):
        """Write ASCII FBX 7.4 file."""

        # Generate IDs
        root_id = self.get_id()
        mesh_id = self.get_id()
        mesh_model_id = self.get_id()
        material_id = self.get_id()

        bone_ids = {}
        bone_node_ids = {}
        for bone in bones:
            bone_ids[bone["index"]] = self.get_id()
            bone_node_ids[bone["index"]] = self.get_id()

        skin_id = self.get_id()
        cluster_ids = {bone["index"]: self.get_id() for bone in bones}

        timestamp = int(time.time())

        with open(output_path, "w") as f:
            # FBX Header
            f.write("; FBX 7.4.0 project file\n")
            f.write("; Exported by mml_ebd2fbx\n")
            f.write("; ----------------------------------------------------\n\n")

            # FBX Header Extension
            f.write("FBXHeaderExtension:  {\n")
            f.write("\tFBXHeaderVersion: 1003\n")
            f.write("\tFBXVersion: 7400\n")
            f.write("\tCreationTimeStamp:  {\n")
            f.write("\t\tVersion: 1000\n")
            f.write(f"\t\tYear: {time.localtime().tm_year}\n")
            f.write(f"\t\tMonth: {time.localtime().tm_mon}\n")
            f.write(f"\t\tDay: {time.localtime().tm_mday}\n")
            f.write(f"\t\tHour: {time.localtime().tm_hour}\n")
            f.write(f"\t\tMinute: {time.localtime().tm_min}\n")
            f.write(f"\t\tSecond: {time.localtime().tm_sec}\n")
            f.write("\t\tMillisecond: 0\n")
            f.write("\t}\n")
            f.write('\tCreator: "mml_ebd2fbx"\n')
            f.write("}\n\n")

            # Global Settings
            f.write("GlobalSettings:  {\n")
            f.write("\tVersion: 1000\n")
            f.write("\tProperties70:  {\n")
            f.write('\t\tP: "UpAxis", "int", "Integer", "",1\n')
            f.write('\t\tP: "UpAxisSign", "int", "Integer", "",1\n')
            f.write('\t\tP: "FrontAxis", "int", "Integer", "",2\n')
            f.write('\t\tP: "FrontAxisSign", "int", "Integer", "",1\n')
            f.write('\t\tP: "CoordAxis", "int", "Integer", "",0\n')
            f.write('\t\tP: "CoordAxisSign", "int", "Integer", "",1\n')
            f.write('\t\tP: "OriginalUpAxis", "int", "Integer", "",1\n')
            f.write('\t\tP: "OriginalUpAxisSign", "int", "Integer", "",1\n')
            f.write('\t\tP: "UnitScaleFactor", "double", "Number", "",1\n')
            f.write("\t}\n")
            f.write("}\n\n")

            # Documents
            f.write("Documents:  {\n")
            f.write("\tCount: 1\n")
            f.write(f'\tDocument: {timestamp}, "", "Scene" {{\n')
            f.write("\t\tProperties70:  {\n")
            f.write(f'\t\t\tP: "SourceObject", "object", "", ""\n')
            f.write(f'\t\t\tP: "ActiveAnimStackName", "KString", "", "", ""\n')
            f.write("\t\t}\n")
            f.write(f"\t\tRootNode: 0\n")
            f.write("\t}\n")
            f.write("}\n\n")

            # Definitions
            f.write("Definitions:  {\n")
            f.write("\tVersion: 100\n")
            f.write(f"\tCount: {5 + len(bones) * 2}\n")
            f.write('\tObjectType: "GlobalSettings" {\n')
            f.write("\t\tCount: 1\n")
            f.write("\t}\n")
            f.write('\tObjectType: "Model" {\n')
            f.write(f"\t\tCount: {1 + len(bones)}\n")
            f.write("\t}\n")
            f.write('\tObjectType: "Geometry" {\n')
            f.write("\t\tCount: 1\n")
            f.write("\t}\n")
            f.write('\tObjectType: "Material" {\n')
            f.write("\t\tCount: 1\n")
            f.write("\t}\n")
            f.write('\tObjectType: "Deformer" {\n')
            f.write(f"\t\tCount: {1 + len(bones)}\n")
            f.write("\t}\n")
            f.write('\tObjectType: "NodeAttribute" {\n')
            f.write(f"\t\tCount: {len(bones)}\n")
            f.write("\t}\n")
            f.write('\tObjectType: "Pose" {\n')
            f.write("\t\tCount: 1\n")
            f.write("\t}\n")
            f.write("}\n\n")

            # Objects
            f.write("Objects:  {\n\n")

            # Mesh Geometry
            f.write(f'\tGeometry: {mesh_id}, "Geometry::Mesh", "Mesh" {{\n')

            # Vertices
            f.write(f"\t\tVertices: *{len(vertices) * 3} {{\n")
            f.write("\t\t\ta: ")
            vert_strings = []
            for vx, vy, vz in vertices:
                vert_strings.append(f"{vx:.6f},{vy:.6f},{vz:.6f}")
            f.write(",".join(vert_strings))
            f.write("\n\t\t}\n")

            # Polygon indices
            f.write(f"\t\tPolygonVertexIndex: *{len(indices) * 3} {{\n")
            f.write("\t\t\ta: ")
            idx_strings = []
            for i0, i1, i2 in indices:
                # Last index is negated and decremented (FBX convention)
                idx_strings.append(f"{i0},{i1},{-i2-1}")
            f.write(",".join(idx_strings))
            f.write("\n\t\t}\n")

            # UV Layer
            f.write("\t\tLayerElementUV: 0 {\n")
            f.write("\t\t\tVersion: 101\n")
            f.write('\t\t\tName: "UVMap"\n')
            f.write('\t\t\tMappingInformationType: "ByPolygonVertex"\n')
            f.write('\t\t\tReferenceInformationType: "Direct"\n')
            f.write(f"\t\t\tUV: *{len(uvs) * 2} {{\n")
            f.write("\t\t\t\ta: ")
            uv_strings = []
            for u, v in uvs:
                uv_strings.append(f"{u:.6f},{v:.6f}")
            f.write(",".join(uv_strings))
            f.write("\n\t\t\t}\n")
            f.write("\t\t}\n")

            # Layer
            f.write("\t\tLayer: 0 {\n")
            f.write("\t\t\tVersion: 100\n")
            f.write("\t\t\tLayerElement:  {\n")
            f.write('\t\t\t\tType: "LayerElementUV"\n')
            f.write("\t\t\t\tTypedIndex: 0\n")
            f.write("\t\t\t}\n")
            f.write("\t\t}\n")
            f.write("\t}\n\n")

            # Mesh Model
            f.write(
                f'\tModel: {mesh_model_id}, "Model::MML_Model_{model_index}", "Mesh" {{\n'
            )
            f.write("\t\tVersion: 232\n")
            f.write("\t\tProperties70:  {\n")
            f.write('\t\t\tP: "DefaultAttributeIndex", "int", "Integer", "",0\n')
            f.write("\t\t}\n")
            f.write("\t\tShading: T\n")
            f.write('\t\tCulling: "CullingOff"\n')
            f.write("\t}\n\n")

            # Material
            f.write(f'\tMaterial: {material_id}, "Material::Material", "" {{\n')
            f.write("\t\tVersion: 102\n")
            f.write('\t\tShadingModel: "lambert"\n')
            f.write("\t\tProperties70:  {\n")
            f.write('\t\t\tP: "DiffuseColor", "Color", "", "A",0.8,0.8,0.8\n')
            f.write("\t\t}\n")
            f.write("\t}\n\n")

            # Bone Node Attributes (LimbNode)
            for bone in bones:
                bid = bone_ids[bone["index"]]
                f.write(
                    f'\tNodeAttribute: {bid}, "NodeAttribute::{bone["name"]}", "LimbNode" {{\n'
                )
                f.write('\t\tTypeFlags: "Skeleton"\n')
                f.write("\t}\n\n")

            # Bone Models
            for bone in bones:
                nid = bone_node_ids[bone["index"]]
                tx, ty, tz = bone["local_translation"]
                f.write(f'\tModel: {nid}, "Model::{bone["name"]}", "LimbNode" {{\n')
                f.write("\t\tVersion: 232\n")
                f.write("\t\tProperties70:  {\n")
                f.write(
                    f'\t\t\tP: "Lcl Translation", "Lcl Translation", "", "A",{tx:.6f},{ty:.6f},{tz:.6f}\n'
                )
                f.write('\t\t\tP: "DefaultAttributeIndex", "int", "Integer", "",0\n')
                f.write("\t\t}\n")
                f.write("\t\tShading: Y\n")
                f.write('\t\tCulling: "CullingOff"\n')
                f.write("\t}\n\n")

            # Skin Deformer
            f.write(f'\tDeformer: {skin_id}, "Deformer::Skin", "Skin" {{\n')
            f.write("\t\tVersion: 101\n")
            f.write("\t\tLink_DeformAcuracy: 50\n")
            f.write("\t}\n\n")

            # Cluster Deformers (one per bone)
            for bone in bones:
                cid = cluster_ids[bone["index"]]
                bone_idx = bone["index"]

                # Find vertices assigned to this bone
                assigned_verts = []
                for vi, bi in enumerate(bone_assignments):
                    if bi == bone_idx:
                        assigned_verts.append(vi)

                # Get bone world position for TransformLink matrix
                if bone_idx < len(world_positions):
                    bx, by, bz = world_positions[bone_idx]
                else:
                    bx, by, bz = 0, 0, 0

                f.write(
                    f'\tDeformer: {cid}, "SubDeformer::{bone["name"]}", "Cluster" {{\n'
                )
                f.write("\t\tVersion: 100\n")
                f.write('\t\tUserData: "", ""\n')

                if assigned_verts:
                    f.write(f"\t\tIndexes: *{len(assigned_verts)} {{\n")
                    f.write("\t\t\ta: ")
                    f.write(",".join(str(v) for v in assigned_verts))
                    f.write("\n\t\t}\n")

                    f.write(f"\t\tWeights: *{len(assigned_verts)} {{\n")
                    f.write("\t\t\ta: ")
                    f.write(",".join("1.0" for _ in assigned_verts))
                    f.write("\n\t\t}\n")

                # Transform matrix (mesh bind pose - identity)
                f.write("\t\tTransform: *16 {\n")
                f.write("\t\t\ta: 1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1\n")
                f.write("\t\t}\n")

                # TransformLink matrix (bone bind pose - translation only)
                f.write("\t\tTransformLink: *16 {\n")
                f.write(
                    f"\t\t\ta: 1,0,0,0,0,1,0,0,0,0,1,0,{bx:.6f},{by:.6f},{bz:.6f},1\n"
                )
                f.write("\t\t}\n")

                f.write("\t}\n\n")

            # Bind Pose
            pose_id = self.get_id()
            f.write(f'\tPose: {pose_id}, "Pose::BindPose", "BindPose" {{\n')
            f.write('\t\tType: "BindPose"\n')
            f.write("\t\tVersion: 100\n")
            f.write(f"\t\tNbPoseNodes: {1 + len(bones)}\n")

            # Mesh pose node
            f.write("\t\tPoseNode:  {\n")
            f.write(f"\t\t\tNode: {mesh_model_id}\n")
            f.write("\t\t\tMatrix: *16 {\n")
            f.write("\t\t\t\ta: 1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1\n")
            f.write("\t\t\t}\n")
            f.write("\t\t}\n")

            # Bone pose nodes
            for bone in bones:
                nid = bone_node_ids[bone["index"]]
                bone_idx = bone["index"]
                if bone_idx < len(world_positions):
                    bx, by, bz = world_positions[bone_idx]
                else:
                    bx, by, bz = 0, 0, 0

                f.write("\t\tPoseNode:  {\n")
                f.write(f"\t\t\tNode: {nid}\n")
                f.write("\t\t\tMatrix: *16 {\n")
                f.write(
                    f"\t\t\t\ta: 1,0,0,0,0,1,0,0,0,0,1,0,{bx:.6f},{by:.6f},{bz:.6f},1\n"
                )
                f.write("\t\t\t}\n")
                f.write("\t\t}\n")

            f.write("\t}\n\n")

            f.write("}\n\n")

            # Connections
            f.write("Connections:  {\n")

            # Connect mesh geometry to mesh model
            f.write(f'\tC: "OO",{mesh_id},{mesh_model_id}\n')

            # Connect mesh model to root
            f.write(f'\tC: "OO",{mesh_model_id},0\n')

            # Connect material to mesh model
            f.write(f'\tC: "OO",{material_id},{mesh_model_id}\n')

            # Connect skin to mesh geometry
            f.write(f'\tC: "OO",{skin_id},{mesh_id}\n')

            # Connect bone attributes to bone models
            for bone in bones:
                bid = bone_ids[bone["index"]]
                nid = bone_node_ids[bone["index"]]
                f.write(f'\tC: "OO",{bid},{nid}\n')

            # Connect bone models to parents (or root)
            for bone in bones:
                nid = bone_node_ids[bone["index"]]
                if bone["parent"] == -1:
                    f.write(f'\tC: "OO",{nid},0\n')
                else:
                    parent_nid = bone_node_ids[bone["parent"]]
                    f.write(f'\tC: "OO",{nid},{parent_nid}\n')

            # Connect clusters to skin and bones
            for bone in bones:
                cid = cluster_ids[bone["index"]]
                nid = bone_node_ids[bone["index"]]
                f.write(f'\tC: "OO",{cid},{skin_id}\n')
                f.write(f'\tC: "OO",{nid},{cid}\n')

            f.write("}\n")


def usage():
    print(f"mml_ebd2fbx v{__version__} - Convert MML EBD models to FBX with skeleton")
    print(
        f"Usage: {os.path.basename(sys.argv[0])} [options] <input.ebd> [output.fbx] [model_index]"
    )
    print(f"")
    print(f"Options:")
    print(f"  -a, --all    Export all models as separate FBX files")
    print(f"")
    print(f"Arguments:")
    print(f"  input.ebd    Input EBD file")
    print(f"  output.fbx   Output FBX file (default: input name with .fbx extension)")
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
                f"  Model {i}: {len(model['limbs'])} limbs, {total_verts} vertices, "
                f"{total_tris} tris, {total_quads} quads"
            )

        exporter = FBXExporter()

        if export_all:
            print(f"\nExporting all {len(ebd.models)} models...")
            for i in range(len(ebd.models)):
                output_file = f"{base_name}_model{i}.fbx"
                print(f"\nExporting model {i}...")
                exporter.export(ebd, output_file, i)
            print(f"\nDone! Exported {len(ebd.models)} models.")
        else:
            output_file = args[1] if len(args) > 1 else base_name + ".fbx"
            model_index = int(args[2]) if len(args) > 2 else 0
            print(f"\nExporting model {model_index}...")
            exporter.export(ebd, output_file, model_index)

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
