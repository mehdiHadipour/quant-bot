import unittest
import os
import shutil
import tempfile
from cryptography.fernet import Fernet

import state_manager


class TestStateManager(unittest.TestCase):
    def setUp(self):
        # Never touch the real state/ directory during tests — that would
        # risk corrupting or committing test data as if it were real bot
        # state. Everything happens in a throwaway temp directory instead.
        self.tmpdir = tempfile.mkdtemp()
        self._orig_key = state_manager.config.ENCRYPTION_KEY
        state_manager.config.ENCRYPTION_KEY = Fernet.generate_key().decode()
        self._orig_state_path = state_manager.STATE_PATH
        self._orig_backup_path = state_manager.BACKUP_PATH
        state_manager.STATE_PATH = os.path.join(self.tmpdir, "state.json.enc")
        state_manager.BACKUP_PATH = os.path.join(self.tmpdir, "state.json.enc.bak")

    def tearDown(self):
        state_manager.config.ENCRYPTION_KEY = self._orig_key
        state_manager.STATE_PATH = self._orig_state_path
        state_manager.BACKUP_PATH = self._orig_backup_path
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_default_state_has_expected_keys(self):
        state = state_manager.load_state()
        self.assertIn("trades", state)
        self.assertIn("stats", state)
        for key in ("wins", "losses", "streak", "equity_r", "peak_equity_r", "max_drawdown_r"):
            self.assertIn(key, state["stats"])
        self.assertIn("symbol_cooldowns", state)
        self.assertIn("consecutive_fetch_failures", state)
        self.assertIn("last_report_date", state)

    def test_save_and_load_roundtrip(self):
        state = state_manager.load_state()
        state["stats"]["wins"] = 5
        state["trades"].append({"symbol": "BTCUSDT", "status": "open"})
        state_manager.save_state(state)

        loaded = state_manager.load_state()
        self.assertEqual(loaded["stats"]["wins"], 5)
        self.assertEqual(len(loaded["trades"]), 1)
        self.assertEqual(loaded["trades"][0]["symbol"], "BTCUSDT")

    def test_backup_recovery_when_primary_file_is_corrupted(self):
        state = state_manager.load_state()
        state["stats"]["wins"] = 7
        state_manager.save_state(state)  # first save: primary written, no backup yet

        state["stats"]["wins"] = 8
        state_manager.save_state(state)  # second save: wins=7 gets copied to backup first

        # Simulate corruption (e.g. an interrupted write) of the primary file.
        with open(state_manager.STATE_PATH, "wb") as f:
            f.write(b"this-is-not-valid-encrypted-data")

        recovered = state_manager.load_state()
        # Should silently fall back to the backup (wins=7) rather than
        # crashing or resetting all progress to zero.
        self.assertEqual(recovered["stats"]["wins"], 7)

    def test_missing_state_file_returns_clean_default(self):
        # No file exists yet at all (fresh install) — must not raise.
        state = state_manager.load_state()
        self.assertEqual(state["trades"], [])
        self.assertEqual(state["stats"]["wins"], 0)


if __name__ == "__main__":
    unittest.main()
