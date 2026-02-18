import unittest
import struct
import sys
import os
from unittest.mock import patch, mock_open

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from parsers.ebd_reader import EBDReader

RAM_ADDR   = 0x80100000
DATA_START = 0x800


def _make_ps1_addr(file_offset):
    """Convert a file offset back to its PS1 RAM address."""
    return file_offset - DATA_START + RAM_ADDR


def _pack_ps1_addr(buf, offset, file_offset):
    """Write a PS1 RAM address (little-endian uint32) into buf at offset."""
    struct.pack_into('<I', buf, offset, _make_ps1_addr(file_offset))


def _make_base_buf(size=0x1000):
    """Minimal valid EBD header with model_count=0."""
    data = bytearray(b'\x00' * size)
    struct.pack_into('<I', data, 0x0C, RAM_ADDR)   # ram_address
    struct.pack_into('<I', data, DATA_START, 0)     # model_count = 0
    return data


def _make_reader(data):
    with patch('builtins.open', new_callable=mock_open) as m:
        m.return_value.read.return_value = bytes(data)
        return EBDReader("dummy.ebd")


# ---------------------------------------------------------------------------
# Existing tests (preserved)
# ---------------------------------------------------------------------------

class TestEBDReader(unittest.TestCase):
    def setUp(self):
        self.header_size = 0x804
        self.base_ram_addr = 0x80100000
        self.data_start = 0x800

    def _create_mock_ebd_data(self):
        data = bytearray(b'\x00' * 4096)
        struct.pack_into('<I', data, 0x00, 0)
        struct.pack_into('<I', data, 0x04, 2048)
        struct.pack_into('<I', data, 0x0C, self.base_ram_addr)
        struct.pack_into('<I', data, self.data_start, 0)
        return bytes(data)

    @patch('builtins.open', new_callable=mock_open)
    def test_init_structure(self, mock_file):
        mock_data = self._create_mock_ebd_data()
        mock_file.return_value.read.return_value = mock_data
        reader = EBDReader("dummy.ebd")
        self.assertEqual(reader.ram_address, self.base_ram_addr)
        self.assertEqual(reader.model_count, 0)

    @patch('builtins.open', new_callable=mock_open)
    def test_ps1_to_file_offset(self, mock_file):
        mock_data = self._create_mock_ebd_data()
        mock_file.return_value.read.return_value = mock_data
        reader = EBDReader("dummy.ebd")

        ps1_addr = self.base_ram_addr
        expected_offset = self.data_start
        self.assertEqual(reader.ps1_to_file_offset(ps1_addr), expected_offset)

        offset_val = 0x100
        ps1_addr = self.base_ram_addr + offset_val
        expected_offset = self.data_start + offset_val
        self.assertEqual(reader.ps1_to_file_offset(ps1_addr), expected_offset)

        self.assertIsNone(reader.ps1_to_file_offset(0x00100000))


# ---------------------------------------------------------------------------
# Binary read utilities
# ---------------------------------------------------------------------------

class TestEBDReaderBinaryUtils(unittest.TestCase):
    """Tests for read_int, read_short, read_ushort."""

    TARGET = 0x100  # Safe offset that doesn't overlap the EBD header

    def _reader_with_value(self, pack_fmt, value):
        buf = _make_base_buf()
        struct.pack_into(pack_fmt, buf, self.TARGET, value)
        return _make_reader(buf)

    def test_read_int_round_trip(self):
        reader = self._reader_with_value('<I', 0xDEADBEEF)
        self.assertEqual(reader.read_int(self.TARGET), 0xDEADBEEF)

    def test_read_int_zero(self):
        reader = _make_reader(_make_base_buf())
        self.assertEqual(reader.read_int(self.TARGET), 0)

    def test_read_short_positive(self):
        reader = self._reader_with_value('<h', 1000)
        self.assertEqual(reader.read_short(self.TARGET), 1000)

    def test_read_short_negative(self):
        reader = self._reader_with_value('<h', -500)
        self.assertEqual(reader.read_short(self.TARGET), -500)

    def test_read_short_sign_extends_high_bit(self):
        """Packing 0x8000 as unsigned and reading as signed should give -32768."""
        buf = _make_base_buf()
        struct.pack_into('<H', buf, self.TARGET, 0x8000)
        reader = _make_reader(buf)
        self.assertEqual(reader.read_short(self.TARGET), -32768)

    def test_read_ushort_max(self):
        reader = self._reader_with_value('<H', 0xFFFF)
        self.assertEqual(reader.read_ushort(self.TARGET), 0xFFFF)

    def test_read_ushort_does_not_sign_extend(self):
        """0x8000 read as unsigned must remain positive."""
        buf = _make_base_buf()
        struct.pack_into('<H', buf, self.TARGET, 0x8000)
        reader = _make_reader(buf)
        self.assertEqual(reader.read_ushort(self.TARGET), 0x8000)


# ---------------------------------------------------------------------------
# ps1_to_file_offset — additional edge cases
# ---------------------------------------------------------------------------

class TestPs1ToFileOffsetEdgeCases(unittest.TestCase):

    def setUp(self):
        self.reader = _make_reader(_make_base_buf())

    def test_zero_address_returns_none(self):
        self.assertIsNone(self.reader.ps1_to_file_offset(0))

    def test_address_at_ram_base_maps_to_data_start(self):
        self.assertEqual(self.reader.ps1_to_file_offset(RAM_ADDR), DATA_START)


# ---------------------------------------------------------------------------
# parse_limb_info
# ---------------------------------------------------------------------------

class TestParseLimbInfo(unittest.TestCase):
    """
    Limb info is a 20-byte structure.  Pointer validity is determined by
    checking whether the high byte of the stored address == 0x80.
    """

    LIMB  = 0x900   # offset for the limb info block
    VERTS = 0x960   # offset for vertex data
    TRIS  = 0x980   # offset for triangle data
    QUADS = 0x9C0   # offset for quad data

    def _buf(self):
        return _make_base_buf(0x1000)

    def _write_header(self, buf, tri=0, quad=0, vert=0, num=0, tex=0, clut=0):
        buf[self.LIMB + 0] = tri
        buf[self.LIMB + 1] = quad
        buf[self.LIMB + 2] = vert
        buf[self.LIMB + 3] = num
        struct.pack_into('<H', buf, self.LIMB + 12, tex)
        struct.pack_into('<H', buf, self.LIMB + 14, clut)

    # --- no-geometry case ---

    def test_no_geometry_returns_empty_lists(self):
        buf = self._buf()
        self._write_header(buf, num=5, tex=3, clut=7)
        result = _make_reader(buf).parse_limb_info(self.LIMB)

        self.assertEqual(result['number'], 5)
        self.assertEqual(result['texture_page'], 3)
        self.assertEqual(result['clut_page'], 7)
        self.assertEqual(result['vertices'], [])
        self.assertEqual(result['triangles'], [])
        self.assertEqual(result['quads'], [])

    # --- vertex parsing ---

    def test_vertices_y_and_z_negated(self):
        """Y and Z must be negated when stored; X is unchanged."""
        buf = self._buf()
        self._write_header(buf, vert=2)
        _pack_ps1_addr(buf, self.LIMB + 16, self.VERTS)

        # Vertex 0: raw (10, 20, 30) → expected (10, -20, -30)
        struct.pack_into('<h', buf, self.VERTS +  0, 10)
        struct.pack_into('<h', buf, self.VERTS +  2, 20)
        struct.pack_into('<h', buf, self.VERTS +  4, 30)

        # Vertex 1: raw (-5, -8, 0) → expected (-5, 8, 0)
        struct.pack_into('<h', buf, self.VERTS +  8, -5)
        struct.pack_into('<h', buf, self.VERTS + 10, -8)
        struct.pack_into('<h', buf, self.VERTS + 12,  0)

        result = _make_reader(buf).parse_limb_info(self.LIMB)

        self.assertEqual(len(result['vertices']), 2)
        self.assertEqual(result['vertices'][0], (10, -20, -30))
        self.assertEqual(result['vertices'][1], (-5,   8,   0))

    def test_invalid_vert_pointer_skipped(self):
        """Pointer whose high byte != 0x80 must not trigger vertex parsing."""
        buf = self._buf()
        self._write_header(buf, vert=1)
        struct.pack_into('<I', buf, self.LIMB + 16, 0x00001234)  # high byte ≠ 0x80
        result = _make_reader(buf).parse_limb_info(self.LIMB)
        self.assertEqual(result['vertices'], [])

    # --- triangle parsing ---

    def test_triangle_uvs_and_indices_use_dashviewer_order(self):
        """
        DashViewer reorders triangle vertices as (b, a, c) for both UVs and indices.
        Raw layout: a@[0,1], b@[2,3], c@[4,5]; ai@8, bi@9, ci@10.
        Expected output order: b, a, c → uvs=[(3,4),(1,2),(5,6)], indices=(bi,ai,ci)=(9,8,10... wait let me re-read.

        Code: uvs = [b, a, c], indices = (data[t+9], data[t+8], data[t+10]) = (bi, ai, ci)
        """
        buf = self._buf()
        self._write_header(buf, tri=1)
        _pack_ps1_addr(buf, self.LIMB + 4, self.TRIS)

        t = self.TRIS
        buf[t+0]=1; buf[t+1]=2   # a UV
        buf[t+2]=3; buf[t+3]=4   # b UV
        buf[t+4]=5; buf[t+5]=6   # c UV
        buf[t+8]=7                # ai
        buf[t+9]=8                # bi
        buf[t+10]=9               # ci

        result = _make_reader(buf).parse_limb_info(self.LIMB)

        self.assertEqual(len(result['triangles']), 1)
        tri = result['triangles'][0]
        self.assertEqual(tri['uvs'],     [(3,4), (1,2), (5,6)])   # b, a, c
        self.assertEqual(tri['indices'], (8, 7, 9))               # bi, ai, ci

    # --- quad parsing ---

    def test_quad_uvs_and_indices_use_dashviewer_order(self):
        """DashViewer reorders quad vertices as (b, a, c, d)."""
        buf = self._buf()
        self._write_header(buf, quad=1)
        _pack_ps1_addr(buf, self.LIMB + 8, self.QUADS)

        q = self.QUADS
        buf[q+0]=1;  buf[q+1]=2   # a UV
        buf[q+2]=3;  buf[q+3]=4   # b UV
        buf[q+4]=5;  buf[q+5]=6   # c UV
        buf[q+6]=7;  buf[q+7]=8   # d UV
        buf[q+8]=10; buf[q+9]=11; buf[q+10]=12; buf[q+11]=13  # ai,bi,ci,di

        result = _make_reader(buf).parse_limb_info(self.LIMB)

        self.assertEqual(len(result['quads']), 1)
        quad = result['quads'][0]
        self.assertEqual(quad['uvs'],     [(3,4), (1,2), (5,6), (7,8)])  # b,a,c,d
        self.assertEqual(quad['indices'], (11, 10, 12, 13))              # bi,ai,ci,di


# ---------------------------------------------------------------------------
# parse_animations
# ---------------------------------------------------------------------------

class TestParseAnimations(unittest.TestCase):
    """
    Memory layout used by these tests (all offsets are file offsets):

        0xA00  hierarchy block
               [0xA00] → ptr to limb_trans  (= 0xA08, marks end of anim table)
               [0xA04] → ptr to anim0 frame-ptr table (= 0xB00)

        0xB00  animation-0 frame-ptr table
               [0xB00] → ptr to frame0  (= 0xB08, marks end of frame-ptr table)
               [0xB04] → ptr to frame1  (= 0xB11)

        0xB08  frame0 data  (9 bytes)
        0xB11  frame1 data  (9 bytes)

    frame_len = 0xB11 - 0xB08 = 9
    bone_count = int((9 - 4.5) / 4.5) = 1  (one even bone → 5 bytes)
    """

    HIER    = 0xA00
    ANIM0   = 0xB00
    FRAME0  = 0xB08
    FRAME1  = 0xB11

    def _buf(self):
        return _make_base_buf(0x2000)

    def _build_structure(self, buf, frame0=None, frame1=None):
        # Hierarchy pointers
        _pack_ps1_addr(buf, self.HIER + 0, 0xA08)   # limb_trans end-marker
        _pack_ps1_addr(buf, self.HIER + 4, self.ANIM0)

        # Animation 0 frame-pointer table
        _pack_ps1_addr(buf, self.ANIM0 + 0, self.FRAME0)  # first_frame_ofs
        _pack_ps1_addr(buf, self.ANIM0 + 4, self.FRAME1)

        # Frame data
        if frame0:
            for i, b in enumerate(frame0):
                buf[self.FRAME0 + i] = b
        if frame1:
            for i, b in enumerate(frame1):
                buf[self.FRAME1 + i] = b

    # --- early-exit guards ---

    def test_none_hierarchy_returns_empty(self):
        reader = _make_reader(self._buf())
        self.assertEqual(reader.parse_animations(None, limb_count=1), [])

    def test_ps1_hierarchy_start_returns_empty(self):
        """hierarchy_start is a file offset; a PS1 address (high byte 0x80) must be rejected."""
        reader = _make_reader(self._buf())
        self.assertEqual(reader.parse_animations(0x80100000, limb_count=1), [])

    # --- zero-value frame ---

    def test_all_zero_frame_produces_zero_translation_and_rotation(self):
        buf = self._buf()
        self._build_structure(buf)  # frame bytes default to 0x00
        anims = _make_reader(buf).parse_animations(self.HIER, limb_count=1)

        self.assertEqual(len(anims), 1)
        anim = anims[0]
        self.assertEqual(anim['frame_count'], 2)
        self.assertEqual(anim['bone_count'],  1)

        frame0 = anim['frames'][0]
        self.assertEqual(frame0['root_translation'], (0, 0, 0))
        self.assertEqual(frame0['bone_rotations'],   [(0.0, 0.0, 0.0)])

    # --- maximum rotation (even bone) ---

    def test_max_rotation_even_bone_yields_360_degrees(self):
        """
        Even bone bytes [0xF0, 0xFF, 0xFF, 0xFF, 0xFF] pack all three 12-bit
        rotation fields to 0xFFF, which converts to 360.0 degrees each.

        Verification:
          rx = (ushort(0xF0,0xFF) >> 4) & 0xFFF = 0xFFF0 >> 4 = 0x0FFF ✓
          ry = ushort(0xFF,0xFF)        & 0xFFF = 0xFFFF & 0xFFF = 0xFFF ✓
          rz = (ushort(0xFF,0xFF) >> 4) & 0xFFF = 0xFFFF >> 4  = 0x0FFF ✓
        """
        buf = self._buf()
        frame1 = [0x00]*4 + [0xF0, 0xFF, 0xFF, 0xFF, 0xFF]
        self._build_structure(buf, frame1=frame1)
        anims = _make_reader(buf).parse_animations(self.HIER, limb_count=1)

        rotations = anims[0]['frames'][1]['bone_rotations']
        self.assertEqual(len(rotations), 1)
        self.assertAlmostEqual(rotations[0][0], 360.0)
        self.assertAlmostEqual(rotations[0][1], 360.0)
        self.assertAlmostEqual(rotations[0][2], 360.0)

    # --- sign extension on root translation ---

    def test_negative_root_z_sign_extended(self):
        """
        raw_z is a 12-bit value read via read_ushort(ofs+3) & 0xFFF.
        raw_z = 0x900 has bit-11 set → sign_extend_12(0x900) = -1792.

        Byte layout for root position (4 bytes, but z-ushort spans into byte 4):
          bytes[3] = 0x00, bytes[4] = 0x09
          → ushort at ofs+3 = struct.unpack('<H', b'\\x00\\x09') = 0x0900
          → raw_z = 0x900 → pos_z = -(0x800 - 0x100) = -1792

        Byte 4 (0x09) is also the low byte of the even-bone rx ushort:
          rx = (ushort(0x09, 0x00) >> 4) & 0xFFF = 0 → rot_x = 0.0 (no interference)
        """
        buf = self._buf()
        # frame1: zero root x/y, z→-1792; zero bone rotations
        frame1 = [0x00, 0x00, 0x00, 0x00, 0x09, 0x00, 0x00, 0x00, 0x00]
        self._build_structure(buf, frame1=frame1)
        anims = _make_reader(buf).parse_animations(self.HIER, limb_count=1)

        root = anims[0]['frames'][1]['root_translation']
        self.assertEqual(root[0], 0)
        self.assertEqual(root[1], 0)
        self.assertEqual(root[2], -1792)

    # --- animation metadata ---

    def test_animation_index_is_recorded(self):
        buf = self._buf()
        self._build_structure(buf)
        anims = _make_reader(buf).parse_animations(self.HIER, limb_count=1)
        self.assertEqual(anims[0]['index'], 0)

    def test_bone_count_derived_from_frame_length(self):
        """frame_len=9 → bone_count = int((9-4.5)/4.5) = 1."""
        buf = self._buf()
        self._build_structure(buf)
        anims = _make_reader(buf).parse_animations(self.HIER, limb_count=1)
        self.assertEqual(anims[0]['bone_count'], 1)


if __name__ == '__main__':
    unittest.main()
