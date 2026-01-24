#!/usr/bin/env python3
"""
MML Maya Importer UI

Dockable Maya window for browsing and importing MML assets.
"""

import os
import sys
import tempfile

# Add parent directory to path for imports
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if '__file__' in dir() else r"o:\Desktop\MML"
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
from mml_tim2png import read_mml_tim

# Internal imports
from mml_maya.bin_reader import MMLBinReader, MMLAsset
from mml_maya.maya_importer import MMLMayaImporter
from mml_maya.preview_widget import AssetPreviewWidget


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
        self._ebd_cache = {}
        
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
        
        # Preview
        preview_group = QtWidgets.QGroupBox("Preview")
        preview_layout = QtWidgets.QVBoxLayout(preview_group)
        self.preview_widget = AssetPreviewWidget()
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
        
        # Import Button
        self.import_btn = QtWidgets.QPushButton("Import Selected")
        self.import_btn.setMinimumHeight(40)
        self.import_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.import_btn.clicked.connect(self._import_selected)
        self.import_btn.setEnabled(False)
        right_layout.addWidget(self.import_btn)
        
        # Tools Group
        tools_group = QtWidgets.QGroupBox("Tools")
        tools_layout = QtWidgets.QVBoxLayout(tools_group)
        
        # Reset pose row
        reset_row = QtWidgets.QHBoxLayout()
        self.reset_pose_btn = QtWidgets.QPushButton("Reset Pose (Zero Rotations)")
        self.reset_pose_btn.clicked.connect(self._reset_pose)
        reset_row.addWidget(self.reset_pose_btn)
        tools_layout.addLayout(reset_row)
        
        # Animation row
        anim_row = QtWidgets.QHBoxLayout()
        anim_row.addWidget(QtWidgets.QLabel("Animation:"))
        self.anim_spin = QtWidgets.QSpinBox()
        self.anim_spin.setMinimum(0)
        self.anim_spin.setMaximum(999)
        self.anim_spin.setValue(0)
        self.anim_spin.setToolTip("Animation index to apply")
        anim_row.addWidget(self.anim_spin)
        
        self.apply_anim_btn = QtWidgets.QPushButton("Apply Animation")
        self.apply_anim_btn.clicked.connect(self._apply_animation)
        self.apply_anim_btn.setEnabled(False)
        anim_row.addWidget(self.apply_anim_btn)
        tools_layout.addLayout(anim_row)
        
        right_layout.addWidget(tools_group)
        
        self.last_import_result = None
        
        splitter.addWidget(right_panel)
        splitter.setSizes([350, 350])
        
        main_layout.addWidget(splitter, 1)
        
        # Status
        self.status_label = QtWidgets.QLabel("")
        main_layout.addWidget(self.status_label)
    
    def _create_connections(self):
        """Connect signals and slots."""
        self.browse_btn.clicked.connect(self._browse_file)
        self.filter_combo.currentTextChanged.connect(self._filter_assets)
        self.asset_tree.itemSelectionChanged.connect(self._on_selection_changed)
    
    def _reset_pose(self):
        """Reset rotation of selected objects hierarchy to zero."""
        selection = cmds.ls(selection=True)
        if not selection:
            self.status_label.setText("Select root joint/group to reset pose")
            return
            
        count = 0
        for item in selection:
            relatives = cmds.listRelatives(item, allDescendents=True, type='joint', fullPath=True) or []
            if cmds.nodeType(item) == 'joint':
                relatives.append(item)
            
            for node in relatives:
                try:
                    cmds.setAttr(f"{node}.rotate", 0, 0, 0)
                    count += 1
                except:
                    pass
        
        self.status_label.setText(f"Reset rotation for {count} joints")
    
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
            
            self.filter_combo.clear()
            self.filter_combo.addItem("All")
            for type_name in self.bin_reader.get_asset_types():
                self.filter_combo.addItem(type_name)
            
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
        
        assets_by_type = {}
        for asset in self.bin_reader.assets:
            if type_filter and type_filter != "All" and asset.type_name != type_filter:
                continue
            
            if asset.type_name not in assets_by_type:
                assets_by_type[asset.type_name] = []
            assets_by_type[asset.type_name].append(asset)
        
        for type_name, assets in sorted(assets_by_type.items()):
            type_item = QtWidgets.QTreeWidgetItem([type_name, f"({len(assets)})"])
            type_item.setExpanded(True)
            
            for asset in sorted(assets, key=lambda a: a.name):
                if asset.extension in ('.EBD', '.PBD'):
                    ebd = self._get_ebd_data(asset)
                    if ebd and len(ebd.models) > 0:
                        asset_item = QtWidgets.QTreeWidgetItem([
                            asset.name,
                            f"{len(ebd.models)} model(s)"
                        ])
                        asset_item.setData(0, QtCore.Qt.UserRole, asset)
                        asset_item.setForeground(0, QtGui.QBrush(QtGui.QColor(100, 200, 100)))
                        
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
                            model_item.setData(1, QtCore.Qt.UserRole, i)
                            model_item.setForeground(0, QtGui.QBrush(QtGui.QColor(150, 220, 150)))
                            
                            asset_item.addChild(model_item)
                        
                        type_item.addChild(asset_item)
                        continue
                
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
        model_index = item.data(1, QtCore.Qt.UserRole)
        
        if not asset:
            self.info_label.setText("Select an asset to view details")
            self.import_btn.setEnabled(False)
            return
        
        if model_index is not None:
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
                
                vertices, faces = self._get_model_geometry(asset, model_index)
                if vertices and faces:
                    self.preview_widget.set_model_data(vertices, faces)
            else:
                info_text = f"<b>{asset.name}</b><br>Model {model_index} not found"
        else:
            info_text = f"<b>{asset.name}</b><br>"
            info_text += f"Type: {asset.type_name}<br>"
            info_text += f"Size: {asset.size:,} bytes<br>"
            info_text += f"Path: {asset.path}"
            
            if asset.extension in ('.EBD', '.PBD'):
                ebd = self._get_ebd_data(asset)
                if ebd:
                    info_text += f"<br>Models: {len(ebd.models)}"
                    info_text += "<br><i>Expand to see individual models</i>"
                    
                    if ebd.models:
                        vertices, faces = self._get_model_geometry(asset, 0)
                        if vertices and faces:
                            self.preview_widget.set_model_data(vertices, faces)
            
            elif asset.file_type == MMLAsset.TYPE_TIM:
                try:
                    temp_tim = os.path.join(tempfile.gettempdir(), asset.name)
                    with open(temp_tim, 'wb') as f:
                        f.write(asset.data)
                    
                    image = read_mml_tim(temp_tim)
                    if image:
                        info_text += f"<br>Size: {image.width}x{image.height}"
                        self.preview_widget.set_texture_data(image)
                    
                    if os.path.exists(temp_tim):
                        os.remove(temp_tim)
                except Exception as e:
                    info_text += f"<br>Preview failed: {e}"
        
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
                    idx = model_index if model_index is not None else 0
                    result = MMLMayaImporter.import_ebd(asset, idx)
                    
                    if result and isinstance(result, dict):
                        self.last_import_result = result
                        num_anims = len(result.get('animations', []))
                        self.anim_spin.setMaximum(max(0, num_anims - 1))
                        self.apply_anim_btn.setEnabled(num_anims > 0)
                        if num_anims > 0:
                            self.status_label.setText(f"Imported {asset.name} ({num_anims} animations available)")
                        
                elif asset.file_type == MMLAsset.TYPE_TIM:
                    result = MMLMayaImporter.import_tim(asset)
                else:
                    continue
                
                if result:
                    imported += 1
                    
            except Exception as e:
                cmds.warning(f"Failed to import {asset.name}: {e}")
                import traceback
                traceback.print_exc()
        
        if imported > 0 and not self.status_label.text().startswith("Imported"):
            self.status_label.setText(f"Imported {imported} asset(s)")
    
    def _apply_animation(self):
        """Apply the selected animation to the last imported model."""
        if not self.last_import_result:
            cmds.warning("No model imported yet. Import an EBD model first.")
            return
        
        model_name = self.last_import_result.get('model_name')
        animations = self.last_import_result.get('animations', [])
        bone_translations = self.last_import_result.get('bone_translations', [])
        anim_index = self.anim_spin.value()
        
        if not animations:
            cmds.warning("No animations available for this model")
            return
        
        if anim_index >= len(animations):
            cmds.warning(f"Animation index {anim_index} out of range (max: {len(animations) - 1})")
            return
        
        self.status_label.setText(f"Applying animation {anim_index}...")
        QtWidgets.QApplication.processEvents()
        
        try:
            success = MMLMayaImporter.apply_animation(model_name, animations, anim_index, bone_translations=bone_translations)
            if success:
                num_frames = len(animations[anim_index].get('frames', []))
                self.status_label.setText(f"Applied animation {anim_index} ({num_frames} frames)")
            else:
                self.status_label.setText("Failed to apply animation")
        except Exception as e:
            cmds.warning(f"Animation error: {e}")
            import traceback
            traceback.print_exc()


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
