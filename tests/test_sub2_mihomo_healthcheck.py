import importlib.util
import socket
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
HEALTHCHECK = ROOT / "deploy" / "sub2-mihomo" / "healthcheck.py"


def load_healthcheck():
    spec = importlib.util.spec_from_file_location("sub2_mihomo_healthcheck", HEALTHCHECK)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class Sub2MihomoHealthcheckTest(unittest.TestCase):
    def test_proxy_check_requires_http_response(self):
        healthcheck = load_healthcheck()
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        def respond():
            connection, _ = server.accept()
            with connection:
                connection.recv(1024)
                connection.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            server.close()

        thread = threading.Thread(target=respond, daemon=True)
        thread.start()
        healthcheck.PROXY_PORT = port
        self.assertTrue(healthcheck.proxy_ok())
        thread.join(timeout=2)

    def test_inactive_service_is_restarted_immediately(self):
        healthcheck = load_healthcheck()
        with (
            patch.object(healthcheck, "service_ok", return_value=False),
            patch.object(healthcheck, "controller_ok", return_value=False),
            patch.object(healthcheck, "proxy_ok", return_value=False),
            patch.object(healthcheck, "save_failures") as save_failures,
            patch.object(healthcheck.subprocess, "run") as run,
        ):
            self.assertEqual(healthcheck.main(), 0)

        run.assert_called_once_with(["systemctl", "restart", healthcheck.SERVICE], check=False)
        save_failures.assert_called_once_with(0)

    def test_hung_proxy_restarts_after_threshold(self):
        healthcheck = load_healthcheck()
        with (
            patch.object(healthcheck, "service_ok", return_value=True),
            patch.object(healthcheck, "controller_ok", return_value=True),
            patch.object(healthcheck, "proxy_ok", return_value=False),
            patch.object(healthcheck, "load_failures", return_value=2),
            patch.object(healthcheck, "save_failures") as save_failures,
            patch.object(healthcheck.subprocess, "run") as run,
        ):
            self.assertEqual(healthcheck.main(), 0)

        run.assert_called_once_with(["systemctl", "restart", healthcheck.SERVICE], check=False)
        self.assertEqual([call.args[0] for call in save_failures.call_args_list], [3, 0])


if __name__ == "__main__":
    unittest.main()
