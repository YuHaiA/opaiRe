# 服务器部署说明

本文档按“第一次上服务器部署”的思路来写，尽量做到：

- 命令一步一步照抄
- 每一步都说明要做什么
- 默认适配 `Ubuntu 22.04 / 24.04`
- 默认推荐 `Docker Compose` 部署

如果你是第一次在服务器上跑这个项目，建议先只走：

1. 安装基础依赖
2. 拉代码
3. 启动 Docker Compose
4. 打开网页
5. 再去填配置

---

## 1. 你要准备什么

开始前请确认你已经有：

- 一台 Linux 服务器
- 一个可登录的普通用户或 root 用户
- 服务器可以访问 GitHub
- 如果你要绑定域名，提前准备好域名解析

推荐环境：

- 系统：`Ubuntu 22.04` 或 `Ubuntu 24.04`
- 内存：至少 `2 GB`
- 磁盘：至少 `10 GB`

---

## 2. 推荐部署方式

推荐优先级：

1. `Docker Compose` 部署
2. `Python 直接运行`

推荐你优先使用 `Docker Compose`，原因是：

- 环境更稳定
- 不容易缺依赖
- 升级更简单
- 更适合长期运行

---

## 3. 第一次部署：Docker Compose 方案

这一节是最推荐、最省事的方案。

### 3.1 登录服务器

在你自己的电脑终端执行：

```bash
ssh root@你的服务器IP
```

如果你不是 `root`，把上面的 `root` 换成你的用户名。

---

### 3.2 更新系统软件包

```bash
apt update
apt -y upgrade
```

---

### 3.3 安装基础依赖

```bash
apt -y install git curl ca-certificates gnupg lsb-release
```

这些依赖的作用：

- `git`：拉代码、后续更新
- `curl`：下载工具
- `ca-certificates`：HTTPS 证书
- `gnupg`：安装 Docker 时需要
- `lsb-release`：识别系统版本

---

### 3.4 安装 Docker

如果你的服务器还没安装 Docker，就按下面执行。

先添加 Docker 官方源：

```bash
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt update
```

再安装 Docker：

```bash
apt -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

安装完成后检查版本：

```bash
docker --version
docker compose version
```

---

### 3.5 创建部署目录

推荐统一放到：

```bash
mkdir -p /opt/opaiRe
cd /opt/opaiRe
```

---

### 3.6 拉取项目代码

如果你用 HTTPS：

```bash
git clone https://github.com/YuHaiA/opaiRe.git .
```

如果你用 SSH：

```bash
git clone git@github.com:YuHaiA/opaiRe.git .
```

拉完后确认目录里有这些文件：

```bash
ls
```

你应该至少能看到：

- `docker-compose.yml`
- `Dockerfile`
- `config.example.yaml`
- `wfxl_openai_regst.py`

---

### 3.7 创建数据目录

```bash
mkdir -p data
```

项目的实际配置、数据库、运行 PID 等都会放在这里。

---

### 3.8 启动项目

```bash
docker compose up -d --build
```

第一次启动会做这些事：

- 构建镜像
- 安装 Python 依赖
- 启动 Web 服务
- 自动创建 `data/`
- 如果 `data/config.yaml` 不存在，会按示例配置初始化

---

### 3.9 查看运行状态

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f
```

如果只想看最后 200 行：

```bash
docker compose logs --tail=200
```

---

### 3.10 打开网页

默认监听：

```text
http://127.0.0.1:18000
```

如果你在服务器本机浏览器打开，就直接访问：

```text
http://127.0.0.1:18000
```

如果你在自己电脑访问，需要把服务器 IP 换进去：

```text
http://你的服务器IP:18000
```

默认 Web 密码通常是：

```text
admin
```

首次登录后，请优先修改：

- Web 控制台密码
- 集群密钥
- 代理
- 邮箱/API Token/订阅链接等敏感配置

---

## 4. 首次部署后必须做的事

### 4.1 备份默认配置

项目实际运行配置一般在：

```bash
data/config.yaml
```

建议先备份一份：

```bash
cp data/config.yaml data/config.yaml.bak
```

---

### 4.2 如果你不想公网直接暴露 18000 端口

推荐只监听本机，再走 Nginx/Caddy 反代。

当前仓库默认已经是：

```text
127.0.0.1:18000 -> 容器 8000
```

这意味着：

- 服务器外部默认不能直接访问
- 更适合你后面再挂 Nginx

---

## 5. 绑定域名：Nginx 反向代理

### 5.1 安装 Nginx

```bash
apt -y install nginx
```

---

### 5.2 新建站点配置

```bash
cat > /etc/nginx/sites-available/opaire <<'EOF'
server {
    listen 80;
    server_name 你的域名;

    location / {
        proxy_pass http://127.0.0.1:18000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF
```

把 `你的域名` 改成你自己的域名。

---

### 5.3 启用站点

```bash
ln -sf /etc/nginx/sites-available/opaire /etc/nginx/sites-enabled/opaire
nginx -t
systemctl restart nginx
```

---

### 5.4 开 HTTPS（可选）

如果你要 HTTPS，推荐装 certbot：

```bash
apt -y install certbot python3-certbot-nginx
certbot --nginx -d 你的域名
```

---

## 6. 如果你要启用 Clash 订阅自助更新

只有当你要使用：

- Clash 订阅自助更新
- Mihomo 多实例代理池
- Web 面板一键更新订阅

才需要这一节。

### 6.1 宿主机准备目录

默认约定目录：

```bash
mkdir -p /opt/mihomo-pool
```

该目录至少要有：

```text
/opt/mihomo-pool/
├── pool.env
├── update_pool.sh
├── status_pool.sh
├── config_1/config.yaml
├── config_2/config.yaml
└── ...
```

---

### 6.2 修改 docker-compose.yml 挂载

把下面三行取消注释：

```yaml
- /opt/mihomo-pool:/opt/mihomo-pool
- /var/run/docker.sock:/var/run/docker.sock
- /usr/bin/docker:/usr/local/bin/docker:ro
```

改完后重启：

```bash
docker compose up -d --build
```

---

## 7. 后续升级

### 7.1 Docker Compose 升级

进入项目目录：

```bash
cd /opt/opaiRe
```

先看当前工作区是否干净：

```bash
git status
```

如果没有自己改过源码，直接升级：

```bash
git pull
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f --tail=200
```

---

### 7.2 如果你想回退到某个 tag

先查看 tag：

```bash
git tag --list
```

切到指定 tag：

```bash
git checkout v10.1.1-bfansye-hotfix1
docker compose up -d --build
```

注意：

- 这更适合开发者
- 普通用户建议直接用网页里的“更新中心”

---

## 8. 不用 Docker：Python 直接运行

如果你的服务器不方便装 Docker，也可以直接跑 Python。

### 8.1 安装系统依赖

```bash
apt update
apt -y install git python3 python3-venv python3-pip
```

检查版本：

```bash
python3 --version
pip3 --version
```

推荐：

- Python `3.11`

---

### 8.2 拉代码

```bash
mkdir -p /opt/opaiRe
cd /opt/opaiRe
git clone https://github.com/YuHaiA/opaiRe.git .
```

---

### 8.3 创建虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

### 8.4 安装依赖

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

### 8.5 启动项目

```bash
python wfxl_openai_regst.py
```

默认访问：

```text
http://127.0.0.1:8000
```

---

### 8.6 后台运行（推荐）

你可以先临时这样跑：

```bash
nohup .venv/bin/python wfxl_openai_regst.py > run.out.log 2> run.err.log &
```

看日志：

```bash
tail -f run.out.log
```

---

## 9. 常用命令速查

### 9.1 Docker 启动

```bash
cd /opt/opaiRe
docker compose up -d --build
```

### 9.2 Docker 停止

```bash
cd /opt/opaiRe
docker compose down
```

### 9.3 Docker 重启

```bash
cd /opt/opaiRe
docker compose restart
```

### 9.4 看日志

```bash
cd /opt/opaiRe
docker compose logs -f --tail=200
```

### 9.5 看容器状态

```bash
cd /opt/opaiRe
docker compose ps
```

### 9.6 备份配置

```bash
cd /opt/opaiRe
cp data/config.yaml data/config.yaml.bak
```

---

## 10. 常见问题

### 10.1 页面打不开

先看服务是否起来：

```bash
cd /opt/opaiRe
docker compose ps
docker compose logs --tail=200
```

如果你走了 Nginx，也要检查：

```bash
systemctl status nginx
nginx -t
```

---

### 10.2 页面白屏

常见原因：

- 容器没有重建
- 反代还在指向旧实例
- 浏览器缓存没清

处理方法：

```bash
cd /opt/opaiRe
docker compose up -d --build
```

然后浏览器强制刷新。

---

### 10.3 一键更新订阅失败

优先检查：

- `/opt/mihomo-pool` 是否真的存在
- `update_pool.sh` / `status_pool.sh` 是否真的存在
- `docker-compose.yml` 里的 3 条挂载是否已经打开
- 订阅链接返回的是不是 Mihomo YAML

---

### 10.4 升级后配置丢了

正常情况下，只要你一直保留：

```text
/opt/opaiRe/data
```

配置就不会丢。

所以不要随便删除：

- `data/`
- `data/config.yaml`
- `data/data.db`

如果你是通过“更新中心”下载新版本，也建议先迁移配置，再启动新目录。

---

## 11. 最简单的一套命令总结

如果你只想最快把它跑起来，按下面顺序直接执行：

```bash
apt update
apt -y upgrade
apt -y install git curl ca-certificates gnupg lsb-release
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt update
apt -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
mkdir -p /opt/opaiRe
cd /opt/opaiRe
git clone https://github.com/YuHaiA/opaiRe.git .
mkdir -p data
docker compose up -d --build
docker compose ps
docker compose logs --tail=200
```

启动完成后，访问：

```text
http://你的服务器IP:18000
```

如果你做了 Nginx 反代，就访问你的域名。
