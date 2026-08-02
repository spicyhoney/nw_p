---
inclusion: always
---
# 技術基線與方向

## 技術棧

| 領域 | 現況 |
|---|---|
| Runtime | Python `>=3.11`，setuptools，`src/` layout |
| Contracts | Pydantic 2.x；外部輸入與 Tool response 採嚴格結構化模型 |
| Web | FastAPI、Uvicorn、無 build 的 HTML／CSS／JavaScript |
| Agent | 自製 `AgentRunner`，以 `ModelClient`／`ToolClient` ports 隔離 provider 與 transport |
| MCP | Python MCP SDK 1.x（專案範圍 `>=1.27,<2`），FastMCP，stdio 與 Streamable HTTP |
| Model | deterministic Mock；可選 Hugging Face Inference Providers text／VLM adapters |
| Database | PostgreSQL、psycopg 3 async、SQLAlchemy／pandas 用於資料流程 |
| Media | Pillow；目前為本機私有檔案儲存 |
| Quality | pytest、Ruff、Node.js regression（前端競態） |

`boto3` 雖在 optional app dependencies 中，但目前沒有 Bedrock、AgentCore、S3 或其他 AWS adapter。依賴存在不代表能力完成。

## 模型 provider 邊界

### Mock

- 預設本機與 CI 可重現模式，使用 synthetic 記憶體資料。
- 能證明 Agent／MCP 編排，不證明 LLM 語意品質。
- 不提供假照片分析，也不得偽裝成 Bedrock 或正式 AI 成果。

### Hugging Face

- Text adapter 可做 hosted chat completion／function calling；VLM adapter只產生待確認的結構化照片建議。
- token 只可由執行環境取得；缺 token、套件或設定時 fail fast，不得靜默切回 Mock。
- 呼叫前須理解會送出的內容；照片每次都要取得外部處理同意。
- provider 錯誤、逾時與非法回覆須轉成安全錯誤，不回傳 credential 或供應商內部 payload。
- contract tests 與單次 live smoke 不等於模型品質、可用性或額度保證。

### 未來 AWS provider

- `BedrockModelClient`、AgentCore Gateway／Runtime 尚未實作。
- Bedrock、AgentCore、RDS、S3、Region、模型、hosting、IAM role 與額度均待確認。
- 任何 AWS 選型在決策前只能稱「候選目標架構」，不可稱競賽硬性要求或既成事實。
- 新 provider 必須實作既有 port；不得把模型 SDK、provider-specific response 或商業規則擴散至 Service Layer。

## MCP 邊界

目前只有四個唯讀工具：

1. `search_services`
2. `resolve_location`
3. `get_consultation_form`
4. `match_service_providers`

共同規則：

- 標記 read-only、non-destructive、idempotent、closed-world。
- MCP 是 adapter：只轉換輸入／輸出並呼叫 `ReadServiceLayer`。
- Tool 不接受 SQL、table／column 名稱、任意 URL 或任意程式碼。
- 缺資料、歧義或空候選需回結構化結果，不得猜 ID、地址或服務商。
- Agent 只看得到白名單內的唯讀工具；Web 的派單／接單由明確按鈕直接呼叫 `CaseWorkflowService`。
- 寫入 MCP Tool 尚未核准。若未來需要，必須另做 Spec，涵蓋身分、最小權限、確認、冪等、交易、稽核與重放風險。
- 記憶體內 MCP protocol tests 已存在；外部 Streamable HTTP Client／Gateway E2E 尚未完成。

## 資料庫與 repository

- 原始輸入不可覆寫；清洗輸出保留來源、品質與 quarantine。
- PostgreSQL 目前使用 `core`、`quarantine`、`demo`、`agent`、`workflow` 等 schema／views。
- 唯讀 repository 使用固定參數化 SQL，僅查 `agent.*` security-barrier views。
- workflow 寫入只能透過 `CaseWorkflowRepository` 與 `CaseWorkflowService` 的交易邊界。
- Web 唯讀服務資料目前固定來自 `DemoReadRepository`；`WEB_CASE_REPOSITORY=postgres` 只切換案件、訂單、冪等與 audit，不能宣稱整個 Web 已查 PostgreSQL 正式目錄。
- PostgreSQL integration 只能使用明確的測試資料庫；不得連正式或未知資料庫。
- 正式個資加密、查詢 hash、金鑰管理、保存與刪除政策尚未實作；現況只允許 synthetic contact。

## 照片功能

既有照片流程必須重用，不得另寫平行的上傳、VLM 或服務判斷管線：

```text
Web multipart
  -> LocalMediaStorage（實際解碼、重編碼、去 metadata、安全路徑）
  -> HuggingFaceVisionClient（建議，不決策）
  -> 使用者更正／確認
  -> 既有 search_services 重驗唯一服務
  -> 派單時保存相對 path + 已確認結構化分析
```

目前限制：每個 session 一張；JPEG／PNG／WebP；8 MiB；binary 不進 PostgreSQL／audit／log；Browser 不取得內部 path。S3、presigned URL、retention／GC、正式住家照片政策與 session-to-case 檔案搬移仍未完成。

## 測試與驗證

開發順序：先跑受影響模組，再跑完整測試。MCP 必須透過 Client／Server protocol 驗證，不能只直接呼叫 Python 函式。

常用命令：

```powershell
python -m pytest <affected-tests> -q
python -m pytest -q
python -m ruff check src tests
node .\tests\test_checklist_concurrency.js
```

截至 2026-08-01，本 workspace 以 `.venv` 實跑完整 pytest：

```text
134 passed, 18 skipped, 52 subtests passed
```

- skip 代表環境條件未提供，不得列為成功證據。
- PostgreSQL 測試只在提供隔離的 `TEST_DATABASE_URL` 時執行。
- hosted model／VLM live eval 不進預設 CI，且只能使用無個資 synthetic 測資。
- 前端 source-string tests 不是完整瀏覽器行為證據；重要流程仍需 HTTP 或瀏覽器 smoke。
- 驗證結果改變時，同步更新模組 README 與 `docs/implementation-index.md`。

## AWS 最終方向

競賽最新交付要求包含 AWS 雲端技術架構內容，但目前未指定必須採用的 AWS 服務，也未證明 Demo 必須部署在 AWS。團隊預計朝 AWS 部署探索，候選包含 Bedrock、AgentCore、RDS、S3、IAM 與 CloudWatch；所有選型保持 provisional，直到帳號、Region、模型、權限、預算、網路與 hosting 決策確認。

不可破壞原則：

- 本機與 AWS 共用 domain／service contracts，以 adapter 替換 provider、transport、repository 與 object storage。
- AWS workload 使用 IAM role／短期 credential 與最小權限；不得把長期 access key 寫入程式、文件、測試或 Git。
- log、trace、prompt 與 demo recording 不得包含 token、完整個資、完整地址或私有照片。
- 不得為了架構圖預先建立未使用、無權限邊界或無成本控制的雲端資源。
