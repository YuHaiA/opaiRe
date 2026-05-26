import unittest
from unittest.mock import patch

from utils.integrations import clash_manager


class ClashManagerSubscriptionAddTests(unittest.TestCase):
    def test_add_subscription_make_selected_triggers_patch_and_persists_selection(self):
        fake_config = {
            "clash_proxy_pool": {
                "sub_urls": [],
                "sub_url": "",
                "selected_subscription_id": "",
            }
        }
        saved_config = {}

        def fake_reload_all_configs(new_config_dict=None):
            saved_config["value"] = new_config_dict

        with patch.object(clash_manager, "_read_runtime_config", return_value=fake_config), \
                patch.object(clash_manager, "patch_and_update", return_value=(True, "ok")) as patch_update, \
                patch.object(clash_manager.cfg, "reload_all_configs", side_effect=fake_reload_all_configs):
            ok, msg = clash_manager.add_subscription("资源", "https://example.com/sub.yaml", make_selected=True)

        self.assertTrue(ok)
        self.assertIn("已添加并已同步", msg)
        patch_update.assert_called_once()
        self.assertEqual("https://example.com/sub.yaml", patch_update.call_args.args[0])
        self.assertEqual("all", patch_update.call_args.args[1])
        self.assertTrue(patch_update.call_args.args[2])
        clash_conf = saved_config["value"]["clash_proxy_pool"]
        self.assertEqual("https://example.com/sub.yaml", clash_conf["sub_url"])
        self.assertEqual(clash_conf["selected_subscription_id"], clash_conf["sub_urls"][0]["id"])
        self.assertEqual("资源", clash_conf["sub_urls"][0]["name"])


if __name__ == "__main__":
    unittest.main()
