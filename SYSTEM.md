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

## 最新修改

- 修改文件：
  - `utils/proxy_manager.py`
  - `utils/integrations/clash_manager.py`
  - `utils/core_engine.py`
  - `routers/service_routes.py`
  - `static/js/app.js`
  - `index.html`
  - `utils/config_save_guard.py`
  - `tests/test_proxy_manager_node_eviction.py`
  - `tests/test_clash_manager_evicted_nodes_clear.py`
  - `tests/test_register_shared_batch_net_check.py`
  - `tests/test_system_routes_config_save.py`
  - `SYSTEM.md`
- 变更内容：
  - Clash 节点池新增 `preferred_nodes` 标优池与 `preferred_only_mode` 运行态开关。
  - 共享 Clash 并发批次在同一批内成功产出 `2` 个账号后，会把当前节点自动标记为“标优”，并确保它同时进入当前策略组的活节点池显示范围。
  - 节点页新增“标优节点池”计数、“只用标优”切换按钮，以及表格中的“标优”标签。
  - 当前端开启“只用标优”后，后端自动切换与手动切换都会严格限制在该策略组的标优池内，不再退回普通活节点候选。
  - 配置保存链路现在会保留 `preferred_nodes` 与 `preferred_only_mode`，避免节点页切换后的运行态被旧配置覆盖回去。
- 修改原因：
  - 用户希望把“实际在生产批次里跑出结果的节点”沉淀为更可信的候选池，并能一键切到“只用标优节点”模式。
  - 现有 `tested_nodes` 只代表测速通过，不等于真实注册/补货表现稳定；引入标优池后，可把“测速可用”和“实战产出”分层管理。
- 影响范围：
  - 影响 Clash 节点池切换策略、节点页展示与运行态配置保存。
  - 不改变原始代理池、邮箱逻辑、云端库存逻辑或非 Clash 场景下的切换行为。

- 修改文件：
  - `utils/proxy_manager.py`
  - `utils/core_engine.py`
  - `tests/test_proxy_manager_node_eviction.py`
  - `SYSTEM.md`
- 变更内容：
  - Clash 节点淘汰前现在会先计算当前策略组剩余有效候选数；当有效节点只剩 `5` 个或更少时，触发保底保护，跳过写入 `evicted_nodes`。
  - 保底保护优先按当前策略组的“测速通过节点池”计算；若该池为空，则回退按当前策略组过滤后的有效节点总数判断。
  - 节点测活失败但命中保底保护时，日志会明确显示“触发保底保护”，不再误报成普通剔除失败。
  - 新增回归测试，分别覆盖“候选池充足时正常拉黑”和“候选池只剩 5 个时跳过拉黑”两条路径。
- 修改原因：
  - 现有逻辑在节点连续异常时会持续把坏节点加入 `evicted_nodes`，当有效节点池已经很薄时，容易把候选池越拉越空。
  - 用户希望先落地一个更保守的保底规则，避免节点池在低存量阶段被自动拉黑机制抽干。
- 影响范围：
  - 仅影响 Clash 节点淘汰与相关日志输出策略。
  - 不改变批次切换、原始代理池处理、账号成功保存逻辑或其他邮箱/验证码链路。

- 修改文件：
  - 删除 `stop_openai_cpa.ps1`
  - `SYSTEM.md`
- 变更内容：
  - 清理了根目录未被项目文档、前端、后端路由或部署配置引用的历史本地停止脚本 `stop_openai_cpa.ps1`。
  - 保留 `scripts/server_disk_cleanup.sh` 与 `scripts/rollback_server1_to_f1.ps1`，因为这两者仍有系统维护代码或文档记录依赖。
- 修改原因：
  - `stop_openai_cpa.ps1` 仅用于本机按进程名强停旧版启动方式，当前仓库内没有任何入口引用它，继续保留只会增加根目录噪音。
  - 相比之下，其他维护脚本仍属于项目已知运维路径，不能误删。
- 影响范围：
  - 仅影响本地历史辅助脚本存量。
  - 不改变业务逻辑、接口行为、测试流程或现有部署链路。

- 修改文件：
  - `tests/test_cloud_accounts_route.py`
  - `tests/test_local_microsoft_service_abuse_mode.py`
  - 删除 `tests/test_mail_service_abuse_mode.py`
  - 删除 `tests/test_reg_engine_executor_cleanup.py`
  - `SYSTEM.md`
- 变更内容：
  - 清理了两份与当前实现脱节或依赖过时内部结构的测试文件，减少本地无关测试噪音。
  - `test_cloud_accounts_route.py` 改为直接覆盖 FastAPI 依赖，不再通过 `sys.modules` 注入残缺假模块污染整套测试环境。
  - `test_local_microsoft_service_abuse_mode.py` 改为拦截 `builtins.print` 验证告警日志，避免受 `core_engine` 全局打印代理影响而产生假失败。
- 修改原因：
  - 本地继续清理项目无关/过时测试代码时，发现少数旧测试会引用已移除的内部函数，或通过全局模块替身把其他测试一起带崩。
  - 这类测试不仅失去回归价值，还会干扰真实有效的测试结果判断。
- 影响范围：
  - 仅影响测试层的稳定性与可维护性。
  - 不改变业务逻辑、接口行为或运行配置。

- 修改文件：
  - `SYSTEM.md`
  - 本地运行日志 `run.out.log`、`run.err.log`
  - 非 `.venv` 目录下的 `__pycache__/` 与 `.pyc/.pyo` 缓存文件
- 变更内容：
  - 清理了仓库工作区里的本地运行产物，仅移除非源码缓存与日志文件。
  - 保留 `tests/` 下的正式回归测试源码，不把项目验证资产误删成“测试垃圾”。
- 修改原因：
  - 当前工作区存在一批与正式源码无关的 Python 编译缓存和运行日志，容易干扰本地排查与目录可读性。
  - `.gitignore` 已覆盖这些产物，适合做一次定向保洁。
- 影响范围：
  - 仅影响本地工作区整洁度与磁盘占用。
  - 不改变任何业务逻辑、接口行为、测试源码或运行配置。

- 修改文件：
  - `utils/task_log_guard.py`
  - `utils/core_engine.py`
  - `tests/test_task_log_guard.py`
  - `tests/test_core_engine_abort_cleanup.py`
- 变更内容：
  - 可计数错误触发节点淘汰 / 批次熔断的门槛，从 3 次上调到 5 次；`curl(28) timeout`、提交邮箱 `409`、无密码发信 `409` 现在都按 5 次累计后才会触发拉黑与切节点。
  - `_execute_registration_run()` 在捕获 `TaskAbortError` 后，会先脱离当前 task/batch 上下文，再执行节点淘汰与配置重载，避免清理过程里的日志打印重新命中已中止批次，反手抛出 `BatchAbortError` 把整个补货线程炸停。
  - 新增回归测试，覆盖 5 次阈值与“淘汰清理期间不应二次重入已中止批次”的收尾行为。
- 修改原因：
  - 线上日志显示 `Sub2API` 线程在触发节点淘汰后，没有正常返回 `switch_node` 进入下一批，而是在清理节点时因配置重载打印日志重新触发 `BatchAbortError`，直接把补货主线程打崩，表现成“像只跑完一个批次就没继续”。
  - 同时，用户希望 `curl(28)` 等可计数超时不要过早拉黑节点，门槛需要从 3 次放宽到 5 次。
- 影响范围：
  - 影响共享批次里节点淘汰的触发阈值与异常收尾稳定性。
  - 不改变节点测活成功后的主流程衔接，也不影响普通成功路径。

- 修改文件：
  - `index.html`
- 变更内容：
  - 更新前端静态资源版本号，强制浏览器重新拉取最新的 `app.js / index.js / css`，避免页面模板已更新但脚本仍命中旧缓存。
- 修改原因：
  - Clash 节点页最近新增了“拉黑节点池”相关前端方法与模板片段；如果服务器已更新 HTML，但浏览器仍复用旧版 `app.js`，会出现点击策略组后节点页无法正常进入、看起来像“点了没反应”的前端缓存错配。
- 影响范围：
  - 仅影响前端静态资源缓存刷新。
  - 不改变任何业务逻辑、节点切换规则或后端接口行为。

- 修改文件：
  - `utils/auth_pipeline/register.py`
  - `tests/test_register_shared_batch_net_check.py`
- 变更内容：
  - 修复无密码接管首段 OTP 校验循环的流程缩进错误：验证码校验结果现在会在每轮取码后立即处理，命中 `200` 时直接继续后续 `continue_url` 主流程，不再掉出到外层注册重试循环。
  - 新增回归测试，覆盖“无密码接管拿到首个验证码并校验通过后，不应再额外触发 `email-otp/resend`，且应继续执行后续登录回调流转”。
- 修改原因：
  - 旧逻辑把 `code_resp.status_code` 判断错放到重发循环外，导致验证码已经通过时，流程没有承接到后面的工作区/回调链路，表现成“验证码接上了，但后续没接上”，同时也容易给人造成仍在重复取码/重发的观感。
- 影响范围：
  - 影响无密码接管首段 OTP 验证成功后的主流程衔接。
  - 不影响普通密码注册 OTP 流程，也不改变节点测活和批次切换策略。

- 修改文件：
  - `utils/integrations/clash_manager.py`
  - `routers/service_routes.py`
  - `static/js/app.js`
  - `index.html`
  - `tests/test_clash_manager_evicted_nodes_clear.py`
- 变更内容：
  - Clash 状态接口现在会把运行期 `evicted_nodes` 拉黑节点池一并返回给前端。
  - 新增 `/api/clash/evicted_nodes/clear`，可在面板里手动清空被淘汰节点列表，而不影响 `tested_nodes` 有效池与其他 Clash 运行态。
  - Clash 节点详情页新增“拉黑节点池”数量展示与“清空拉黑池”按钮，方便在确认节点环境恢复后手动放回候选池。
  - 新增定向测试，覆盖拉黑池清空后的配置写回，以及本地 GUI 模式下状态接口会正确暴露 `evicted_nodes`。
- 修改原因：
  - 现在线上已经把坏节点淘汰写入 `clash_proxy_pool.evicted_nodes`，但面板缺少可视化与人工清理入口；一旦需要重新放回候选池，只能手改配置，不利于排障和运营。
- 影响范围：
  - 仅影响 Clash 节点池管理面板与相关后端接口。
  - 不改变主补货流程、节点切换判定、验证码链路与批次熔断逻辑。

- 修改文件：
  - `utils/email_providers/mail_service.py`
- 变更内容：
  - `OPENAI-CPA` 本地 webhook 等码在正式判定超时前，会额外做两轮短暂宽限补捞，优先接住“第一轮刚超时、第二轮其实已到码”的延迟验证码。
- 修改原因：
  - 现网日志里频繁出现“第一次超时未拿到验证码，但紧接着第二次重发/重取又能拿到”的现象，说明 webhook 入池存在轻微延迟抖动。
  - 通过短宽限补捞，减少无意义重发和由此带来的整体节奏放大。
- 影响范围：
  - 仅影响 `OPENAI-CPA` 走本地 `code_pool` 的等码尾部逻辑。
  - 不改变主流程分支，只让“差一点到码”的场景更容易在首轮被接住。

- 修改文件：
  - `utils/email_providers/mail_service.py`
  - `tests/test_mail_service_code_wait.py`
- 变更内容：
  - 修复 `get_email_and_token()` 对“批次域名预分配”的误判：现在只有在 `assigned_domain` 真正存在时，才会把该 worker 视为预分配域名批次。
  - 新增定向测试，覆盖“仅有 `batch_id/worker_index`、但未预分配域名”时，`openai_cpa` 仍应正常回退到主域名池生成邮箱。
- 修改原因：
  - 新版把 `batch_id` 扩大用于批次熔断后，`mail_service` 仍沿用旧语义把 `batch_id + worker_index` 当成“域名已预分配”，导致共享批次里未启用域名运行时控制时直接 `return None, None`。
  - 这会让主流程在“创建邮箱”之前短路，既看不到正常补货推进，也不会留下失败统计，表现为 `0/1000`、`失败 0`、然后继续切节点。
- 影响范围：
  - 影响所有使用 `batch_id` 做批次控制、但未启用域名预分配的多线程注册链路。
  - 修复后，批次熔断与主域名回退逻辑重新解耦。

- 修改文件：
  - `utils/auth_pipeline/register.py`
  - `utils/email_providers/mail_service.py`
- 变更内容：
  - 共享全局节点批次在跳过重复代理网络检查后，仍会按 `worker_index` 做極輕量錯峰，但延遲已再進一步下調，盡量貼近 `f1` 體感。
  - `OPENAI-CPA` 無密碼接管鏈路保留發碼前並發閘門，但槽位放寬到更高，發碼前延遲也同步縮短。
  - `get_oai_code()` 對本地 `code_pool` 模式的等待輪數從先前保守值下調，只保留比原始配置略高的緩衝。
- 修改原因：
  - 在修复 `batch_id` 衔接 bug 后，之前为排障加上的轻节流仍让整体体感偏慢，需要再向 `f1` 收敛。
  - 保留必要的洪峰保护，但尽量减少额外等待时间。
- 影响范围：
  - 影响共享全局节点模式下的批次推进节奏。
  - 不改变节点切换规则本身，只调整批次内 worker 进入邮箱 / OTP 阶段的速度与本地 webhook 等码容忍度。

- 修改文件：
  - `utils/core_engine.py`
  - `utils/auth_pipeline/register.py`
  - `tests/test_register_shared_batch_net_check.py`
- 变更内容：
  - `_collect_sync_batch_results()` 与 `_collect_async_batch_results()` 现在会把“批次已熔断后产生的预期取消 future”当作正常批次收尾处理，不再让 `CancelledError` 直接炸掉 `Sub2API` / `CPA` 主线程。
  - 共享全局节点模式下，`当前批次已完成共享节点测活，跳过重复代理网络检查` 这条日志现在只在每批首个 worker 打一次，不再 30 线程刷满整屏。
  - 新增定向测试，覆盖同步/异步批次收敛阶段对已取消 future 的容错。
- 修改原因：
  - 解决主流程启动后，批次里一旦出现预期取消，`CancelledError` 会直接把补货线程打崩，表现成“看起来只是在测活、后面流程没继续跑”。
  - 减少共享批次日志噪音，让真正的邮箱、OTP、OAuth 或节点故障日志能露出来。
- 影响范围：
  - 影响常规量产、CPA 补货、Sub2API 补货三条主流程在批次熔断后的收尾行为。
  - 不改变节点切换策略本身，只修正批次取消时的异常传播和日志可读性。

- 修改文件：
  - `routers/account_routes.py`
  - `tests/test_cloud_accounts_route.py`
- 变更内容：
  - `/api/cloud/accounts` 现在默认不再逐账号请求 `Sub2API /usage`，只有显式传 `include_usage=true` 时才会拉取 usage 细节。
  - 新增路由测试，覆盖默认路径不会调用 `get_account_usage()`，避免云端库存列表接口在后台把 `Sub2API usage timeout` 放大成业务噪音。
- 修改原因：
  - 解决云端库存/详情页默认逐账号拉 usage 时，网络超时会占用线程和网络资源，间接影响主业务补货链路的问题。
  - 让 `Sub2API usage timeout` 成为“仅影响详情展示”的非关键错误，而不是默认路径上的高开销步骤。
- 影响范围：
  - 仅影响云端库存接口 `/api/cloud/accounts` 的 Sub2API 详情加载行为。
  - 默认展示仍保留账号基础状态、计划类型和现有百分比字段，不影响主业务注册 / 补货流程。

- 修改文件：
  - `utils/core_engine.py`
  - `tests/test_register_shared_batch_net_check.py`
- 变更内容：
  - 共享全局 Clash 节点模式下，常规量产、CPA 补货、Sub2API 补货三条流程不再“每个批次都 `force=True` 真切一次节点”。
  - 现在只有上一批因 `switch_node` 故障信号被中断时，下一批开头才会强制切节点；正常完成的批次只走普通切换，继续受原有 10 秒冷却保护。
  - 新增定向断言，覆盖“只有故障批次之后才应请求强制切换”的状态判断。
- 修改原因：
  - 对齐 `f1` 更接近的运行体感，减少共享全局节点模式下批次很快结束时的“每批都真切节点”现象。
  - 保留节点故障后的强制切换能力，避免坏节点刚被淘汰却又被冷却机制吞掉下一批应有的换节点动作。
- 影响范围：
  - 影响常规量产、CPA 补货、Sub2API 补货在共享全局 Clash 节点模式下的批次切换时机。
  - 不影响原始代理池、独立代理池，也不影响故障批次后的强制切换逻辑。

- 修改文件：
  - `utils/core_engine.py`
  - `utils/auth_pipeline/register.py`
  - `tests/test_register_shared_batch_net_check.py`
- 变更内容：
  - 共享全局 Clash 节点模式下，批次开头完成节点切换与测活后，会通过 `run_ctx.skip_proxy_net_check` 给同批 worker 打标记。
  - `utils/auth_pipeline/register.py` 现在识别该标记；命中时会跳过每个 worker 自己重复执行的 `cloudflare trace` 代理网络检查，并打印“当前批次已完成共享节点测活，跳过重复代理网络检查”。
  - 新增定向测试，覆盖“共享批次标记存在时，不应再发起 worker 级代理网络检查”。
- 修改原因：
  - 解决共享全局节点模式下“节点池刚测活成功，但 30 个 worker 又各自重复打一遍网络检查，导致批次内大量 curl(28) timeout，再触发下一批继续切节点”的链路放大问题。
- 影响范围：
  - 仅影响共享全局 Clash 节点模式下的 worker 级注册前预检查行为。
  - 原始代理池、独立代理池以及显式 `SKIP_NET_CHECK` 开关逻辑不变。

- 修改文件：
  - `scripts/rollback_server1_to_f1.ps1`
- 变更内容：
  - Server 1 回退脚本不再通过 `ssh ... bash -s` 直接走标准输入传输远端 shell 内容，改为先在本机生成 LF 换行的临时脚本，再通过 `scp` 上传到服务器 `/tmp` 后执行。
  - 增加 `scp` / `ssh` 退出码检查；远程回退失败时不再误报 `Done`，会直接抛出错误并停止。
  - 回退目标改为固定切换到现有保底分支 `rollback/f1c243e`，不再为每次回退额外新建时间戳 `rollback/f1-*` 分支。
- 修改原因：
  - 修复 Windows PowerShell 手动执行时，远端 bash 把 `set -euo pipefail` 读成带 `\r` 的参数，报出 `invalid option namepefail`，导致回退根本没有真正执行。
  - 修复脚本在远程失败后仍继续打印“完成”的误导行为。
  - 对齐当前使用习惯：服务器已经存在固定的 f1 保底分支，回退只需要切回该分支并重启，不需要保留每次新建的回退分支。
- 影响范围：
  - 仅影响本机手动执行 `scripts/rollback_server1_to_f1.ps1` 的远程回退流程。
  - 不影响项目运行逻辑、服务端主流程或面板功能。

- 修改文件：
  - `utils/core_engine.py`
  - `utils/proxy_manager.py`
  - `tests/test_proxy_manager_node_eviction.py`
- 变更内容：
  - 共享全局 Clash 节点模式的“批次切换”规则已通用化到常规量产、CPA 补货、Sub2API 补货三条主流程：每个并发批次开始前都会主动切一次节点。
  - `smart_switch_node()` 新增 `force` 参数；当批次边界明确要求切节点时，会绕过原先 10 秒冷却，不再出现“本来该切下一批节点，却被冷却吞成跳过本次请求”的偏差。
  - 当前批次若触发 `switch_node` 故障信号，仍会立即终止当前并发批次并进入下一批；下一批开头会按强制切换规则重新挑选并测活节点。
  - 新增/更新测试，覆盖“强制切换可绕过共享冷却”和“非强制切换仍保留冷却保护”两条行为。
- 修改原因：
  - 对齐预期的通用节点池模型：一个并发批次对应一个节点，批次结束后下一批再切；若当前节点连续错误达到阈值则淘汰并立刻切到下一批新节点。
  - 解决新版本共享全局节点模式里“批次本该切换，但被 10 秒冷却吞掉”与“逻辑只顾 Sub2API、没有统一到常规/CPA 流程”的结构性偏差。
- 影响范围：
  - 影响常规量产、CPA 补货、Sub2API 补货在共享全局 Clash 节点模式下的切换时机。
  - 原始代理池与独立代理池逻辑不变，只有共享单节点模式的批次切换会绕过冷却。

- 修改文件：
  - `routers/system_routes.py`
  - `utils/config_save_guard.py`
  - `utils/task_log_guard.py`
  - `utils/auth_pipeline/http_utils.py`
  - `utils/auth_pipeline/register.py`
  - `utils/core_engine.py`
  - `utils/proxy_manager.py`
  - `utils/integrations/clash_manager.py`
  - `config.example.yaml`
  - `tests/test_proxy_manager_node_eviction.py`
  - `tests/test_system_routes_config_save.py`
  - `tests/test_clash_manager_subscription_add.py`
  - `tests/test_task_log_guard.py`
- 变更内容：
  - 新增 `utils/config_save_guard.py`，把“普通保存配置时必须保留的 Clash 运行态字段”独立收敛，避免前端旧快照把 `sub_urls / selected_subscription_id / tested_nodes / evicted_nodes` 覆盖回旧值。
  - `/api/config` 现在会先合并并保留 Clash 运行态，再执行 `reload_all_configs()`；修复了“个人配置保存后运行一段时间又被旧值/默认态顶回去”的核心覆写链路。
  - `add_subscription(..., make_selected=True)` 现在会真正调用 `patch_and_update()` 下发订阅到 Mihomo，再回写 `sub_url / selected_subscription_id`；避免“新增时前端看似选中，但核心策略组仍停留在旧订阅”。
  - Clash 运行时淘汰节点不再污染 `clash_proxy_pool.blacklist` 关键词黑名单；新增 `clash_proxy_pool.evicted_nodes` 专门记录被测活淘汰的具体节点名。
  - `utils/proxy_manager.py` 切换节点时会同时参考 `blacklist` 关键词和 `evicted_nodes` 精确节点名；坏节点会从 `tested_nodes` 活节点池移除，但不会覆盖用户原有的关键词过滤配置。
  - `utils/proxy_manager.py` 写回运行配置时现在优先基于内存中的 `cfg._c` 快照，而不是只信磁盘 YAML，降低运行期专用状态被旧文件回写覆盖的概率。
  - `utils/core_engine.py` 的并发批次收敛逻辑改为：一旦任一 worker 返回 `switch_node`，会立刻标记整批中止、取消未开始的 future，并跳过“等整批 futures 顺序跑完”的旧行为。
  - 日志打印钩子现在在每次写日志后都会补查 `raise_if_current_batch_aborted()`，让同批其他 worker 在下一次日志输出时能尽快感知熔断并退出，而不是继续把当前坏节点跑到底。
  - 新增 `task_log_guard.sleep_with_batch_abort()`，把原本固定 `sleep` 改成可中断等待；同批一旦熔断，重试等待、验证码重发等待、注册成功后的同步等待都会尽快提前结束。
  - `utils/auth_pipeline/register.py` 现在在无密码重发、OTP 重发、OAuth 重试、二次安全验证码重试、OAuth 跳转追踪等长流程入口补了批次熔断检查点，减少“已判定切节点，但其他线程还继续等完整重试周期”的拖尾。
  - `utils/auth_pipeline/http_utils.py` 的底层重试退避等待也改成可中断，避免网络重试 sleep 自己把同批切节点拖慢。
  - 新增/更新测试，覆盖配置保存保留运行态、节点淘汰不污染关键词黑名单、以及原有任务熔断守卫链路。
- 修改原因：
  - 解决 GitHub 最新代码里三类实际问题：配置会被旧快照回写、节点熔断后同批任务仍继续跑、运行时坏节点写进手动关键词黑名单覆盖用户原配置。
  - 解决“新增订阅后策略组不跟着更新”的问题：新增并选中订阅时，必须同步下发到核心，而不是只写配置文件。
- 影响范围：
  - 影响常规注册、CPA 补货、Sub2API 补货三条任务调度链路。
  - 影响 Clash 配置保存链路、活节点池淘汰行为与运行态持久化格式。
  - 旧配置若仍只有 `blacklist` 而无 `evicted_nodes` 也可继续运行；新逻辑只会把后续淘汰节点写入 `evicted_nodes`。

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
- 修改文件：`utils/config.py`
- 新增文件：`SYSTEM.md`
- 新增文件：`static/css/index.css`
- 新增文件：`static/js/index.js`
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
  - Clash 订阅拉取链路已进一步拆到独立抓取模块，切换订阅时会按“代理/直连 + 多浏览器指纹”依次回退，降低部分订阅源对单一服务器指纹返回 `HTTP 403` 时的切换失败概率。
  - 订阅抓取的多路 fallback 已从 `clash_manager.py` 拆到 `utils/integrations/subscription_fetcher.py`，便于单独维护和测试。
  - Clash 订阅 YAML 解析失败时会收敛成短提示，不再把底层 `PyYAML` 的长异常原文直接回给前端。
  - Clash 订阅列表与当前选中态由专用订阅 API 维护；普通“保存配置”不再允许前端旧快照把 `sub_urls / selected_subscription_id / tested_nodes` 覆盖回旧值。
  - `fetchClashPool()` 现在会把最新订阅列表同步回前端 `config.clash_proxy_pool` 缓存，避免后续点击“保存配置”时把新订阅误覆盖掉。
  - H5 导航现已改为左侧抽屉式菜单：移动端通过顶部汉堡按钮展开/收起，桌面端继续保持原侧栏样式与布局。
  - H5 头部布局改为两段式紧凑结构：模式与进度在上层，协议/主题/语言/状态/启动按钮在下层按等宽网格排布，仅影响 767px 以下移动端。
  - H5 表格页新增移动端专用压缩样式：工具栏改为纵向堆叠、按钮与搜索框减少挤压，表格保持横向滚动并锁定最小宽度，避免表头与单元格在手机上被压成竖排或错位。
  - 吸收上游 `v14.4.1` 更新：把原本塞在 `index.html` 的移动端库存 / 云端 / 护眼样式拆到 `static/css/index.css`，并新增 `static/js/index.js` 负责页面初始化时恢复暗色主题。
  - `README.md` 已同步到上游新版说明结构，`APP_VERSION` 已提升到 `v14.4.1`。
  - 移动端顶栏右侧按钮区改为更窄屏友好的换行布局，启动按钮与模式切换不再强行挤在同一行，避免不同手机下右侧内容被截断。
  - 移动端顶栏后续又收敛回单排 flex：在保持一行的前提下进一步压缩模式条、进度条、协议/主题/语言/运行状态与启动按钮的宽度，避免不同手机上出现右侧截断。
  - 移动端顶栏再次收敛为单排横向布局，并恢复“协议 / 日间 / 护眼 / 运行中 / 启动”等完整文案；若窄屏仍放不下，改由顶部横向滚动承载，不再用单字缩写。
  - 移动端顶栏后续又回调成两列：第一列只放模式与进度条，第二列固定五个控制按钮同排平铺，保留完整文案并缩小按钮尺寸，避免不同手机下标题被挤掉。
  - 移动端第二排控制按钮进一步改为 `1:4` 宽度分配：`协议` 自身占 1 份，右侧四个按钮共享 4 份，并清掉 `协议` 外层多余内边距，避免看起来像左右留白过大。
  - 移动端第一排顶栏进一步调整为：除左侧 `nav` 汉堡按钮外，`模式` 与 `进度条` 两个区块按剩余宽度 `50% / 50%` 平分，不再使用固定进度条宽度。
  - 日间模式下的移动导航抽屉与遮罩已去掉毛玻璃透明效果，改为实色背景；仅保留护眼模式的深色质感，不再让浅色导航透出后方页面内容。
  - 吸收上游 `v14.4.3`：`APP_VERSION` 已提升到 `v14.4.3`，同时同步了集群账号上传超时配置、热加载相关修复，以及“内存池走原密码注册”的后端逻辑调整。
  - 吸收上游 `v14.4.4` 及后续 `upstream/main` 更新：同步了短信平台按供应商代理开关、验证码接管失败后的处理优化、集群账号分批上传与热加载修复，以及配置文件冲突处理相关更新。
  - 吸收上游 `v15.0.0`：同步了配置文件冲突处理、注册流程与验证码读取清洗优化、短信平台代理开关延续更新，以及新增的集群同步相关测试文件。
  - Web 控制台启动逻辑已调整为“端口被占用就顺延寻找下一个可用端口”，即便检测到已有本项目实例正在运行，也不再直接退出，而是继续在扫描区间内启动新的控制台实例。
  - Windows 下的端口占用探测已改为优先读取 `netstat`，并移除 `SO_REUSEADDR` 误判逻辑，避免 `8000` 已被监听时仍被错误判断为可用。
  - Linux / systemd 场景下的端口占用探测已改为优先读取 `ss -ltnp` 解析真实监听 PID，避免固定端口模式只能得到“端口被占用”但无法识别是否为上一轮同一服务实例。
  - Web 控制台新增 `WEB_PORT_STRICT` 固定端口模式：启用后若指定端口被占用则直接报错退出，不再自动顺延到 `8002/8003...`；适合服务器配合 Nginx 做固定反代端口。
  - Web 控制台启动逻辑进一步补强为：当检测到 systemd 运行环境时，若未显式关闭 `WEB_PORT_STRICT`，默认也会进入固定端口模式，避免服务器重启后端口漂移导致 Nginx 反代失效。
  - 固定端口模式下若检测到占用者仍是上一轮同一控制台进程，启动端会先等待端口释放再继续，而不是立即 `exit 1` 触发 systemd 连环重启。
  - 邮箱页的域名运行时列表新增“删除域名”入口；删除时会同步从发信域名池移除，并尝试一并删除 CF 托管。
  - 批量删除 CF 托管区域新增“同步从发信域名池删除”开关；开启后，批量删除会同时更新 `mail_domains`、禁用域名列表和分组配置，并同步刷新前端列表。
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
  - Clash 订阅切换失败时，后端提示文案会明确说明“当前仍保留原订阅”，避免前端误以为已成功切走但只是策略组刷新失败。
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
  - 服务器 Web 控制台在 systemd 场景下默认锁定固定端口，减少重启后自动跳端口引发的 `502` 风险。
  - 服务器在固定端口重启时会先等待上一实例释放监听端口，降低短时间内因自撞端口导致的短暂 `502`。
  - 已新增 `tests/test_subscription_fetcher.py`，覆盖订阅抓取在“代理 403 后直连成功”和“多次尝试后仍 403”两条基础回退路径。
  - Linux 单核心 Mihomo 启动后的控制接口探测等待时间已放宽，减少控制端口实际已起来但面板过早判定失败的误报。
  - Linux 单核心写入订阅配置时会先剥离与目标 `mixed-port` 冲突的监听项（如源订阅自带的 `port`），避免 Mihomo 因 `port` 与 `mixed-port` 重复占用同端口而启动后立刻退出。
  - Clash 订阅列表、选中态与 `tested_nodes` 的读写现在优先基于运行中的 `cfg._c` 配置快照，而不是直接信任磁盘 YAML，避免专用 API 修改后又被其他配置保存流程从旧快照覆盖回去。
  - Clash 前端在测速成功后会优先展示本次刚保存的 `healthy_nodes`，并同步 runtime group 名称别名，避免出现“本次测速已保存 162 个，但有效节点池仍显示旧的 28 个”这类前端展示分叉。
  - 服务器现支持 `local://imported/...` 形式的本地导入订阅源；前端仍显示其原始 `display_url`，并保持与普通订阅相同的切换、删除入口。
  - 内存预测页面不再只是展示数值，而是直接给出建议值与可执行按钮，便于快速收敛并发。
  - 并发与系统页面重新具备 Git 运维入口，可直接查看本地与远端差异并触发同步操作。
  - 并发与系统页面现在同时具备服务器保洁与紧急降载重启动作，更贴近“防卡死”而不是纯展示。
  - 服务器保洁的释放空间方式现在更直接，优先清最旧内容，而不是仅按固定保留行数截断。
  - Proxy 页面中的 Clash 区块从“基础配置 + 实例同步”恢复为更完整的运维面板，减少后端已有能力在前端失联的情况。
  - Clash 延迟测试会继续自动写入 `clash_proxy_pool.tested_nodes`，前端切换节点时优先使用有效节点池；清空后不会删除订阅或真实节点，只移除筛选结果。
  - Clash 订阅切换后的策略组来源现在与当前订阅配置保持一致，不会继续显示上一个订阅残留的策略组。
  - 主库存类页面重新回到“工具栏 / 统计区固定、表格内部滚动、分页固定”的结构，避免数据量上来后把整页撑开。
  - 云端列表分页现在基于前端已拉取的原始合并数据切片显示，筛选、搜索和翻页不再每次都重新触发全平台聚合请求。
  - 本地仓库现已完成对上游 `v14.4.1` 的代码吸收，后续再跟进移动端样式时需要同时关注 `index.html`、`static/css/index.css` 与 `static/js/index.js` 三处，不再只改单一 HTML 内联块。

## 后续约定

- 新增表格页时，优先复用 `.data-panel` 与 `.data-table-scroll`，避免再次出现外层滚动抢占的问题。
- 若某页头部筛选区明显更高，应优先在面板高度或分区布局上调整，不要退回内容撑高方案。

## 本次上游同步记录

- 修改类型：
  - 吸收 `upstream/main` 最新更新，并将本地有效版本推进到 `v15.0.3`。
- 本次同步涉及文件：
  - `index.html`
  - `routers/account_routes.py`
  - `static/js/app.js`
  - `utils/config.py`
  - `utils/core_engine.py`
  - `utils/db_manager.py`
  - `utils/auth_core.cpython-311-aarch64-linux-gnu.so`
  - `utils/auth_core.cpython-311-darwin.so`
  - `utils/auth_core.cpython-311-x86_64-linux-gnu.so`
  - `utils/auth_core.pyd`
- 本次吸收的主要变化：
  - `APP_VERSION` 提升到 `v15.0.3`。
  - CPA 与 Sub2API 的库存报警阈值在设为 `0` 时，改为跳过云端库存巡检，直接按单次补发量执行补货。
  - 前端在 CPA / Sub2API 阈值输入区新增了“阈值为 0 时跳过云端全量获取”的提示文案。
  - Team 模式超速开关开启时会同步确保 `team_mode.enable = true`。
  - 批量删除账号的路由与数据库删除实现重新对齐：路由直接调用批量删除，数据库层负责按分块执行，避免 SQL 过长问题。
  - 云端库同步节流逻辑被放宽，刷新云端库时更积极地同步本地库。
  - 静态资源版本号更新到较新的上游缓存版本。
- 合并时的本地处理：
  - `index.html` 出现的唯一冲突是静态资源版本号，已保留较新的上游版本号；功能逻辑未发生手工改写冲突。
- 影响范围：
  - 影响补货策略、账号删除路径、Team 模式启用行为，以及前端静态资源缓存失效版本。
  - 后续若排查“阈值为 0 仍请求云端库存”的问题，应以本次同步后的逻辑为准。

## 记忆同步记录

- 新增文件：`.codex/skills/project-memory/SKILL.md`
- 修改原因：
  - 为当前项目建立可长期复用的项目级记忆 skill。
  - 将稳定的架构、部署约束、服务器映射、前端约定与长期决策从对话上下文中迁移到仓库内，降低后续切换 session 时的信息丢失风险。
- 记录内容：
  - 项目目标、当前架构、稳定约定、重要决策、部署与服务器记忆、已知问题、后续跟进点与安全清理说明。
- 影响范围：
  - 不影响运行逻辑，仅新增项目维护记忆层。
  - 后续需要恢复上下文时，可优先读取 `.codex/skills/project-memory/SKILL.md`，不必依赖历史聊天记录。

## 记忆补抽记录

- 修改文件：`.codex/skills/project-memory/SKILL.md`
- 修改原因：
  - 继续从历史 `opaiRe` 会话中提炼尚未沉淀的稳定记忆，避免重要运行规律只留在旧 session 中。
- 本次补充的稳定信息：
  - `Sub2API` 在关闭自动测活时，补货判断仍会直接读取云端全量库存；该链路本身较重，较容易受本地超时或 DNS 波动影响。
  - Clash / Mihomo 相关问题排查时，不能只看面板显示值，必须同时核对 `data/config.yaml`、`data/mihomo-pool/manual-config.yaml` 与实际监听端口。
  - `default_proxy` 是代理设置页与 Clash 订阅更新链路共用的关键配置值；若服务器表现异常，优先验证服务器侧保存值是否真的变更。
  - Server 1 若出现 `22` 端口可达但 SSH banner 超时，应优先按主机运行态异常处理，重点查 `sshd`、服务启动时序、负载、磁盘与 OOM，而不是先怀疑本地代码或 Git。
  - 服务器自动清理应保持保守策略，优先清日志、缓存与 Python 缓存目录，不应误碰运行态目录。
- 影响范围：
  - 不影响业务逻辑，仅增强项目级长期记忆的完整度。
  - 后续做服务器排障、代理排障与 Sub2API 仓库相关任务时，可先读取该记忆，减少重复查证成本。

## Session 清理记录

- 执行动作：
  - 已按当前用户指令完成 `opaiRe` 旧 session 清理，并额外删除此前生成的本地备份目录。
- 已清理的旧 session：
  - `019de390-b84d-7402-9471-fbf13a6d6fb7`
  - `019dfcf3-2190-74c1-8ac1-955cf7676129`
- 保留的活跃 session：
  - `019e45c4-1c2c-7492-9384-95eb94639aae`
- 影响范围：
  - 不影响项目代码与运行逻辑。
  - 已清理的旧 session 当前不再保留本地备份，如需追溯，不能再从该本机的备份目录恢复。

## Server 3 轻量部署记录

- 修改文件：
  - `AGENTS.md`
  - `.codex/skills/project-memory/SKILL.md`
  - `SYSTEM.md`
- 修改原因：
  - 将新建的 Server 3 从历史 session 中抽取为稳定项目记忆，避免后续部署和排障时反复追溯旧对话。
  - 明确 Oracle E2 小规格服务器的轻量部署边界，避免误走 Docker / Watchtower 这类重部署方式。
- Server 3 当前记录：
  - 当前公网 IP：`132.226.99.236`
  - SSH 用户：`opc`
  - SSH key：`C:\Users\admin\Desktop\file\ssh-key-2026-05-27.key`
  - 推荐远端项目路径：`/home/opc/opaiRe`
  - 已知 swap 状态：`/swapfile-oci` 已扩容为 `4G`，总 swap 约 `4.5GiB`
- 轻量部署决策：
  - Server 3 默认用于 opaiRe Web 面板和轻量管理，不作为高并发执行机。
  - 默认不使用 Docker、Watchtower、浏览器 worker 或 Clash 重任务。
  - 推荐使用 Python 3.11 venv 源码部署，并控制为单 worker、低并发、固定 `WEB_PORT`。
  - 上传代码时应排除 `.git`、`.venv`、`__pycache__`、`.pytest_cache`、`tests` 与不必要的大型运行态数据。
- 影响范围：
  - 本次只更新项目文档与长期记忆，不改变业务逻辑、接口行为或现有 Server 1 / Server 2 部署方式。
  - 后续用户说 `detect 3`、`restart 3` 或部署到 Server 3 时，应按此记录优先处理。

## Server 3 轻量源码部署执行记录

- 修改文件：
  - `SYSTEM.md`
- 远端变更：
  - 将本地项目打包为轻量源码包并上传到 Server 3。
  - 远端项目路径：`/home/opc/opaiRe`
  - 轻量包大小：约 `10.5MB`
  - 解压后源码目录大小：约 `27MB`
  - 已排除 `.git`、`.venv`、`data`、`__pycache__`、`tests`、`.codex`、`.github`、Docker 相关文件和本地 `config.yaml`。
  - 远端自动生成默认 `data/config.yaml` 与 `data/data.db`。
  - 已安装 Oracle Linux 包：`python3.11`、`python3.11-pip`
  - 已在 `/home/opc/opaiRe/.venv` 创建 Python 3.11 venv 并安装 `requirements.txt`。
  - 已创建并启用 systemd 服务：`opaire-lite.service`
- 运行方式：
  - 服务仅绑定 `127.0.0.1:8000`，不直接暴露公网端口。
  - systemd 使用 `/bin/bash -lc` 启动 venv Python，避免 Oracle Linux / systemd 直接执行 home 目录 venv symlink 时触发 `203/EXEC` 权限问题。
  - 访问建议使用 SSH tunnel：`ssh -i C:\Users\admin\Desktop\file\ssh-key-2026-05-27.key -L 8000:127.0.0.1:8000 opc@132.226.99.236`
- 验证结果：
  - `systemctl is-active opaire-lite.service` 返回 `active`。
  - `ss -ltnp` 显示服务监听 `127.0.0.1:8000`。
  - 远端 `curl http://127.0.0.1:8000/` 返回 `200`。
  - 当前进程 RSS 约 `22MB`，启动峰值约 `98MB`，Server 3 总 swap 约 `4.5GiB`。
- 注意事项：
  - 当前未开放 OS 防火墙或 OCI 安全组的公网 `8000` 入站，避免默认密码面板裸露公网。
  - 若后续需要公网访问，应先修改默认密码，再考虑限制来源 IP 或改用 Nginx/HTTPS。
  - Server 3 仍只适合 Web 面板和轻量管理，不适合高并发注册、Clash 重任务、浏览器 worker 或 Docker/Watchtower。

## Server 3 Nginx 反代记录

- 修改文件：
  - `AGENTS.md`
  - `.codex/skills/project-memory/SKILL.md`
  - `SYSTEM.md`
- 远端变更：
  - Server 3 已安装 `nginx`。
  - 新增 Nginx 反代配置：`/etc/nginx/conf.d/opaire.conf`
  - Nginx 监听宿主机 `80`，反代到 `http://127.0.0.1:8000`。
  - `opaire-lite.service` 仍只绑定 `127.0.0.1:8000`，不直接暴露 Python 服务。
  - 已通过 `firewall-cmd --permanent --add-service=http` 放行 OS firewalld 的 HTTP 服务。
  - 已启用 SELinux 标准反代布尔值 `httpd_can_network_connect`，允许 Nginx 连接本机后端端口。
- 验证结果：
  - `nginx -t` 通过。
  - `systemctl is-active nginx` 返回 `active`。
  - `systemctl is-active opaire-lite.service` 返回 `active`。
  - Server 3 本机 `curl http://127.0.0.1/` 返回 `200`。
  - Server 3 本机 `curl http://127.0.0.1:8000/` 返回 `200`。
  - 本机到 Server 3 公网 `22/tcp` 可达，但 `80/tcp` 仍超时。
- 当前阻塞：
  - Server OS 内部已经完成反代与防火墙放行。
  - 外网访问仍需在 OCI 控制台的 VCN Security List 或 NSG 中新增入站规则：source `0.0.0.0/0`，protocol `TCP`，destination port `80`。
- 安全说明：
  - 当前只做 HTTP 反代，未配置 HTTPS。
  - 若要长期公网访问，应尽快改掉面板默认密码，并优先配置域名、HTTPS 或来源 IP 限制。

## Server 3 域名与 HTTPS 准备记录

- 修改文件：
  - `SYSTEM.md`
- 域名状态：
  - `dazhou.bond` A 记录已解析到 `132.226.99.236`。
  - `www.dazhou.bond` A 记录已解析到 `132.226.99.236`。
- Server 端绑定：
  - `/etc/nginx/conf.d/opaire.conf` 的 `server_name` 已配置为 `dazhou.bond www.dazhou.bond 132.226.99.236`。
  - Server 3 本机使用 `Host: dazhou.bond` 请求 `http://127.0.0.1/` 返回 `200`。
  - firewalld 已放行 `http` 与 `https` 服务。
- 当前 HTTPS 阻塞：
  - 本机外网访问 `http://dazhou.bond/` 超时。
  - 本机外网访问 `https://dazhou.bond/` 超时。
  - Server 内部 Nginx 与 opaiRe 均正常，阻塞点仍是 OCI VCN Security List 或 NSG 未放行公网 `80/tcp` 与 `443/tcp`。
- 下一步：
  - 在 OCI 控制台添加入站规则：`80/tcp` 与 `443/tcp`，来源 `0.0.0.0/0`。
  - 放行后再安装/运行 ACME 客户端签发 Let’s Encrypt 证书，并将 Nginx 切换到 HTTPS。

## Server 3 HTTPS 启用记录

- 修改文件：
  - `AGENTS.md`
  - `.codex/skills/project-memory/SKILL.md`
  - `SYSTEM.md`
- 远端变更：
  - 已通过 certbot webroot 模式为 `dazhou.bond` 与 `www.dazhou.bond` 签发 Let's Encrypt 证书。
  - 证书路径：`/etc/letsencrypt/live/dazhou.bond/fullchain.pem`
  - 私钥路径：`/etc/letsencrypt/live/dazhou.bond/privkey.pem`
  - 证书有效期至：`2026-08-26 04:38:59 UTC`
  - Nginx 已配置 `80` 跳转到 HTTPS。
  - Nginx 已配置 `443 ssl http2`，反代到 `http://127.0.0.1:8000`。
  - 已新增 `certbot-renew.service` 与 `certbot-renew.timer`，每天两次检查续期，续期后自动 reload Nginx。
- 验证结果：
  - 外网 `http://dazhou.bond/` 返回 `301` 到 `https://dazhou.bond/`。
  - 外网 `https://dazhou.bond/` 可返回 opaiRe 页面 HTML。
  - 外网 `https://www.dazhou.bond/` 使用同一证书并能到达 Nginx / 后端。
  - Server 3 本机 `curl --resolve dazhou.bond:443:127.0.0.1 https://dazhou.bond/` 返回 `200`。
  - `nginx`、`opaire-lite.service` 与 `certbot-renew.timer` 均处于启用 / 运行状态。
- 安全说明：
  - 当前面板已经可公网 HTTPS 访问，应尽快修改默认面板密码。
  - 若后续需要更严格访问控制，可在 Nginx 或 OCI Security List / NSG 限制来源 IP。

## Server 3 Mihomo 轻量接管记录

- 修改文件：
  - `SYSTEM.md`
  - `utils/integrations/clash_manager.py`
- 远端变更：
  - 已安装 MetaCubeX Mihomo `v1.19.25` 的 `linux-amd64-v1` 二进制到 `/usr/local/bin/mihomo`。
  - 曾临时创建独立 `mihomo-lite.service` 用于验证本机轻量核心可运行，后续已停用并 disable。
  - 当前选择让 opaiRe 自带 Clash/Mihomo 管理模块接管 Mihomo，而不是使用独立 systemd Mihomo 服务。
- 当前 opaiRe Clash 配置：
  - `clash_proxy_pool.enable: true`
  - `clash_proxy_pool.pool_mode: false`
  - `default_proxy: http://127.0.0.1:7897`
  - `clash_proxy_pool.api_url: http://127.0.0.1:9097`
  - `clash_proxy_pool.test_proxy_url: http://127.0.0.1:7897`
  - `clash_proxy_pool.secret` 已设置，但不在文档中记录明文。
- 当前运行状态：
  - opaiRe 已识别为 `linux_single_core` 模式。
  - 订阅保存后，`data/mihomo-pool/manual-config.yaml` 已生成，`mihomo-local` 可由 opaiRe 直接启动。
  - Linux 单核心模式写入 Mihomo 配置时会强制使用 `allow-lan: false` 与 `bind-address: 127.0.0.1`，避免轻量服务器把代理端口暴露到公网网卡。
- 注意事项：
  - Server 3 只适合轻量单核心使用，不适合 Docker Clash 池、多实例或高频测速。
  - Mihomo 端口应保持只监听本机回环地址，不对公网开放。
  - 若面板显示本地单核心停止，优先检查 `data/mihomo-pool/manual-config.yaml` 是否存在、`7897/9097` 是否监听，以及 `data/mihomo-pool/mihomo-core.log`。

## Server 3 Sub2API 与 Mihomo 启动排障记录

- 修改文件：
  - `utils/core_engine.py`
  - `utils/integrations/clash_manager.py`
  - `SYSTEM.md`
- 变更内容：
  - `RegEngine.stop()` 现在会先通知任务停止并短暂等待当前线程退出，再决定是否关闭共享 executor，避免任务线程仍在调用 `loop.run_in_executor()` 时出现 `cannot schedule new futures after shutdown`。
  - `_ensure_executor()` 会在检测到 executor 已 shutdown 时重建线程池，避免旧线程池状态污染后续 Sub2API / CPA 补货任务。
  - Linux 单核心 Mihomo 写入配置时固定 `allow-lan: false` 与 `bind-address: 127.0.0.1`，避免 `7897` 代理端口监听公网网卡。
- Server 3 验证结果：
  - `utils/core_engine.py` 与 `utils/integrations/clash_manager.py` 已同步到 `/home/opc/opaiRe`。
  - `python -m py_compile utils/integrations/clash_manager.py` 通过。
  - `sync_single_core_runtime_from_saved_config()` 返回成功，`mihomo-local` 为 `running`。
  - `ss -ltnp` 显示 opaiRe 监听 `127.0.0.1:8000`，Mihomo 监听 `127.0.0.1:7897` 与 `127.0.0.1:9097`。
  - `opaire-lite.service`、`nginx`、`certbot-renew.timer` 均为 `active`，本机 `curl http://127.0.0.1:8000/` 返回 `200`。
- 影响范围：
  - 只影响任务停止 / 重启时的线程池生命周期，以及 Linux 单核心 Mihomo 的监听安全边界。
  - 不改变订阅保存、节点策略组、HTTPS 反代或 Docker Clash 池逻辑。

## OpenAI-CPA 内存池收信排障记录

- 修改文件：
  - `routers/service_routes.py`
  - `utils/email_providers/mail_service.py`
  - `tests/test_mail_service_code_wait.py`
  - `SYSTEM.md`
- 问题现象：
  - Cloudflare Email Routing 后台可看到发往 `zsae1du.qzz.io` 的 OpenAI 验证邮件，但 opaiRe 日志显示 OpenAI-CPA 内存池未拉取到验证码。
- 根因：
  - Server 3 当前使用 `email_api_mode: openai_cpa`，验证码不直接从 CF 邮件列表查询，而是依赖 Worker 将邮件 POST 到面板 `/api/webhook/email` 后写入 60 秒 TTL 内存池。
  - 线上 `openai-cpa` Worker 的 `EMAIL_WEBHOOK_URL` 仍指向旧面板 `https://mycodexy.duckdns.org`，导致邮件被推送到旧地址，当前 Server 3 内存池收不到。
- 远端修复：
  - 已将 Cloudflare Worker `openai-cpa` 的 `EMAIL_WEBHOOK_URL` 更新为 `https://dazhou.bond`。
  - 已验证 Worker 原有 `TEMP_MAIL_DB` D1 绑定被保留。
  - 已用测试 webhook 验证 Server 3 `/api/webhook/email -> 内存池 -> /api/ext/get_mail_code` 链路可正确取码。
- 代码修复：
  - `/api/cloudflare/deploy_worker` 不再因为 Worker 已存在就直接跳过；后续会继续更新 Worker 代码与 webhook 环境变量。
  - 重新部署既有 Worker 时会保留 D1 / KV / R2 / Durable Object / Service 等资源型 binding，避免更新 webhook 时误删已有资源绑定。
  - `cloudflare_temp_email` 模式增加管理端按地址补捞逻辑：当 mailbox JWT 查询为空时，可用 `admin_auth` 从 `/admin/mails?address=...` 再查一次。
- 注意事项：
  - OpenAI-CPA 内存池 TTL 为 60 秒，项目重启或 webhook 延迟超过 TTL 都会造成 CF 后台有信但项目取不到。
  - 后续更换面板域名、服务器或 Worker 名称时，必须重新部署 / 更新 Worker 环境变量，不能只改 CF 邮件路由。

## 服务器更新方式与授权状态保护记录

- 修改文件：
  - `AGENTS.md`
  - `.codex/skills/project-memory/SKILL.md`
  - `SYSTEM.md`
- 更新规则：
  - Server 1 默认按 Git 方式更新；只有远端 Git / HTTPS fetch 异常时，才改用本地到服务器的文件同步兜底。
  - Server 3 默认按轻量源代码覆盖方式更新，不使用 Docker / Watchtower，不把本地 `.git`、`.venv`、`data`、测试目录或缓存上传到远端。
  - Server 3 更新必须是原地覆盖源码，保留远端 `data/`、`.venv`、`.codex`、`data/mihomo-pool` 等运行态目录。
- 授权 / 机器码说明：
  - 当前项目页面与后端路由显示授权文件、HWID 与租约状态会存放在系统库中，例如 `auth_license_file`、`auth_hwid_data` 等键。
  - Server 3 使用源代码包覆盖源码本身不会让项目识别成新机器；只要仍是同一台服务器，并且远端 `data/data.db` 与配置状态被保留，授权 / HWID 状态应继续沿用。
  - 风险点是删除、重建或用本地文件覆盖 Server 3 的 `data/data.db` / `data/config.yaml`，或把其他机器的数据库迁移到 Server 3；这种情况下才可能触发机器码 / 授权不匹配。
- 执行约束：
  - 普通 Server 3 更新禁止同步本地 `data/`。
  - 如确实要迁移数据库或清理授权 / HWID，必须先单独确认，因为这会影响机器识别和授权状态。

## Server 4 轻量部署与 Mihomo 接管记录

- 修改文件：
  - `AGENTS.md`
  - `.codex/skills/project-memory/SKILL.md`
  - `SYSTEM.md`
- 远端变更：
  - 新增 Server 4：`137.131.12.149`，SSH 用户 `opc`，SSH key `C:\Users\admin\Desktop\file\ssh-key-2026-05-27.key`。
  - 按 Server 3 的轻量方式部署到 `/home/opc/opaiRe`，不使用 Docker / Watchtower。
  - 已安装 `python3.11`、`python3.11-pip`、`policycoreutils-python-utils`，并在 `/home/opc/opaiRe/.venv` 创建 venv 后安装 `requirements.txt`。
  - 已创建并启用 `opaire-lite.service`，固定 `WEB_HOST=127.0.0.1`、`WEB_PORT=8000`、`WEB_PORT_STRICT=1`。
  - 已启用 `nginx`，主 Nginx 配置当前反代到 `http://127.0.0.1:8000`。
  - 已通过 firewalld 放行 `http`，并开启 SELinux `httpd_can_network_connect`。
  - 已安装 MetaCubeX Mihomo `v1.19.25` 到 `/usr/local/bin/mihomo`。
- Mihomo 决策：
  - Server 4 与 Server 3 保持一致，由 opaiRe 自带 Clash/Mihomo 管理模块接管 Mihomo。
  - 不使用独立 `mihomo-lite.service`，避免与面板保存订阅、端口和控制接口状态分叉。
  - 当前配置为 `clash_proxy_pool.enable: true`、`clash_proxy_pool.pool_mode: false`、`default_proxy: http://127.0.0.1:7897`、控制接口 `http://127.0.0.1:9097`。
  - `clash_proxy_pool.secret` 已设置，但不在文档中记录明文。
  - 当前尚未保存订阅，因此 `data/mihomo-pool/manual-config.yaml` 尚未生成，`7897/9097` 未监听属于正常状态。
- 验证结果：
  - `python -m py_compile wfxl_openai_regst.py routers/service_routes.py utils/email_providers/mail_service.py` 已通过。
  - `systemctl is-active opaire-lite.service` 返回 `active`。
  - `systemctl is-active nginx` 返回 `active`。
  - `systemctl is-enabled opaire-lite.service` 与 `systemctl is-enabled nginx` 均返回 `enabled`。
  - 远端 `curl http://127.0.0.1:8000/` 返回 `200`。
  - 远端 `curl http://127.0.0.1/` 返回 `200`。
  - 本机外网访问 `http://137.131.12.149/` 返回 `200`。
  - opaiRe `get_pool_status()` 返回 `linux_single_core`，实例数为 `1`。
- 注意事项：
  - Server 4 规格很小，约 `498MiB` RAM、约 `2.5GiB` swap、约 `30GiB` root disk，只适合 Web 面板和个人轻量使用。
  - 普通更新必须保留远端 `data/`、`.venv`、`.codex`、`data/mihomo-pool`，禁止用本地 `data/` 覆盖远端运行态。
  - 若后续保存订阅后排查 Mihomo，应同时核对 `data/config.yaml`、`data/mihomo-pool/manual-config.yaml`、`7897/9097` 监听与 `data/mihomo-pool/mihomo-core.log`。
  - 当前 Server 4 尚未绑定域名或 HTTPS；若需要 HTTPS，应先提供域名并确认 DNS A 记录指向 `137.131.12.149`。

## Server 4 代理保存卡顿排查记录

- 修改文件：
  - `routers/service_routes.py`
  - `SYSTEM.md`
- 问题现象：
  - Server 4 代理开启后保存配置体感较慢，用户怀疑 Clash/Mihomo 鉴权 `SECRET` 不正确。
- 排查结果：
  - Server 4 `clash_proxy_pool.secret` 已设置，未在日志或文档中记录明文。
  - 使用当前配置访问 Mihomo 控制端 `/version` 与 `/proxies` 返回 `200`，说明 `SECRET` 与控制端匹配。
  - opaiRe 识别模式为 `linux_single_core`，`7897` 与 `9097` 均只监听 `127.0.0.1`。
  - `sync_single_core_runtime_from_saved_config()` 实测耗时约 `3.15s`，主要来自写入运行配置、重启 Mihomo 并等待控制端恢复；在 Server 4 约 `498MiB` RAM 的小规格上属于可预期延迟。
  - 日志发现 `/api/sub2api/groups` 在 `SUB2API_KEY` 为 `None` 时会触发 `None.strip()`，可能让配置保存后的前端刷新看起来卡顿或异常。
- 本次修复：
  - `routers/service_routes.py` 对 `SUB2API_URL` 与 `SUB2API_KEY` 增加 `None` 安全转换，空值时返回“请先保存 Sub2API URL 和 API key”，不再抛 500。
- 影响范围：
  - 只影响 Sub2API 分组读取接口的空配置容错。
  - 不改变 Mihomo `SECRET`、订阅保存、单核心启动或节点切换逻辑。

## Server 4 xh-ai.cyou 域名绑定记录

- 修改文件：
  - `SYSTEM.md`
- 远端变更：
  - DNS 检查显示 `xh-ai.cyou` 与 `www.xh-ai.cyou` 均已解析到 Server 4：`137.131.12.149`。
  - 已备份并修改 Server 4 `/etc/nginx/nginx.conf`，将主 server block 的 `server_name` 更新为 `xh-ai.cyou www.xh-ai.cyou 137.131.12.149 _`。
  - Nginx 仍反代到 `http://127.0.0.1:8000`，不直接暴露 Python 服务。
- 验证结果：
  - 修改后 `nginx -t` 通过。
  - Server 4 本机使用 `Host: xh-ai.cyou` 请求 `http://127.0.0.1/` 返回 `200`。
  - Server 4 本机使用 `Host: www.xh-ai.cyou` 请求 `http://127.0.0.1/` 返回 `200`。
  - 公网 `http://www.xh-ai.cyou/` 曾返回 `200`。
  - 对 `/` 发 `HEAD` 会返回 `405`，这是后端只允许 `GET` 的表现，不代表域名绑定失败。
- HTTPS 状态：
  - 最初尝试在 Server 4 安装 `certbot` / `python3-certbot-nginx`，但 `dnf install` 在小规格实例上长时间未返回，并导致 SSH banner exchange 超时、HTTP 请求超时。
  - 重启后已清理 `/var/cache/dnf`，缓存从约 `681M` 降为 `0`。
  - 后续改用更轻的 `acme.sh` + webroot HTTP-01 方式签发 Let's Encrypt 证书。
  - 已在 Nginx 中增加 `/.well-known/acme-challenge/` 静态路径，webroot 为 `/var/www/acme-challenge`。
  - 已安装证书到 `/etc/nginx/ssl/xh-ai.cyou/fullchain.cer`，私钥到 `/etc/nginx/ssl/xh-ai.cyou/xh-ai.cyou.key`。
  - 已新增 Nginx `443 ssl` server block，反代到 `http://127.0.0.1:8000`。
  - 已通过 firewalld 放行 `https`。
  - `acme.sh` 已安装 cron 自动续期任务，续期后 reload Nginx。
- HTTPS 验证结果：
  - 外网 `https://xh-ai.cyou/` 返回 `200`。
  - 外网 `https://www.xh-ai.cyou/` 返回 `200`。
  - Server 4 本机 `curl --resolve xh-ai.cyou:443:127.0.0.1 https://xh-ai.cyou/` 返回 `200`。
  - 证书签发方为 Let's Encrypt，当前证书到期时间为 `2026-08-27 02:33:38 GMT`。
- 注意事项：
  - Server 4 内存约 `498MiB`，安装系统包时可能显著拖慢 SSH / Nginx / opaiRe。
  - Server 4 不建议再安装 `python3-certbot-nginx` 这类较重插件；后续域名证书优先沿用 `acme.sh` + webroot。
