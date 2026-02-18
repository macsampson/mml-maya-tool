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
        self.faces = []
        self.rotation_y = 25
        self.rotation_x = 20
        self._model_center = (0.0, 0.0, 0.0)
        self._model_diagonal = 1.0

        # Texture preview data
        self.texture_image = None  # QImage

        # Current preview mode
        self.preview_mode = self.PREVIEW_NONE

    def set_model_data(self, vertices, faces):
        """Set model data for mesh preview."""
        self.preview_mode = self.PREVIEW_MODEL
        self.vertices = vertices
        self.faces = faces
        self.texture_image = None

        # Pre-compute 3D bounding box center and diagonal.
        # The diagonal is the maximum possible projected extent in any direction at any
        # rotation angle, so using it as the scale reference keeps scale rotation-invariant.
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

        self.update()

    def set_texture_data(self, image_data):
        """Set texture data for image preview.

        Args:
            image_data: PIL Image object or bytes of PNG/image data
        """
        self.preview_mode = self.PREVIEW_TEXTURE
        self.vertices = []
        self.faces = []

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
        self.faces = []
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
        elif self.preview_mode == self.PREVIEW_MODEL and self.vertices and self.faces:
            self._draw_mesh(painter)
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

    def _draw_mesh(self, painter):
        """Draw solid shaded mesh with wireframe on front-facing faces.

        Uses painter's algorithm (back-to-front sort by average view-space Z) for
        hidden surface removal. Faces are shaded with a simple Lambertian model using
        a light fixed in view space so shading is stable across rotation.
        """
        cx, cy, cz = self._model_center

        ay = math.radians(self.rotation_y)
        ax = math.radians(self.rotation_x)
        cos_ay, sin_ay = math.cos(ay), math.sin(ay)
        cos_ax, sin_ax = math.cos(ax), math.sin(ax)

        # Scale from 3D diagonal — rotation-invariant, guaranteed no clipping.
        padding = 20
        available_w = self.width() - padding * 2
        available_h = self.height() - padding * 2
        scale = min(available_w, available_h) / self._model_diagonal

        half_w = self.width() / 2
        half_h = self.height() / 2

        # Project all vertices, storing full view-space coords for normal/depth work.
        view_coords = []   # (rx, ry2, rz2) after both rotations
        screen_pts = []    # (px, py) projected to screen

        for vx, vy, vz in self.vertices:
            x, y, z = vx - cx, vy - cy, vz - cz

            # Y-axis rotation
            rx  =  x * cos_ay + z * sin_ay
            ry  =  y
            rz  = -x * sin_ay + z * cos_ay

            # X-axis rotation
            ry2 = ry * cos_ax - rz * sin_ax
            rz2 = ry * sin_ax + rz * cos_ax

            view_coords.append((rx, ry2, rz2))
            screen_pts.append((half_w + rx * scale, half_h - ry2 * scale))

        # Light direction in view space: right, above, toward viewer.
        # Fixed in view space so shading doesn't shift as the model rotates.
        # (1, 1, 2) normalized.
        LIGHT = (0.408, 0.408, 0.816)
        AMBIENT = 0.35

        # Build per-face data: depth, 2D polygon, front-facing flag, fill gray.
        face_data = []
        n_verts = len(self.vertices)

        for face in self.faces:
            indices = [i for i in face if i < n_verts]
            if len(indices) < 3:
                continue

            verts_view = [view_coords[i] for i in indices]
            pts_2d     = [screen_pts[i]  for i in indices]

            # Average depth for painter's algorithm (larger rz2 = closer to viewer).
            avg_z = sum(v[2] for v in verts_view) / len(verts_view)

            # Face normal via cross product of first two edges (in view space).
            # The Z component of the normal directly indicates front (nz > 0) vs. back.
            v0, v1, v2 = verts_view[0], verts_view[1], verts_view[2]
            e1x = v1[0] - v0[0];  e1y = v1[1] - v0[1];  e1z = v1[2] - v0[2]
            e2x = v2[0] - v0[0];  e2y = v2[1] - v0[1];  e2z = v2[2] - v0[2]
            nx = e1y * e2z - e1z * e2y
            ny = e1z * e2x - e1x * e2z
            nz = e1x * e2y - e1y * e2x

            n_len = math.sqrt(nx * nx + ny * ny + nz * nz)
            if n_len > 0:
                nx /= n_len;  ny /= n_len;  nz /= n_len
            else:
                nz = 0.0

            front_facing = nz > 0

            # Lambertian shading: dot of normal with light direction, clamped to [0, 1].
            dot = max(0.0, nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2])
            brightness = AMBIENT + (1.0 - AMBIENT) * dot
            gray = max(20, min(210, int(brightness * 210)))

            face_data.append((avg_z, pts_2d, front_facing, gray))

        # Sort back-to-front so nearer faces paint over farther ones.
        face_data.sort(key=lambda f: f[0])

        # Pass 1 — solid fill for all faces (establishes depth ordering).
        painter.setPen(QtCore.Qt.NoPen)
        for _, pts_2d, _, gray in face_data:
            painter.setBrush(QtGui.QBrush(QtGui.QColor(gray, gray, gray)))
            painter.drawPolygon(QtGui.QPolygonF(
                [QtCore.QPointF(p[0], p[1]) for p in pts_2d]
            ))

        # Pass 2 — wireframe outline on front-facing faces only.
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setPen(QtGui.QPen(QtGui.QColor(100, 200, 100, 160), 1))
        for _, pts_2d, front_facing, _ in face_data:
            if front_facing:
                painter.drawPolygon(QtGui.QPolygonF(
                    [QtCore.QPointF(p[0], p[1]) for p in pts_2d]
                ))

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
