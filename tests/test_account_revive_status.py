import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import utils.db_manager as db_manager


def _create_accounts_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            password TEXT,
            token_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            push_platform VARCHAR(50) DEFAULT NULL,
            push_time VARCHAR(50) DEFAULT NULL
        )
        """
    )
    conn.commit()
    conn.close()


class AccountReviveStatusTests(unittest.TestCase):
    def test_mark_revive_failed_is_visible_and_filterable(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "data.db"
            _create_accounts_db(db_path)

            with patch.object(db_manager, "DB_PATH", str(db_path)):
                db_manager.save_account_to_db(
                    "dead@example.com",
                    "pw",
                    json.dumps({"refresh_token": "rt", "access_token": "at"}),
                )
                db_manager.save_account_to_db(
                    "alive@example.com",
                    "pw",
                    json.dumps({"refresh_token": "rt2", "access_token": "at2"}),
                )

                ok = db_manager.mark_account_revive_failed(
                    "dead@example.com", "invalid_grant", "unit_test"
                )
                failed_page = db_manager.get_accounts_page(status_filter="revive_failed")
                stats = db_manager.get_inventory_stats()

        self.assertTrue(ok)
        self.assertEqual(1, failed_page["total"])
        self.assertEqual("dead@example.com", failed_page["data"][0]["email"])
        self.assertEqual("failed", failed_page["data"][0]["revive_status"])
        self.assertEqual("invalid_grant", failed_page["data"][0]["revive_failed_reason"])
        self.assertEqual(0, failed_page["data"][0]["is_active"])
        self.assertEqual(1, stats["local"]["revive_failed"])

    def test_clear_revive_failed_removes_status_metadata(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "data.db"
            _create_accounts_db(db_path)

            with patch.object(db_manager, "DB_PATH", str(db_path)):
                db_manager.save_account_to_db(
                    "revived@example.com",
                    "pw",
                    json.dumps({"refresh_token": "rt", "access_token": "at"}),
                )
                db_manager.mark_account_revive_failed(
                    "revived@example.com", "temporary failure", "unit_test"
                )
                db_manager.clear_account_revive_failed("revived@example.com")
                page = db_manager.get_accounts_page(status_filter="revive_failed")
                token_data = db_manager.get_token_by_email("revived@example.com")

        self.assertEqual(0, page["total"])
        self.assertNotIn("revive_status", token_data)
        self.assertNotIn("revive_failed_reason", token_data)

    def test_sync_cloud_missing_marks_and_clears_local_accounts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "data.db"
            _create_accounts_db(db_path)

            with patch.object(db_manager, "DB_PATH", str(db_path)):
                db_manager.save_account_to_db(
                    "missing@example.com",
                    "pw",
                    json.dumps({"refresh_token": "rt", "access_token": "at"}),
                )
                db_manager.save_account_to_db(
                    "present@example.com",
                    "pw",
                    json.dumps({"refresh_token": "rt2", "access_token": "at2"}),
                )
                db_manager.update_account_push_info(
                    ["missing@example.com", "present@example.com"], "CPA", mode="sync"
                )

                marked = db_manager.sync_cloud_missing_accounts({
                    "CPA": ["present@example.com"],
                })
                missing_page = db_manager.get_accounts_page(status_filter="cloud_missing")
                stats = db_manager.get_inventory_stats()

                cleared = db_manager.sync_cloud_missing_accounts({
                    "CPA": ["missing@example.com", "present@example.com"],
                })
                cleared_page = db_manager.get_accounts_page(status_filter="cloud_missing")

        self.assertEqual(1, marked["marked"])
        self.assertEqual(1, missing_page["total"])
        self.assertEqual("missing@example.com", missing_page["data"][0]["email"])
        self.assertEqual("missing", missing_page["data"][0]["cloud_status"])
        self.assertEqual(["CPA"], missing_page["data"][0]["cloud_missing_platforms"])
        self.assertEqual(1, stats["local"]["cloud_missing"])
        self.assertEqual(1, cleared["cleared"])
        self.assertEqual(0, cleared_page["total"])


if __name__ == "__main__":
    unittest.main()
