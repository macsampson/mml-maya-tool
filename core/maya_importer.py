#!/usr/bin/env python3
"""
MML Maya Importer - Core import logic

Import MML assets (EBD models, TIM textures) into Maya.
This file serves as a facade, delegating logic to specialized importer modules.
"""

import os
import sys

# Add parent directory to path for imports
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) if '__file__' in dir() else r"o:\Desktop\MML"
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# Import sub-modules
from MML.core.importers.model import ModelImporter
from MML.core.importers.animation import AnimationImporter
from MML.core.importers.texture import TextureImporter


class MMLMayaImporter:
    """Import MML assets into Maya.
    
    This class acts as a facade for ModelImporter, AnimationImporter, and TextureImporter.
    """
    
    # Scale factor for models (exposed for backward compatibility, although used internally by submodules)
    SCALE = ModelImporter.SCALE
    
    @classmethod
    def import_ebd(cls, asset, model_index=0):
        """Import an EBD model into Maya with action figure-style rigging."""
        return ModelImporter.import_ebd(asset, model_index)
    
    @classmethod
    def _create_rigged_model(cls, model, name):
        """Create model with separate mesh pieces parented to joints."""
        return ModelImporter._create_rigged_model(model, name)
        
    @classmethod
    def _create_mesh(cls, model, name, ebd):
        """Create Maya mesh from EBD model data."""
        return ModelImporter._create_mesh(model, name, ebd)
    
    @classmethod
    def _create_skeleton(cls, model, name):
        """Create Maya skeleton from EBD model data."""
        return ModelImporter._create_skeleton(model, name)
    
    @classmethod
    def _bind_skin_rigid(cls, mesh, joints, vertex_bone_map):
        """Bind mesh to skeleton with rigid weights."""
        return ModelImporter._bind_skin_rigid(mesh, joints, vertex_bone_map)
    
    @classmethod
    def import_tim(cls, asset, palette_index=0):
        """Import a TIM texture into Maya as a material."""
        return TextureImporter.import_tim(asset, palette_index)
    
    @classmethod
    def apply_animation(cls, model_name, animations, anim_index=0, fps=30.0, bone_translations=None):
        """Apply an animation to an imported model's skeleton."""
        return AnimationImporter.apply_animation(model_name, animations, anim_index, fps, bone_translations)
    
    @classmethod
    def get_animations(cls, asset):
        """Get animation data from an EBD asset without importing the model."""
        return AnimationImporter.get_animations(asset)
