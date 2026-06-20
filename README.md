# opaiRe

opaiRe 是一套註冊流程與資源管理 Web 控制台，包含 Python 後端與單頁前端。它用於集中管理註冊任務、郵箱 / OTP、代理切換、帳號庫、雲端倉庫與運行日誌。

> 僅在你擁有或明確獲授權的環境中使用。不要提交或公開任何密鑰、Token、Cookie、帳號庫、代理連結或本機運行資料。

## 核心能力

- Web 控制台：任務啟停、配置管理、日誌與狀態查看。
- 郵箱 / OTP：支援多種郵箱後端與驗證碼輪詢流程。
- 帳號庫：本機 SQLite 庫、查詢、導出與清理。
- 代理管理：Clash / Mihomo 相關配置、節點切換與連通性檢查。
- 雲端倉庫：CPA / Sub2API 類庫存檢查、補貨與推送流程。
- 通知：Webhook / Telegram Bot 等任務通知能力。

## 運行環境

- Windows：建議 Python 3.12。
- Linux / macOS：建議 Python 3.11。
- Docker：可用 `Dockerfile` / `docker-compose.yml` 部署。

具體版本以當前 `requirements.txt` 與服務端實測環境為準。

## 快速啟動

```bash
pip install -r requirements.txt
python wfxl_openai_regst.py
```

默認本機入口：

```text
http://127.0.0.1:8000
```

首次配置請以 `config.example.yaml` 為模板建立自己的運行配置。正式運行資料應放在 `data/` 下，並保持不提交。

## 主要目錄

```text
.
├── wfxl_openai_regst.py   # 後端 / Web 控制台啟動入口
├── index.html             # 前端主頁
├── routers/               # API 路由
├── utils/                 # 核心工具、配置、外部整合
├── luckmail/              # LuckMail 相關整合
├── static/                # 前端 JS / CSS 資源
├── assets/                # 靜態資源與截圖
├── public/                # 瀏覽器插件 / 公開資源
├── data/                  # 運行資料，本地敏感資料不提交
├── tests/                 # 測試
├── deploy/                # 部署輔助文件
├── config.example.yaml    # 配置模板
├── requirements.txt       # Python 依賴
├── SYSTEM.md              # 維護者架構與運維摘要
└── README.md              # 本文件
```

## 配置與資料

- 不要提交 `data/`、資料庫、日誌、帳號導出、私有配置或代理訂閱。
- 密鑰、Token、Cookie、API 憑據與代理密碼必須放在私有配置或運行環境中。
- 服務端排障時，以服務端現場的 `data/config.yaml`、systemd 狀態、端口與日誌為準，不要假設本機配置等於遠端配置。

## 開發約定

- 修改核心流程、部署形態或運維拓撲時，同步更新 `SYSTEM.md`。
- 新功能優先模塊化，不把大量邏輯堆到入口文件。
- 測試文件放入 `tests/`，臨時運維文件放入 `.codex/tmp/` 並用後清理。
- 文檔保持短而準：記結論、路徑、端口、驗證狀態和注意事項，不記流水帳。

## 私有運維文檔

- `SYSTEM.md`：長期維護摘要與伺服器 / 代理權威資訊。
- `.codex/docs/README.md`：Codex 私有運維文檔策略。

更多即時狀態應直接查遠端現場，不依賴過期長文檔。
