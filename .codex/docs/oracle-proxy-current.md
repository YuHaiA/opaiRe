# Oracle Proxy Current State

更新日期：2026-06-20

## 權威拓撲

| 角色 | 實例 | 公網入口 | 私網 IP | 域名 | 職責 |
| --- | --- | --- | --- | --- | --- |
| Server 3 | `instance-20260613-1403` | NLB `132.226.146.175` | `10.31.0.239` | `dazhou.bond`, `www.dazhou.bond` | Web / 訂閱 / Reality / TG |
| Server 4 | `code` | NLB `132.226.146.175` | `10.0.0.154` | `xh-ai.cyou`, `www.xh-ai.cyou` | Reality / TG 後端 |

不要把 `instance-20260604-1123 / 10.0.0.112` 當作當前 Server 4 代理後端，除非未來重新遷移並驗證。

## 入口與路由

- 四個域名均解析到共享 NLB `132.226.146.175`。
- Web / 訂閱：Server 3 Nginx HTTPS 後端發布。
- Server 4 Reality：客戶端連 `xh-ai.cyou:443`，Reality SNI `www.cloudflare.com`，Server 3 stream 轉 `10.0.0.154:24444`。
- 訂閱文件：Server 3 `/var/www/proxy-subs/clash.yaml`、`/var/www/proxy-subs/v2ray.txt`。

## Telegram

- 本機 TG 連結文件：`C:\Users\admin\Desktop\file\tg-links.txt`，包含 secret / 密碼，不貼聊天或文檔。
- MTProto：`dazhou.bond:18453`、`xh-ai.cyou:18454`。
- SOCKS5：`dazhou.bond:18443`、`xh-ai.cyou:18444`，均使用密碼認證。
- 遠端 SOCKS 憑據：`/root/tg_socks_credentials.json`。
- 2026-06-20 本機測速：SOCKS5 曾達約 `3.76MB/s`（Server 3）與 `4.68MB/s`（Server 4）；MTProto 約 `900KB/s`，不作提速主路徑。

## SSH

- Server 3：`ssh -i C:\Users\admin\Desktop\file\ssh-key-2026-05-27.key opc@132.226.146.175`
- Server 4：經 Server 3 ProxyCommand 到 `opc@10.0.0.154`。
