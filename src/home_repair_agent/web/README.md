# Web P1：消費者與服務廠商 Demo

## 1. 做了什麼

這個模組把本機 Agent、四個唯讀 MCP Tools、可切換的案件 repository 與受控
案件 workflow 包成 FastAPI Web Demo。

消費者端 `/`：

- 建立 process-local 諮詢 session。
- 以自然語言觸發 Agent 查詢服務、行政區與諮詢單。
- 手動完成動態表單與 `Asia/Taipei` 希望時段。
- 呼叫 `match_service_providers` 顯示 synthetic 候選。
- 選擇候選並明確確認後建立 `pending_provider` Demo 案件。
- 輪詢廠商回覆，顯示拒絕、接單與 synthetic Demo 訂單編號。

廠商端 `/provider`：

- 切換兩個 synthetic Demo 廠商身分。
- 只列出指派給目前身分的案件。
- 依 `pending_provider / accepted / rejected` 篩選。
- 查看需求摘要、表單答案、希望時段、聯絡資料權限與 audit。
- 二次確認接受或拒絕案件。
- 待回覆時顯示遮罩 contact；接單後才顯示完整 synthetic contact。

詳細五項規則、狀態機與 API 流程請見
[服務廠商派單／接單 P0](../../../docs/provider-workflow.md)。

刻意沒做：

- Web 對話 session 尚未寫進 PostgreSQL；程式重啟後聊天畫面不能直接恢復。
- PostgreSQL 模式尚未連接 RDS；目前只驗證相同的 PostgreSQL 16.14 契約。
- 廠商下拉選單是身分模擬，不是登入或正式授權。
- 尚未保留時段、付款、通知、照片、語音或使用真實個資。
- 尚未新增寫入 MCP Tool；現有四個 MCP Tools 仍全部唯讀。
- 尚未連接 AWS、Bedrock、AgentCore、RDS 或公開網域。

## 2. 為什麼這樣設計

FastAPI route 只做 HTTP adapter。主要責任分工如下：

- `WebSessionService`：消費者 session、表單驗證、Agent／媒合編排。
- `CaseWorkflowService`：確認、冪等、授權、audit 與案件狀態轉換。
- `DemoCaseWorkflowRepository`：預設 process-local 快速 Demo。
- `PostgresCaseWorkflowRepository`：可選的 async transaction 持久化。
- `AgentRunner`：模型多輪與唯讀 Tool loop。
- `ReadServiceLayer`：服務、行政區、表單與媒合規則。

聊天文字與商業狀態不混用。LLM 回覆負責說明與追問；服務、地點、表單、候選、
案件與訂單都來自後端結構化 view model。

模型只看前三個查詢 Tool；第四個媒合 Tool 必須在使用者手動送出且後端驗證
表單後執行。派單與廠商決策則由明確按鈕直接呼叫 Service Layer，不經 LLM，
避免模型自行觸發副作用。

P1 仍採無 build 的 HTML/CSS/JavaScript，讓本機與比賽環境可由同一個 FastAPI
網址提供，部署時不需要第二個前端服務。

## 3. 輸入、輸出與資料流

### 查詢與媒合

```text
Browser message
  -> FastAPI
  -> WebSessionService
  -> AgentRunner
  -> Mock / Hugging Face ModelClient
  -> MCPToolClient
  -> search_services / resolve_location / get_consultation_form
  -> ReadServiceLayer
  -> structured SessionView

Browser confirmed form
  -> WebSessionService validates fields and +08:00 window
  -> match_service_providers MCP Tool
  -> synthetic candidates
```

### 派單與接單

```text
Consumer explicit confirmation
  -> POST /api/sessions/{id}/dispatch
  -> CaseWorkflowService
  -> memory 或 PostgreSQL CaseWorkflowRepository
  -> pending_provider + audit
  -> assigned provider queue

Provider explicit decision
  -> POST /api/provider/cases/{case_id}/decision
  -> CaseWorkflowService
  -> 同一 transaction 更新案件、訂單、audit 與 idempotency
  -> accepted + SYN-ORDER-* + full synthetic contact
     or rejected + unavailable contact
  -> consumer polling reflects terminal state
```

## 4. API

| Method | Path | 用途 |
|---|---|---|
| `GET` | `/api/health` | 模式與服務健康狀態 |
| `POST` | `/api/sessions` | 建立消費者 session |
| `GET` | `/api/sessions/{id}` | 取得最新 session／案件狀態 |
| `POST` | `/api/sessions/{id}/messages` | 傳送自然語言需求 |
| `POST` | `/api/sessions/{id}/form` | 驗證表單並媒合 |
| `POST` | `/api/sessions/{id}/dispatch` | 明確確認派單 |
| `POST` | `/api/sessions/{id}/reset` | 未建案前重設；已有 audit 時拒絕清除 |
| `GET` | `/api/provider/identities` | 列出 synthetic Demo 身分 |
| `GET` | `/api/provider/cases` | 列出目前指派案件 |
| `GET` | `/api/provider/cases/{case_id}` | 取得分級案件詳情 |
| `POST` | `/api/provider/cases/{case_id}/decision` | 確認接受或拒絕 |

廠商 API 以 `X-Demo-Provider-Id` 傳入模擬身分。正式環境不得沿用這個 header
當作登入機制。

## 5. 安全與資料邊界

- session 永遠仍是 process-local。
- `WEB_CASE_REPOSITORY=memory` 時，案件、訂單與 audit 也會隨程式重啟消失。
- `WEB_CASE_REPOSITORY=postgres` 時，案件、訂單、idempotency 與 audit 可由新
  Repository 實例重新讀取；但尚不能恢復消費者聊天 session。
- 所有廠商、聯絡資料、案件與訂單均標示 `synthetic`。
- 輸入區會警告不得填真實個資；P1 不宣稱能自動偵測所有自由文字個資。
- 列表永遠只回遮罩 contact；只有指派廠商接單後的詳情回完整 synthetic contact。
- 未指派廠商讀取案件時回 404，避免洩漏案件是否存在。
- 寫入必須有 `confirmed=true`、idempotency key、合法狀態與指定廠商身分。
- 相同 idempotency key 不得搭配不同 payload。
- 並行接受／拒絕只能有一個合法轉換成功。
- FastAPI、Case Service 與 PostgreSQL repository 全程 async；HTTP 案件路徑
  不呼叫同步 `psycopg.connect`。
- 已建立 audit 的 session 不能用 reset 擦除。
- API response 使用 `Cache-Control: no-store`；頁面加 CSP 等安全 headers。
- 前端只用 `textContent` 呈現 Agent 與 Tool 文字。
- 瀏覽器不直接連 Hugging Face、MCP 或資料庫。
- FastAPI route 不含 SQL；SQL 只在 PostgreSQL Repository。
- 專案不含正式資料庫憑證、AWS 金鑰或寫入 MCP Tool。

## 6. 執行方式

安裝：

```powershell
python -m pip install -e ".[app,dev]"
```

使用 Mock Model：

```powershell
home-repair-web
```

預設網址：

```text
消費者端：http://127.0.0.1:8080/
廠商端：http://127.0.0.1:8080/provider
```

也可直接啟動：

```powershell
python -m home_repair_agent.web.app
```

Windows 的 psycopg async 需要 Selector event loop；上述兩個專案入口會自動
設定。Windows PostgreSQL 模式不要改用裸 `python -m uvicorn ...` 啟動。
Linux／AWS 不受此限制。

| 變數 | 預設 | 用途 |
|---|---|---|
| `WEB_MODEL_PROVIDER` | `mock` | `mock` 或 `huggingface` |
| `WEB_CASE_REPOSITORY` | `memory` | `memory` 或 `postgres` |
| `DATABASE_URL` | 無 | PostgreSQL 模式必填；不得提交正式密碼 |
| `WEB_HOST` | `127.0.0.1` | Web bind host |
| `WEB_PORT` | `8080` | Web port |
| `HF_TOKEN` 等 | 見 `.env.example` | Hugging Face 模式 |

`WEB_MODEL_PROVIDER=huggingface` 會把對話與 Tool schema 傳到外部 hosted API；
沒有 `HF_TOKEN` 時啟動會直接失敗，不會靜默切回 Mock。HF 不影響派單與廠商
狀態機，這些規則仍由本機 Service Layer 執行。

## 7. 測試與實際結果

```powershell
python -m pytest -q `
  tests/test_case_workflow.py `
  tests/test_web_app.py `
  tests/test_postgres_case_repository.py
```

2026-07-30 無資料庫聚焦結果：`33 passed, 6 skipped, 3 subtests passed`。
真實 PostgreSQL 與原有 loader／read integration 合跑為 `15 passed`。除了
原有 Web session、
三個初始 Tools、動態
表單、時區驗證、媒合與安全 headers，亦涵蓋確認、冪等、授權、遮罩、接單、
拒絕、改派、audit、並行狀態競爭、派單時段重新驗證與 workflow 注入一致性。

完整 suite（提供測試 PostgreSQL）：`113 passed, 43 subtests passed`。受影響
Python 檔案 Ruff／format、compileall 與 diff check 通過。新增回歸測試會封鎖
同步 `psycopg.connect`，確認 Web 使用的 repository 呼叫仍能完成建案與讀回。
另在 Windows 以專案入口實際啟動 async Web + PostgreSQL，走完 session、需求、
表單、媒合與 `dispatch_pending` 建案 smoke。

`.github/workflows/postgresql-ci.yml` 會在 PR、`main` push 或手動
`workflow_dispatch` 時建立乾淨 PostgreSQL 16.14 service，重跑靜態檢查與完整
pytest；不使用開發者本機資料庫或正式 RDS。

瀏覽器已在桌機 `1280x720` 與手機 `390x844` 驗證：

- 消費者完成諮詢、媒合、選擇與確認派單。
- 指派廠商 pending 時只見遮罩 contact。
- 廠商二次確認接單後才見完整 synthetic contact。
- 消費者自動取得接單狀態與 `SYN-ORDER-*`。
- 未指派廠商列表為空。
- filter 排除目前案件時，右側詳情與決策按鈕不會殘留。
- 無水平 overflow 或 console error。

真實 HF Web fixed case 使用 `Qwen/Qwen3-4B-Instruct-2507`、
`provider=auto`：synthetic「台北市大安區水龍頭漏水」於 7.41 秒依序完成
`search_services`、`resolve_location`、`get_consultation_form`，正確停在
`awaiting_form`，媒合 Tool 未提前暴露或執行。從 Windows PowerShell 以 pipe
執行臨時 Python live harness 時，中文必須使用 UTF-8 檔案或 Unicode escape
並驗證 code points，避免測試輸入被轉成 `?`。

測試環境有 FastAPI `TestClient` 對未來 `httpx2` 遷移的第三方 deprecation
warning；目前不影響功能或結果。

## 8. 下一階段

1. 持久化 Web session／Agent 記憶，並設計同意、保存期間與刪除機制。
2. 加入正式 authentication／authorization 與廠商帳號。
3. 實作時段保留與排程衝突控制。
4. 將單一 HF live case 擴成正常、模糊服務、缺地點、多地點與 provider error
   的固定矩陣；live 測試不放進預設 CI。
5. 取得 AWS 環境後建立 RDS、套用相同 migration，並替換 model／tool adapters。
6. 決定 Demo 部署環境並提供公開 HTTPS 網址。
7. 只有外部 Agent 確實需要時，才設計受限寫入 MCP Tools。
