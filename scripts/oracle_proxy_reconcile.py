#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


SERVER3_EXPECTED_HOSTNAME = "instance-20260613-1403"
SERVER4_EXPECTED_HOSTNAME = "code"
SERVER4_SSH = "opc@10.0.0.154"
SERVER4_KEY = "/home/opc/.ssh/server4_reconcile_key"
SERVER4_EXPECTED_PRIVATE_IP = "10.0.0.154"
SERVER4_REALITY_PORT = 24444
SERVER4_TG_PORT = 18454
NLB_NAME = "server3-public-nlb"
BACKEND_SET_REALITY = "s4-tcp-24444"
BACKEND_SET_TG = "s4-tcp-18454"
OCI_CONFIG_TEMPLATE = Path("/home/opc/opaiRe/tmp/oci.txt")
OCI_KEY_PATH = Path("/home/opc/opaiRe/tmp/oci_api_key.pem")
OCI_CONFIG_PATH = Path("/home/opc/.oci/config")
NGINX_CONF = "/etc/nginx/nginx.conf"


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def run_shell(command: str) -> subprocess.CompletedProcess[str]:
    return run(["bash", "-lc", command])


def shell_quote(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"


def sudo_shell(command: str) -> subprocess.CompletedProcess[str]:
    return run_shell(f"sudo bash -lc {shell_quote(command)}")


def ssh_server4(command: str) -> subprocess.CompletedProcess[str]:
    return run(
        [
            "ssh",
            "-i",
            SERVER4_KEY,
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            SERVER4_SSH,
            command,
        ]
    )


def print_results(results: list[CheckResult]) -> int:
    failed = 0
    for item in results:
        status = "OK" if item.ok else "FAIL"
        print(f"[{status}] {item.name}: {item.detail}")
        if not item.ok:
            failed += 1
    return failed


def check_server3_host() -> CheckResult:
    res = run(["hostname"])
    text = (res.stdout or res.stderr).strip()
    return CheckResult("server3_host", SERVER3_EXPECTED_HOSTNAME in text, text)


def check_server4_host() -> CheckResult:
    res = ssh_server4("hostname")
    text = (res.stdout or res.stderr).strip()
    return CheckResult("server4_host", SERVER4_EXPECTED_HOSTNAME in text, text)


def get_server4_private_ip() -> str:
    res = ssh_server4("hostname -I 2>/dev/null || ip -4 addr show | awk '/inet /{print $2}'")
    text = (res.stdout or "").strip()
    match = re.search(r"\b10\.\d+\.\d+\.\d+\b", text)
    return match.group(0) if match else SERVER4_EXPECTED_PRIVATE_IP


def check_nginx_upstreams() -> CheckResult:
    res = sudo_shell("nginx -T")
    text = (res.stdout or "") + (res.stderr or "")
    current_ip = get_server4_private_ip()
    want = f"server {current_ip}:{SERVER4_REALITY_PORT};"
    count = text.count(want)
    return CheckResult(
        "server3_nginx_reality_upstreams",
        count >= 2,
        f"expected at least 2 upstream hits for {want}, found {count}",
    )


def apply_nginx_fix() -> CheckResult:
    current_ip = get_server4_private_ip()
    script = f"""
set -e
changed=$(python3 - <<'PY'
import re
import time
from pathlib import Path
path = Path({NGINX_CONF!r})
text = path.read_text(encoding='utf-8')
desired_ip = {current_ip!r}
updated = re.sub(r'server 10\\.\\d+\\.\\d+\\.\\d+:24444;', f'server {{desired_ip}}:24444;', text)
if updated == text:
    print('unchanged')
    raise SystemExit(0)
backup = Path(str(path) + '.bak-codex-reconcile-' + time.strftime('%Y%m%d-%H%M%S'))
backup.write_text(text, encoding='utf-8')
text = updated
path.write_text(text, encoding='utf-8')
print('changed')
PY
)
if [ "$changed" = "unchanged" ]; then
    echo "no nginx upstream drift found"
    exit 0
fi
nginx -t
systemctl reload nginx
"""
    res = sudo_shell(script)
    return CheckResult("apply_server3_nginx_fix", res.returncode == 0, (res.stdout or res.stderr).strip())


def check_subscription_domain_mode() -> CheckResult:
    res = run(["cat", "/var/www/proxy-subs/clash.yaml"])
    text = res.stdout or ""
    ok = (
        "name: server4-reality-24444" in text
        and "name: server4-reality-443" not in text
        and "server: xh-ai.cyou" in text
        and "server: 132.226.146.175" not in text
        and "server: 137.131." not in text
        and "server: 129.146." not in text
    )
    return CheckResult(
        "subscription_domain_mode",
        ok,
        "subscription should publish domain-based public entries, not old public IPs",
    )


def prepare_oci_config() -> CheckResult:
    if not OCI_CONFIG_TEMPLATE.exists():
        return CheckResult("prepare_remote_oci_config", False, f"missing template: {OCI_CONFIG_TEMPLATE}")
    if not OCI_KEY_PATH.exists():
        return CheckResult("prepare_remote_oci_config", False, f"missing key: {OCI_KEY_PATH}")
    text = OCI_CONFIG_TEMPLATE.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^key_file=.*$", f"key_file={OCI_KEY_PATH}", text)
    OCI_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    OCI_CONFIG_PATH.write_text(text, encoding="utf-8")
    os.chmod(OCI_CONFIG_PATH, 0o600)
    os.chmod(OCI_KEY_PATH, 0o600)
    return CheckResult("prepare_remote_oci_config", True, str(OCI_CONFIG_PATH))


def check_oci_sdk() -> CheckResult:
    try:
        import oci  # noqa: F401
        return CheckResult("oci_sdk_probe", True, "True")
    except Exception as exc:
        return CheckResult("oci_sdk_probe", False, str(exc))


def get_oci_client():
    import oci
    from oci.network_load_balancer import NetworkLoadBalancerClient

    config = oci.config.from_file(str(OCI_CONFIG_PATH), "DEFAULT")
    client = NetworkLoadBalancerClient(config)
    return client, config


def get_nlb_id(client, compartment_id: str) -> str | None:
    data = client.list_network_load_balancers(compartment_id=compartment_id).data
    items = list(getattr(data, "items", []) or [])
    for item in items:
        if getattr(item, "display_name", "") == NLB_NAME:
            return item.id
    return None


def list_backends(client, nlb_id: str, backend_set_name: str):
    data = client.list_backends(
        network_load_balancer_id=nlb_id,
        backend_set_name=backend_set_name,
    ).data
    return list(getattr(data, "items", []) or [])


def check_nlb_backend_expectations() -> CheckResult:
    current_ip = get_server4_private_ip()
    return CheckResult(
        "nlb_backend_expectations",
        True,
        f"server4 current private ip observed={current_ip}; target backend sets={BACKEND_SET_TG},{BACKEND_SET_REALITY}",
    )


def wait_for_backend(client, nlb_id: str, backend_set_name: str, backend_name: str, timeout_sec: int = 60) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        names = {item.name for item in list_backends(client, nlb_id, backend_set_name)}
        if backend_name in names:
            return True
        time.sleep(5)
    return False


def reconcile_backend_set(client, nlb_id: str, backend_set_name: str, desired_ip: str, port: int) -> list[str]:
    from oci.network_load_balancer.models import CreateBackendDetails

    changes: list[str] = []
    desired_name = f"{desired_ip}:{port}"
    backends = list_backends(client, nlb_id, backend_set_name)
    existing_names = {item.name for item in backends}

    if desired_name not in existing_names:
        client.create_backend(
            network_load_balancer_id=nlb_id,
            backend_set_name=backend_set_name,
            create_backend_details=CreateBackendDetails(
                ip_address=desired_ip,
                port=port,
            ),
        )
        if not wait_for_backend(client, nlb_id, backend_set_name, desired_name):
            raise RuntimeError(f"backend {desired_name} not visible after create")
        changes.append(f"created {backend_set_name}->{desired_name}")

    backends = list_backends(client, nlb_id, backend_set_name)
    stale_names = [item.name for item in backends if item.port == port and item.ip_address != desired_ip]
    for stale_name in stale_names:
        client.delete_backend(
            network_load_balancer_id=nlb_id,
            backend_set_name=backend_set_name,
            backend_name=stale_name,
        )
        changes.append(f"deleted {backend_set_name}->{stale_name}")

    return changes


def apply_nlb_fix() -> CheckResult:
    prep = prepare_oci_config()
    if not prep.ok:
        return CheckResult("apply_nlb_fix", False, prep.detail)

    try:
        client, config = get_oci_client()
        nlb_id = get_nlb_id(client, config["tenancy"])
        if not nlb_id:
            return CheckResult("apply_nlb_fix", False, f"cannot find NLB {NLB_NAME}")

        current_ip = get_server4_private_ip()
        changes: list[str] = []
        changes.extend(reconcile_backend_set(client, nlb_id, BACKEND_SET_REALITY, current_ip, SERVER4_REALITY_PORT))
        changes.extend(reconcile_backend_set(client, nlb_id, BACKEND_SET_TG, current_ip, SERVER4_TG_PORT))
        return CheckResult("apply_nlb_fix", True, "no backend drift found" if not changes else "; ".join(changes))
    except Exception as exc:
        return CheckResult("apply_nlb_fix", False, str(exc))


def install_timer() -> CheckResult:
    service_unit = """[Unit]
Description=Oracle proxy reconcile check
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/home/opc/opaiRe
ExecStart=/bin/bash -lc 'cd /home/opc/opaiRe && exec /usr/bin/python3 /home/opc/opaiRe/scripts/oracle_proxy_reconcile.py --apply-nginx-fix --apply-nlb-fix'
"""
    timer_unit = """[Unit]
Description=Run Oracle proxy reconcile periodically

[Timer]
OnBootSec=3min
OnUnitActiveSec=10min
Unit=oracle-proxy-reconcile.service
Persistent=true

[Install]
WantedBy=timers.target
"""
    script = (
        "set -e\n"
        "cat >/etc/systemd/system/oracle-proxy-reconcile.service <<'EOF'\n"
        f"{service_unit}"
        "EOF\n"
        "cat >/etc/systemd/system/oracle-proxy-reconcile.timer <<'EOF'\n"
        f"{timer_unit}"
        "EOF\n"
        "systemctl daemon-reload\n"
        "systemctl enable --now oracle-proxy-reconcile.timer\n"
        "systemctl restart oracle-proxy-reconcile.timer\n"
        "systemctl start oracle-proxy-reconcile.service\n"
        "systemctl --no-pager --full status oracle-proxy-reconcile.timer\n"
    )
    res = sudo_shell(script)
    return CheckResult("install_server3_timer", res.returncode == 0, (res.stdout or res.stderr).strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Check/fix Oracle proxy mapping drift.")
    parser.add_argument("--apply-nginx-fix", action="store_true")
    parser.add_argument("--apply-nlb-fix", action="store_true")
    parser.add_argument("--install-timer", action="store_true")
    args = parser.parse_args()

    checks = [
        check_server3_host(),
        check_server4_host(),
        check_nginx_upstreams(),
        check_subscription_domain_mode(),
        check_oci_sdk(),
        check_nlb_backend_expectations(),
    ]
    failed = print_results(checks)

    if args.apply_nginx_fix:
        print("\n[INFO] applying Server 3 nginx upstream fix...")
        fix = apply_nginx_fix()
        print_results([fix])
        if not fix.ok:
            return 2

    if args.apply_nlb_fix:
        print("\n[INFO] applying OCI NLB backend fix...")
        fix = apply_nlb_fix()
        print_results([fix])
        if not fix.ok:
            return 3

    if args.install_timer:
        print("\n[INFO] installing Server 3 systemd timer...")
        timer = install_timer()
        print_results([timer])
        if not timer.ok:
            return 4

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
