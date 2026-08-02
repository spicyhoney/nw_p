# HANDOFF：修繕小隊長

> 更新：2026-08-02（Asia/Taipei）
> 用途：只記錄目前可接手狀態，維持 150 行內；歷史證據放在實作索引與 ENGINEER LOG。

## 目前狀態

- 黑客松已結束；專案正在收斂為公開作品集版本，穩定目標分支為 `main`。
- 最終程式包含消費者／廠商雙端 Web、引導式水電修繕對話、人工 Checklist、圖片建議、
  台語／國語 STT、四個唯讀 MCP Tools、memory／async PostgreSQL 案件 repository，
  以及 Mock、Hugging Face、Bedrock 與 AgentCore Remote MCP adapters。
- 預設 `mock + local MCP + memory` 可在沒有 token、AWS 或 PostgreSQL 時執行完整 Demo。
- 比賽期間的 Quick Tunnel、PID、Runtime ARN 與本機路徑都不是目前契約；不要假設任何
  公開 URL、process 或 AWS Runtime 仍存在。

## 最近驗證

- Python 3.12：`327 passed, 17 skipped, 168 subtests passed`。
- `python -m ruff check .`：passed。
- `python -m ruff format --check .`：passed。
- 消費者與廠商 Web 在 `1280x720`、`390x844` 無水平 overflow；Mock 首頁無 console error。
- 17 個 skip 是未提供測試 PostgreSQL 或外部 live provider 時的條件式測試，不列入成功
  證據。GitHub CI 會提供 PostgreSQL 16 service 重跑整套測試。

## 最短啟動方式

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[app,data,dev]"
home-repair-web
```

- 消費者端：`http://127.0.0.1:8080/`
- 廠商端：`http://127.0.0.1:8080/provider`
- 預設不需任何 secret；完整步驟見 [README](README.md)。

## 目前產品契約

1. 產品只支援 `service_id=17` 水電修繕；五分支為水龍頭、馬桶、水管、電氣與其他。
2. 模型可以提出分支、欄位與工具呼叫，但不能替使用者勾 Checklist、確認摘要或派單。
3. 四個 MCP Tools 僅能查服務、行政區、諮詢表單與 synthetic 媒合候選。
4. 建案與廠商狀態轉換只經 `CaseWorkflowService`，並保留確認、冪等、交易與 audit。
5. pending 廠商只能看遮罩聯絡資料；accepted 才能看完整 synthetic contact。
6. Remote MCP 初始化或 provider 設定失敗時 fail closed，不得靜默 fallback。
7. 原始資料不覆寫；斷裂 mapping 不猜；synthetic 與人工設定必須保留來源標籤。

## 重要邊界

- 不提交 `.env`、token、AWS key、Runtime ARN、DATABASE_URL、真實個資或圖片 bytes。
- Agent 不執行任意 SQL；MCP／FastAPI 只做 adapter，規則放 Service Layer，SQL 放 repository。
- Demo provider、聯絡資料、時段、案件與訂單不代表真實服務或預約。
- Web session／Checklist 仍是 process-local；只有案件 workflow 能切換至 PostgreSQL。
- 正式登入、RBAC、付款、通知、真實廠商與時段保留尚未實作。

## AWS 帳務安全

- PR #19 的短效 direct-code Runtime POC 文件記錄 cleanup 已完成。
- 最終 Remote MCP Demo 是在另一台筆電與比賽 AWS credential 執行；本桌機沒有 AWS
  profile，無法重新查證帳號內是否仍有 Runtime、S3、IAM role 或 CloudWatch log group。
- Repo 中的 `ExpiresAt` 只是一個追蹤標籤，不會自動刪除資源。帳號持有人仍須登入當時
  AWS 帳號完成一次 console／billing audit；此項列於 [TASKS](TASKS.md)。

## 接手閱讀順序

1. [README](README.md)：作品、啟動方式與限制。
2. [TASKS](TASKS.md)：只列尚未完成項目。
3. [實作索引](docs/implementation-index.md)：已完成且有驗證的功能。
4. [系統架構](docs/architecture.md)：本機、PostgreSQL、Bedrock 與 AgentCore 邊界。
5. 修改模組內的 README 與 [AGENTS](AGENTS.md)。
