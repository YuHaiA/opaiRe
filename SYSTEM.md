# SYSTEM

## 项目目标

- 本项目是一个基于单页前端与 Python 后端的注册管理系统。
- 主要用于账号注册流程配置、运行监控、库存管理、邮箱资源管理、云端凭证管理与团队账号管理。

## 当前结构

- 前端主界面集中在 `index.html`
- 后端路由位于 `routers/`
- 工具与辅助逻辑位于 `utils/`
- 测试文件位于 `tests/`
- 运行数据与配置位于 `data/`

## 最新吸收

- 2026-08-16 合并上游 `wenfxl/openai-cpa` 的 `upstream/main`，对应标签 `v18.1.3` / 提交 `e5662e6`。
- 吸收 `v18.1.1 -> v18.1.3`：Grok 丢弃数统计、检测状态优化、IPv6 入站代理兼容、Grok 独立检测代理。
- 本地 `APP_VERSION` 已同步到 `v18.1.3`。
- 保留本地 CPA 收码路径、Mihomo/Clash 定制、email-bridge 与 `.codex` 文档体系。
- 顺手修正上游集群页把丢弃数绑到 `pwd_blocked` 的显示错误。

## 前端界面要点

- 主布局由顶部状态区、左侧导航、右侧主内容区组成。
- `accounts`、`mailboxes`、`cloud`、`team_accounts` 为典型数据表格页。
- 这些页面现在统一采用“固定面板高度 + 表格区域内部滚动 + 底部分页固定”的布局约定。

## 本次修改

- 修改文件：`index.html`
- 修改文件：`routers/service_routes.py`
- 修改文件：`utils/integrations/clash_manager.py`
- 修改文件：`static/js/app.js`
- 修改文件：`wfxl_openai_regst.py`
- 修改文件：`docker-compose.yml`
- 修改文件：`docker-compose2.yml`
- 修改文件：`README.md`
- 新增文件：`SYSTEM.md`
- 变更内容：
  - 增加 `.data-panel` 与 `.data-table-scroll` 复用类。
  - 将账号库、邮箱库、云端库存、团队账号库四个主表格卡片改为纵向 `flex` 布局。
  - 让表格区域使用固定高度内滚动，不再依赖外层页面被内容撑开。
  - 让表头在表格内部滚动时保持吸顶。
  - 启动端口支持通过 `WEB_PORT` 或 `PORT` 环境变量指定。
  - Docker 映射端口改为支持 `${WEB_PORT:-8000}`。
  - 前端说明文案和 README 不再把访问地址写死为 `8000`。
  - 进一步压缩账号库统计卡高度，扩大表格主体可视区域。
  - 端口占用探测同时检查 `0.0.0.0` 与 `127.0.0.1`，避免本地回环端口已被占用时仍误判可用。
  - 补回上游 `v14.2.3+` 引入的验证码提取单次轮询最大次数前端配置入口。
  - 邮箱配置页新增 CF 托管域名批量删除功能，并在后端提供对应删除接口。
  - CF 托管删除改为独立输入框，不再绑定发信域名池。
  - 邮箱右侧“渠道专属参数”底部新增全局可见的 CF 托管删除卡片，所有邮箱模式都能看到同一入口。
  - 修复邮箱配置页中 `mail_domains` 与 `freemail.api_url` 两处重复按钮标签，避免前端模板结构污染导致后续区块渲染异常。
  - 补齐 `isTestingTg` 与 `showMailboxesPlaintext` 前端状态，避免 Telegram 测试与邮箱明文切换在渲染时触发 Vue 未定义告警。
  - 邮箱明文切换按钮改为直接读取 `showPwd.showMailboxesPlaintext`，统一走已存在的密码显示状态对象，避免继续访问根级未定义状态。
  - 清理了前端根级重复的 `showMailboxesPlaintext` 状态，只保留 `showPwd` 内部版本，减少 Vue 作用域混淆。
  - 主内容区新增“配置加载失败/未完成”占位卡，避免 `config` 未成功返回时页面只剩顶栏与侧栏的空白状态。
  - 修复邮箱页末尾缺失的外层 `div` 收尾；此前 `sms / proxy / notify / concurrency / team_accounts / cloud / relay` 会被浏览器错误解析成 `email` 区块子节点，导致这些页面切换后主内容空白。
  - “云端授权管理控制台”里的授权重置功能恢复为旧行为：页面内保留按钮，点击后才弹出可关闭的确认弹窗，不再默认显现。
  - 授权重置弹窗已重新放回 `#app` 根节点内，避免落到 Vue 根节点外时 `v-if` 失效，出现“默认弹出且无法关闭”的假象。
  - CF 托管删除卡片恢复独立域名输入框，删除动作仅针对手动填写的域名列表，不再默认使用发信域名池。
  - Clash 订阅链接现在会在前端自动把 `sub?target=clash...` 这类相对路径补成完整 URL；切换订阅时也会把补全后的 URL 传给后端，避免服务器端无法拉取导致“订阅看似切换但策略组不刷新”。
  - Clash 服务器端拉取订阅改为使用 `curl_cffi` 模拟浏览器请求；订阅切换失败时不再提前写入 `selected_subscription_id/sub_url`，避免出现“前端显示已切换，实际运行未切换”的错位状态。
  - Clash 订阅拉取现在在“配置了代理但代理不可达”时，会自动回退到服务器直连，避免本地代理端口失效把订阅切换链路整体卡死。
  - H5 导航现已改为左侧抽屉式菜单：移动端通过顶部汉堡按钮展开/收起，桌面端继续保持原侧栏样式与布局。
  - H5 头部布局改为两段式紧凑结构：模式与进度在上层，协议/主题/语言/状态/启动按钮在下层按等宽网格排布，仅影响 767px 以下移动端。
  - H5 表格页新增移动端专用压缩样式：工具栏改为纵向堆叠、按钮与搜索框减少挤压，表格保持横向滚动并锁定最小宽度，避免表头与单元格在手机上被压成竖排或错位。
  - 保存代理/控制端口/Secret 时，会同步重建 Linux 单核心 Mihomo 运行配置，避免配置与运行端口不一致。
  - 新增服务器磁盘自动清理脚本与 systemd timer，默认磁盘使用率达到 80% 才清理日志、缓存和 Python 缓存目录。
  - 内存预测页现在会返回可执行建议、推荐降载方案与行动项，前端可一键回填注册 / CPA / Sub2API 并发与日志行数。
  - 新增 `tests/test_memory_predictor.py`，覆盖高压降载与低压保持配置的核心路径。
  - 恢复“并发与系统”页面内的 Git 更新模块，前端重新接入 Git 状态读取、远端抓取与强制同步入口，并展示分支、提交差异、工作区脏状态与操作输出。
  - 并发与系统页面新增“磁盘 / 日志清理”功能面板，前端可查看 Linux 清理脚本状态、磁盘占用、阈值，并可执行按阈值清理或强制立即清理。
  - 内存预测页新增“套用建议并重启”动作，用于服务器已明显吃紧时，直接降载并热重启释放压力。
  - `server_disk_cleanup.sh` 新增 `--force` 参数，允许在未达到阈值时也执行清理，避免手动保洁无效果。
  - 新增 `utils/system_maintenance.py` 与 `tests/test_system_maintenance.py`，把清理状态检测从路由中拆出并补上基础测试。
  - `server_disk_cleanup.sh` 的主清理策略调整为“优先释放最早 30%”：超大主日志会裁掉最早 30% 内容，历史日志 / 缓存文件会按最旧排序删除 30%，并保留最小安全余量，减少误清过头的风险。
  - Clash 模块前端重新接回运行模式说明、启停重启控制、订阅新增/切换/删除、策略组延迟测试和手动切换节点等能力，和现有后端 Clash API 对齐。
  - Clash 节点页把有效节点池状态显性化，延迟测试成功后会提示并展示自动保存的有效节点数量。
  - 新增 `/api/clash/tested_nodes/clear`，可清空单个策略组已保存的有效节点池，让节点列表恢复为完整策略组节点。
  - Clash 订阅切换不再只改本地选中状态；现在会立即把新订阅下发到当前目标实例，并刷新该订阅对应的策略组列表。
  - Clash 已保存订阅卡片的当前选中态进一步强化，整行高亮、标题胶囊和标签会一起变化，降低误判。
  - 本地账号库、邮箱库、云端库存、Team 团队账号库恢复为固定计算高度的表格面板；滚动重新限制在表格内部，保留当前新增模块与功能入口。
  - 本地账号库统计卡片改为更紧凑布局，并补充“已推送 / 有凭证”等可点击状态筛选卡，直接联动账号列表过滤。
  - 本地账号库筛选卡补齐 `Img凭证`，并把本地与云端统计卡整体缩成更接近“大按钮”的紧凑样式。
  - 云端库存改为前端按平台分批串行拉取，增加当前批次、完成进度与状态提示，避免多平台一次性获取时无反馈。
- 修改原因：
  - 解决“表格内容把页面往下撑开，滚动发生在外层页面而不是表格内部”的问题。
  - 解决控制台端口说明写死 `8000`，容易与实际运行端口不一致的问题。
- 影响范围：
  - 仅影响主数据表格页面的布局与滚动行为，不改变数据接口和业务逻辑。
  - 启动方式与部署说明现在支持自定义主机端口，运行时兼容现有默认值。
  - 账号库页面现在会优先给表格主体让出更多高度。
  - 并发与系统页面现在可直接配置 `otp_poll_max_attempts`，并在本地配置文件中持久化。
  - Cloudflare 域名托管支持批量删除危险操作，需二次确认后执行。
  - 删除 CF 托管域名时可独立指定待删除域名列表，避免误删发信域名池。
  - 邮箱右侧参数区现在额外提供全局可见的 CF 托管删除入口，方便所有邮箱模式共用同一危险操作入口。
  - 服务器单核心 Clash/Mihomo 在保存配置后会自动同步端口与控制器配置。
  - 服务器现在可以通过 `opaire-disk-cleanup.timer` 做低风险磁盘保洁，避免因无 swap、小磁盘和日志堆积导致重启后恢复变慢。
  - 内存预测页面不再只是展示数值，而是直接给出建议值与可执行按钮，便于快速收敛并发。
  - 并发与系统页面重新具备 Git 运维入口，可直接查看本地与远端差异并触发同步操作。
  - 并发与系统页面现在同时具备服务器保洁与紧急降载重启动作，更贴近“防卡死”而不是纯展示。
  - 服务器保洁的释放空间方式现在更直接，优先清最旧内容，而不是仅按固定保留行数截断。
  - Proxy 页面中的 Clash 区块从“基础配置 + 实例同步”恢复为更完整的运维面板，减少后端已有能力在前端失联的情况。
  - Clash 延迟测试会继续自动写入 `clash_proxy_pool.tested_nodes`，前端切换节点时优先使用有效节点池；清空后不会删除订阅或真实节点，只移除筛选结果。
  - Clash 订阅切换后的策略组来源现在与当前订阅配置保持一致，不会继续显示上一个订阅残留的策略组。
  - 主库存类页面重新回到“工具栏 / 统计区固定、表格内部滚动、分页固定”的结构，避免数据量上来后把整页撑开。
  - 云端列表分页现在基于前端已拉取的原始合并数据切片显示，筛选、搜索和翻页不再每次都重新触发全平台聚合请求。

## 服务1 CPA 节点探测覆盖修复（2026-08-09）

- 当前公网页面入口为 `https://kaikj.bond/`；SSH 使用 `ubuntu@18.118.93.106`（旧直连域名 `mycodexy.duckdns.org`），本机密钥为 `C:\Users\yu\Desktop\file\sub2.pem`。

- 现象：28 路出口中 **18 路从未被探测过**，有数据的 10 路里最新的也已过期 126 分钟，中位数 19.5 小时，节点健康度基本处于盲区。
- 根因一：`guard.go:1078` 的主动探测调度整段被 `if pol.Mode == "active" || pol.Mode == "hybrid"` 包住，而线上是 `mode=passive`，**整块是死代码**。因此原计划的「`active_interval_seconds` 3600 → 900」根本不会有任何效果，必须先切模式。少数几路有 active 数据，来自不受 mode 限制的隔离恢复路径 `guard.go:1074`。
- 根因二：`soft_tps` / `hard_tps` 是 **反伪造上限**，不是速度下限。`classifyTPS`（`guard.go:236`）里 `tps >= hard` 判 hard、`tps >= soft` 判 soft，**吐字越快评级越差**，用途是识别伪造/重放响应。线上却被收紧成 `150/250`，落在正常输出区间内。
- 实测误判：以 `150/250` 开启 hybrid 后，lane 10、11 分别在 252、308 TPS 被隔离，lane 1/2/17/19 在 218–226 TPS 记 soft，**14 路里误判 6 路**，且全部 `ContentValid=true`（首尾标记、`finish_reason`、正文均合法）。lane 10 还触发 `node_rotation_failed`，连轮换自救都做不到。
- 阈值为什么会配错：被动通道采样真实用户流量，reasoning 密集、速度慢（约 58–170 TPS），`150/250` 看着合理；主动探测发的是 `max_tokens: 256` 的纯文本题目（TLS 1.3 握手 8 条事实），不含 reasoning，健康节点本就跑到 **101–348 TPS**。按被动流量收紧上限，等于给主动探测设了个够不着的天花板，同时也在误判被动通道。
- 修复：阈值恢复作者默认 `soft_tps: 700` / `hard_tps: 1500`，再切 `mode: hybrid`、`active_interval_seconds: 900`。当前实测最高 348 TPS，距离软上限仍有 **2.0 倍余量**。
- 结果：节点观测覆盖 10/28 → **28/28**，分类 **28 路全 healthy**，隔离 0 路，观测新鲜度中位数从 19.5 小时降到 15 分钟内。两次误隔离在阈值修正后自动解除（`quarantined=2, restored=2`），**没有任何账号被禁用**。已跨 `systemctl restart cliproxyapi` 验证：策略持久化在 `/opt/CLIProxyAPI/plugin-data/egress-guard/state.json`，28 路观测数据全部保留。
- 调度节奏：30 秒 ticker 每次只探一个节点（`guard.go:1063-1090` 里显式 `break` 防止并发洪峰），冷启动约 14 分钟铺满 28 路，之后按 900 秒周期滚动。
- **账号再平衡已无必要**：实测 339 个账号中 50 个绑定到 lane，289 个无 `proxy_url`（未纳管），28 路每路 1–2 个、**零空闲**，`capacity.plan` 显示 `required_nodes=26`、`sufficient=true`。此前记录的「14-19 路全空」已过期，不要再执行 rebalance —— 那会改写约 23 个账号的出口 IP，对养号敏感，却在解决一个不存在的问题。
- ⚠️ 后续调阈值时**不能只看被动流量**：两个通道共用同一组上限，被动（reasoning）和主动（纯文本）TPS 差约 3 倍，改动前务必对照主动区间 101–348 校验。
- 探测开销：`interval=900` 时约为 28 路 × 96 次/天 × 250 输出 token ≈ 67 万 token/天，全部走 `grok-4.5`（当前唯一有额度的模型）。嫌贵可调大间隔，覆盖率是平滑退化的。
- 备份：`/opt/CLIProxyAPI/backups/probe-hybrid-20260809T050513Z/`（`state.json`、`config.yaml`），路径同时记录在 `/tmp/probe-bak-path`。回退主动探测只需 `POST /policy {"mode":"passive"}`；阈值应保持 700/1500，旧的 150/250 对两个通道都是错的。
## 服务1 CPA 回归官方发行版 7.2.125（2026-08-09）

- 线上主程序由自编译的 `7.2.71-stream-bootstrap.3-cgo` 升级为官方发行版 `CLIProxyAPI 7.2.125`（Commit `2e6b1d83`，BuiltAt `2026-08-08T21:13:51Z`），落后量为 54 个版本 / 366 提交 / 300 文件。
- 升级前做了符号级比对，确认**主程序不含任何本地定制代码**：`opaire`、`grok2api-egress`、`mihomo`、`lane_manager`、`egress-guard`、`semanticguard` 在旧二进制中计数全为 0，`local-semantic-guard-cgo` 只是构建标签；163 个"仅旧版存在"的函数全部落在官方包路径下，属官方重构改名或内联。
- 当初自编译的唯一理由 `streaming.bootstrap-retries`，官方 v7.2.125 已内置同名配置项 `streaming.{keepalive-seconds,bootstrap-retries}`，键名完全一致，`config.yaml` 原样保留即可，启动无 unknown field / deprecated 告警。
- **结论：全部定制都在插件层，今后升级只需替换二进制，服务器不必再维护 Go 工具链。**
- 官方资产用带插件支持的 `CLIProxyAPI_7.2.125_linux_amd64.tar.gz`（**不能用 no-plugin 版**），sha256 `4e940b7dc5bdf867b5c58ca30f1b368fae6dc2e041e8a351d5c2c07f3f610233`，已校验。
- 升级前先在隔离实例（端口 `18825`，不碰生产）预验证：两插件正常加载、零 error/panic、`/v1/models` 返回 14 个、真实推理 3/3 全 200、`passive.total` 有增量，确认 service1.8 的 usage 修复在新版仍生效后才动生产。
- 升级后核验：模型数 13 -> **14**（新增 `grok-imagine-video-1.5`），`cpa-xai-quota-guard 0.3.33-opaire.2` 与 `grok2api-egress 1.1.0-service1.8` 均正常注册，auths 保持 **339 个未动**，policy 三开关 `auto_rotate_accounts` / `auto_switch_on_degraded` / `auto_rotate_lanes` 全部为真，nodes 28 路，真实推理 3/3 HTTP 200，被动统计 `passive.total` 持续增长。
- 回滚备份：`/opt/CLIProxyAPI/backups/upgrade-7.2.125-20260809T044131Z/`，含旧二进制 `cli-proxy-api-7.2.71-custom`、`config.yaml`、`egress-state.json`、`.management-key`、`auth-count.txt`、`status-before.json`。回滚即停服后 `install` 回旧二进制再起服。
- 值得关注的上游改动：`fix(usage)` 三连（normalized token accounting v2、partial token 分类、canonical token 规范化，正是插件依赖的数据源）、xAI executor 输出控制与 x_search 注入、Grok Imagine Video 1.5 GA、Claude TLS 会话复用、`fix(pluginhost)` Windows response buffer、request lifecycle 插件拦截能力。

### 陷阱：升级停服会连带停掉 cliproxy-login

- `cliproxy-login.service` 带 `PartOf=cliproxyapi.service`，而 systemd 的 `PartOf` **只传播 stop/restart，不传播 start**。因此 `systemctl stop cliproxyapi` + `systemctl start cliproxyapi` 这种分开的升级操作会把 login 服务停掉且不再拉起，`Restart=always` 也救不回来（systemd 主动 stop 会抑制 Restart），表现为 `8012` 端口无监听、`https://kaikj.bond/` 打不开。
- 已加固：新增 drop-in `/etc/systemd/system/cliproxyapi.service.d/10-login-companion.conf`，内容为 `[Unit] Wants=cliproxy-login.service`，让 start 时把 login 一起带起来。已实测 stop -> 两者同停、start -> 两者同起，`8012` 恢复监听，`https://kaikj.bond/` 302 跳 `/cliproxy/login` 并返回 200。
## 服务1 CPA 出口守护（2026-08-07）

- 服务1运行 CPA 原生插件 `grok2api-egress v1.1.0-service1.4`，源码位于 `C:\Users\yu\Desktop\grok2api-egress-service1\cpa-plugin\go`，不属于 opaiRe 主进程。
- 插件“出口守护 -> 守护策略”负责自动轮换开关与分钟间隔；Mihomo Web 只负责物理节点查看、手动指定和立即轮换。
- 当前策略：10% 灰度、36 个受管账号、13 路 `7951-7963`、每路最多 3 个账号、故障预留容量 1 路；账号按请求自动 Round Robin，物理出口自动轮换开启且每路间隔 10 分钟，多个通道错峰执行。
- 质量探测只计算可见正文 Token；HTTP 200 空响应、固定首尾标记缺失、非 `finish_reason=stop` 或流未收到 `[DONE]` 都按错误处理。旧默认阈值 `700/1500` 已迁移为 `150/250`。
- Mihomo 自动轮换候选必须有有效延迟、通过 xAI 连通验证，且物理节点名和实际出口 IP 都不得与其他通道重复。
- 2026-08-07 线上验证：13 路连通检测全部成功且出口 IP 全部不同；账号分布为每路 2-3 个；CPA、Mihomo、Nginx 均为 active，内外 `/healthz` 均为 200。
- 该阶段 CPA 为 `7.2.71-stream-bootstrap.2-cgo`，同时加载 `cpa-xai-quota-guard 0.3.33-opaire.2` 与 `grok2api-egress 1.1.0-service1.4`。配置为 `request-retry: 3`、`max-retry-credentials: 3`、`streaming.bootstrap-retries: 2`。（当前线上已升级到官方 `7.2.125`，见「回归官方发行版」章节。）
- 服务器 `/opt/cpa-mihomo` 已增加订阅定时自动更新：Mihomo 页面“订阅导入与更新”可配置开关和间隔（5-10080 分钟），当前线上为开启、60 分钟。更新失败保留旧订阅/provider/通道，不与手动更新并发；面板状态显示上次尝试、成功、错误和下次时间。部署备份：`/opt/backups/cpa-mihomo-auto-update-20260807T152441Z`。本地 `grok2api-egress-service1/service1/cpa-mihomo` 仅为源码副本，不能替代线上运行态。
- 完整回滚备份：服务1 `/opt/backups/cpa-rotation-20260807T142300Z`，包含新旧 CPA、插件、配置、state、完整 auths 与 Mihomo 状态。临时构建目录清理后根盘占用从 91% 降至 74%。`patrol-capacity-cooldown.timer` 继续保持 disabled/inactive。

## 服务1 CPA 流式首包换号（2026-08-05）

- 服务1已部署 `CLIProxyAPI 7.2.71-stream-bootstrap.1`（基线 `5b7f2361`），生产配置启用 `streaming.bootstrap-retries: 2`。
- 公共流处理器现同时识别 Claude、OpenAI Chat Completions、OpenAI Responses 和 Gemini 的协议前导；消息 ID、角色、空 thinking、签名、空 content part 等事件会先缓存，不再过早提交给客户端。
- 在首个真实正文、推理内容或工具参数之前发生 EOF / 5xx / 认证类错误时，CPA 可以丢弃失败账号的前导事件并重新选择账号；一旦已有真实内容下发，禁止自动重放，避免重复正文和工具调用。
- 前导缓存上限为 64 块或 1 MiB；上游正常结束时会补发合法空响应的前导，未知协议保持原有首块即提交行为。
- 生产切换前已验证 Linux CGO 二进制、`18818` 临时实例、健康端点及 `cpa-xai-quota-guard` / `grok2api-egress` 插件加载；生产回滚备份位于 `/var/backups/cliproxy-stream-bootstrap-20260805T083825Z`。
- 线上 OpenAI Chat 与 OpenAI Responses 流均验证为 HTTP 200、包含真实 delta 和完整终止事件、无错误事件。
- Claude 最小请求在新旧二进制上都可能首字节前长时间等待，已排除本次缓存逻辑和 `grok2api-egress` 插件回归。单账号对照显示，现有 `xai_health_check.py` 的极简 Responses 载荷返回 200，并不代表同账号能处理 Claude / Chat 转换后的 reasoning、include、store 和工具字段；后续账号测活应增加富载荷探测，不能只按当前 `live` 结果判断 Claude 可用性。

## 后续约定

- 新增表格页时，优先复用 `.data-panel` 与 `.data-table-scroll`，避免再次出现外层滚动抢占的问题。
- 若某页头部筛选区明显更高，应优先在面板高度或分区布局上调整，不要退回内容撑高方案。
