# 工程紀錄

## 2026-07-27：Hugging Face adapter review 修正

- 分支：`feature/huggingface-model-adapter`
- 目標：修正 SDK 相容性、無限等待、Demo 日期過期與驗證文件矛盾，不擴張
  Web、AWS 或寫入 Tool scope。

### 實作

- 專案已使用並檢查 `huggingface_hub 1.24.0`，因此 `app` extra 的最低版本
  從不完整支援 `provider=auto` 的 `0.30` 提高為 `1.24`。
- 新增 `HF_TIMEOUT_SECONDS`，預設 60 秒；驗證正整數後傳入
  `InferenceClient(timeout=...)`，避免 provider 無回應時永久等待。
- System prompt 明定：只有使用者提供完整且含時區的開始、結束時間時，才可
  傳媒合時間窗；不得把「星期六下午」自行換成年月日或修改偏好。
- `DemoReadRepository` 改由可注入的 `reference_time` 產生下一個仍在未來的
  星期六時段，並在表單題目顯示 Demo 候選日期；不再寫死 `2026-08-01`。

### 驗證與證據邊界

- focused tests：34 passed。
- 完整 suite：65 passed、9 skipped、40 subtests passed；9 個 skipped 皆需要
  隔離的 `TEST_DATABASE_URL`。
- Mock scripted smoke 依序呼叫四個唯讀 MCP Tools，顯示未來 synthetic 時段。
- scoped Ruff、`compileall`、`git diff --check`：通過。
- 團隊 handoff 紀錄先前已有一次以 synthetic prompts 執行的 HF 四工具 live
  smoke；本次修正環境沒有 `HF_TOKEN`，沒有重跑 live。此紀錄不能取代固定
  eval，也不代表模型準確率。
- 新增／修改內容與本分支歷史皆未發現 token、AWS key 或 private key pattern。

### 下一步

- 對方排程 AI 讀取本 commit 後，先重跑測試並檢查 review findings；不要自動
  merge PR #5 或 force-push stacked branches。
- 日後拿到可用 token／額度時，以固定 synthetic cases 重跑 live eval，記錄
  tool selection、參數、timeout、延遲與成本，不提交 token 或原始 transcript。

## 2026-07-27：Hugging Face hosted model adapter

- 分支：`feature/huggingface-model-adapter`
- 基線：`feature/matching-terminal-demo` 的 `ab9fe49`
- 目標：在不改寫 `AgentRunner`／MCP 契約的前提下，讓 terminal demo 可顯式
  切換到 Hugging Face hosted open model 做 function calling。

### 實作

- 新增 `HuggingFaceModelClient`，把內部多輪訊息與 MCP `ToolDefinition`
  轉成 Hugging Face chat-completion messages／function schema。
- 嚴格解析文字回覆或 tool calls；tool call 必須有 ID、名稱與 JSON object
  參數，不合法回覆與 provider 例外統一轉成安全 adapter error。
- Demo 新增 `--model-provider mock|huggingface`；預設仍為 deterministic Mock。
- Hugging Face mode 讀取 `HF_TOKEN`、`HF_MODEL_ID`、`HF_PROVIDER`、
  `HF_MAX_TOKENS` 與 `HF_TIMEOUT_SECONDS`。缺 token／套件／設定時 fail fast，
  不靜默 fallback。
- 預設模型為 `Qwen/Qwen3-4B-Instruct-2507`，provider 為 `auto`；兩者都可由
  環境設定替換。依賴加入 `app` extra，未下載本機模型權重。

### 安全與限制

- token 不進程式、log、物件 repr 或 Git；`.env.example` 只留空白欄位與說明。
- Agent 仍只把 `readOnlyHint=true` 的四個 MCP Tools 交給模型；Demo 仍不寫
  PostgreSQL、不保留時段、不建立案件。
- Hosted mode 會把對話、system prompt、Tool schema 與 Tool result 送至所選
  Inference Provider；不會送主辦方檔案或資料庫連線。
- `d2e953c` 初始實作環境未設定 `HF_TOKEN`，當時沒有進行 live provider call；
  後續團隊 handoff 另記錄一次 synthetic 四工具 live smoke。固定 eval 與品質
  指標仍未完成。

### 驗證

```powershell
python -m pytest tests/test_huggingface_model.py tests/test_agent_demo.py tests/test_agent_loop.py -q
python -m home_repair_agent.agent.demo --scripted
python -m pytest -q
python -m ruff check src/home_repair_agent/agent tests/test_agent_loop.py tests/test_agent_demo.py tests/test_huggingface_model.py
python -m compileall -q src tests
```

結果：

- provider／Agent／Demo focused tests：30 passed。
- Mock scripted smoke 依序呼叫四個唯讀 MCP Tools並顯示 synthetic 候選。
- 完整 suite：60 passed、10 skipped、40 subtests passed。
- scoped Ruff、`compileall` 與 `git diff --check`：通過。
- 已安裝並檢查真實 `huggingface_hub 1.24.0`；
  `InferenceClient.chat_completion` 支援 `tools` 與 `tool_choice`。
- 全 repo Ruff 另列出 22 個既有 data-cleaning／script 問題；本分支沒有修改
  那些檔案，未在本次順手改動。

### 下一步

- 將已完成的一次 synthetic live smoke 整理成可重複 eval；記錄每輪 tool
  selection、參數、timeout、延遲與額度，不送敏感資料。
- 將同一組 eval cases 日後用於 Hugging Face 與 Bedrock，才能比較模型品質。
- PR #5 與 terminal demo stacked 分支整理完成前，不合併或 force-push。

## 2026-07-27：終端 Demo 串接唯讀媒合

- 分支：`feature/matching-terminal-demo`
- 基線：PR #5 head `55110e3c246e6f588dd575cb2c0716a47ea3dc27`
- 目標：讓人工 Demo 在完成表單追問後，實際呼叫第四個唯讀 MCP Tool 並顯示
  synthetic 師傅候選。

### 實作

- 將既有本機 terminal demo 移植到 PR #5 之上的 stacked branch。
- `DemoReadRepository` 新增兩位明確標示的 synthetic 師傅與空檔。
- `RuleBasedRepairMockModel` 在必填回答完成後，沿用工具回傳的
  `service_id` / `location_id` 呼叫 `match_service_providers`。
- 回覆顯示候選數、首選、時段與 `match_score`；來源標籤缺漏或空結果時安全停止，
  不自行捏造師傅。

### 安全與限制

- Demo 仍不連 AWS、不連 PostgreSQL、不寫資料、不保留時段、不建立案件。
- Mock 尚未把「星期六下午」解析成含時區的時間窗；目前媒合不傳
  `preferred_start` / `preferred_end`，不可宣稱已完成自然語言時間抽取。
- 此分支依賴尚未合併的 PR #5；PR #5 合併後才能 rebase 並建立後續 PR。

### 驗證

```powershell
python -m home_repair_agent.agent.demo --scripted
python -m pytest tests/test_agent_loop.py tests/test_agent_demo.py -q
python -m pytest -q
python -m ruff check src/home_repair_agent/agent tests/test_agent_loop.py tests/test_agent_demo.py
```

結果：

- 腳本化 Demo 依序呼叫四個唯讀 MCP Tools，顯示 2 位 synthetic 候選。
- 目標測試：18 passed。
- 完整測試：48 passed、10 skipped、40 subtests passed。
- Scoped Ruff、`compileall` 與 `git diff --check`：通過。

## 2026-07-26：本機 Agent 終端 Demo

- 分支：`feature/agent-terminal-demo`
- 基線：PR #4 head `1cde8a7677764f4b19169205911d0376d9ca1172`
- 目標：在沒有 PostgreSQL 與 AWS 環境時，提供可人工操作且可重現的 Agent
  閉環展示。

### 實作

- 新增 `home_repair_agent.agent.demo`，使用真實 `AgentRunner`、
  `MCPToolClient`、FastMCP Server 與 `ReadServiceLayer`。
- 新增明確標示的記憶體合成資料；只含一個服務、兩個行政區與縮短諮詢表單。
- 提供互動模式、固定三輪 `--scripted` 模式、MCP trace、`/help`、`/reset`
  與 `/quit`。
- 修正行政區查詢失敗後仍沿用舊地點的問題；重試時改解析最新使用者訊息。
- 新增 console entry point `home-repair-agent-demo`。

### 安全與限制

- Demo 不讀主辦方資料集、不連 PostgreSQL、不連 AWS、不寫入資料。
- Mock Model 僅證明 Agent 與 MCP 編排，不代表真實 LLM 的分類、抽取或回答品質。
- Agent 仍只允許 MCP catalog 中 `readOnlyHint=true` 的工具。

### 驗證

```powershell
python -m home_repair_agent.agent.demo --scripted
python -m pytest tests/test_agent_loop.py tests/test_agent_demo.py -q
python -m pytest -q
python -m ruff check src/home_repair_agent/agent tests/test_agent_loop.py tests/test_agent_demo.py
```

結果：

- 腳本化 Demo 依序呼叫 `search_services`、`resolve_location`、
  `get_consultation_form`，完成兩輪追問後停在確認前。
- 目標測試：14 passed。
- 完整測試：39 passed、9 skipped、25 subtests passed。
- Ruff：通過。

### 下一步

- 由獨立分支實作 `BedrockModelClient`，不要改動 `AgentRunner` 與 MCP 契約。
- 用固定 eval cases 比較 Mock 與 Bedrock 的 tool selection、參數抽取和失敗重試。
- AWS 環境可用後，再部署同一個 Agent 核心至 AgentCore Runtime。
