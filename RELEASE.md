# 发版说明

这份说明只保留你真正常用的发版命令。

---

## 最短命令

如果你只是正常发一个新版本，直接用这一条：

```powershell
.\release.ps1 -Version v10.1.7 -Auto
```

这条命令会自动完成：

- 更新版本号
- 更新文档里的版本元数据
- 创建提交
- 创建 tag
- 推送 `main`
- 推送 tag

推送 tag 后，GitHub Actions 会自动创建对应 Release。

---

## 你真正要记住的流程

平时只要记这 3 步：

1. 改代码
2. 确认工作区没脏文件
3. 执行：

```powershell
.\release.ps1 -Version v10.1.7 -Auto
```

---

## 如果上游基线变了

如果你这次不只是改自己仓库版本，还同步了新的上游基线，再用这一条：

```powershell
.\release.ps1 -Version v10.1.7 -UpstreamVersion v10.1.2 -Auto
```

---

## 如果你只想先改版本，不马上发

```powershell
.\release.ps1 -Version v10.1.7
```

这时脚本只会：

- 改 `VERSION`
- 改 `UPSTREAM_VERSION`
- 同步前端版本号
- 同步 README / CHANGELOG / PR 描述里的版本元数据

不会自动提交、不会打 tag、不会推送。

---

## 自动 Release

仓库已经内置自动 Release 工作流：

- 文件：`.github/workflows/release.yml`
- 触发条件：推送符合 `v*` 的 tag
- 行为：自动创建 GitHub Release

也就是说，你只要成功 push tag，Release 会自动出现。

---

## 当前项目怎么检查更新

网页“检查更新”现在会：

1. 优先读取 GitHub 最新 Release
2. 如果 Release 不可用，再回退读取最新 tag

普通用户更新会下载并解压到：

```text
updates/<版本>/source
```

开发者更新则走当前 Git 工作区的安全更新流程。

---

## 发版前的硬规则

`release.ps1` 会自动检查：

- 当前分支必须是 `main`
- 工作区必须干净

如果不满足，脚本会直接拦住，不会继续发版。

---

## 当前版本来源

- 本仓库独立版本：`VERSION`
- 上游对齐基线：`UPSTREAM_VERSION`

---

## 备注

- 脚本不会自动帮你写详细 changelog
- 如果需要更漂亮的 Release 描述，可以去 GitHub 网页上再补充
- 日常发版，优先用：

```powershell
.\release.ps1 -Version 新版本号 -Auto
```
