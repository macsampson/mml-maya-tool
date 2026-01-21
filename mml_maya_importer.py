#!/usr/bin/env python3
"""
MML Maya Importer - Import Mega Man Legends assets into Maya

A dockable Maya tool that extracts MML .bin archives, displays assets in a 
browser UI, and imports EBD models and TIM textures into the scene.

Usage:
    exec(open(r"o:\Desktop\MML\mml_maya_importer.py").read())
    show_mml_importer()
"""

import os
import sys
import struct
import tempfile
import re

# Add parent directory to path for imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else r"o:\Desktop\MML"
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# Maya imports
import maya.cmds as cmds
import maya.OpenMayaUI as omui

# PySide2 imports
from PySide2 import QtWidgets, QtCore, QtGui
from shiboken2 import wrapInstance

# Import existing parsers
from mml_ebd2fbx import EBDReader
from mml_tim2png import read_mml_tim, read_mml_tim_all_palettes


# =============================================================================
# BIN Archive Reader (adapted from DashEditor/Formats/BIN.py)
# =============================================================================

class MMLAsset:
    """Represents a single asset extracted from a BIN archive."""
    
    # File type constants
    TYPE_DATA = 0
    TYPE_TIM = 1
    TYPE_FONT = 3
    TYPE_CLUT = 4
    TYPE_VAB = 5
    TYPE_SEP = 8
    TYPE_TIM_CLUT_ONLY = 9
    TYPE_TIM_CLUT_PATCH = 10
    
    TYPE_NAMES = {
        0: "Data",
        1: "TIM Image",
        3: "Font",
        4: "CLUT",
        5: "VAB Sound",
        8: "SEP Sound",
        9: "TIM CLUT Only",
        10: "TIM CLUT Patch",
    }
    
    def __init__(self, path, file_type, data, size):
        self.path = path  # Original file path (e.g., "OBJ\\ENEMY\\EN00.EBD")
        self.file_type = file_type
        self.data = data  # Raw bytes
        self.size = size
        
        # Derive name and extension
        self.name = os.path.basename(path)
        self.extension = os.path.splitext(path)[1].upper()
        
    @property
    def type_name(self):
        """Human-readable type name."""
        if self.file_type == 0:
            # Data files - categorize by extension
            if self.extension in ('.EBD', '.PBD'):
                return "Model"
            elif self.extension == '.MSG':
                return "Message"
            elif self.extension == '.MDT':
                return "Map Data"
            return "Data"
        return self.TYPE_NAMES.get(self.file_type, f"Unknown ({self.file_type})")
    
    @property
    def is_importable(self):
        """Whether this asset can be imported into Maya."""
        if self.extension in ('.EBD', '.PBD'):
            return True
        if self.file_type == self.TYPE_TIM:
            return True
        return False
    
    def __repr__(self):
        return f"MMLAsset({self.name}, {self.type_name}, {self.size} bytes)"


class MMLBinReader:
    """Read and parse MML .bin archive files."""
    
    PADDING = 2048  # 0x800
    
    def __init__(self, filepath):
        self.filepath = filepath
        self.assets = []
        
        with open(filepath, 'rb') as f:
            self.data = f.read()
        
        self._parse()
    
    def _parse(self):
        """Parse all assets from the archive."""
        offset = 0
        
        while offset < len(self.data):
            # Check for archive end marker
            if self.data[offset:offset + 4] == b'\xFF\xFF\xFF\xFF':
                break
            
            # Check for valid file header (starts with "..\\" at offset 64)
            if not self.data[offset + 64:offset + 67].startswith(b"..\\"):
                offset += self.PADDING
                continue
            
            # Read file type
            file_type = struct.unpack('<I', self.data[offset:offset + 4])[0]
            
            # Read original file path
            path_bytes = self.data[offset + 67:offset + 128]
            path = path_bytes.replace(b'\x00', b'').decode('ascii', errors='ignore')
            path = path.replace('\\', '/')
            
            # Calculate file size based on type
            file_len = self._get_file_size(offset, file_type)
            
            # Align to padding
            padded_size = ((file_len // self.PADDING) + 1) * self.PADDING
            
            # Handle edge cases for alignment
            if self.data[offset + file_len + 64:offset + file_len + 67].startswith(b"..\\"):
                file_len = file_len - 1
                padded_size = ((file_len // self.PADDING) + 1) * self.PADDING
            elif not (self.data[offset + padded_size + 64:offset + padded_size + 67].startswith(b"..\\") or
                      self.data[offset + padded_size:offset + padded_size + 4].startswith(b"\xFF\xFF\xFF\xFF")):
                if file_type == 0:  # Only for data files
                    file_len = file_len + self.PADDING
                    padded_size = ((file_len // self.PADDING) + 1) * self.PADDING
            
            # Extract asset data
            asset_data = self.data[offset:offset + padded_size]
            
            # Create asset object
            asset = MMLAsset(path, file_type, asset_data, padded_size)
            self.assets.append(asset)
            
            offset += padded_size
    
    def _get_file_size(self, offset, file_type):
        """Calculate file size based on type."""
        if file_type == 1:  # TIM
            width = struct.unpack('<I', self.data[offset + 36:offset + 40])[0]
            height = struct.unpack('<I', self.data[offset + 40:offset + 44])[0]
            return width * height * 2
        elif file_type in (4, 9, 10):  # CLUT types
            width = struct.unpack('<I', self.data[offset + 20:offset + 24])[0]
            height = struct.unpack('<I', self.data[offset + 24:offset + 28])[0]
            return width * height * 2
        elif file_type == 3:  # Font
            return struct.unpack('<I', self.data[offset + 4:offset + 8])[0] + 1
        else:  # Data files
            return struct.unpack('<I', self.data[offset + 4:offset + 8])[0] + self.PADDING
    
    def get_assets_by_type(self, type_filter=None):
        """Get assets filtered by type."""
        if type_filter is None:
            return self.assets
        return [a for a in self.assets if a.type_name == type_filter]
    
    def get_asset_types(self):
        """Get list of unique asset types in archive."""
        return sorted(set(a.type_name for a in self.assets))


# =============================================================================
# Maya Import Functions
# =============================================================================

class MMLMayaImporter:
    """Import MML assets into Maya."""
    
    SCALE = 1.0 / 100.0  # Scale factor for models
    
    @classmethod
    def import_ebd(cls, asset, model_index=0):
        """Import an EBD model into Maya with action figure-style rigging.
        
        Creates separate mesh pieces per limb, each parented directly to its bone.
        This ensures truly rigid movement with no vertex blending.
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
            
            return root_group
            
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
        
        # Compute world positions for bones
        world_positions = []
        for i in range(len(limb_indices)):
            wx, wy, wz = 0, 0, 0
            current_idx = i
            visited = set()
            
            while current_idx < len(limb_indices) and current_idx not in visited:
                visited.add(current_idx)
                limb_info = limb_indices[current_idx]
                trans_idx = limb_info['translation']
                
                if trans_idx < len(bone_translations):
                    tx, ty, tz = bone_translations[trans_idx]
                    wx += tx
                    wy += ty
                    wz += tz
                
                parent_idx = limb_info['parent']
                if parent_idx == current_idx or parent_idx >= len(limb_indices):
                    break
                current_idx = parent_idx
            
            world_positions.append((wx * cls.SCALE, wy * cls.SCALE, wz * cls.SCALE))
        
        # Create root group
        root_group = cmds.group(empty=True, name=f"{name}_grp")
        
        # Create joints first
        joints = []
        cmds.select(clear=True)
        
        for i, limb_info in enumerate(limb_indices):
            parent_idx = limb_info['parent']
            render_idx = limb_info['render']
            
            # Determine if root
            is_root = parent_idx == i or parent_idx >= len(limb_indices)
            
            # Check for cycles
            if not is_root and parent_idx < len(limb_indices):
                parent_render = limb_indices[parent_idx]['render']
                if parent_render >= render_idx:
                    is_root = True
            
            # Get position
            if i < len(world_positions):
                px, py, pz = world_positions[i]
            else:
                px, py, pz = 0, 0, 0
            
            # Select parent if not root
            if not is_root and parent_idx < len(joints):
                cmds.select(joints[parent_idx])
            else:
                cmds.select(clear=True)
            
            # Create joint
            joint_name = cmds.joint(
                name=f'{name}_Bone_{i:02d}',
                position=(px, py, pz),
                absolute=True
            )
            joints.append(joint_name)
        
        cmds.select(clear=True)
        
        # Parent root joints to the group
        for i, limb_info in enumerate(limb_indices):
            parent_idx = limb_info['parent']
            is_root = parent_idx == i or parent_idx >= len(limb_indices)
            if not is_root and parent_idx < len(limb_indices):
                parent_render = limb_indices[parent_idx]['render']
                if parent_render >= limb_info['render']:
                    is_root = True
            
            if is_root:
                cmds.parent(joints[i], root_group)
        
        # Create mesh pieces for each bone and parent them
        for bone_idx, limb_info in enumerate(limb_indices):
            render_idx = limb_info['render']
            if render_idx >= len(model['limbs']):
                continue
            
            limb = model['limbs'][render_idx]
            
            if not limb['vertices']:
                continue
            
            # Get bone world position
            if bone_idx < len(world_positions):
                bx, by, bz = world_positions[bone_idx]
            else:
                bx, by, bz = 0, 0, 0
            
            # Build vertices in world space
            vertices = []
            for vx, vy, vz in limb['vertices']:
                wx = vx * cls.SCALE + bx
                wy = vy * cls.SCALE + by
                wz = vz * cls.SCALE + bz
                vertices.append((wx, wy, wz))
            
            # Collect faces
            faces = []
            for tri in limb['triangles']:
                i0, i1, i2 = tri['indices']
                faces.append([vertices[i0], vertices[i1], vertices[i2]])
            
            for quad in limb['quads']:
                i0, i1, i2, i3 = quad['indices']
                # Split quad into two triangles
                faces.append([vertices[i0], vertices[i1], vertices[i2]])
                faces.append([vertices[i0], vertices[i2], vertices[i3]])
            
            if not faces:
                continue
            
            # Create mesh piece from faces
            temp_meshes = []
            for face_verts in faces:
                try:
                    facet = cmds.polyCreateFacet(point=face_verts, constructionHistory=False)
                    if facet:
                        temp_meshes.append(facet[0])
                except:
                    continue
            
            if not temp_meshes:
                continue
            
            # Combine into single mesh for this limb
            limb_mesh_name = f"{name}_Limb_{bone_idx:02d}"
            if len(temp_meshes) > 1:
                result = cmds.polyUnite(temp_meshes, constructionHistory=False, name=limb_mesh_name)
                limb_mesh = result[0]
            else:
                limb_mesh = cmds.rename(temp_meshes[0], limb_mesh_name)
            
            cmds.delete(limb_mesh, constructionHistory=True)
            
            # Parent mesh directly to its bone
            cmds.parent(limb_mesh, joints[bone_idx])
        
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
                trans_idx = limb_info['translation']
                
                if trans_idx < len(bone_translations):
                    tx, ty, tz = bone_translations[trans_idx]
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
                vertex_bone_map.append(bone_idx)  # Track which bone owns this vertex
            
            # Add triangles
            for tri in limb['triangles']:
                i0, i1, i2 = tri['indices']
                all_faces.append([
                    vertex_offset + i0,
                    vertex_offset + i1,
                    vertex_offset + i2
                ])
                for u, v in tri['uvs']:
                    all_uvs.append((u / 255.0, 1.0 - v / 255.0))
            
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
                trans_idx = limb_info['translation']
                
                if trans_idx < len(bone_translations):
                    tx, ty, tz = bone_translations[trans_idx]
                    wx += tx
                    wy += ty
                    wz += tz
                
                parent_idx = limb_info['parent']
                if parent_idx == current_idx or parent_idx >= len(limb_indices):
                    break
                current_idx = parent_idx
            
            world_positions.append((wx * cls.SCALE, wy * cls.SCALE, wz * cls.SCALE))
        
        # Create joints
        joints = []
        cmds.select(clear=True)
        
        for i, limb_info in enumerate(limb_indices):
            parent_idx = limb_info['parent']
            render_idx = limb_info['render']
            
            # Determine if root
            is_root = parent_idx == i or parent_idx >= len(limb_indices)
            
            # Check for cycles
            if not is_root and parent_idx < len(limb_indices):
                parent_render = limb_indices[parent_idx]['render']
                if parent_render >= render_idx:
                    is_root = True
            
            # Get position
            if i < len(world_positions):
                px, py, pz = world_positions[i]
            else:
                px, py, pz = 0, 0, 0
            
            # Select parent if not root
            if not is_root and parent_idx < len(joints):
                cmds.select(joints[parent_idx])
            else:
                cmds.select(clear=True)
            
            # Create joint
            joint_name = cmds.joint(
                name=f'{name}_Bone_{i:02d}',
                position=(px, py, pz),
                absolute=True
            )
            joints.append(joint_name)
        
        cmds.select(clear=True)
        return joints
    
    @classmethod
    def _bind_skin_rigid(cls, mesh, joints, vertex_bone_map):
        """Bind mesh to skeleton with rigid weights (action figure style).
        
        Each vertex is assigned 100% weight to exactly one bone.
        No smooth blending between bones.
        """
        if not joints or not vertex_bone_map:
            return None
        
        try:
            # Create skin cluster with all joints
            skin = cmds.skinCluster(
                joints, mesh,
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
                bone_idx = vertex_bone_map[vtx_idx]
                if bone_idx < len(joints):
                    # Set this vertex to 100% weight on its owning joint
                    vtx = f"{mesh}.vtx[{vtx_idx}]"
                    cmds.skinPercent(
                        skin, vtx,
                        transformValue=(joints[bone_idx], 1.0),
                        normalize=True
                    )
            
            return skin
            
        except Exception as e:
            cmds.warning(f"Failed to bind skin: {e}")
            return None
    
    @classmethod
    def import_tim(cls, asset, palette_index=0):
        """Import a TIM texture into Maya as a material."""
        # Save asset to temp file
        temp_tim = os.path.join(tempfile.gettempdir(), asset.name)
        with open(temp_tim, 'wb') as f:
            f.write(asset.data)
        
        try:
            # Convert to PNG using existing parser
            image = read_mml_tim(temp_tim)
            
            # Save as PNG
            png_name = os.path.splitext(asset.name)[0] + '.png'
            png_path = os.path.join(tempfile.gettempdir(), png_name)
            image.save(png_path, 'PNG')
            
            # Create Maya material
            mat_name = os.path.splitext(asset.name)[0] + '_mat'
            shader = cmds.shadingNode('lambert', asShader=True, name=mat_name)
            shading_group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=f'{mat_name}SG')
            cmds.connectAttr(f'{shader}.outColor', f'{shading_group}.surfaceShader')
            
            # Create file texture
            file_node = cmds.shadingNode('file', asTexture=True, name=f'{mat_name}_file')
            place2d = cmds.shadingNode('place2dTexture', asUtility=True)
            
            # Connect place2dTexture to file
            cmds.connectAttr(f'{place2d}.coverage', f'{file_node}.coverage')
            cmds.connectAttr(f'{place2d}.translateFrame', f'{file_node}.translateFrame')
            cmds.connectAttr(f'{place2d}.rotateFrame', f'{file_node}.rotateFrame')
            cmds.connectAttr(f'{place2d}.mirrorU', f'{file_node}.mirrorU')
            cmds.connectAttr(f'{place2d}.mirrorV', f'{file_node}.mirrorV')
            cmds.connectAttr(f'{place2d}.stagger', f'{file_node}.stagger')
            cmds.connectAttr(f'{place2d}.wrapU', f'{file_node}.wrapU')
            cmds.connectAttr(f'{place2d}.wrapV', f'{file_node}.wrapV')
            cmds.connectAttr(f'{place2d}.repeatUV', f'{file_node}.repeatUV')
            cmds.connectAttr(f'{place2d}.offset', f'{file_node}.offset')
            cmds.connectAttr(f'{place2d}.rotateUV', f'{file_node}.rotateUV')
            cmds.connectAttr(f'{place2d}.noiseUV', f'{file_node}.noiseUV')
            cmds.connectAttr(f'{place2d}.vertexUvOne', f'{file_node}.vertexUvOne')
            cmds.connectAttr(f'{place2d}.vertexUvTwo', f'{file_node}.vertexUvTwo')
            cmds.connectAttr(f'{place2d}.vertexUvThree', f'{file_node}.vertexUvThree')
            cmds.connectAttr(f'{place2d}.vertexCameraOne', f'{file_node}.vertexCameraOne')
            cmds.connectAttr(f'{place2d}.outUV', f'{file_node}.uv')
            cmds.connectAttr(f'{place2d}.outUvFilterSize', f'{file_node}.uvFilterSize')
            
            # Set texture path
            cmds.setAttr(f'{file_node}.fileTextureName', png_path, type='string')
            
            # Connect to shader
            cmds.connectAttr(f'{file_node}.outColor', f'{shader}.color')
            
            return shader
            
        finally:
            # Cleanup temp TIM file
            if os.path.exists(temp_tim):
                os.remove(temp_tim)


# =============================================================================
# Wireframe Preview Widget
# =============================================================================

class WireframePreviewWidget(QtWidgets.QWidget):
    """Widget that draws a 2D wireframe preview of a model."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.vertices = []  # List of (x, y, z) tuples
        self.edges = []     # List of (v1_idx, v2_idx) tuples
        self.rotation_y = 25  # Degrees of Y rotation for perspective
        self.setStyleSheet("background-color: #1a1a1a;")
    
    def set_model_data(self, vertices, faces):
        """Set model data for preview.
        
        Args:
            vertices: List of (x, y, z) tuples
            faces: List of face index lists (triangles or quads)
        """
        self.vertices = vertices
        
        # Extract edges from faces
        edge_set = set()
        for face in faces:
            for i in range(len(face)):
                v1 = face[i]
                v2 = face[(i + 1) % len(face)]
                edge = (min(v1, v2), max(v1, v2))
                edge_set.add(edge)
        self.edges = list(edge_set)
        
        self.update()
    
    def clear(self):
        """Clear the preview."""
        self.vertices = []
        self.edges = []
        self.update()
    
    def paintEvent(self, event):
        """Draw the wireframe."""
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        
        # Background
        painter.fillRect(self.rect(), QtGui.QColor(26, 26, 26))
        
        if not self.vertices or not self.edges:
            # Draw placeholder text
            painter.setPen(QtGui.QColor(100, 100, 100))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, "Select a model to preview")
            return
        
        # Calculate bounds
        xs = [v[0] for v in self.vertices]
        ys = [v[1] for v in self.vertices]
        zs = [v[2] for v in self.vertices]
        
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        min_z, max_z = min(zs), max(zs)
        
        # Center of model
        cx = (min_x + max_x) / 2
        cy = (min_y + max_y) / 2
        cz = (min_z + max_z) / 2
        
        # Calculate scale to fit in widget
        range_x = max_x - min_x if max_x != min_x else 1
        range_y = max_y - min_y if max_y != min_y else 1
        range_z = max_z - min_z if max_z != min_z else 1
        max_range = max(range_x, range_y, range_z)
        
        padding = 20
        scale = min(self.width() - padding * 2, self.height() - padding * 2) / max_range
        
        # Apply simple rotation for 3D effect
        import math
        angle = math.radians(self.rotation_y)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        
        # Project vertices to 2D with rotation
        projected = []
        for vx, vy, vz in self.vertices:
            # Center
            x = vx - cx
            y = vy - cy
            z = vz - cz
            
            # Rotate around Y axis
            rx = x * cos_a + z * sin_a
            rz = -x * sin_a + z * cos_a
            
            # Simple orthographic projection (X, Y) with slight Z influence
            px = self.width() / 2 + rx * scale
            py = self.height() / 2 - y * scale  # Flip Y for screen coords
            
            projected.append((px, py))
        
        # Draw edges
        painter.setPen(QtGui.QPen(QtGui.QColor(100, 200, 100), 1))
        for v1, v2 in self.edges:
            if v1 < len(projected) and v2 < len(projected):
                p1 = projected[v1]
                p2 = projected[v2]
                painter.drawLine(int(p1[0]), int(p1[1]), int(p2[0]), int(p2[1]))
    
    def mousePressEvent(self, event):
        """Start drag for rotation."""
        self.last_pos = event.pos()
    
    def mouseMoveEvent(self, event):
        """Rotate model with mouse drag."""
        if hasattr(self, 'last_pos'):
            dx = event.pos().x() - self.last_pos.x()
            self.rotation_y += dx * 0.5
            self.last_pos = event.pos()
            self.update()


# =============================================================================
# Maya UI
# =============================================================================

def get_maya_main_window():
    """Get Maya's main window as a QWidget."""
    main_window_ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(main_window_ptr), QtWidgets.QWidget)


class MMLImporterUI(QtWidgets.QDialog):
    """MML Asset Importer UI for Maya."""
    
    WINDOW_TITLE = "MML Asset Importer"
    WINDOW_NAME = "mmlAssetImporterWindow"
    
    def __init__(self, parent=get_maya_main_window()):
        super().__init__(parent)
        
        self.setWindowTitle(self.WINDOW_TITLE)
        self.setObjectName(self.WINDOW_NAME)
        self.setMinimumSize(700, 700)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Window)
        
        self.bin_reader = None
        self.current_file = None
        self._ebd_cache = {}  # Cache parsed EBD data
        
        self._create_ui()
        self._create_connections()
    
    def _create_ui(self):
        """Create the UI layout."""
        main_layout = QtWidgets.QVBoxLayout(self)
        
        # File selection
        file_layout = QtWidgets.QHBoxLayout()
        self.file_edit = QtWidgets.QLineEdit()
        self.file_edit.setPlaceholderText("Select a .bin file...")
        self.browse_btn = QtWidgets.QPushButton("Browse...")
        file_layout.addWidget(self.file_edit)
        file_layout.addWidget(self.browse_btn)
        main_layout.addLayout(file_layout)
        
        # Filter
        filter_layout = QtWidgets.QHBoxLayout()
        filter_layout.addWidget(QtWidgets.QLabel("Filter:"))
        self.filter_combo = QtWidgets.QComboBox()
        self.filter_combo.addItem("All")
        filter_layout.addWidget(self.filter_combo)
        filter_layout.addStretch()
        main_layout.addLayout(filter_layout)
        
        # Splitter for tree and preview
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        
        # Asset tree
        self.asset_tree = QtWidgets.QTreeWidget()
        self.asset_tree.setHeaderLabels(["Name", "Info"])
        self.asset_tree.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.asset_tree.setColumnWidth(0, 220)
        self.asset_tree.setColumnWidth(1, 150)
        splitter.addWidget(self.asset_tree)
        
        # Right panel with preview and info
        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Wireframe preview
        preview_group = QtWidgets.QGroupBox("Model Preview (drag to rotate)")
        preview_layout = QtWidgets.QVBoxLayout(preview_group)
        self.preview_widget = WireframePreviewWidget()
        self.preview_widget.setMinimumSize(250, 250)
        preview_layout.addWidget(self.preview_widget)
        right_layout.addWidget(preview_group)
        
        # Info panel
        info_group = QtWidgets.QGroupBox("Asset Info")
        info_layout = QtWidgets.QVBoxLayout(info_group)
        self.info_label = QtWidgets.QLabel("Select an asset to view details")
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(QtCore.Qt.AlignTop)
        info_layout.addWidget(self.info_label)
        right_layout.addWidget(info_group)
        
        splitter.addWidget(right_panel)
        splitter.setSizes([350, 350])
        
        main_layout.addWidget(splitter, 1)
        
        # Import button
        self.import_btn = QtWidgets.QPushButton("Import Selected")
        self.import_btn.setEnabled(False)
        self.import_btn.setMinimumHeight(40)
        main_layout.addWidget(self.import_btn)
        
        # Status
        self.status_label = QtWidgets.QLabel("")
        main_layout.addWidget(self.status_label)
    
    def _create_connections(self):
        """Connect signals and slots."""
        self.browse_btn.clicked.connect(self._browse_file)
        self.filter_combo.currentTextChanged.connect(self._filter_assets)
        self.asset_tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.import_btn.clicked.connect(self._import_selected)
    
    def _browse_file(self):
        """Open file browser to select .bin file."""
        start_dir = os.path.dirname(self.current_file) if self.current_file else ""
        
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select MML BIN File",
            start_dir,
            "BIN Files (*.bin);;All Files (*.*)"
        )
        
        if file_path:
            self._load_file(file_path)
    
    def _load_file(self, file_path):
        """Load and parse a BIN file."""
        self.status_label.setText("Loading...")
        QtWidgets.QApplication.processEvents()
        
        try:
            self.bin_reader = MMLBinReader(file_path)
            self.current_file = file_path
            self.file_edit.setText(file_path)
            self._ebd_cache.clear()
            
            # Update filter combo
            self.filter_combo.clear()
            self.filter_combo.addItem("All")
            for type_name in self.bin_reader.get_asset_types():
                self.filter_combo.addItem(type_name)
            
            # Populate tree
            self._populate_tree()
            
            self.status_label.setText(f"Loaded {len(self.bin_reader.assets)} assets")
            
        except Exception as e:
            self.status_label.setText(f"Error: {e}")
            cmds.warning(f"Failed to load BIN file: {e}")
    
    def _get_ebd_data(self, asset):
        """Get parsed EBD data, using cache."""
        if asset.name in self._ebd_cache:
            return self._ebd_cache[asset.name]
        
        try:
            temp_path = os.path.join(tempfile.gettempdir(), asset.name)
            with open(temp_path, 'wb') as f:
                f.write(asset.data)
            ebd = EBDReader(temp_path)
            os.remove(temp_path)
            self._ebd_cache[asset.name] = ebd
            return ebd
        except:
            return None
    
    def _populate_tree(self, type_filter=None):
        """Populate the asset tree with expandable EBD models."""
        self.asset_tree.clear()
        self.preview_widget.clear()
        
        if not self.bin_reader:
            return
        
        # Group assets by type
        assets_by_type = {}
        for asset in self.bin_reader.assets:
            if type_filter and type_filter != "All" and asset.type_name != type_filter:
                continue
            
            if asset.type_name not in assets_by_type:
                assets_by_type[asset.type_name] = []
            assets_by_type[asset.type_name].append(asset)
        
        # Create tree items
        for type_name, assets in sorted(assets_by_type.items()):
            type_item = QtWidgets.QTreeWidgetItem([type_name, f"({len(assets)})"])
            type_item.setExpanded(True)
            
            for asset in sorted(assets, key=lambda a: a.name):
                # For EBD/PBD files, expand to show individual models
                if asset.extension in ('.EBD', '.PBD'):
                    ebd = self._get_ebd_data(asset)
                    if ebd and len(ebd.models) > 0:
                        # Parent item for the EBD file
                        asset_item = QtWidgets.QTreeWidgetItem([
                            asset.name,
                            f"{len(ebd.models)} model(s)"
                        ])
                        asset_item.setData(0, QtCore.Qt.UserRole, asset)
                        asset_item.setForeground(0, QtGui.QBrush(QtGui.QColor(100, 200, 100)))
                        
                        # Add child items for each model
                        for i, model in enumerate(ebd.models):
                            total_verts = sum(len(limb['vertices']) for limb in model['limbs'])
                            total_tris = sum(len(limb['triangles']) for limb in model['limbs'])
                            total_quads = sum(len(limb['quads']) for limb in model['limbs'])
                            total_faces = total_tris + total_quads * 2
                            num_bones = len(model.get('limb_indices', []))
                            
                            model_item = QtWidgets.QTreeWidgetItem([
                                f"Model {i}",
                                f"{total_verts}v, {total_faces}f, {num_bones}b"
                            ])
                            model_item.setData(0, QtCore.Qt.UserRole, asset)
                            model_item.setData(1, QtCore.Qt.UserRole, i)  # Model index
                            model_item.setForeground(0, QtGui.QBrush(QtGui.QColor(150, 220, 150)))
                            
                            asset_item.addChild(model_item)
                        
                        type_item.addChild(asset_item)
                        continue
                
                # Regular asset item
                item = QtWidgets.QTreeWidgetItem([
                    asset.name,
                    f"{asset.size:,} bytes"
                ])
                item.setData(0, QtCore.Qt.UserRole, asset)
                
                if asset.is_importable:
                    item.setForeground(0, QtGui.QBrush(QtGui.QColor(100, 200, 100)))
                else:
                    item.setForeground(0, QtGui.QBrush(QtGui.QColor(150, 150, 150)))
                
                type_item.addChild(item)
            
            self.asset_tree.addTopLevelItem(type_item)
    
    def _filter_assets(self, filter_text):
        """Filter assets by type."""
        if filter_text == "All":
            self._populate_tree()
        else:
            self._populate_tree(filter_text)
    
    def _get_model_geometry(self, asset, model_index):
        """Extract vertices and faces from a model for preview."""
        ebd = self._get_ebd_data(asset)
        if not ebd or model_index >= len(ebd.models):
            return [], []
        
        model = ebd.models[model_index]
        limb_indices = model.get('limb_indices', [])
        bone_translations = model.get('bone_translations', [])
        
        # Compute world positions
        scale = 1.0 / 100.0
        world_positions = []
        for i in range(len(limb_indices)):
            wx, wy, wz = 0, 0, 0
            current_idx = i
            visited = set()
            while current_idx < len(limb_indices) and current_idx not in visited:
                visited.add(current_idx)
                limb_info = limb_indices[current_idx]
                trans_idx = limb_info['translation']
                if trans_idx < len(bone_translations):
                    tx, ty, tz = bone_translations[trans_idx]
                    wx += tx
                    wy += ty
                    wz += tz
                parent_idx = limb_info['parent']
                if parent_idx == current_idx or parent_idx >= len(limb_indices):
                    break
                current_idx = parent_idx
            world_positions.append((wx * scale, wy * scale, wz * scale))
        
        # Collect geometry
        all_vertices = []
        all_faces = []
        vertex_offset = 0
        
        for bone_idx, limb_info in enumerate(limb_indices):
            render_idx = limb_info['render']
            if render_idx >= len(model['limbs']):
                continue
            
            limb = model['limbs'][render_idx]
            bx, by, bz = world_positions[bone_idx] if bone_idx < len(world_positions) else (0, 0, 0)
            
            for vx, vy, vz in limb['vertices']:
                all_vertices.append((vx * scale + bx, vy * scale + by, vz * scale + bz))
            
            for tri in limb['triangles']:
                i0, i1, i2 = tri['indices']
                all_faces.append([vertex_offset + i0, vertex_offset + i1, vertex_offset + i2])
            
            for quad in limb['quads']:
                i0, i1, i2, i3 = quad['indices']
                all_faces.append([vertex_offset + i0, vertex_offset + i1, vertex_offset + i2, vertex_offset + i3])
            
            vertex_offset += len(limb['vertices'])
        
        return all_vertices, all_faces
    
    def _on_selection_changed(self):
        """Handle tree selection changes."""
        selected_items = self.asset_tree.selectedItems()
        self.preview_widget.clear()
        
        if not selected_items:
            self.info_label.setText("Select an asset to view details")
            self.import_btn.setEnabled(False)
            return
        
        item = selected_items[0]
        asset = item.data(0, QtCore.Qt.UserRole)
        model_index = item.data(1, QtCore.Qt.UserRole)  # May be None for parent items
        
        if not asset:
            self.info_label.setText("Select an asset to view details")
            self.import_btn.setEnabled(False)
            return
        
        # Build info text
        if model_index is not None:
            # Specific model selected
            ebd = self._get_ebd_data(asset)
            if ebd and model_index < len(ebd.models):
                model = ebd.models[model_index]
                total_verts = sum(len(limb['vertices']) for limb in model['limbs'])
                total_tris = sum(len(limb['triangles']) for limb in model['limbs'])
                total_quads = sum(len(limb['quads']) for limb in model['limbs'])
                num_bones = len(model.get('limb_indices', []))
                
                info_text = f"<b>{asset.name} - Model {model_index}</b><br>"
                info_text += f"Vertices: {total_verts}<br>"
                info_text += f"Triangles: {total_tris}<br>"
                info_text += f"Quads: {total_quads}<br>"
                info_text += f"Bones: {num_bones}<br>"
                info_text += f"Limbs: {len(model['limbs'])}"
                
                # Show wireframe preview
                vertices, faces = self._get_model_geometry(asset, model_index)
                if vertices and faces:
                    self.preview_widget.set_model_data(vertices, faces)
            else:
                info_text = f"<b>{asset.name}</b><br>Model {model_index} not found"
        else:
            # Asset or EBD parent selected
            info_text = f"<b>{asset.name}</b><br>"
            info_text += f"Type: {asset.type_name}<br>"
            info_text += f"Size: {asset.size:,} bytes<br>"
            info_text += f"Path: {asset.path}"
            
            if asset.extension in ('.EBD', '.PBD'):
                ebd = self._get_ebd_data(asset)
                if ebd:
                    info_text += f"<br>Models: {len(ebd.models)}"
                    info_text += "<br><i>Expand to see individual models</i>"
                    
                    # Show first model in preview
                    if ebd.models:
                        vertices, faces = self._get_model_geometry(asset, 0)
                        if vertices and faces:
                            self.preview_widget.set_model_data(vertices, faces)
        
        self.info_label.setText(info_text)
        self.import_btn.setEnabled(asset.is_importable)
    
    def _import_selected(self):
        """Import selected assets into Maya."""
        selected_items = self.asset_tree.selectedItems()
        
        imported = 0
        for item in selected_items:
            asset = item.data(0, QtCore.Qt.UserRole)
            model_index = item.data(1, QtCore.Qt.UserRole)
            
            if not asset or not asset.is_importable:
                continue
            
            try:
                self.status_label.setText(f"Importing {asset.name}...")
                QtWidgets.QApplication.processEvents()
                
                if asset.extension in ('.EBD', '.PBD'):
                    # Use specific model index if selected, otherwise 0
                    idx = model_index if model_index is not None else 0
                    result = MMLMayaImporter.import_ebd(asset, idx)
                elif asset.file_type == MMLAsset.TYPE_TIM:
                    result = MMLMayaImporter.import_tim(asset)
                else:
                    continue
                
                if result:
                    imported += 1
                    
            except Exception as e:
                cmds.warning(f"Failed to import {asset.name}: {e}")
        
        self.status_label.setText(f"Imported {imported} asset(s)")


# =============================================================================
# Entry Point
# =============================================================================

_mml_importer_window = None

def show_mml_importer():
    """Show the MML Importer window."""
    global _mml_importer_window
    
    # Close existing window
    if _mml_importer_window is not None:
        try:
            _mml_importer_window.close()
            _mml_importer_window.deleteLater()
        except:
            pass
    
    # Create and show new window
    _mml_importer_window = MMLImporterUI()
    _mml_importer_window.show()
    
    return _mml_importer_window


# Run if executed directly (for testing outside Maya)
if __name__ == "__main__":
    print("This script is designed to run inside Maya.")
    print("Usage: exec(open('mml_maya_importer.py').read()); show_mml_importer()")
