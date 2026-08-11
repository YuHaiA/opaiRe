# Maintenance History

本文件是歷史運維記錄的精簡版。詳細命令與臨時測試結果已刪除；需要再查時以遠端現場、shell history、Git diff 與 OCI 控制台為準。

## 2026-06-13 Server 3 重建與 NLB / NAT

- Server 3 重建為 `instance-20260613-1403`，私網 IP `10.31.0.239`。
- 共享 NLB `132.226.146.175` 成為服務入口。
- `dazhou.bond` / `www.dazhou.bond` 指向共享 NLB。
- 恢復 Nginx、TLS、Xray、訂閱文件與輕量 `opaire-lite.service`。
- 訂閱入口恢復：`/clash`、`/sub`。

## 2026-06-13 至 2026-06-14 雙節點代理調整

- Server 3 / Server 4 訂閱合併，保留兩台服務器節點。
- 測試多個 Reality 備用端口與 443 SNI stream 分流。
- HY2 UDP 443 曾作為對照，對本地有改善但未達雲端速度。
- 後續精簡訂閱，避免測試節點過多造成客戶端混亂。

## 2026-06-19 Server 4 權威後端校正

- 排查 `xh-ai.cyou` / Server 4 代理漂移問題。
- 當前權威結論：Server 4 代理後端是 `code / 10.0.0.154`。
- 需要避免使用舊的 `instance-20260604-1123 / 10.0.0.112` 作為 Server 4 後端。
- `server4-reality-443` 應對齊 `code` 機器的 Xray 配置與訂閱。

## 2026-06-20 TG 獨立 SOCKS5 恢復

- 使用者希望 Telegram 不依賴本機 Mihomo 或第三方節點。
- 恢復 Server 3 / Server 4 認證 SOCKS5 TG 入口。
- 本機 `tg-links.txt` 保留 2 條 MTProto + 2 條 SOCKS5。
- SOCKS5 本機測速可突破 `3MB/s`，建議 Telegram App 優先測 SOCKS5。

## 2026-06-20 文檔整理

- 根目錄 `README.md` 壓縮為公開快速說明。
- 根目錄 `SYSTEM.md` 壓縮為長期維護摘要。
- `.codex/docs` 從多份長流水整理為索引、當前代理狀態、歷史摘要與新機接手清單。
