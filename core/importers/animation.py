#!/usr/bin/env python3
"""
MML Animation Importer
Handles loading EBD animations and applying them to Maya rigs.
"""

import os
import tempfile
import maya.cmds as cmds
from MML.parsers.ebd2fbx import EBDReader

class AnimationImporter:
    """Handles parsing and applying MML animations in Maya."""
    
    SCALE = 1.0 / 100.0  # Scale factor for models
    
    @classmethod
    def apply_animation(cls, model_name, animations, anim_index=0, fps=30.0, bone_translations=None):
        """Apply an animation to an imported model's skeleton.
        
        Args:
            model_name: Base name of the model (used to find joints)
            animations: List of animation data from EBDReader
            anim_index: Which animation to apply (default 0)
            fps: Frames per second for the animation
            bone_translations: Optional list of bone rest positions (x,y,z)
        
        Returns:
            True if animation was applied, False otherwise
        """
        if not animations or anim_index >= len(animations):
            cmds.warning(f"Animation index {anim_index} out of range (have {len(animations)})")
            return False
        
        anim = animations[anim_index]
        frames = anim.get('frames', [])
        
        if not frames:
            cmds.warning("Animation has no frames")
            return False
        
        # Find all joints for this model
        joints = cmds.ls(f'{model_name}_Bone_*', type='joint')
        if not joints:
            cmds.warning(f"No joints found for model {model_name}")
            return False
        
        # Sort joints by index
        joint_dict = {}
        for joint in joints:
            # Extract bone index from name
            parts = joint.split('_Bone_')
            if len(parts) == 2:
                try:
                    idx = int(parts[1].split('|')[0])
                    joint_dict[idx] = joint
                except ValueError:
                    pass
        
        # Set playback range
        cmds.playbackOptions(
            minTime=0,
            maxTime=len(frames) - 1,
            animationStartTime=0,
            animationEndTime=len(frames) - 1
        )
        
        # Get root Y rest position
        root_rest_y = 0.0
        if bone_translations and len(bone_translations) > 0:
            root_rest_y = bone_translations[0][1] * cls.SCALE
        elif 0 in joint_dict:
            root_rest_y = cmds.getAttr(f'{joint_dict[0]}.translateY')
        
        # Apply keyframes for each frame
        for frame_idx, frame in enumerate(frames):
            # Root translation
            root_trans = frame.get('root_translation', (0, 0, 0))
            bone_rots = frame.get('bone_rotations', [])
            
            for bone_idx, joint in joint_dict.items():
                # Set Rotation Order to ZYX (5) to minimize Gimbal Lock and match game conventions
                if frame_idx == 0:
                     cmds.setAttr(f'{joint}.rotateOrder', 5)

                if bone_idx < len(bone_rots):
                    rot = bone_rots[bone_idx]
                    rx = rot[0]
                    ry = -rot[1]  # Restored negation
                    rz = -rot[2]  # Restored negation
                    
                    cmds.setKeyframe(joint, attribute='rotateX', value=rx, time=frame_idx)
                    cmds.setKeyframe(joint, attribute='rotateY', value=ry, time=frame_idx)
                    cmds.setKeyframe(joint, attribute='rotateZ', value=rz, time=frame_idx)
                
                # Root bone also gets translation
                if bone_idx == 0:
                    tx = root_trans[0] * cls.SCALE
                    # Add rest position Y to animation Y
                    ty = root_rest_y + (root_trans[1] * cls.SCALE)
                    tz = root_trans[2] * cls.SCALE
                    
                    cmds.setKeyframe(joint, attribute='translateX', value=tx, time=frame_idx)
                    cmds.setKeyframe(joint, attribute='translateY', value=ty, time=frame_idx)
                    cmds.setKeyframe(joint, attribute='translateZ', value=tz, time=frame_idx)
        
        print(f"Applied animation {anim_index} ({len(frames)} frames) to {len(joint_dict)} joints (RotateOrder: ZYX)")

        return True
    
    @classmethod
    def get_animations(cls, asset):
        """Get animation data from an EBD asset without importing the model.
        
        Args:
            asset: MMLAsset with EBD data
            
        Returns:
            List of animations, or empty list if parsing fails
        """
        temp_path = os.path.join(tempfile.gettempdir(), asset.name)
        with open(temp_path, 'wb') as f:
            f.write(asset.data)
        
        try:
            ebd = EBDReader(temp_path)
            if ebd.models:
                return ebd.models[0].get('animations', [])
            return []
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
