# Server2 Mihomo (simple panel)

Local-style subscription console for Server2, same UX as `mihomo共享代理`.

## URLs

- Simple panel: `https://tupai.cyou/mihomo/`
- Advanced UI: `https://tupai.cyou/mihomo/ui/`
- Host mixed proxy: `http://127.0.0.1:7890`
- Docker mixed proxy: `http://172.20.0.1:7890`
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
2. Paste subscription URL or multi-line `vless://` / `vmess://` links
3. Click **保存并导入** (or **更新现有订阅**)
4. Pick node in the list if needed

No Zashboard "配置后端" step is required for daily use.
