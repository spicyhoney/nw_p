# 工程紀錄

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
