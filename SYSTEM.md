# SYSTEM.md

本文件只保存 opaiRe 的長期維護關鍵資訊。流水帳、臨時測試、完整命令輸出、密鑰、Token、Cookie、資料庫內容、完整代理連結與訂閱內容不得寫入此文件。

## 項目目標

opaiRe 是一套註冊與資源管理系統，包含單頁 Web 控制台與 Python 後端。核心能力包括註冊流程控制、帳號庫管理、郵箱與雲資源管理、代理 / Mihomo 操作、團隊帳號與運維輔助。

## 代碼結構

- `wfxl_openai_regst.py`：主要啟動入口。
- `index.html`：前端主入口。
- `static/css/`、`static/js/`：前端樣式與腳本。
- `routers/`：後端路由。
- `utils/`：共用工具與外部整合。
- `data/`：本機 / 服務端運行資料與配置，通常不提交。
- `tests/`：測試文件。
- `deploy/`、`Dockerfile`、`docker-compose*.yml`：部署相關文件。
- `.codex/docs/`：只放 Codex 私有運維摘要，不放公開產品文檔。

## 維護規則

- 新增或修改核心行為時，同步更新本文件，保持短而準。
- 不把臨時排障過程、完整日誌、完整命令輸出塞進文檔。
- 不記錄 secret、raw proxy link、API key、Cookie、Token、資料庫內容或私鑰。
- 服務端排障先驗證現場狀態，再修改配置。
- Server 3 / Server 4 輕量部署保留遠端 `data/`、`.venv`、`.codex` 與運行態資料。
- 測試與臨時文件放到 `tests/` 或 `.codex/tmp/`，用完清理。

## 伺服器速查

### Server 1

- 角色：主項目服務器。
- Host：`mycodexy.duckdns.org`
- SSH：`ubuntu@mycodexy.duckdns.org`
- Key：`C:\Users\admin\Desktop\file\sub2.pem`
- 遠端項目：`/home/ubuntu/opaiRe`
- 注意：排障時以遠端 `data/config.yaml`、systemd 狀態、監聽端口與日誌為準。

### Server 2

- 角色：Sub2API / 中轉服務器。
- Host：`mysuby.duckdns.org`
- SSH：`ec2-user@mysuby.duckdns.org`
- Key：`C:\Users\admin\Desktop\file\sub2.pem`
- 典型形態：Nginx `80/443` 反代到 Docker `127.0.0.1:8080`。

### Server 3

- 角色：Oracle 輕量 Web / 訂閱 / Reality / TG 後端。
- OCI instance：`instance-20260613-1403`
- 公網入口：共享 NLB `132.226.146.175`
- 私網 IP：`10.31.0.239`
- 域名：`dazhou.bond`、`www.dazhou.bond`
- SSH：`opc@132.226.146.175`
- Key：`C:\Users\admin\Desktop\file\ssh-key-2026-05-27.key`
- 遠端項目：`/home/opc/opaiRe`
- Web：`opaire-lite.service`，通常綁定 `127.0.0.1:8000`。
- 訂閱發布目錄：`/var/www/proxy-subs/`
- 運維原則：輕量源碼部署，不默認 Docker；保留遠端 `data/` 與 `.venv`。

### Server 4

- 角色：Oracle 代理後端。
- 權威 instance：`code`
- 權威私網 IP：`10.0.0.154`
- 公網入口：共享 NLB `132.226.146.175`，經 Server 3 / NLB 分流。
- 域名：`xh-ai.cyou`、`www.xh-ai.cyou`
- SSH：經 Server 3 ProxyCommand 連 `opc@10.0.0.154`
- Key：`C:\Users\admin\Desktop\file\ssh-key-2026-05-27.key`
- 重要規則：不要把 `instance-20260604-1123 / 10.0.0.112` 當作當前 Server 4 代理後端，除非未來明確遷移並重新驗證。

## 代理與訂閱當前權威

- `dazhou.bond`、`www.dazhou.bond`、`xh-ai.cyou`、`www.xh-ai.cyou` 解析到共享 NLB `132.226.146.175`。
- Server 3 Nginx stream 使用 SNI 分流：
  - Web / 訂閱 SNI：轉到本機 HTTPS 後端。
  - Reality SNI `www.cloudflare.com`：轉到 Server 4 `10.0.0.154:24444`。
- 主要 Reality 入口：
  - Server 4：`xh-ai.cyou:443`，Reality SNI `www.cloudflare.com`，後端 `10.0.0.154:24444`。
  - Server 3：保留 `server3-reality-2053` / `24443` 相關配置時需以遠端 Xray 與訂閱文件重新確認。
- 主訂閱文件：
  - Clash：`/var/www/proxy-subs/clash.yaml`
  - V2Ray/Base64：`/var/www/proxy-subs/v2ray.txt`
  - 公網入口：`https://dazhou.bond/clash`、`https://dazhou.bond/sub`、`https://xh-ai.cyou/clash`、`https://xh-ai.cyou/sub`
- 不在文檔中保存 raw UUID、公鑰、short-id、完整 VLESS / HY2 / SOCKS / MTProto 連結。

## Telegram 代理狀態

- 使用者希望 Telegram 獨立，不依賴本機 Mihomo，也不依賴第三方節點。
- 本機連結記錄：`C:\Users\admin\Desktop\file\tg-links.txt`
- 該文件包含代理 secret / 密碼，不貼到聊天或文檔。
- 當前 TG App 直連入口：
  - Server 3 MTProto：`dazhou.bond:18453`
  - Server 4 MTProto：`xh-ai.cyou:18454`
  - Server 3 SOCKS5：`dazhou.bond:18443`
  - Server 4 SOCKS5：`xh-ai.cyou:18444`
- SOCKS5 使用密碼認證，遠端憑據文件：`/root/tg_socks_credentials.json`。
- 2026-06-20 本機測速結論：
  - MTProto 最高約 `900KB/s`，不建議作為提速主路徑。
  - SOCKS5 本機 20MB 測試曾達約 `3.76MB/s`（Server 3）與 `4.68MB/s`（Server 4）。
  - Telegram 下載仍低時，優先懷疑 Telegram CDN / 單文件源 / 客戶端限速，而不是只調 TCP buffer。

## 已知部署偏好

- Server 3 / 4：優先輕量源碼部署，不默認 Docker / Watchtower。
- 同步 Server 3 / 4 時不要覆蓋遠端：
  - `data/config.yaml`
  - `data/data.db`
  - `data/mihomo-pool/`
  - `.venv`
  - `.codex`
- Server 1：Git 正常時優先遠端 `git pull --ff-only`；若遠端 HTTPS Git TLS 出錯，再走本機 SSH 文件同步。
- 上游同步時需同步檢查 upstream release tag / version，不只合併 commit。

## 已知問題

- 本地到 OCI Phoenix / NLB 的線路會造成速度波動；雲端互測速度不能直接代表本地 Telegram 體感。
- Server 3/4 的歷史拓撲多次變更，排障時以本文件的「當前權威」和遠端現場驗證為準。
- `SYSTEM.md` 曾累積大量流水帳；2026-06-20 已精簡為長期維護摘要。

## 文檔清理記錄

- 2026-06-20：清理專案文檔，保留根目錄 `README.md`、`AGENTS.md`、精簡版 `SYSTEM.md`。
- `.codex/docs/` 改為精簡運維記錄區，保留：
  - `README.md`：文檔索引與規則。
  - `oracle-proxy-current.md`：Oracle / NLB / Reality / TG 當前權威狀態。
  - `maintenance-history.md`：歷史操作精簡摘要。
  - `new-computer-handoff.md`：新機接手最小清單。
- 已吸收並清理的舊長文檔包括 6/19 修復長摘要、OCI NLB/NAT 長 runbook、Server 3 重建流水筆記。
- 若未來需要詳細命令，應重新查遠端現場與 shell history，而不是依賴過期長文檔。
