import os
import tempfile
import unittest
from unittest.mock import patch
from cryptography.fernet import Fernet

import state_manager

class StateManagerExtraTests(unittest.TestCase):
    def test_save_state_uses_current_fernet_and_roundtrips_unicode(self):
        with tempfile.TemporaryDirectory() as d:
            state_path = os.path.join(d, "state.enc")
            backup_path = os.path.join(d, "state.bak")
            key = Fernet.generate_key().decode()
            with patch.object(state_manager, "STATE_PATH", state_path), patch.object(state_manager, "BACKUP_PATH", backup_path), patch.object(state_manager.config, "ENCRYPTION_KEY", key):
                payload = {"trades": [], "note": "آزمایش"}
                state_manager.save_state(payload)
                loaded = state_manager.load_state()
                self.assertEqual(loaded["note"], "آزمایش")
                self.assertEqual(loaded["schema_version"], state_manager.STATE_SCHEMA_VERSION)

    def test_invalid_key_fails_explicitly(self):
        with patch.object(state_manager.config, "ENCRYPTION_KEY", "not-a-valid-fernet-key"):
            with self.assertRaises(RuntimeError):
                state_manager._get_fernet()

if __name__ == "__main__":
    unittest.main()
