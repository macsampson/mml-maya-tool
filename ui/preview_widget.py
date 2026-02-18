#!/usr/bin/env python3
"""
MML Asset Preview Widget

Qt widget for displaying wireframe models and texture images.
"""

import math

from PySide2 import QtWidgets, QtCore, QtGui


class AssetPreviewWidget(QtWidgets.QWidget):
    """Widget that displays either a wireframe model or a texture image."""

    PREVIEW_NONE = 0
    PREVIEW_MODEL = 1
    PREVIEW_TEXTURE = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setStyleSheet("background-color: #1a1a1a;")

        # Model preview data
        self.vertices = []
        self.edges = []
        self.rotation_y = 25
        self.rotation_x = 20

        # Texture preview data
        self.texture_image = None  # QImage

        # Current preview mode
        self.preview_mode = self.PREVIEW_NONE

    def set_model_data(self, vertices, faces):
        """Set model data for wireframe preview."""
        self.preview_mode = self.PREVIEW_MODEL
        self.vertices = vertices
        self.texture_image = None

        # Pre-compute the 3D bounding box center and diagonal.
        # Using the diagonal as the scale reference means scale is rotation-invariant:
        # the model always fits inside the viewport at any viewing angle.
        if vertices:
            xs = [v[0] for v in vertices]
            ys = [v[1] for v in vertices]
            zs = [v[2] for v in vertices]
            self._model_center = (
                (min(xs) + max(xs)) / 2,
                (min(ys) + max(ys)) / 2,
                (min(zs) + max(zs)) / 2,
            )
            range_x = (max(xs) - min(xs)) or 1.0
            range_y = (max(ys) - min(ys)) or 1.0
            range_z = (max(zs) - min(zs)) or 1.0
            self._model_diagonal = math.sqrt(range_x**2 + range_y**2 + range_z**2)
        else:
            self._model_center = (0.0, 0.0, 0.0)
            self._model_diagonal = 1.0

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

    def set_texture_data(self, image_data):
        """Set texture data for image preview.

        Args:
            image_data: PIL Image object or bytes of PNG/image data
        """
        self.preview_mode = self.PREVIEW_TEXTURE
        self.vertices = []
        self.edges = []

        try:
            # Convert PIL Image to QImage
            if hasattr(image_data, 'tobytes'):  # PIL Image
                # Convert to RGBA
                if image_data.mode != 'RGBA':
                    image_data = image_data.convert('RGBA')

                width, height = image_data.size
                data = image_data.tobytes('raw', 'RGBA')
                self.texture_image = QtGui.QImage(
                    data, width, height,
                    QtGui.QImage.Format_RGBA8888
                ).copy()  # Copy to own the data
            else:
                self.texture_image = None
        except Exception:
            self.texture_image = None

        self.update()

    def clear(self):
        """Clear the preview."""
        self.preview_mode = self.PREVIEW_NONE
        self.vertices = []
        self.edges = []
        self.texture_image = None
        self.update()

    def paintEvent(self, event):
        """Draw the preview."""
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        # Background
        painter.fillRect(self.rect(), QtGui.QColor(26, 26, 26))

        if self.preview_mode == self.PREVIEW_TEXTURE and self.texture_image:
            self._draw_texture(painter)
        elif self.preview_mode == self.PREVIEW_MODEL and self.vertices and self.edges:
            self._draw_wireframe(painter)
        else:
            # Draw placeholder text
            painter.setPen(QtGui.QColor(100, 100, 100))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, "Select an asset to preview")

    def _draw_texture(self, painter):
        """Draw texture image scaled to fit."""
        if not self.texture_image:
            return

        img_width = self.texture_image.width()
        img_height = self.texture_image.height()

        padding = 10
        available_width = self.width() - padding * 2
        available_height = self.height() - padding * 2

        scale_x = available_width / img_width
        scale_y = available_height / img_height
        scale = min(scale_x, scale_y, 4.0)

        draw_width = int(img_width * scale)
        draw_height = int(img_height * scale)

        x = (self.width() - draw_width) // 2
        y = (self.height() - draw_height) // 2

        # Checkerboard background
        checker_size = 8
        light = QtGui.QColor(60, 60, 60)
        dark = QtGui.QColor(40, 40, 40)
        for cy in range(y, y + draw_height, checker_size):
            for cx in range(x, x + draw_width, checker_size):
                if ((cx - x) // checker_size + (cy - y) // checker_size) % 2 == 0:
                    painter.fillRect(cx, cy, checker_size, checker_size, light)
                else:
                    painter.fillRect(cx, cy, checker_size, checker_size, dark)

        scaled = self.texture_image.scaled(
            draw_width, draw_height,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation
        )
        painter.drawImage(x, y, scaled)

        painter.setPen(QtGui.QPen(QtGui.QColor(80, 80, 80), 1))
        painter.drawRect(x, y, draw_width - 1, draw_height - 1)

        painter.setPen(QtGui.QColor(150, 150, 150))
        painter.drawText(
            self.rect().adjusted(0, 0, -5, -5),
            QtCore.Qt.AlignBottom | QtCore.Qt.AlignRight,
            f"{img_width}x{img_height}"
        )

    def _draw_wireframe(self, painter):
        """Draw wireframe model with all-axis rotation and stable scaling."""
        cx, cy, cz = self._model_center

        ay = math.radians(self.rotation_y)
        ax = math.radians(self.rotation_x)
        cos_ay, sin_ay = math.cos(ay), math.sin(ay)
        cos_ax, sin_ax = math.cos(ax), math.sin(ax)

        # Scale derived from the 3D diagonal rather than the post-rotation 2D extents.
        # The diagonal is the maximum possible projected extent in any direction at any
        # rotation, so this scale is rotation-invariant — no stretching at top/bottom view.
        padding = 20
        available_w = self.width() - padding * 2
        available_h = self.height() - padding * 2
        scale = min(available_w, available_h) / self._model_diagonal

        half_w = self.width() / 2
        half_h = self.height() / 2

        projected = []
        for vx, vy, vz in self.vertices:
            x = vx - cx
            y = vy - cy
            z = vz - cz

            # Y-axis rotation
            rx = x * cos_ay + z * sin_ay
            ry = y
            rz = -x * sin_ay + z * cos_ay

            # X-axis rotation applied to Y-rotated result
            ry2 = ry * cos_ax - rz * sin_ax

            projected.append((half_w + rx * scale, half_h - ry2 * scale))

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
        """Rotate model on all axes with mouse drag."""
        if self.preview_mode == self.PREVIEW_MODEL and hasattr(self, 'last_pos'):
            dx = event.pos().x() - self.last_pos.x()
            dy = event.pos().y() - self.last_pos.y()
            self.rotation_y += dx * 0.5
            self.rotation_x += dy * 0.5
            self.last_pos = event.pos()
            self.update()
