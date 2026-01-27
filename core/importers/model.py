#!/usr/bin/env python3
"""
MML Model Importer
Handles loading EBD models and creating geometry/skeletons in Maya.
"""

import os
import sys
import tempfile
import maya.cmds as cmds
import maya.api.OpenMaya as om
from MML.parsers.ebd2fbx import EBDReader

class ModelImporter:
    """Handles parsing and creating MML models in Maya."""
    
    SCALE = 1.0 / 100.0  # Scale factor for models
    
    @classmethod
    def import_ebd(cls, asset, model_index=0):
        """Import an EBD model into Maya with action figure-style rigging.
        
        Creates separate mesh pieces per limb, each parented directly to its bone.
        This ensures truly rigid movement with no vertex blending.
        
        Returns:
            dict with 'root_group', 'model_name', and 'animations' keys
        """
        # Save asset to temp file for parser
        temp_path = os.path.join(tempfile.gettempdir(), asset.name)
        with open(temp_path, 'wb') as f:
            f.write(asset.data)
        
        try:
            # Parse with existing EBDReader
            ebd = EBDReader(temp_path)
            
            if model_index >= len(ebd.models):
                cmds.warning(f"Model index {model_index} out of range")
                return None
            
            model = ebd.models[model_index]
            model_name = os.path.splitext(asset.name)[0]
            
            # Create the rigged model with separate mesh pieces per bone
            root_group = cls._create_rigged_model(model, model_name)
            
            # Get animations and rest pose
            animations = model.get('animations', [])
            bone_translations = model.get('bone_translations', [])
            
            return {
                'root_group': root_group,
                'model_name': model_name,
                'animations': animations,
                'bone_translations': bone_translations
            }
            
        finally:
            # Cleanup temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @classmethod
    def _create_rigged_model(cls, model, name):
        """Create model with separate mesh pieces parented to joints.
        
        This is action figure-style: each limb mesh is parented directly
        to its joint, so rotating a joint moves only that limb's geometry.
        """
        limb_indices = model.get('limb_indices', [])
        bone_translations = model.get('bone_translations', [])
        
        
        if not limb_indices:
            return None
        
        # Build render_to_bone mapping: render_idx (primId) -> bone_idx (childBone)
        # Also build bone parent hierarchy
        # This matches JavaScript: lookup[weights.primId] = bones[weights.childBone]
        render_to_bone = {}  # render_idx -> first bone that uses this mesh
        bone_parent = {}     # bone_idx -> parent_bone_idx
        
        for i, limb_info in enumerate(limb_indices):
            render_idx = limb_info['render']
            parent_bone = limb_info['parent']
            child_bone = limb_info['bone_index']
            
            # Map this mesh to the bone (only first occurrence)
            if render_idx not in render_to_bone:
                render_to_bone[render_idx] = child_bone
            
            # Build hierarchy (skip first entry like JS does)
            if i == 0:
                continue
            # Skip if self-referential
            if parent_bone == child_bone:
                continue
            # Only set parent if not already set (like JS: if(bones[...].parent) continue)
            if child_bone not in bone_parent:
                bone_parent[child_bone] = parent_bone
        
        # Compute world positions for each BONE (not limb_indices entry)
        # Walk up the bone parent hierarchy
        num_bones = len(bone_translations)
        bone_world_positions = {}
        
        for bone_idx in range(num_bones):
            wx, wy, wz = 0, 0, 0
            current = bone_idx
            visited = set()
            
            while current not in visited:
                visited.add(current)
                if current < len(bone_translations):
                    tx, ty, tz = bone_translations[current]
                    wx += tx
                    wy += ty
                    wz += tz
                
                if current in bone_parent:
                    current = bone_parent[current]
                else:
                    break
            
            bone_world_positions[bone_idx] = (wx * cls.SCALE, wy * cls.SCALE, wz * cls.SCALE)
        
        # Create root group
        root_group = cmds.group(empty=True, name=f"{name}_grp")
        
        # Create joints for each bone
        joints = {}  # bone_idx -> joint_name
        cmds.select(clear=True)
        
        for bone_idx in range(num_bones):
            # Get position
            px, py, pz = bone_world_positions.get(bone_idx, (0, 0, 0))
            
            # Select parent if exists
            parent_bone = bone_parent.get(bone_idx)
            if parent_bone is not None and parent_bone in joints:
                cmds.select(joints[parent_bone])
            else:
                cmds.select(clear=True)
            
            # Create joint
            joint_name = cmds.joint(
                name=f'{name}_Bone_{bone_idx:02d}',
                position=(px, py, pz),
                absolute=True
            )
            joints[bone_idx] = joint_name
        
        cmds.select(clear=True)
        
        # Parent root bones to the group
        for bone_idx in range(num_bones):
            if bone_idx not in bone_parent:
                if bone_idx in joints:
                    cmds.parent(joints[bone_idx], root_group)
        
        # Create meshes - iterate through model['limbs'] (the actual primitives)
        # Only create meshes that are in render_to_bone lookup (like JS does)
        for limb in model['limbs']:
            mesh_number = limb['number']  # This is the primId
            
            # Skip if this mesh isn't mapped to any bone (like JS: if(!lookup[prim.primId]) continue)
            if mesh_number not in render_to_bone:
                continue
            
            bone_idx = render_to_bone[mesh_number]
            
            # Prepare mesh data arrays
            points = om.MFloatPointArray()
            counts = om.MIntArray()
            connects = om.MIntArray()
            u_coords = om.MFloatArray()
            v_coords = om.MFloatArray()
            
            # Helper to add UVs and return UV index
            uv_map = {}  # (u, v) -> index
            next_uv_idx = 0
            
            def get_uv_idx(u_val, v_val):
                nonlocal next_uv_idx
                # UV values are pixel coordinates within texture page (256x256)
                # Normalize to 0-1 based on texture page dimensions
                # V is flipped (PSX uses opposite Y direction)
                u_norm = u_val / 256.0
                v_norm = 1.0 - (v_val / 256.0)
                
                key = (u_norm, v_norm)
                if key not in uv_map:
                    u_coords.append(u_norm)
                    v_coords.append(v_norm)
                    uv_map[key] = next_uv_idx
                    next_uv_idx += 1
                return uv_map[key]

            # Add vertices
            # NOTE: We keep vertices in LOCAL space relative to the bone for parenting!
            # The bone is at (bx, by, bz).
            # The vertex global pos is (vx*s + bx, vy*s + by, vz*s + bz).
            # To get local pos relative to bone: Global - Bone = (vx*s, vy*s, vz*s).
            # So we just scale the raw vertex coordinates.
            for vx, vy, vz in limb['vertices']:
                # Action figure method: Vertices are local to the bone
                points.append(om.MFloatPoint(vx * cls.SCALE, vy * cls.SCALE, vz * cls.SCALE))
            
            # Process faces and UVs
            face_uv_counts = om.MIntArray()
            face_uv_ids = om.MIntArray()
            
            has_geometry = False
            
            # Triangles
            for tri in limb['triangles']:
                i0, i1, i2 = tri['indices']
                counts.append(int(3))
                connects.append(int(i0)); connects.append(int(i1)); connects.append(int(i2))
                
                # UVs
                face_uv_counts.append(3)
                for u, v in tri['uvs']:
                    face_uv_ids.append(get_uv_idx(u, v))
                has_geometry = True

            # Quads (split to triangles) - matches mml_ebd2fbx.py logic exactly
            for quad in limb['quads']:
                i0, i1, i2, i3 = quad['indices']
                
                # Triangle 1: (i0, i1, i2) with UVs (0, 1, 2)
                counts.append(int(3))
                connects.append(int(i0)); connects.append(int(i1)); connects.append(int(i2))
                face_uv_counts.append(3)
                face_uv_ids.append(get_uv_idx(quad['uvs'][0][0], quad['uvs'][0][1]))
                face_uv_ids.append(get_uv_idx(quad['uvs'][1][0], quad['uvs'][1][1]))
                face_uv_ids.append(get_uv_idx(quad['uvs'][2][0], quad['uvs'][2][1]))
                
                # Triangle 2: (i0, i2, i3) with UVs (0, 2, 3)
                counts.append(int(3))
                connects.append(int(i0)); connects.append(int(i2)); connects.append(int(i3))
                face_uv_counts.append(3)
                face_uv_ids.append(get_uv_idx(quad['uvs'][0][0], quad['uvs'][0][1]))
                face_uv_ids.append(get_uv_idx(quad['uvs'][2][0], quad['uvs'][2][1]))
                face_uv_ids.append(get_uv_idx(quad['uvs'][3][0], quad['uvs'][3][1]))
                has_geometry = True
            
            if not has_geometry:
                continue
            
            # Check if this bone has a joint
            if bone_idx not in joints:
                cmds.warning(f"Bone {bone_idx} not found for mesh {mesh_number}")
                continue
                
            # Create Mesh using MFnMesh
            limb_mesh_name = f"{name}_Mesh_{mesh_number:02d}"
            fn_mesh = om.MFnMesh()
            
            try:
                mesh_obj = fn_mesh.create(
                    points, counts, connects,
                    u_coords, v_coords,
                    parent=om.MObject.kNullObj  # Create under world first
                )
                
                # Assign UVs
                fn_mesh.assignUVs(face_uv_counts, face_uv_ids)
                
                # Rename transform
                dep_node = om.MFnDependencyNode(mesh_obj)
                transform_obj = fn_mesh.parent(0)
                dep_transform = om.MFnDependencyNode(transform_obj)
                dep_transform.setName(limb_mesh_name)
                
                # Parent to joint using commands (safer for mixed API usage)
                cmds.parent(limb_mesh_name, joints[bone_idx])
                
                # Reset transform (since vertices were local, we want identity transform)
                # But fn_mesh.create makes it at origin, so just parenting is enough.
                # However, ensure pivots are zeroed if needed.
                cmds.makeIdentity(limb_mesh_name, apply=False, t=1, r=1, s=1, n=0, pn=1)
                
                # Assign default shader (lambert1) to ensure visibility
                cmds.sets(limb_mesh_name, edit=True, forceElement='initialShadingGroup')
                
            except Exception as e:
                cmds.warning(f"Failed to create mesh for bone {bone_idx}: {e}")
                continue
                
        cmds.select(clear=True)
        return root_group

    @classmethod
    def _create_mesh(cls, model, name, ebd):
        """Create Maya mesh from EBD model data."""
        limb_indices = model.get('limb_indices', [])
        bone_translations = model.get('bone_translations', [])
        
        # Compute world positions for bones
        world_positions = []
        for i in range(len(limb_indices)):
            wx, wy, wz = 0, 0, 0
            current_idx = i
            visited = set()
            
            while current_idx < len(limb_indices) and current_idx not in visited:
                visited.add(current_idx)
                limb_info = limb_indices[current_idx]
                bone_idx = limb_info['bone_index']
                
                if bone_idx < len(bone_translations):
                    tx, ty, tz = bone_translations[bone_idx]
                    wx += tx
                    wy += ty
                    wz += tz
                
                parent_idx = limb_info['parent']
                if parent_idx == current_idx or parent_idx >= len(limb_indices):
                    break
                current_idx = parent_idx
            
            world_positions.append((wx * cls.SCALE, wy * cls.SCALE, wz * cls.SCALE))
        
        # Collect all geometry with vertex-to-bone mapping
        all_vertices = []
        all_faces = []
        all_uvs = []
        vertex_bone_map = []  # Maps each vertex index to its owning bone index
        vertex_offset = 0
        
        for bone_idx, limb_info in enumerate(limb_indices):
            render_idx = limb_info['render']
            if render_idx >= len(model['limbs']):
                continue
            
            limb = model['limbs'][render_idx]
            
            # Get bone world position
            if bone_idx < len(world_positions):
                bx, by, bz = world_positions[bone_idx]
            else:
                bx, by, bz = 0, 0, 0
            
            # Add vertices transformed to world space
            for vx, vy, vz in limb['vertices']:
                wx = vx * cls.SCALE + bx
                wy = vy * cls.SCALE + by
                wz = vz * cls.SCALE + bz
                all_vertices.append((wx, wy, wz))
                vertex_bone_map.append(limb_info['bone_index'])  # Track which bone owns this vertex
            
            # Add triangles
            for tri in limb['triangles']:
                i0, i1, i2 = tri['indices']
                all_faces.append([
                    vertex_offset + i0,
                    vertex_offset + i1,
                    vertex_offset + i2
                ])
                PIXEL_TO_FLOAT = 1.0 / 256.0
                PIXEL_ADJUST = 0.5 / 256.0
                for u, v in tri['uvs']:
                    all_uvs.append((
                        u * PIXEL_TO_FLOAT + PIXEL_ADJUST,
                        1.0 - (v * PIXEL_TO_FLOAT + PIXEL_ADJUST)
                    ))
            
            # Add quads (split into triangles)
            for quad in limb['quads']:
                i0, i1, i2, i3 = quad['indices']
                # First triangle
                all_faces.append([
                    vertex_offset + i0,
                    vertex_offset + i1,
                    vertex_offset + i2
                ])
                # Second triangle
                all_faces.append([
                    vertex_offset + i0,
                    vertex_offset + i2,
                    vertex_offset + i3
                ])
                # UVs for both triangles
                u0, v0 = quad['uvs'][0]
                u1, v1 = quad['uvs'][1]
                u2, v2 = quad['uvs'][2]
                u3, v3 = quad['uvs'][3]
                all_uvs.extend([
                    (u0 / 255.0, 1.0 - v0 / 255.0),
                    (u1 / 255.0, 1.0 - v1 / 255.0),
                    (u2 / 255.0, 1.0 - v2 / 255.0),
                ])
                all_uvs.extend([
                    (u0 / 255.0, 1.0 - v0 / 255.0),
                    (u2 / 255.0, 1.0 - v2 / 255.0),
                    (u3 / 255.0, 1.0 - v3 / 255.0),
                ])
            
            vertex_offset += len(limb['vertices'])
        
        if not all_vertices or not all_faces:
            cmds.warning("No geometry to create")
            return None
        
        # Create mesh using polyCreateFacet for each face, then combine
        mesh_name = cmds.createNode('mesh', name=f'{name}Shape')
        mesh_transform = cmds.listRelatives(mesh_name, parent=True)[0]
        mesh_transform = cmds.rename(mesh_transform, name)
        
        # Build mesh data
        num_verts = len(all_vertices)
        num_faces = len(all_faces)
        
        # Create vertex positions
        points = []
        for v in all_vertices:
            points.extend(v)
        
        # Create face connects and counts
        face_connects = []
        face_counts = []
        for face in all_faces:
            face_counts.append(len(face))
            face_connects.extend(face)
        
        # Use MEL to create the mesh (more reliable for complex meshes)
        cmds.select(clear=True)
        temp_meshes = []
        
        for face in all_faces:
            verts = [all_vertices[i] for i in face]
            try:
                facet = cmds.polyCreateFacet(point=verts, constructionHistory=False)
                if facet:
                    temp_meshes.append(facet[0])
            except:
                continue
        
        if temp_meshes:
            if len(temp_meshes) > 1:
                result = cmds.polyUnite(temp_meshes, constructionHistory=False, name=name)
                mesh_transform = result[0]
            else:
                mesh_transform = cmds.rename(temp_meshes[0], name)
            
            cmds.delete(mesh_transform, constructionHistory=True)
            cmds.select(clear=True)
            return (mesh_transform, vertex_bone_map)
        
        return None
    
    @classmethod
    def _create_skeleton(cls, model, name):
        """Create Maya skeleton from EBD model data."""
        limb_indices = model.get('limb_indices', [])
        bone_translations = model.get('bone_translations', [])
        
        if not limb_indices:
            return []
        
        # Compute world positions
        world_positions = []
        for i in range(len(limb_indices)):
            wx, wy, wz = 0, 0, 0
            current_idx = i
            visited = set()
            
            while current_idx < len(limb_indices) and current_idx not in visited:
                visited.add(current_idx)
                limb_info = limb_indices[current_idx]
                bone_idx = limb_info['bone_index']
                
                if bone_idx < len(bone_translations):
                    tx, ty, tz = bone_translations[bone_idx]
                    wx += tx
                    wy += ty
                    wz += tz
                
                parent_idx = limb_info['parent']
                if parent_idx == current_idx or parent_idx >= len(limb_indices):
                    break
                current_idx = parent_idx
            
            world_positions.append((wx * cls.SCALE, wy * cls.SCALE, wz * cls.SCALE))
        
        # Create joints
        joint_map = {}
        cmds.select(clear=True)
        
        for i, limb_info in enumerate(limb_indices):
            bone_idx = limb_info['bone_index']  # The actual bone index
            
            # Only create a joint if this is a Structural Bone (Index == Weight ID)
            # If Index != Weight ID, this is just extra geometry for an existing bone
            # This filters out "multiple chest bones" (19, 20, 21) which map to Bone 0
            if i != bone_idx:
                continue
                
            parent_idx = limb_info['parent']
            render_idx = limb_info['render']
            
            # Determine if root
            is_root = parent_idx == i or parent_idx >= len(limb_indices)
            
            # Additional cycle check: Parent cannot be SELF
            if parent_idx == i:
                is_root = True
            
            # Get position
            if i < len(world_positions):
                px, py, pz = world_positions[i]
            else:
                px, py, pz = 0, 0, 0
            
            # Select parent if not root
            # Parent must exist in our map
            if not is_root and parent_idx in joint_map:
                cmds.select(joint_map[parent_idx])
            else:
                cmds.select(clear=True)
            
            # Create joint
            joint_name = cmds.joint(
                name=f'{name}_Bone_{i:02d}',
                position=(px, py, pz),
                absolute=True
            )
            joint_map[i] = joint_name
        
        cmds.select(clear=True)
        return joint_map
    
    @classmethod
    def _bind_skin_rigid(cls, mesh, joints, vertex_bone_map):
        """Bind mesh to skeleton with rigid weights (action figure style).
        
        Each vertex is assigned 100% weight to exactly one bone.
        No smooth blending between bones.
        """
        if not joints or not vertex_bone_map:
            return None
        
        try:
            # Create list of joint names for skinCluster
            joint_list = list(joints.values())
            
            # Create skin cluster with all joints
            skin = cmds.skinCluster(
                joint_list, mesh,
                toSelectedBones=True,
                bindMethod=0,  # Closest distance
                normalizeWeights=1,
                weightDistribution=0,
                maximumInfluences=1,  # Only 1 bone per vertex
                obeyMaxInfluences=True,
                name=f"{mesh}_skinCluster"
            )[0]
            
            # Get vertex count
            vertex_count = cmds.polyEvaluate(mesh, vertex=True)
            
            # Set rigid weights: 100% to owning bone, 0% to all others
            for vtx_idx in range(min(vertex_count, len(vertex_bone_map))):
                bone_weight_id = vertex_bone_map[vtx_idx]
                if bone_weight_id in joints:
                    # Set this vertex to 100% weight on its owning joint
                    vtx = f"{mesh}.vtx[{vtx_idx}]"
                    cmds.skinPercent(
                        skin, vtx,
                        transformValue=(joints[bone_weight_id], 1.0),
                        normalize=True
                    )
            
            return skin
            
        except Exception as e:
            cmds.warning(f"Failed to bind skin: {e}")
            return None
