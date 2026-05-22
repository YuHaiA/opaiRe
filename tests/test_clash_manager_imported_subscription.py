import os
import tempfile
import unittest
from unittest.mock import patch

from utils.integrations import clash_manager


class ClashManagerImportedSubscriptionTests(unittest.TestCase):
    def test_resolve_imported_subscription_path_stays_inside_import_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(clash_manager, "IMPORTED_SUBSCRIPTION_DIR", temp_dir):
                path = clash_manager._resolve_imported_subscription_path("local://imported/gui/krBDPZx.yaml")
                self.assertTrue(path.startswith(os.path.abspath(temp_dir)))
                self.assertTrue(path.endswith(os.path.join("gui", "krBDPZx.yaml")))

                escaped = clash_manager._resolve_imported_subscription_path("local://imported/../../secret.txt")
                self.assertEqual("", escaped)


if __name__ == "__main__":
    unittest.main()
