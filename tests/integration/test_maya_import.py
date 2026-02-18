
import unittest
import os
import sys

# This test requires Maya's python interpreter (mayapy)
try:
    import maya.standalone
    import maya.cmds as cmds
    MAYA_AVAILABLE = True
except ImportError:
    MAYA_AVAILABLE = False

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

@unittest.skipUnless(MAYA_AVAILABLE, "Maya not available")
class TestMayaImport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        maya.standalone.initialize(name='python')
        
    def setUp(self):
        cmds.file(new=True, force=True)

    def test_import_stub(self):
        """Skeleton test to verify Maya import."""
        # TODO: Load a real EBD file or mock the importer calls
        # from MML.core.maya_importer import MMLMayaImporter
        # MMLMayaImporter.import_ebd(mock_asset)
        
        # Verify scene state
        # self.assertTrue(cmds.objExists("ExpectedNode"))
        pass

    @classmethod
    def tearDownClass(cls):
        # maya.standalone.uninitialize() # Often causes crashes if called multiple times or on exit
        pass

if __name__ == '__main__':
    unittest.main()
