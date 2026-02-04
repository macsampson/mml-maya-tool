
import time

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

                # Add this bone's translation using the actual bone index
                bone_idx = limb_info["bone_index"]
                if bone_idx < len(bone_translations):
                    tx, ty, tz = bone_translations[bone_idx]
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
                    "anim_bone_index": limb_info["bone_index"],
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

        # Build a mapping from render_number (primId) to the actual bone index
        # This matches JavaScript: lookup[weights.primId] = bones[weights.childBone]
        render_to_bone = {}
        for limb_info in limb_indices:
            render_number = limb_info["render"]  # primId
            bone_idx = limb_info["bone_index"]   # childBone - the ACTUAL bone index
            if render_number not in render_to_bone:
                render_to_bone[render_number] = bone_idx

        # Build lookup table: limb number -> limb data
        limb_by_number = {}
        for limb in model["limbs"]:
            limb_by_number[limb["number"]] = limb

        # Process each unique mesh exactly once
        # Iterate through meshes by their number (not array position)
        processed_meshes = set()
        
        for limb in model["limbs"]:
            mesh_number = limb["number"]
            
            # Skip if already processed (shouldn't happen, but safety check)
            if mesh_number in processed_meshes:
                continue
            processed_meshes.add(mesh_number)
            
            # Find which bone this mesh belongs to
            bone_idx = render_to_bone.get(mesh_number)
            if bone_idx is None:
                # No bone references this mesh - skip it
                continue

            # Get bone world position
            if bone_idx < len(world_positions):
                raw_pos = world_positions[bone_idx]
                bx = raw_pos[0] * scale
                by = raw_pos[1] * scale
                bz = raw_pos[2] * scale
            else:
                bx, by, bz = 0.0, 0.0, 0.0

            # Add vertices - assign to the correct bone
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
                u0, u1, u2, u3 = quad["uvs"]
                
                # Tri 1: i0, i1, i2 (bi, ai, ci)
                all_indices.append(
                    (
                        global_vertex_offset + i0,
                        global_vertex_offset + i1,
                        global_vertex_offset + i2,
                    )
                )
                
                # Tri 2: i3, i0, i2 (di, bi, ci)
                all_indices.append(
                    (
                        global_vertex_offset + i3,
                        global_vertex_offset + i0,
                        global_vertex_offset + i2,
                    )
                )

                # UVs processing
                # Tri 1: u0, u1, u2 (b, a, c)
                u_0, v_0 = u0
                u_1, v_1 = u1
                u_2, v_2 = u2
                
                all_uvs.extend(
                    [
                        (u_0 / 255.0, 1.0 - v_0 / 255.0),
                        (u_1 / 255.0, 1.0 - v_1 / 255.0),
                        (u_2 / 255.0, 1.0 - v_2 / 255.0),
                    ]
                )
                
                # Tri 2: u3, u0, u2 (d, b, c)
                u_3, v_3 = u3
                
                all_uvs.extend(
                    [
                        (u_3 / 255.0, 1.0 - v_3 / 255.0),
                        (u_0 / 255.0, 1.0 - v_0 / 255.0),
                        (u_2 / 255.0, 1.0 - v_2 / 255.0),
                    ]
                )

            global_vertex_offset += len(limb["vertices"])

        # Get animations
        animations = model.get("animations", [])

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
            animations,
        )

        print(f"Exported to {output_path}")
        print(f"  Bones: {len(bones)}")
        print(f"  Vertices: {len(all_vertices)}")
        print(f"  Triangles: {len(all_indices)}")
        print(f"  Animations: {len(animations)}")
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
        animations=None,
    ):
        """Write ASCII FBX 7.4 file with optional animations."""
        if animations is None:
            animations = []

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

        # Animation IDs
        anim_stack_ids = []
        anim_layer_ids = []
        anim_curve_node_ids = {}  # {(anim_idx, bone_idx, 'R'/'T'): id}
        anim_curve_ids = {}  # {(anim_idx, bone_idx, 'R'/'T', axis): id}
        
        for anim_idx, anim in enumerate(animations):
            anim_stack_ids.append(self.get_id())
            anim_layer_ids.append(self.get_id())
            
            for bone in bones:
                # Rotation curve node
                anim_curve_node_ids[(anim_idx, bone["index"], 'R')] = self.get_id()
                # Translation curve node (only for root)
                if bone["parent"] == -1:
                    anim_curve_node_ids[(anim_idx, bone["index"], 'T')] = self.get_id()
                
                # Individual axis curves for rotation
                for axis in ['X', 'Y', 'Z']:
                    anim_curve_ids[(anim_idx, bone["index"], 'R', axis)] = self.get_id()
                    if bone["parent"] == -1:
                        anim_curve_ids[(anim_idx, bone["index"], 'T', axis)] = self.get_id()

        timestamp = int(time.time())

        with open(output_path, "w") as f:
            # FBX Header
            f.write("; FBX 7.4.0 project file\\n")
            f.write("; Exported by mml_ebd2fbx\\n")
            f.write("; ----------------------------------------------------\\n\\n")

            # FBX Header Extension
            f.write("FBXHeaderExtension:  {\\n")
            f.write("\\tFBXHeaderVersion: 1003\\n")
            f.write("\\tFBXVersion: 7400\\n")
            f.write("\\tCreationTimeStamp:  {\\n")
            f.write("\\t\\tVersion: 1000\\n")
            f.write(f"\\t\\tYear: {time.localtime().tm_year}\\n")
            f.write(f"\\t\\tMonth: {time.localtime().tm_mon}\\n")
            f.write(f"\\t\\tDay: {time.localtime().tm_mday}\\n")
            f.write(f"\\t\\tHour: {time.localtime().tm_hour}\\n")
            f.write(f"\\t\\tMinute: {time.localtime().tm_min}\\n")
            f.write(f"\\t\\tSecond: {time.localtime().tm_sec}\\n")
            f.write("\\t\\tMillisecond: 0\\n")
            f.write("\\t}\\n")
            f.write('\\tCreator: "mml_ebd2fbx"\\n')
            f.write("}\\n\\n")

            # Global Settings
            f.write("GlobalSettings:  {\\n")
            f.write("\\tVersion: 1000\\n")
            f.write("\\tProperties70:  {\\n")
            f.write('\\t\\tP: "UpAxis", "int", "Integer", "",1\\n')
            f.write('\\t\\tP: "UpAxisSign", "int", "Integer", "",1\\n')
            f.write('\\t\\tP: "FrontAxis", "int", "Integer", "",2\\n')
            f.write('\\t\\tP: "FrontAxisSign", "int", "Integer", "",1\\n')
            f.write('\\t\\tP: "CoordAxis", "int", "Integer", "",0\\n')
            f.write('\\t\\tP: "CoordAxisSign", "int", "Integer", "",1\\n')
            f.write('\\t\\tP: "OriginalUpAxis", "int", "Integer", "",1\\n')
            f.write('\\t\\tP: "OriginalUpAxisSign", "int", "Integer", "",1\\n')
            f.write('\\t\\tP: "UnitScaleFactor", "double", "Number", "",1\\n')
            f.write("\\t}\\n")
            f.write("}\\n\\n")

            # Documents
            f.write("Documents:  {\\n")
            f.write("\\tCount: 1\\n")
            f.write(f'\\tDocument: {timestamp}, "", "Scene" {{\\n')
            f.write("\\t\\tProperties70:  {\\n")
            f.write(f'\\t\\t\\tP: "SourceObject", "object", "", ""\\n')
            f.write(f'\\t\\t\\tP: "ActiveAnimStackName", "KString", "", "", ""\\n')
            f.write("\\t\\t}\\n")
            f.write(f"\\t\\tRootNode: 0\\n")
            f.write("\\t}\\n")
            f.write("}\\n\\n")

            # Definitions
            # Calculate animation object counts
            num_anim_stacks = len(animations)
            num_anim_layers = len(animations)
            num_curve_nodes = len(anim_curve_node_ids)
            num_curves = len(anim_curve_ids)
            
            base_count = 5 + len(bones) * 2
            if animations:
                base_count += 4  # AnimationStack, AnimationLayer, AnimationCurveNode, AnimationCurve
            
            f.write("Definitions:  {\\n")
            f.write("\\tVersion: 100\\n")
            f.write(f"\\tCount: {base_count}\\n")
            f.write('\\tObjectType: "GlobalSettings" {\\n')
            f.write("\\t\\tCount: 1\\n")
            f.write("\\t}\\n")
            f.write('\\tObjectType: "Model" {\\n')
            f.write(f"\\t\\tCount: {1 + len(bones)}\\n")
            f.write("\\t}\\n")
            f.write('\\tObjectType: "Geometry" {\\n')
            f.write("\\t\\tCount: 1\\n")
            f.write("\\t}\\n")
            f.write('\\tObjectType: "Material" {\\n')
            f.write("\\t\\tCount: 1\\n")
            f.write("\\t}\\n")
            f.write('\\tObjectType: "Deformer" {\\n')
            f.write(f"\\t\\tCount: {1 + len(bones)}\\n")
            f.write("\\t}\\n")
            f.write('\\tObjectType: "NodeAttribute" {\\n')
            f.write(f"\\t\\tCount: {len(bones)}\\n")
            f.write("\\t}\\n")
            f.write('\\tObjectType: "Pose" {\\n')
            f.write("\\t\\tCount: 1\\n")
            f.write("\\t}\\n")
            
            # Animation definitions
            if animations:
                f.write('\\tObjectType: "AnimationStack" {\\n')
                f.write(f"\\t\\tCount: {num_anim_stacks}\\n")
                f.write("\\t}\\n")
                f.write('\\tObjectType: "AnimationLayer" {\\n')
                f.write(f"\\t\\tCount: {num_anim_layers}\\n")
                f.write("\\t}\\n")
                f.write('\\tObjectType: "AnimationCurveNode" {\\n')
                f.write(f"\\t\\tCount: {num_curve_nodes}\\n")
                f.write("\\t}\\n")
                f.write('\\tObjectType: "AnimationCurve" {\\n')
                f.write(f"\\t\\tCount: {num_curves}\\n")
                f.write("\\t}\\n")
            
            f.write("}\\n\\n")

            # Objects
            f.write("Objects:  {\\n\\n")

            # Mesh Geometry
            f.write(f'\\tGeometry: {mesh_id}, "Geometry::Mesh", "Mesh" {{\\n')

            # Vertices
            f.write(f"\\t\\tVertices: *{len(vertices) * 3} {{\\n")
            f.write("\\t\\t\\ta: ")
            vert_strings = []
            for vx, vy, vz in vertices:
                vert_strings.append(f"{vx:.6f},{vy:.6f},{vz:.6f}")
            f.write(",".join(vert_strings))
            f.write("\\n\\t\\t}\\n")

            # Polygon indices
            f.write(f"\\t\\tPolygonVertexIndex: *{len(indices) * 3} {{\\n")
            f.write("\\t\\t\\ta: ")
            idx_strings = []
            for i0, i1, i2 in indices:
                # Last index is negated and decremented (FBX convention)
                idx_strings.append(f"{i0},{i1},{-i2-1}")
            f.write(",".join(idx_strings))
            f.write("\\n\\t\\t}\\n")

            # UV Layer
            f.write("\\t\\tLayerElementUV: 0 {\\n")
            f.write("\\t\\t\\tVersion: 101\\n")
            f.write('\\t\\t\\tName: "UVMap"\\n')
            f.write('\\t\\t\\tMappingInformationType: "ByPolygonVertex"\\n')
            f.write('\\t\\t\\tReferenceInformationType: "Direct"\\n')
            f.write(f"\\t\\t\\tUV: *{len(uvs) * 2} {{\\n")
            f.write("\\t\\t\\t\\ta: ")
            uv_strings = []
            for u, v in uvs:
                uv_strings.append(f"{u:.6f},{v:.6f}")
            f.write(",".join(uv_strings))
            f.write("\\n\\t\\t\\t}\\n")
            f.write("\\t\\t}\\n")

            # Layer
            f.write("\\t\\tLayer: 0 {\\n")
            f.write("\\t\\t\\tVersion: 100\\n")
            f.write("\\t\\t\\tLayerElement:  {\\n")
            f.write('\\t\\t\\t\\tType: "LayerElementUV"\\n')
            f.write("\\t\\t\\t\\tTypedIndex: 0\\n")
            f.write("\\t\\t\\t}\\n")
            f.write("\\t\\t}\\n")
            f.write("\\t}\\n\\n")

            # Mesh Model
            f.write(
                f'\\tModel: {mesh_model_id}, "Model::MML_Model_{model_index}", "Mesh" {{\\n'
            )
            f.write("\\t\\tVersion: 232\\n")
            f.write("\\t\\tProperties70:  {\\n")
            f.write('\\t\\t\\tP: "DefaultAttributeIndex", "int", "Integer", "",0\\n')
            f.write("\\t\\t}\\n")
            f.write("\\t\\tShading: T\\n")
            f.write('\\t\\tCulling: "CullingOff"\\n')
            f.write("\\t}\\n\\n")

            # Material
            f.write(f'\\tMaterial: {material_id}, "Material::Material", "" {{\\n')
            f.write("\\t\\tVersion: 102\\n")
            f.write('\\t\\tShadingModel: "lambert"\\n')
            f.write("\\t\\tProperties70:  {\\n")
            f.write('\\t\\t\\tP: "DiffuseColor", "Color", "", "A",0.8,0.8,0.8\\n')
            f.write("\\t\\t}\\n")
            f.write("\\t}\\n\\n")

            # Bone Node Attributes (LimbNode)
            for bone in bones:
                bid = bone_ids[bone["index"]]
                f.write(
                    f'\\tNodeAttribute: {bid}, "NodeAttribute::{bone["name"]}", "LimbNode" {{\\n'
                )
                f.write('\\t\\tTypeFlags: "Skeleton"\\n')
                f.write("\\t}\\n\\n")

            # Bone Models
            for bone in bones:
                nid = bone_node_ids[bone["index"]]
                tx, ty, tz = bone["local_translation"]
                f.write(f'\\tModel: {nid}, "Model::{bone["name"]}", "LimbNode" {{\\n')
                f.write("\\t\\tVersion: 232\\n")
                f.write("\\t\\tProperties70:  {\\n")
                f.write(
                    f'\\t\\t\\tP: "Lcl Translation", "Lcl Translation", "", "A",{tx:.6f},{ty:.6f},{tz:.6f}\\n'
                )
                f.write('\\t\\t\\tP: "DefaultAttributeIndex", "int", "Integer", "",0\\n')
                f.write("\\t\\t}\\n")
                f.write("\\t\\tShading: Y\\n")
                f.write('\\t\\tCulling: "CullingOff"\\n')
                f.write("\\t}\\n\\n")

            # Skin Deformer
            f.write(f'\\tDeformer: {skin_id}, "Deformer::Skin", "Skin" {{\\n')
            f.write("\\t\\tVersion: 101\\n")
            f.write("\\t\\tLink_DeformAcuracy: 50\\n")
            f.write("\\t}\\n\\n")

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
                    f'\\tDeformer: {cid}, "SubDeformer::{bone["name"]}", "Cluster" {{\\n'
                )
                f.write("\\t\\tVersion: 100\\n")
                f.write('\\t\\tUserData: "", ""\\n')

                if assigned_verts:
                    f.write(f"\\t\\tIndexes: *{len(assigned_verts)} {{\\n")
                    f.write("\\t\\t\\ta: ")
                    f.write(",".join(str(v) for v in assigned_verts))
                    f.write("\\n\\t\\t}\\n")

                    f.write(f"\\t\\tWeights: *{len(assigned_verts)} {{\\n")
                    f.write("\\t\\t\\ta: ")
                    f.write(",".join("1.0" for _ in assigned_verts))
                    f.write("\\n\\t\\t}\\n")

                # Transform matrix (mesh bind pose - identity)
                f.write("\\t\\tTransform: *16 {\\n")
                f.write("\\t\\t\\ta: 1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1\\n")
                f.write("\\t\\t}\\n")

                # TransformLink matrix (bone bind pose - translation only)
                f.write("\\t\\tTransformLink: *16 {\\n")
                f.write(
                    f"\\t\\t\\ta: 1,0,0,0,0,1,0,0,0,0,1,0,{bx:.6f},{by:.6f},{bz:.6f},1\\n"
                )
                f.write("\\t\\t}\\n")

                f.write("\\t}\\n\\n")

            # Bind Pose
            pose_id = self.get_id()
            f.write(f'\\tPose: {pose_id}, "Pose::BindPose", "BindPose" {{\\n')
            f.write('\\t\\tType: "BindPose"\\n')
            f.write("\\t\\tVersion: 100\\n")
            f.write(f"\\t\\tNbPoseNodes: {1 + len(bones)}\\n")

            # Mesh pose node
            f.write("\\t\\tPoseNode:  {\\n")
            f.write(f"\\t\\t\\tNode: {mesh_model_id}\\n")
            f.write("\\t\\t\\tMatrix: *16 {\\n")
            f.write("\\t\\t\\t\\ta: 1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1\\n")
            f.write("\\t\\t\\t}\\n")
            f.write("\\t\\t}\\n")

            # Bone pose nodes
            for bone in bones:
                nid = bone_node_ids[bone["index"]]
                bone_idx = bone["index"]
                if bone_idx < len(world_positions):
                    bx, by, bz = world_positions[bone_idx]
                else:
                    bx, by, bz = 0, 0, 0

                f.write("\\t\\tPoseNode:  {\\n")
                f.write(f"\\t\\t\\tNode: {nid}\\n")
                f.write("\\t\\t\\tMatrix: *16 {\\n")
                f.write(
                    f"\\t\\t\\t\\ta: 1,0,0,0,0,1,0,0,0,0,1,0,{bx:.6f},{by:.6f},{bz:.6f},1\\n"
                )
                f.write("\\t\\t\\t}\\n")
                f.write("\\t\\t}\\n")

            f.write("\\t}\\n\\n")

            # Animation Objects
            for anim_idx, anim in enumerate(animations):
                frames = anim.get("frames", [])
                num_frames = len(frames)
                if num_frames == 0:
                    continue
                
                # Frame rate assumption: 30 FPS
                fps = 30.0
                duration_sec = num_frames / fps
                duration_fbx = int(duration_sec * 46186158000)  # FBX time units
                
                stack_id = anim_stack_ids[anim_idx]
                layer_id = anim_layer_ids[anim_idx]
                
                # AnimationStack
                f.write(f'\\tAnimationStack: {stack_id}, "AnimStack::Anim_{anim_idx:03d}", "" {{\\n')
                f.write("\\t\\tProperties70:  {\\n")
                f.write(f'\\t\\t\\tP: "LocalStop", "KTime", "Time", "",{duration_fbx}\\n')
                f.write(f'\\t\\t\\tP: "ReferenceStop", "KTime", "Time", "",{duration_fbx}\\n')
                f.write("\\t\\t}\\n")
                f.write("\\t}\\n\\n")
                
                # AnimationLayer
                f.write(f'\\tAnimationLayer: {layer_id}, "AnimLayer::BaseLayer", "" {{\\n')
                f.write("\\t}\\n\\n")
                
                # AnimationCurveNodes and AnimationCurves for each bone
                for bone in bones:
                    bone_idx = bone["index"]
                    is_root = bone["parent"] == -1
                    
                    # Rotation CurveNode
                    rot_node_id = anim_curve_node_ids.get((anim_idx, bone_idx, 'R'))
                    if rot_node_id:
                        f.write(f'\\tAnimationCurveNode: {rot_node_id}, "AnimCurveNode::R", "" {{\\n')
                        f.write("\\t\\tProperties70:  {\\n")
                        f.write('\\t\\t\\tP: "d|X", "Number", "", "A",0\\n')
                        f.write('\\t\\t\\tP: "d|Y", "Number", "", "A",0\\n')
                        f.write('\\t\\t\\tP: "d|Z", "Number", "", "A",0\\n')
                        f.write("\\t\\t}\\n")
                        f.write("\\t}\\n\\n")
                    
                    # Translation CurveNode (root only)
                    if is_root:
                        trans_node_id = anim_curve_node_ids.get((anim_idx, bone_idx, 'T'))
                        if trans_node_id:
                            f.write(f'\\tAnimationCurveNode: {trans_node_id}, "AnimCurveNode::T", "" {{\\n')
                            f.write("\\t\\tProperties70:  {\\n")
                            f.write('\\t\\t\\tP: "d|X", "Number", "", "A",0\\n')
                            f.write('\\t\\t\\tP: "d|Y", "Number", "", "A",0\\n')
                            f.write('\\t\\t\\tP: "d|Z", "Number", "", "A",0\\n')
                            f.write("\\t\\t}\\n")
                            f.write("\\t}\\n\\n")
                    
                    # Rotation curves (X, Y, Z)
                    for axis_idx, axis in enumerate(['X', 'Y', 'Z']):
                        curve_id = anim_curve_ids.get((anim_idx, bone_idx, 'R', axis))
                        if curve_id and frames:
                            f.write(f'\\tAnimationCurve: {curve_id}, "AnimCurve::", "" {{\\n')
                            f.write("\\t\\tDefault: 0\\n")
                            f.write(f"\\t\\tKeyVer: 4008\\n")
                            f.write(f"\\t\\tKeyTime: *{num_frames} {{\\n")
                            f.write("\\t\\t\\ta: ")
                            times = []
                            for frame_idx in range(num_frames):
                                time_fbx = int((frame_idx / fps) * 46186158000)
                                times.append(str(time_fbx))
                            f.write(",".join(times))
                            f.write("\\n\\t\\t}\\n")
                            
                            f.write(f"\\t\\tKeyValueFloat: *{num_frames} {{\\n")
                            f.write("\\t\\t\\ta: ")
                            values = []
                            
                            # Get the correct animation track index for this bone (limb)
                            anim_track_idx = bone.get("anim_bone_index", bone_idx)
                            
                            for frame_idx, frame in enumerate(frames):
                                # Get rotation value for this bone from bone_rotations list
                                bone_rots = frame.get("bone_rotations", [])
                                if anim_track_idx < len(bone_rots):
                                    rot = bone_rots[anim_track_idx]
                                    # Values are already in degrees!
                                    degrees = rot[axis_idx] if axis_idx < len(rot) else 0
                                    # Apply Y and Z negation like DashViewer
                                    if axis_idx == 1 or axis_idx == 2:
                                        degrees = -degrees
                                else:
                                    degrees = 0.0
                                values.append(f"{degrees:.6f}")
                            f.write(",".join(values))
                            f.write("\\n\\t\\t}\\n")
                            f.write("\\t}\\n\\n")
                    
                    # Translation curves (root only)
                    if is_root:
                        for axis_idx, axis in enumerate(['X', 'Y', 'Z']):
                            curve_id = anim_curve_ids.get((anim_idx, bone_idx, 'T', axis))
                            if curve_id and frames:
                                scale = 1.0 / 100.0  # Same scale as model
                                f.write(f'\\tAnimationCurve: {curve_id}, "AnimCurve::", "" {{\\n')
                                f.write("\\t\\tDefault: 0\\n")
                                f.write(f"\\t\\tKeyVer: 4008\\n")
                                f.write(f"\\t\\tKeyTime: *{num_frames} {{\\n")
                                f.write("\\t\\t\\ta: ")
                                times = []
                                for frame_idx in range(num_frames):
                                    time_fbx = int((frame_idx / fps) * 46186158000)
                                    times.append(str(time_fbx))
                                f.write(",".join(times))
                                f.write("\\n\\t\\t}\\n")
                                
                                f.write(f"\\t\\tKeyValueFloat: *{num_frames} {{\\n")
                                f.write("\\t\\t\\ta: ")
                                values = []
                                # Get bind pose translation for this bone
                                bind_ty = 0.0
                                if axis_idx == 1:  # Y axis
                                    for b in bones:
                                        if b["index"] == bone_idx:
                                            # local_translation is (tx, ty, tz)
                                            bind_ty = b["local_translation"][1]
                                            break

                                for frame_idx, frame in enumerate(frames):
                                    trans = frame.get("root_translation", (0, 0, 0))
                                    val = trans[axis_idx] * scale if axis_idx < len(trans) else 0
                                    
                                    # Add bind pose Y to animation Y (DashViewer behavior)
                                    if axis_idx == 1:
                                        val += bind_ty
                                        
                                    values.append(f"{val:.6f}")
                                f.write(",".join(values))
                                f.write("\\n\\t\\t}\\n")
                                f.write("\\t}\\n\\n")

            f.write("}\\n\\n")

            # Connections
            f.write("Connections:  {\\n")

            # Connect mesh geometry to mesh model
            f.write(f'\\tC: "OO",{mesh_id},{mesh_model_id}\\n')

            # Connect mesh model to root
            f.write(f'\\tC: "OO",{mesh_model_id},0\\n')

            # Connect material to mesh model
            f.write(f'\\tC: "OO",{material_id},{mesh_model_id}\\n')

            # Connect skin to mesh geometry
            f.write(f'\\tC: "OO",{skin_id},{mesh_id}\\n')

            # Connect bone attributes to bone models
            for bone in bones:
                bid = bone_ids[bone["index"]]
                nid = bone_node_ids[bone["index"]]
                f.write(f'\\tC: "OO",{bid},{nid}\\n')

            # Connect bone models to parents (or root)
            for bone in bones:
                nid = bone_node_ids[bone["index"]]
                if bone["parent"] == -1:
                    f.write(f'\\tC: "OO",{nid},0\\n')
                else:
                    parent_nid = bone_node_ids[bone["parent"]]
                    f.write(f'\\tC: "OO",{nid},{parent_nid}\\n')

            # Connect clusters to skin and bones
            for bone in bones:
                cid = cluster_ids[bone["index"]]
                nid = bone_node_ids[bone["index"]]
                f.write(f'\\tC: "OO",{cid},{skin_id}\\n')
                f.write(f'\\tC: "OO",{nid},{cid}\\n')

            # Animation connections
            for anim_idx, anim in enumerate(animations):
                if not anim.get("frames"):
                    continue
                    
                stack_id = anim_stack_ids[anim_idx]
                layer_id = anim_layer_ids[anim_idx]
                
                # Connect layer to stack
                f.write(f'\\tC: "OO",{layer_id},{stack_id}\\n')
                
                for bone in bones:
                    bone_idx = bone["index"]
                    nid = bone_node_ids[bone_idx]
                    is_root = bone["parent"] == -1
                    
                    # Connect rotation curve node to bone and layer
                    rot_node_id = anim_curve_node_ids.get((anim_idx, bone_idx, 'R'))
                    if rot_node_id:
                        f.write(f'\\tC: "OP",{rot_node_id},{nid},"Lcl Rotation"\\n')
                        f.write(f'\\tC: "OO",{rot_node_id},{layer_id}\\n')
                        
                        # Connect curves to curve node
                        for axis in ['X', 'Y', 'Z']:
                            curve_id = anim_curve_ids.get((anim_idx, bone_idx, 'R', axis))
                            if curve_id:
                                f.write(f'\\tC: "OP",{curve_id},{rot_node_id},"d|{axis}"\\n')
                    
                    # Connect translation curve node (root only)
                    if is_root:
                        trans_node_id = anim_curve_node_ids.get((anim_idx, bone_idx, 'T'))
                        if trans_node_id:
                            f.write(f'\\tC: "OP",{trans_node_id},{nid},"Lcl Translation"\\n')
                            f.write(f'\\tC: "OO",{trans_node_id},{layer_id}\\n')
                            
                            for axis in ['X', 'Y', 'Z']:
                                curve_id = anim_curve_ids.get((anim_idx, bone_idx, 'T', axis))
                                if curve_id:
                                    f.write(f'\\tC: "OP",{curve_id},{trans_node_id},"d|{axis}"\\n')

            f.write("}\\n")
