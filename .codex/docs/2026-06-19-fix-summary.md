# 2026-06-19 修复总结

## 当前服务器 / 域名权威对照

下表是当前 Oracle 代理与域名绑定的源头结论。后续排障、订阅修复、Nginx stream、NLB backend 都以这里为准。

| 角色 | OCI 实例 | 公网入口 | 私网 IP | 域名 | 代理职责 |
| --- | --- | --- | --- | --- | --- |
| 服务 3 | `instance-20260613-1403` | 共享 NLB `132.226.146.175` | `10.31.0.239` | `dazhou.bond`, `www.dazhou.bond` | 服务 3 Web / 订阅 / Reality 后端 |
| 服务 4 代理后端 | `code` | 共享 NLB `132.226.146.175` 经服务 3 stream | `10.0.0.154` | `xh-ai.cyou`, `www.xh-ai.cyou` | 服务 4 Reality 后端 `24444/tcp` |

关键规则：

- 不要把 `instance-20260604-1123 / 10.0.0.112` 当作当前服务 4 代理后端，除非未来明确重新迁移并重新验证。
- `xh-ai.cyou` / `www.xh-ai.cyou` 的 Web 与订阅 URL 必须走 `nginx_https_4443`。
- `server4-reality-443` 客户端入口是 `xh-ai.cyou:443`，Reality SNI 是 `www.cloudflare.com`，由服务 3 Nginx stream 转发到 `10.0.0.154:24444`。
- 服务 3 负责发布共享订阅文件：`/var/www/proxy-subs/clash.yaml` 与 `/var/www/proxy-subs/v2ray.txt`。

## 问题描述
- `xh-ai.cyou` (server4-reality-443) 连接超时
- `dazhou.bond` (server3-reality-2053) 端口配置错误
- yuhai 机器 (10.0.0.112) 上有残留 Xray 服务
- 订阅公钥与服务器配置不匹配

## 已修复的操作

### 1. 清理 yuhai 机器残留 Xray
**机器**: `instance-20260604-1123` (10.0.0.112 / 129.146.42.246)

```bash
# 停止并禁用 xray 服务
sudo systemctl stop xray
sudo systemctl disable xray

# 删除 xray 二进制和配置
sudo rm -f /usr/local/bin/xray
sudo rm -rf /usr/local/etc/xray
sudo rm -f /etc/systemd/system/xray.service
sudo systemctl daemon-reload
```

**结果**: xray 已移除，24444 端口已释放

### 2. 修复服务 3 Nginx stream 配置
**文件**: `/etc/nginx/nginx.conf`

**修改内容**:
- `upstream xray_reality_443`: `server 10.0.0.112:24444` → `server 10.0.0.154:24444`
- `upstream server4_reality_24444`: `server 10.0.0.112:24444` → `server 10.0.0.154:24444`

**备份**: `/etc/nginx/nginx.conf.bak-streamfix-*`

### 3. 修复 xh-ai-proxy.conf
**文件**: `/etc/nginx/conf.d/xh-ai-proxy.conf`

**修改内容**:
- `proxy_pass http://10.0.0.112` → `proxy_pass http://10.0.0.154`
- `proxy_pass https://10.0.0.112` → `proxy_pass https://10.0.0.154`

### 4. 修复 Nginx stream SNI 映射
**文件**: `/etc/nginx/nginx.conf`

**修改内容**:
```nginx
# Web / subscription SNI stays on Nginx HTTPS.
xh-ai.cyou nginx_https_4443;
www.xh-ai.cyou nginx_https_4443;

# Reality client SNI routes to Server 4 Xray.
www.cloudflare.com xray_reality_443;
```

**备份**: `/etc/nginx/nginx.conf.bak-sni-*`、`/etc/nginx/nginx.conf.bak-xhai-sni-web-*`

**验证**:
```bash
sudo nginx -t
sudo systemctl reload nginx
```

### 5. 修复订阅端口
**文件**: 
- `/var/www/proxy-subs/v2ray.txt`
- `/var/www/proxy-subs/clash.yaml`

**修改内容**:
- `dazhou.bond:2053` → `dazhou.bond:24443`
- `port: 2053` → `port: 24443`
- 节点标签: `#server3-reality-2053` → `#server3-reality-24443`

**备份**: 
- `/var/www/proxy-subs/v2ray.txt.bak-portfix-*`
- `/var/www/proxy-subs/clash.yaml.bak-portfix-*`

### 6. 修复订阅公钥
**文件**:
- `/var/www/proxy-subs/v2ray.txt`
- `/var/www/proxy-subs/clash.yaml`

**修改内容**:
- 将 `server4-reality-443` 的 UUID、Reality public key、short-id、SNI 对齐 `code` 机器 `10.0.0.154:24444` 上的实际 Xray 配置。
- 不在文档中记录 raw UUID、公钥、私钥或完整节点链接。

**公钥来源**: 从 `code` 机器 Xray 配置的 privateKey 本机生成，仅用于比对和写入订阅文件。
```bash
sudo /usr/local/bin/xray x25519 -i '<privateKey from /usr/local/etc/xray/config.json>'
```

**备份**:
- `/var/www/proxy-subs/clash.yaml.bak-s4code-*`
- `/var/www/proxy-subs/v2ray.txt.bak-s4code-v2ray-*`

## 当前架构

```
xh-ai.cyou:443
  → NLB 132.226.146.175:443
  → Nginx stream SNI: xh-ai.cyou → nginx_https_4443
  → Web / subscription: https://xh-ai.cyou/clash and /sub

server4-reality-443
  → Client connects xh-ai.cyou:443 with Reality SNI www.cloudflare.com
  → Nginx stream SNI: www.cloudflare.com → xray_reality_443
  → upstream xray_reality_443 → 旧 code 机器 10.0.0.154:24444
  → 状态: ✅ 正常

dazhou.bond:24443
  → NLB 132.226.146.175:24443
  → 服务 3 本地 Xray 24443
  → 状态: ✅ 正常
```

## 2026-06-19 追加校正

用户截图确认当前代理后端应为：

- Server 3: `instance-20260613-1403`, private IP `10.31.0.239`
- Server 4 proxy backend: `code`, private IP `10.0.0.154`

校正结果：

- 清理了误放到 `instance-20260604-1123` 的临时 `/usr/local/bin/xray`，没有创建服务或写入配置。
- 通过 Server 3 跳板确认 `code` 机器 hostname 为 `code`，`xray` 为 `active`，并监听 `24444/tcp`。
- Server 3 `nginx.conf` 的 `xray_reality_443` 与 `server4_reality_24444` upstream 均指向 `10.0.0.154:24444`。
- `xh-ai.cyou` 与 `www.xh-ai.cyou` 的 SNI 映射恢复为 `nginx_https_4443`，避免订阅 URL 被误分流到 Xray。
- `server4-reality-443` 的 Clash 与 V2Ray 订阅参数已对齐 `code` 机器实际 Xray 配置。

验证：

- `https://xh-ai.cyou/clash` 返回 `200`。
- `https://xh-ai.cyou/sub` 返回 `200`。
- `https://dazhou.bond/clash` 返回 `200`。
- 使用 `https://xh-ai.cyou/clash` 中的 `server4-reality-443` 参数创建临时 Xray 客户端，访问 `https://www.gstatic.com/generate_204` 返回 `204`，耗时约 `0.149s`。

## 订阅链接
- `https://xh-ai.cyou/sub` (v2ray.txt)
- `https://xh-ai.cyou/clash` (clash.yaml)
- `https://dazhou.bond/sub`
- `https://dazhou.bond/clash`

## 相关文档
- [server3-rebuild-notes.md](./server3-rebuild-notes.md)
- [oci-nlb-nat-runbook.md](./oci-nlb-nat-runbook.md)


