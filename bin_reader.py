#!/usr/bin/env python3
"""
MML BIN Archive Reader

Classes for reading and parsing MML .bin archive files.
"""

import os
import struct


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
