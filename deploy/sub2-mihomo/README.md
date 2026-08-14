# Sub2API Mihomo 可复用部署包

这套目录与服务 2 当前运行的 Mihomo 核心管理代码、面板和服务配置同源，默认保持 10 个固定出口。它支持订阅节点、HTTP/HTTPS 节点或兼容模式，支持测活、手动切换、定时轮换、出口 IP 去重和账号容量调度。

部署包只保存代码与脱敏模板。以下内容永远只留在服务器：订阅地址、节点、控制器密钥、面板密码、账号状态、日志、数据库和备份。Mihomo 二进制与 Zashboard 也不进 Git，安装时从官方发行版下载最新版。

## 新服务器安装

服务器需要 Linux、systemd、Python 3、Docker、Nginx 和出站网络。将本目录放到服务器后执行：

```bash
cd deploy/sub2-mihomo
bash install.sh
```

默认值与服务 2 兼容：

```text
MIHOMO_ROOT=/opt/sub2-mihomo
MIHOMO_USER=当前执行用户
MIHOMO_DOMAIN=tupai.cyou
MIHOMO_URL_PATH=/mihomo
MIHOMO_PUBLIC_BASE=https://tupai.cyou/mihomo
SUB2API_CONTAINER=sub2api
SUB2API_DOCKER_HOST=172.20.0.1
SUB2API_DEPLOY_DIR=/home/<用户>/sub2api-deploy
SUB2API_POSTGRES_CONTAINER=sub2api-postgres
NGINX_SITE_CONFIG=/etc/nginx/conf.d/sub2api.conf
NGINX_SNIPPET_CONFIG=/etc/nginx/snippets/mihomo.conf
```

其他服务器可在同一条命令前覆盖变量：

```bash
MIHOMO_USER=ubuntu \
MIHOMO_DOMAIN=api.example.com \
MIHOMO_PUBLIC_BASE=https://api.example.com/mihomo \
SUB2API_DOCKER_HOST=172.18.0.1 \
SUB2API_DEPLOY_DIR=/home/ubuntu/sub2api-deploy \
NGINX_SITE_CONFIG=/etc/nginx/sites-enabled/sub2api \
bash install.sh
```

安装器会创建单个 Mihomo 进程、10 个固定出口端口 `7901-7910`、管理面板服务、受限 sudoers 和 Nginx 路由，不会额外创建 Docker 镜像。首次密码与控制器密钥保存在服务器的 `/opt/sub2-mihomo/CREDENTIALS.txt`，权限为 `0600`。

## 更新面板代码

不重新下载核心、不覆盖订阅和运行状态：

```bash
cd deploy/sub2-mihomo
bash install-panel.sh
```

若初次安装使用了自定义变量，更新时继续传入相同变量。安装器会保留现有 `config.yaml`、`providers/`、`state/` 和 `CREDENTIALS.txt`。

## 安全导出

生成可复制到其他服务器的源码包：

```bash
bash export-deployment.sh
```

导出脚本使用文件白名单，不会打包 `config.yaml`、`providers/`、`state/`、`logs/`、`backups/`、`CREDENTIALS.txt`、Mihomo 二进制或 Zashboard 静态缓存。

## 验证

```bash
systemctl is-active sub2-mihomo sub2-mihomo-panel
curl -fsS http://127.0.0.1:19099/api/status
curl -x http://127.0.0.1:7901 https://api.ipify.org
sudo nginx -t
```

面板地址默认为 `https://tupai.cyou/mihomo/`，高级界面为 `https://tupai.cyou/mihomo/ui/`。两者都由 Nginx Basic Auth 保护。
