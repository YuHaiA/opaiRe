# 发版说明

仓库已经内置根目录脚本 `release.ps1`，用于统一更新版本号、文档元数据，并可选创建提交 / tag / push。

## 最常用命令

只更新版本文件与文档：

```powershell
.\release.ps1 -Version v10.1.6 -UpstreamVersion v10.1.1
```

更新版本并直接完成提交、打 tag、推送：

```powershell
.\release.ps1 -Version v10.1.6 -UpstreamVersion v10.1.1 -CreateCommit -CreateTag -Push
```

## 脚本会做什么

- 校验当前分支必须是 `main`
- 校验工作区必须干净
- 更新 [VERSION](/C:/Users/admin/Desktop/opaiRe/VERSION)
- 更新 [UPSTREAM_VERSION](/C:/Users/admin/Desktop/opaiRe/UPSTREAM_VERSION)
- 同步更新前端版本号与核心文档里的版本元数据

## 当前项目的版本来源

- 本仓库独立版本：`VERSION`
- 上游对齐基线：`UPSTREAM_VERSION`

网页“检查更新”现在读取 GitHub 上最新的 `tag`，并直接下载该 tag 对应的源码压缩包。

## 注意

- `release.ps1` 会拒绝在脏工作区上执行，避免把未提交修改混进版本更新
- 如果你只想改本仓库版本，不想改上游基线，可以省略 `-UpstreamVersion`，脚本会沿用当前 `UPSTREAM_VERSION`
- 该脚本不会自动帮你写 changelog 详情，只会同步当前“公共发布版本号”元数据
