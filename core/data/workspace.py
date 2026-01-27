#!/usr/bin/env python3
"""
MML Workspace Manager

Manages multiple BIN files as a unified asset source, enabling cross-file
texture lookups where image data and palette data may come from different files.
"""

import os
from typing import Dict, List, Optional, Tuple
from MML.parsers.bin_reader import MMLBinReader, MMLAsset


class MMLWorkspace:
    """
    Manages multiple BIN files as a unified asset source.
    
    Allows finding assets by their internal path across all loaded BIN files,
    which is essential for texture loading where image and palette may be
    in different files.
    """
    
    def __init__(self, data_folder: str = None):
        """
        Initialize workspace.
        
        Args:
            data_folder: Optional path to folder containing BIN files.
                         If provided, indexes all BIN files in that folder.
        """
        self.data_folder = data_folder
        self.bin_readers: Dict[str, MMLBinReader] = {}  # filename -> reader
        self.asset_index: Dict[str, Tuple[str, MMLAsset]] = {}  # path -> (bin_name, asset)
        
        if data_folder and os.path.isdir(data_folder):
            self.index_folder(data_folder)
    
    def index_folder(self, folder_path: str, pattern: str = "*.BIN") -> int:
        """
        Index all BIN files in a folder.
        
        Args:
            folder_path: Path to folder containing BIN files
            pattern: Glob pattern for files to index
            
        Returns:
            Number of files indexed
        """
        import glob
        
        self.data_folder = folder_path
        bin_files = glob.glob(os.path.join(folder_path, pattern))
        
        count = 0
        for bin_path in bin_files:
            try:
                self.add_bin_file(bin_path)
                count += 1
            except Exception as e:
                print(f"Warning: Failed to index {bin_path}: {e}")
        
        return count
    
    def add_bin_file(self, bin_path: str) -> None:
        """
        Add a single BIN file to the workspace.
        
        Args:
            bin_path: Path to BIN file
        """
        filename = os.path.basename(bin_path).upper()
        
        if filename in self.bin_readers:
            return  # Already loaded
            
        reader = MMLBinReader(bin_path)
        self.bin_readers[filename] = reader
        
        # Index assets by their internal path
        for asset in reader.assets:
            # Normalize path for lookup
            path_key = self._normalize_path(asset.path)
            if path_key not in self.asset_index:
                self.asset_index[path_key] = (filename, asset)
    
    def _normalize_path(self, path: str) -> str:
        """Normalize asset path for consistent lookups."""
        # Convert backslashes to forward slashes
        path = path.replace("\\", "/")
        # Remove leading ".." or "."
        while path.startswith("../") or path.startswith("./"):
            path = path[3:] if path.startswith("../") else path[2:]
        # Uppercase for case-insensitive matching
        return path.upper()
    
    def find_asset_by_path(self, internal_path: str) -> Optional[MMLAsset]:
        """
        Find an asset by its internal path across all loaded BIN files.
        
        Args:
            internal_path: Internal path like "..\\OBJ\\COMM\\PL0000.TIM"
            
        Returns:
            MMLAsset if found, None otherwise
        """
        path_key = self._normalize_path(internal_path)
        
        if path_key in self.asset_index:
            _, asset = self.asset_index[path_key]
            return asset
        
        return None
    
    def find_asset_in_bin(self, bin_name: str, internal_path: str) -> Optional[MMLAsset]:
        """
        Find an asset in a specific BIN file.
        
        Args:
            bin_name: Name of BIN file (e.g., "ST00_00.BIN")
            internal_path: Internal path like "..\\OBJ\\COMM\\PL0000.TIM"
            
        Returns:
            MMLAsset if found, None otherwise
        """
        bin_name = bin_name.upper()
        
        if bin_name not in self.bin_readers:
            # Try loading the file
            if self.data_folder:
                bin_path = os.path.join(self.data_folder, bin_name)
                if os.path.exists(bin_path):
                    self.add_bin_file(bin_path)
        
        if bin_name not in self.bin_readers:
            return None
        
        target_path = self._normalize_path(internal_path)
        
        for asset in self.bin_readers[bin_name].assets:
            if self._normalize_path(asset.path) == target_path:
                return asset
        
        return None
    
    def get_bin_file(self, bin_name: str) -> Optional[MMLBinReader]:
        """Get a loaded BIN reader by filename."""
        bin_name = bin_name.upper()
        
        if bin_name not in self.bin_readers and self.data_folder:
            bin_path = os.path.join(self.data_folder, bin_name)
            if os.path.exists(bin_path):
                self.add_bin_file(bin_path)
        
        return self.bin_readers.get(bin_name)
    
    def get_loaded_files(self) -> List[str]:
        """Get list of currently loaded BIN file names."""
        return sorted(self.bin_readers.keys())
    
    def get_total_assets(self) -> int:
        """Get total number of indexed assets."""
        return len(self.asset_index)
    
    def search_assets(self, pattern: str) -> List[Tuple[str, MMLAsset]]:
        """
        Search for assets matching a pattern.
        
        Args:
            pattern: Substring to search for in asset paths
            
        Returns:
            List of (bin_name, asset) tuples
        """
        pattern = pattern.upper()
        results = []
        
        for path_key, (bin_name, asset) in self.asset_index.items():
            if pattern in path_key:
                results.append((bin_name, asset))
        
        return results
