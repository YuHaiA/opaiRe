# Server2 Mihomo fixed egress pool

Local-style subscription console for Server2, same UX as `mihomo共享代理`.

## URLs

- Simple panel: `https://tupai.cyou/mihomo/`
- Advanced UI: `https://tupai.cyou/mihomo/ui/`
- Legacy shared proxy: `http://127.0.0.1:7890`
- Fixed Sub2API egresses: `http://172.20.0.1:7901` through `http://172.20.0.1:7910`
- Controller (localhost only): `127.0.0.1:9090`

## Layout

- Core: `/opt/sub2-mihomo` + `sub2-mihomo.service`
- Panel: `manager.py` + `web/` + `sub2-mihomo-panel.service` on `127.0.0.1:19099`
- Provider file: `providers/subscription.yaml`
- Source text: `state/subscription.txt`

## Install / refresh panel

```bash
# from a synced copy of deploy/sub2-mihomo on the server
bash install-panel.sh
```

## Use

1. Open `https://tupai.cyou/mihomo/`
2. Paste one or more Clash/Meta subscription URLs, multi-line `http://` / `https://` proxy links, V2Ray share links, or mix these sources together
3. Click **保存并导入** (or **更新现有订阅**)
4. Pick node in the list if needed

## Fixed pool behavior

- The pool is always exactly 10 egresses. It never creates an 11th port or Mihomo process.
- Each fixed port owns an independent `EGRESS-01` through `EGRESS-10` select group.
- Subscription refresh updates the available node pool and preserves the fixed ports.
- Nodes are tested against the Grok and OpenAI quality targets on a configurable schedule. Failed active nodes are replaced immediately.
- The manager probes the real public IP through each fixed port and keeps all 10 active exit IPs unique, even when different subscription node names share one upstream IP.
- Manual switching, scheduled rotation, and health repair skip recently used nodes and public IPs for the configurable reuse cooldown; account proxy bindings remain stable.
- Rotation source mode can use subscription nodes only, directly imported HTTP/HTTPS nodes only, or both pools in compatible mode.
- Scheduled rotation can be enabled or disabled independently from its interval.
- The account capacity per egress is configurable from 1 to 20 and is applied immediately by the account reconciler.
- Remaining managed Grok accounts are marked as standby and are promoted when an online account becomes unavailable.
- `extra.mihomo_pool_managed` distinguishes pool-owned state from administrator-owned account state.

No Zashboard "配置后端" step is required for daily use.
