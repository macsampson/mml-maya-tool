#!/usr/bin/env python3
"""
MML Texture Database

JSON-loadable database that maps models to their texture sources.
Based on the models.json from the DashViewer web app.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class TextureImageConfig:
    """Configuration for a single texture image source."""
    image_file: str  # BIN file containing image data
    image_name: str  # Internal path to TIM image
    pallet_file: str  # BIN file containing palette (CLUT)
    pallet_name: str  # Internal path to palette
    pallet_index: int = 0  # Palette index to use
    
    # Offset for compositing multiple textures
    offset_x: int = 0
    offset_y: int = 0
    
    # Source region (for partial copies)
    src_x: int = 0
    src_y: int = 0
    src_width: int = 0  # 0 = full width
    src_height: int = 0  # 0 = full height
    
    # Destination region
    dst_x: int = 0
    dst_y: int = 0
    dst_width: int = 0
    dst_height: int = 0


@dataclass 
class TextureConfig:
    """Configuration for a model's complete texture."""
    width: int = 256
    height: int = 256
    y_uv_fix: int = 0  # UV offset correction
    images: List[TextureImageConfig] = field(default_factory=list)


@dataclass
class ModelConfig:
    """Configuration for a model's metadata."""
    model_id: str
    name: str
    texture: Optional[TextureConfig] = None
    
    # Special bone indices
    head_bone: Optional[int] = None
    hand_bone: Optional[int] = None
    slice_bones: List[int] = field(default_factory=list)
    hold_bones: List[int] = field(default_factory=list)
    face_bones: List[int] = field(default_factory=list)


class TextureDatabase:
    """
    JSON-loadable database mapping models to texture sources.
    
    Example usage:
        db = TextureDatabase()
        db.load_from_json("models.json")
        config = db.get_model_config("540")  # Megaman
        if config and config.texture:
            for img in config.texture.images:
                # Load image from img.image_file / img.image_name
                # Load palette from img.pallet_file / img.pallet_name
    """
    
    def __init__(self):
        self.models: Dict[str, ModelConfig] = {}
        self._name_index: Dict[str, str] = {}  # lowercase name -> model_id
    
    def load_from_json(self, json_path: str) -> int:
        """
        Load texture database from JSON file.
        
        Args:
            json_path: Path to models.json file
            
        Returns:
            Number of models loaded
        """
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return self._parse_models_dict(data)
    
    def load_from_dict(self, data: Dict[str, Any]) -> int:
        """Load from a dictionary (already parsed JSON)."""
        return self._parse_models_dict(data)
    
    def _parse_models_dict(self, data: Dict[str, Any]) -> int:
        """Parse the models dictionary format."""
        count = 0
        
        for model_id, model_data in data.items():
            if not isinstance(model_data, dict):
                continue
                
            name = model_data.get('name', f'Model_{model_id}')
            
            # Parse texture config - handle both formats:
            # 1. 'textures' array format (simplified)
            # 2. 'texture' object format (web app's original)
            texture = None
            
            # Check for 'textures' array format (current models.json)
            textures_array = model_data.get('textures')
            if textures_array and isinstance(textures_array, list):
                # Convert 'textures' array to TextureConfig
                images = []
                for img_data in textures_array:
                    if isinstance(img_data, dict):
                        img_config = TextureImageConfig(
                            image_file=img_data.get('image_file', ''),
                            image_name=img_data.get('image_name', ''),
                            pallet_file=img_data.get('pallet_file', ''),
                            pallet_name=img_data.get('pallet_name', ''),
                            pallet_index=img_data.get('pallet_index', 0),
                            offset_x=img_data.get('offsetX', 0),
                            offset_y=img_data.get('offsetY', 0),
                            src_x=img_data.get('sx', 0),
                            src_y=img_data.get('sy', 0),
                            src_width=img_data.get('sWidth', 0),
                            src_height=img_data.get('sHeight', 0),
                            dst_x=img_data.get('dx', 0),
                            dst_y=img_data.get('dy', 0),
                            dst_width=img_data.get('dWidth', 0),
                            dst_height=img_data.get('dHeight', 0)
                        )
                        images.append(img_config)
                if images:
                    texture = TextureConfig(
                        width=256,  # Default width
                        height=256,  # Default height
                        y_uv_fix=0,
                        images=images
                    )
            
            # Check for 'texture' object format (web app's original)
            if texture is None:
                tex_data = model_data.get('texture')
                if tex_data:
                    texture = self._parse_texture_config(tex_data)
            
            # Create model config
            config = ModelConfig(
                model_id=model_id,
                name=name,
                texture=texture,
                head_bone=model_data.get('head'),
                hand_bone=model_data.get('hand'),
                slice_bones=model_data.get('slice', []),
                hold_bones=model_data.get('hold', []),
                face_bones=model_data.get('face', [])
            )
            
            self.models[model_id] = config
            self._name_index[name.lower()] = model_id
            count += 1
        
        return count
    
    def _parse_texture_config(self, tex_data: Dict[str, Any]) -> TextureConfig:
        """Parse texture configuration from JSON."""
        images = []
        
        for img_data in tex_data.get('images', []):
            img_config = TextureImageConfig(
                image_file=img_data.get('image_file', ''),
                image_name=img_data.get('image_name', ''),
                pallet_file=img_data.get('pallet_file', ''),
                pallet_name=img_data.get('pallet_name', ''),
                pallet_index=img_data.get('pallet_index', 0),
                offset_x=img_data.get('offsetX', 0),
                offset_y=img_data.get('offsetY', 0),
                src_x=img_data.get('sx', 0),
                src_y=img_data.get('sy', 0),
                src_width=img_data.get('sWidth', 0),
                src_height=img_data.get('sHeight', 0),
                dst_x=img_data.get('dx', 0),
                dst_y=img_data.get('dy', 0),
                dst_width=img_data.get('dWidth', 0),
                dst_height=img_data.get('dHeight', 0)
            )
            images.append(img_config)
        
        return TextureConfig(
            width=tex_data.get('width', 256),
            height=tex_data.get('height', 256),
            y_uv_fix=tex_data.get('y_uv_fix', 0),
            images=images
        )
    
    def get_model_config(self, model_id: str) -> Optional[ModelConfig]:
        """Get model configuration by ID (hex string like '540')."""
        return self.models.get(model_id)
    
    def get_model_by_name(self, name: str) -> Optional[ModelConfig]:
        """Get model configuration by name (case-insensitive)."""
        model_id = self._name_index.get(name.lower())
        if model_id:
            return self.models.get(model_id)
        return None
    
    def search_models(self, pattern: str) -> List[ModelConfig]:
        """Search for models by name pattern."""
        pattern = pattern.lower()
        results = []
        for model_id, config in self.models.items():
            if pattern in config.name.lower():
                results.append(config)
        return results
    
    def get_all_model_names(self) -> List[str]:
        """Get list of all model names."""
        return [m.name for m in self.models.values()]
    
    def get_model_ids(self) -> List[str]:
        """Get list of all model IDs."""
        return list(self.models.keys())


# Default database instance
_default_database: Optional[TextureDatabase] = None


def get_texture_database(json_path: str = None) -> TextureDatabase:
    """
    Get the texture database, loading from JSON if needed.
    
    Args:
        json_path: Path to models.json. If None, looks for it in default locations.
        
    Returns:
        TextureDatabase instance
    """
    global _default_database
    
    if _default_database is None:
        _default_database = TextureDatabase()
        
        if json_path is None:
            # Look for models.json in common locations
            script_dir = os.path.dirname(os.path.abspath(__file__))
            candidates = [
                os.path.join(script_dir, 'data', 'models.json'),
                os.path.join(script_dir, 'models.json'),
                os.path.join(script_dir, 'mml1-psx-master', 'public', 'ebd', 'dat', 'models.json'),
            ]
            for candidate in candidates:
                if os.path.exists(candidate):
                    json_path = candidate
                    break
        
        if json_path and os.path.exists(json_path):
            _default_database.load_from_json(json_path)
    
    return _default_database


def reset_database():
    """Reset the default database (useful for reloading)."""
    global _default_database
    _default_database = None
