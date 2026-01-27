#!/usr/bin/env python3
"""
MML Texture Importer
Handles loading TIM textures and creating Maya materials.
"""

import os
import tempfile
import maya.cmds as cmds
from MML.parsers.tim2png import read_mml_tim

class TextureImporter:
    """Handles parsing and importing TIM textures into Maya."""
    
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
