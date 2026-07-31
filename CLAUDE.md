# CLAUDE.md

opaiRe 项目的持久上下文。详细现场以 `.codex/docs/` 和远端为准，本文件只保留每次会话都该记住的稳定事实与约定。

## 项目概述

- opaiRe 是一个注册管理系统：单页 Web 控制台 + Python 后端。
- 核心职责：注册流程控制、邮箱 / OTP 资源、账号库存、云仓维护、代理 / Mihomo 运维、通知、团队 / 管理操作。
- 仓库同时携带用户部署与代理基础设施的私有 Codex 运维记录。

## 目录结构

- 主启动器：`wfxl_openai_regst.py`
- 前端入口：`index.html`；前端资源：`static/css/`、`static/js/`
- 后端路由：`routers/`
- 共享工具与集成：`utils/`
- 运行数据与配置：`data/`
- 测试：`tests/`
- 部署资产：`deploy/`、`Dockerfile`、`docker-compose*.yml`
- 长期维护摘要：`SYSTEM.md`
- 私有 Codex 运维记录：`.codex/docs/`

## 权威文档与优先级

1. `SYSTEM.md` — 长期架构与服务器事实。
2. `.codex/docs/oracle-proxy-current.md` — 当前 Server 3 / Server 4 / NLB / Reality / TG 权威状态。
3. `.codex/docs/maintenance-history.md` — 压缩后的历史运维记录。
4. `.codex/docs/new-computer-handoff.md` — 新机接手最小清单。
5. `.codex/server-records.md` — 仅历史索引，永远不高于上面两份权威文档。

排障时以远端现场为准，文档只作方向索引。

## 硬规则

- 绝不在文档 / 记忆里保存 secret、raw proxy link、Token、Cookie、密码、私钥、UUID、Reality 公钥、short ID、数据库内容或完整订阅。
- 不假设本地配置等于服务器运行态；先核实远端 `data/config.yaml`。
- 优先模块化改动，避免把逻辑堆进大入口文件（`index.html`、启动器）。
- 测试文件归 `tests/`；临时运维文件放 `.codex/tmp/`，出结果并摘要后清理。
- 服务器同步时保留 `.git`、`data`、`.venv`、`.codex` 与运行态；同步到远端 Git 时应包含含持久文档 / skill 的 `.codex` 文件。
- 移动端 UI 改动要同时考虑 `index.html`、`static/css/`、`static/js/`。
- 重要变更把摘要同步回 `SYSTEM.md`。

## 服务器拓扑（用前先核实远端）

- 本地工作区：`C:\Users\yu\Desktop\opaiRe`；密钥在 `C:\Users\yu\Desktop\file`。
- Server 1：`ubuntu@mycodexy.duckdns.org`，Web 域名 `kaikj.bond`。现役 `cliproxyapi.service`(8818) + `cliproxy-login.service`(8012) + Nginx；邮箱中转已删除(2026-07-27)。
- Server 2：`ec2-user@mysuby.duckdns.org`，域名 `tupai.cyou`。Sub2API Docker 栈 + redis + postgres，Nginx 反代 8080。
- Server 3：OCI `instance-20260613-1403`，NLB 入口 `132.226.146.175`，私网 `10.31.0.239`，域名 `dazhou.bond`。用户 `opc`，项目在 `/home/opc/opaiRe`，Web 服务 `opaire-lite.service`(127.0.0.1:8000)。发布订阅、Reality、TG、proxy-panel。
- Server 4：OCI 实例 `code`（权威代理后端），私网 `10.0.0.154`，域名 `xh-ai.cyou`。经 Server 3 ProxyCommand 访问。**不要**把 `instance-20260604-1123 / 10.0.0.112` 当作 Server 4，除非重新验证并迁移。
- Main ARM：`instance-20260628-0849`，公网 `137.131.36.192`，私网 `10.0.0.242`，A1 Flex 项目主服务器（已撤出代理订阅范围）。

## 代理 / Mihomo 非显性规则

- Windows 由外部本地脚本管理的 Mihomo 单核用 `clash_proxy_pool.runtime_mode: windows_single_core`；项目可读取 / 切换节点、热更新，但不得启动、停止或杀掉外部进程。
- 运行态分组需合并 `/proxies` 与 `/providers/proxies` 的 provider 节点元数据（`manual-config.yaml` 可能属于旧订阅）。
- provider 节点存活测试用 Mihomo `/group/{group}/delay` 批量端点（`/proxies/{provider-node}/delay` 可能返回 404）。
- Server 3 chroot 不是 Docker，即使 rootfs 里有 `/.dockerenv`；不要把 localhost 代理 URL 改写成 `host.docker.internal`。
- 原始代理池 Web 测试：20 项均匀采样或可取消的全量 50 项/批测试；成功项可覆盖写入独立成功池，注册只轮换成功池；运行时失效同步淘汰成功池与原始池并热切换（默认 60 秒内最多 5 次持久驱逐、至少保留 1 个活跃候选）；启用的成功池为空时保存被拒，不回退到未测源列表。

## 上游同步状态

- 本地已于 2026-07-26 合并上游 `v18.0.2`（本地合并提交 `d403d6a`，上游 `f79a049`），`APP_VERSION` = `v18.0.2`。
- 保留的本地定制：任务熔断、代理节点驱逐、IMAGE2API、邮件桥接、Mihomo/Oracle 定制、原始代理池成功池。
- Server 3 运行态在重新部署前可能仍是旧版（曾部署 `v17.0.3`）。
- 合并保留上游四平台 `auth_core` 二进制；Windows 本机加载 `auth_core.pyd` 可能失败，Server 3 用 linux x86_64 `.so`。

## 邮箱 / OTP 中转

- 当前默认：本机 CF Tunnel 直收（openai_cpa.receive_mode: local_webhook）。
- 公网入口示例：lovqf0jm.dpdns.org -> localhost:8000；CF Worker openai-cpa1 的 EMAIL_WEBHOOK_URL 指向 https://lovqf0jm.dpdns.org。
- 本机端点：POST /api/webhook/email（X-Webhook-Secret）、/api/email-bridge/*；local_webhook/dual 会注入 code_pool。
- 收码路径 openai_cpa.receive_mode（兼容旧 bridge_enabled）：
  - remote_bridge：CF Worker -> 公网服务器中转 -> 本机 WS/HTTP 反拉
  - local_webhook：CF Worker -> 本机/隧道直收（当前）
  - dual：本机直收 + 服务器中转备份
- 服务器中转源码：deploy/email-bridge/；完整做法见 .codex/docs/email-bridge-relay-howto.md。
- Server 1 旧中转 grok-email-bridge 已于 2026-07-27 删除；备份在服务器 /opt/backups/email-bridge-removed-20260727T122128Z/。
