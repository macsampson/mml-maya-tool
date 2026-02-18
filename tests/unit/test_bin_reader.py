import unittest
import struct
import sys
import os
from unittest.mock import patch, mock_open

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from parsers.bin_reader import MMLBinReader, MMLAsset


# ---------------------------------------------------------------------------
# Existing tests (preserved)
# ---------------------------------------------------------------------------

class TestMMLBinReader(unittest.TestCase):
    def setUp(self):
        self.padding = 2048

    def _create_mock_bin_data(self):
        data = bytearray(b'\x00' * 4096)

        offset = 0
        file_type = 0
        struct.pack_into('<I', data, offset, file_type)
        file_content_size = 100
        struct.pack_into('<I', data, offset + 4, file_content_size)
        data[offset + 64:offset + 67] = b'..\\'
        path = b'TEST/DATA/MODEL.EBD'
        data[offset + 67:offset + 67 + len(path)] = path

        offset = 4096
        data.extend(b'\x00' * 4096)
        data[offset:offset+4] = b'\xFF\xFF\xFF\xFF'
        return bytes(data)

    @patch('builtins.open', new_callable=mock_open)
    def test_parse_simple_archive(self, mock_file):
        mock_data = self._create_mock_bin_data()
        mock_file.return_value.read.return_value = mock_data
        reader = MMLBinReader("dummy.bin")
        self.assertEqual(len(reader.assets), 1)
        asset = reader.assets[0]
        self.assertEqual(asset.path, "TEST/DATA/MODEL.EBD")
        self.assertEqual(asset.file_type, 0)
        self.assertTrue(asset.is_importable)

    def test_mml_asset_properties(self):
        asset = MMLAsset("OBJ\\TEST\\FILE.EBD", 0, b'data', 100)
        self.assertEqual(asset.name, "FILE.EBD")
        self.assertEqual(asset.extension, ".EBD")
        self.assertEqual(asset.type_name, "Model")

        asset_tim = MMLAsset("TEX.TIM", 1, b'data', 100)
        self.assertEqual(asset_tim.type_name, "TIM Image")
        self.assertTrue(asset_tim.is_importable)


# ---------------------------------------------------------------------------
# MMLAsset.type_name — full coverage of all type variants
# ---------------------------------------------------------------------------

class TestMMLAssetTypeName(unittest.TestCase):

    def _a(self, path, file_type):
        return MMLAsset(path, file_type, b'', 0)

    def test_ebd_is_model(self):
        self.assertEqual(self._a("FILE.EBD", 0).type_name, "Model")

    def test_pbd_is_model(self):
        self.assertEqual(self._a("FILE.PBD", 0).type_name, "Model")

    def test_msg_is_message(self):
        self.assertEqual(self._a("FILE.MSG", 0).type_name, "Message")

    def test_mdt_is_map_data(self):
        self.assertEqual(self._a("FILE.MDT", 0).type_name, "Map Data")

    def test_unknown_data_extension_falls_back_to_data(self):
        self.assertEqual(self._a("FILE.DAT", 0).type_name, "Data")

    def test_type1_tim_image(self):
        self.assertEqual(self._a("FILE.TIM", 1).type_name, "TIM Image")

    def test_type3_font(self):
        self.assertEqual(self._a("FILE.FNT", 3).type_name, "Font")

    def test_type4_clut(self):
        self.assertEqual(self._a("FILE.CLT", 4).type_name, "CLUT")

    def test_type5_vab_sound(self):
        self.assertEqual(self._a("FILE.VAB", 5).type_name, "VAB Sound")

    def test_type8_sep_sound(self):
        self.assertEqual(self._a("FILE.SEP", 8).type_name, "SEP Sound")

    def test_type9_tim_clut_only(self):
        self.assertEqual(self._a("FILE.TIM", 9).type_name, "TIM CLUT Only")

    def test_type10_tim_clut_patch(self):
        self.assertEqual(self._a("FILE.TIM", 10).type_name, "TIM CLUT Patch")

    def test_unknown_type_id_includes_id_in_string(self):
        self.assertEqual(self._a("FILE.XYZ", 99).type_name, "Unknown (99)")


# ---------------------------------------------------------------------------
# MMLAsset.is_importable
# ---------------------------------------------------------------------------

class TestMMLAssetIsImportable(unittest.TestCase):

    def _a(self, path, file_type):
        return MMLAsset(path, file_type, b'', 0)

    def test_ebd_importable(self):
        self.assertTrue(self._a("MODEL.EBD", 0).is_importable)

    def test_pbd_importable(self):
        self.assertTrue(self._a("MODEL.PBD", 0).is_importable)

    def test_tim_importable(self):
        self.assertTrue(self._a("TEX.TIM", 1).is_importable)

    def test_clut_not_importable(self):
        self.assertFalse(self._a("FILE.CLT", 4).is_importable)

    def test_vab_not_importable(self):
        self.assertFalse(self._a("FILE.VAB", 5).is_importable)

    def test_msg_not_importable(self):
        self.assertFalse(self._a("FILE.MSG", 0).is_importable)

    def test_unknown_data_type_not_importable(self):
        self.assertFalse(self._a("FILE.DAT", 0).is_importable)


# ---------------------------------------------------------------------------
# MMLAsset.__repr__
# ---------------------------------------------------------------------------

class TestMMLAssetRepr(unittest.TestCase):

    def test_repr_format(self):
        asset = MMLAsset("FOLDER/MODEL.EBD", 0, b'', 1024)
        self.assertEqual(repr(asset), "MMLAsset(MODEL.EBD, Model, 1024 bytes)")

    def test_repr_tim(self):
        asset = MMLAsset("TEX.TIM", 1, b'', 2048)
        self.assertEqual(repr(asset), "MMLAsset(TEX.TIM, TIM Image, 2048 bytes)")


# ---------------------------------------------------------------------------
# MMLBinReader.get_assets_by_type / get_asset_types
# ---------------------------------------------------------------------------

class TestMMLBinReaderFiltering(unittest.TestCase):
    """
    These methods are pure list operations — bypass __init__ and inject assets
    directly to test filtering logic in isolation from the parser.
    """

    def _reader(self, assets):
        reader = MMLBinReader.__new__(MMLBinReader)
        reader.filepath = "dummy.bin"
        reader.assets = assets
        return reader

    def _a(self, path, file_type):
        return MMLAsset(path, file_type, b'', 0)

    def test_get_assets_by_type_none_returns_all(self):
        assets = [self._a("A.EBD", 0), self._a("B.TIM", 1)]
        reader = self._reader(assets)
        self.assertEqual(reader.get_assets_by_type(None), assets)

    def test_get_assets_by_type_model_filters_correctly(self):
        model = self._a("MODEL.EBD", 0)
        tex   = self._a("TEX.TIM",   1)
        reader = self._reader([model, tex])
        self.assertEqual(reader.get_assets_by_type("Model"), [model])

    def test_get_assets_by_type_no_match_returns_empty(self):
        reader = self._reader([self._a("FILE.EBD", 0)])
        self.assertEqual(reader.get_assets_by_type("VAB Sound"), [])

    def test_get_asset_types_deduplicates_and_sorts(self):
        assets = [
            self._a("A.EBD", 0),   # "Model"
            self._a("B.EBD", 0),   # "Model" (duplicate)
            self._a("C.TIM", 1),   # "TIM Image"
            self._a("D.VAB", 5),   # "VAB Sound"
        ]
        reader = self._reader(assets)
        self.assertEqual(reader.get_asset_types(), ["Model", "TIM Image", "VAB Sound"])

    def test_get_asset_types_empty_archive(self):
        self.assertEqual(self._reader([]).get_asset_types(), [])


# ---------------------------------------------------------------------------
# Multi-asset BIN archive parsing
# ---------------------------------------------------------------------------

class TestMMLBinReaderMultiAsset(unittest.TestCase):
    """
    Build a BIN with two type-0 assets and verify both are parsed correctly.

    Padded-size for a type-0 asset with content_size=100:
      file_len  = 100 + 2048 = 2148
      padded    = ((2148 // 2048) + 1) * 2048 = 4096
    So asset 2 starts at offset 4096.
    """

    PADDING      = 2048
    CONTENT_SIZE = 100

    def _make_two_asset_bin(self):
        buf = bytearray(b'\x00' * (self.PADDING * 6))

        for idx, name in enumerate([b'ONE.EBD', b'TWO.EBD']):
            off = idx * 4096
            struct.pack_into('<I', buf, off,     0)                  # type = 0
            struct.pack_into('<I', buf, off + 4, self.CONTENT_SIZE)  # content size
            buf[off + 64:off + 67] = b'..\\'
            buf[off + 67:off + 67 + len(name)] = name

        # End marker after asset 2
        buf[8192:8196] = b'\xFF\xFF\xFF\xFF'
        return bytes(buf)

    @patch('builtins.open', new_callable=mock_open)
    def test_two_assets_both_parsed(self, mock_file):
        mock_file.return_value.read.return_value = self._make_two_asset_bin()
        reader = MMLBinReader("dummy.bin")

        self.assertEqual(len(reader.assets), 2)
        self.assertEqual(reader.assets[0].name, "ONE.EBD")
        self.assertEqual(reader.assets[1].name, "TWO.EBD")

    @patch('builtins.open', new_callable=mock_open)
    def test_two_assets_correct_types(self, mock_file):
        mock_file.return_value.read.return_value = self._make_two_asset_bin()
        reader = MMLBinReader("dummy.bin")
        self.assertTrue(all(a.file_type == 0 for a in reader.assets))


# ---------------------------------------------------------------------------
# _get_file_size — exercised indirectly via _parse for non-type-0 assets
# ---------------------------------------------------------------------------

class TestMMLBinReaderFileSizeTypes(unittest.TestCase):
    """
    _get_file_size uses different header fields depending on file_type.
    Verify that TIM (type 1) and Font (type 3) assets are parsed without error.
    """

    PADDING = 2048

    def _make_bin(self, file_type, extra_fields):
        """Generic BIN builder; extra_fields is a dict of {offset: (fmt, value)}."""
        buf = bytearray(b'\x00' * (self.PADDING * 4))
        struct.pack_into('<I', buf, 0, file_type)
        for off, (fmt, val) in extra_fields.items():
            struct.pack_into(fmt, buf, off, val)
        buf[64:67] = b'..\\'
        buf[67:74] = b'FILE.TIM'

        # Compute expected padded size and place end marker
        if file_type == 1:
            w = extra_fields[36][1]; h = extra_fields[40][1]
            file_len = w * h * 2
        elif file_type == 3:
            file_len = extra_fields[4][1] + 1
        else:
            file_len = extra_fields[4][1] + self.PADDING

        padded = ((file_len // self.PADDING) + 1) * self.PADDING
        buf[padded:padded + 4] = b'\xFF\xFF\xFF\xFF'
        return bytes(buf)

    @patch('builtins.open', new_callable=mock_open)
    def test_type1_tim_asset_parsed(self, mock_file):
        data = self._make_bin(1, {36: ('<I', 8), 40: ('<I', 8)})
        mock_file.return_value.read.return_value = data
        reader = MMLBinReader("dummy.bin")
        self.assertEqual(len(reader.assets), 1)
        self.assertEqual(reader.assets[0].file_type, 1)

    @patch('builtins.open', new_callable=mock_open)
    def test_type3_font_asset_parsed(self, mock_file):
        data = self._make_bin(3, {4: ('<I', 100)})
        mock_file.return_value.read.return_value = data
        reader = MMLBinReader("dummy.bin")
        self.assertEqual(len(reader.assets), 1)
        self.assertEqual(reader.assets[0].file_type, 3)


if __name__ == '__main__':
    unittest.main()
