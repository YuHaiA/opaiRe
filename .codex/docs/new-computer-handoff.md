# New Computer Handoff

## 最小接手步驟

1. Clone repository。
2. 安裝 Python：Windows 建議 3.12，Linux / macOS 建議 3.11。
3. 建立 venv。
4. `pip install -r requirements.txt`。
5. 從 `config.example.yaml` 建立私有配置。
6. 運行 `python wfxl_openai_regst.py`。
7. 打開 `http://127.0.0.1:8000`。

## 不應提交或搬進 Git 的內容

- `data/` 運行資料。
- SQLite DB、帳號導出、日誌、私有配置。
- API key、Token、Cookie、密碼、私鑰、代理訂閱與 raw proxy link。

## 接手前必讀

- 根目錄 `SYSTEM.md`：長期架構與運維摘要。
- `.codex/docs/oracle-proxy-current.md`：當前 Oracle 代理 / TG 權威狀態。
- `.codex/docs/maintenance-history.md`：精簡歷史操作記錄。
