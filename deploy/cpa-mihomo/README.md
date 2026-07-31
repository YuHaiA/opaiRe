# CPA 独立 Mihomo

供 Server 1 的 CLIProxyAPI 使用，默认仅监听本机：

- 混合代理：`127.0.0.1:7898`
- 控制器：`127.0.0.1:19098`
- CPA 全局 `proxy-url`：`http://127.0.0.1:7898`
- 订阅面板：`https://kaikj.bond/mihomo/`（复用 CPA 登录会话鉴权）

`CPA-STABLE` 使用 Mihomo `fallback` 策略：固定使用第一个存活节点，只在健康检查失败时切换，并且没有 `DIRECT` 回落。注册端可继续每账号换节点，但 CPA 的长期请求不会随注册端切换。

部署时需要：

1. 将 Linux Mihomo 核心安装为 `/opt/cpa-mihomo/bin/mihomo`。
2. 将私有订阅转换后的 provider 文件放到 `/opt/cpa-mihomo/providers/subscription.yaml`，不要提交到 Git。
3. 用随机值替换 `config.yaml` 中的 `__CONTROLLER_SECRET__`。
4. 安装并启用 `cpa-mihomo.service`，确认代理可访问 xAI 后再设置 CPA 全局 `proxy-url`。

## Web 面板

- 页面与管理逻辑来自桌面 `mihomo共享代理` 的 Linux/systemd 适配版。
- `MIHOMO_PRESERVE_CONFIG=1` 保证面板只更新 `providers/subscription.yaml`，不会覆盖 `CPA-STABLE`、端口、控制器密钥或规则。
- 面板服务为 `cpa-mihomo-panel.service`，仅监听 `127.0.0.1:19099`。
- Nginx 使用 `nginx-mihomo.conf`，必须放在 `kaikj.bond` 的 HTTPS server 内并保留 `auth_request /_cliproxy_auth`。

如果要求“每个账号永久绑定注册时的同一节点”，单个共享端口无法实现；需要为账号提供独立可访问代理 URL，或为多个粘性组分配独立监听端口，再写入 auth-file 的 `proxy-url`。
