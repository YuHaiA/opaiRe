# Server 1 xAI Quota Guard 定制版

当前部署版本：`0.3.33-opaire.2`，基于上游 `0.3.32`。

## 安全约束

- `quota_guard_enabled: true`
- `physical_delete_enabled: false`（默认且现网保持关闭）
- `patrol_enabled: false`
- `patrol_recheck_cooldowns: false`
- `patrol_proxy_url: http://127.0.0.1:7898`
- 未显式开启物理删除时，确认失效的 401/403 账号只能禁用，不能删除 auth 文件。

## 定制行为

- 增加“允许物理删除 401/403”危险开关，保存开启时要求确认。
- 增加 `inventory_all` 与“全部账号测活（含禁用）”按钮。
- 全量测活中：200 启用；401/403 默认禁用；402/429 保持禁用或冷却；网络、5xx 等不确定结果保持原状态。
- 巡查统计单列 `total_disabled`，禁用不写入删除历史。
- 历史冷却记录处理完成后写入 resolved 标记，避免每 15 秒重复扫描；CPA 管理请求复用单一 HTTP client/Transport。

## 构建与回滚

- 要求 Go 1.26、Linux amd64、CGO，构建模式为 `-buildmode=c-shared`。
- 目标服务器 `.1/.2` 源码、插件、配置、状态和校验和：`/opt/CLIProxyAPI/plugin-backups/20260730T142921Z-quota-guard-opaire2/`。
- 当前插件路径：`/opt/CLIProxyAPI/plugins/linux/amd64/cpa-xai-quota-guard-v0.3.33-opaire.2.so`。
- 替换版本时必须同步修改 `/opt/CLIProxyAPI/config.yaml` 中该插件的 `store.version`，否则宿主会继续筛选旧版本。
- 重启 `cliproxyapi.service` 后必须检查并启动 `cliproxy-login.service`。

首次全量结果：589 个账号全部完成，98 个 200、270 个 401、221 个 403；最终 98 启用、491 禁用、删除 0，测试前文件无缺失。
