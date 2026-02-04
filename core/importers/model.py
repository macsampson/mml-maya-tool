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
from MML.parsers.ebd_reader import EBDReader

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
                connects.append(int(i0))
                connects.append(int(i1))
                connects.append(int(i2))
                
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
                connects.append(int(i0))
                connects.append(int(i1))
                connects.append(int(i2))

                face_uv_counts.append(3)
                face_uv_ids.append(get_uv_idx(quad['uvs'][0][0], quad['uvs'][0][1]))
                face_uv_ids.append(get_uv_idx(quad['uvs'][1][0], quad['uvs'][1][1]))
                face_uv_ids.append(get_uv_idx(quad['uvs'][2][0], quad['uvs'][2][1]))
                
                # Triangle 2: (i0, i2, i3) with UVs (0, 2, 3)
                counts.append(int(3))
                connects.append(int(i0))
                connects.append(int(i2))
                connects.append(int(i3))
                
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
