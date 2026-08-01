# AWS Bedrock × MCP 完整閉環證據

最後更新：2026-08-01

## 範圍與基底

- 分支：`feature/aws-bedrock-mcp-e2e`。
- branch base：`357cc274b56bfbcaec81aefeccfe97cc730446ac`（PR #17 已合併後的
  `main`）。
- 本輪只新增可重跑的 E2E harness、contract tests 與文件；沒有修改
  `AgentRunner`、`MCPToolClient`、Service Layer、MCP schema、Web、派單／slot state、
  `HANDOFF.md`、`TASKS.md`、`app.py`、`pyproject.toml` 或 Kiro specs。

## 驗證路徑

`scripts/bedrock_mcp_e2e.py` 執行下列真實閉環：

```text
synthetic 使用者需求
  -> AgentRunner
  -> BedrockModelClient / Amazon Bedrock Converse
  -> ModelTurn.tool_calls
  -> MCPToolClient
  -> process-local MCP ClientSession / FastMCP Server
  -> ReadServiceLayer
  -> DemoReadRepository
  -> structured ToolResult
  -> BedrockModelClient
  -> 最終文字回答
```

四個實際 MCP Tool 都由 Nova Lite 自己選擇，工具結果則由既有 MCP／Service 路徑
產生，不在 harness 內手動偽造：

1. `search_services`
2. `resolve_location`
3. `get_consultation_form`
4. `match_service_providers`

`match_service_providers` 只查詢 synthetic 候選，不是建立案件、派單、預約或保留
時段。現有四個 MCP Tools 仍全部唯讀。

## Bedrock live evidence

| 欄位 | 證據 |
|---|---|
| UTC | `2026-08-01T05:47:07+00:00` |
| 臺北時間 | `2026-08-01T13:47:07+08:00` |
| Region | `us-west-2` |
| model ID | `amazon.nova-lite-v1:0` |
| redacted input | `[synthetic repair request with public location names]` |
| redacted output | `[synthetic service/location/form/provider summary; no case or booking created]` |
| output character count | `253` |
| Bedrock requests | `4` |
| request start intervals | `1.797s`、`1.110s`、`1.437s` |
| stop reason | `completed` |
| 結果 | `passed` |

遮罩後 tool trace：

```text
search_services(query=[synthetic repair issue]) -> ok, count=1
resolve_location(county_name=台北市, district_name=大安區) -> ok
get_consultation_form(service_id=17) -> ok
match_service_providers(service_id=17, location_id=DEMO-63000030)
  -> ok, count=2, data_source=synthetic
```

`PacedModelClient` 以 monotonic clock 保證每次 request start 至少相隔 1.1 秒；live
觀測值全部符合比賽每秒最多一個 Bedrock request 的限制。它只包裝既有
`ModelClient` contract，沒有修改 `AgentRunner`。

## 執行方式

AWS 身分仍使用標準 SDK credential provider chain，憑證不得寫入 repo：

```powershell
$env:BEDROCK_REGION = "us-west-2"
$env:BEDROCK_MODEL_ID = "amazon.nova-lite-v1:0"
python scripts/bedrock_mcp_e2e.py
```

harness 只輸出 redacted I/O、必要的 synthetic tool trace、request count／interval 與
資源清單，不輸出完整 provider request／response、credential 或個資。Workshop
credential 只存在瀏覽器記憶體、單次 child process environment 與短效 temp bridge；
`finally` 已刪除橋接檔與環境變數，完成後確認 temp path 不存在。

## AWS 資源與計費

| 項目 | Region | 本輪建立 | 持續計費 |
|---|---|---|---|
| Bedrock on-demand Converse | `us-west-2` | 無持久資源；成功 4 requests | 否；只有已完成 inference 用量 |
| AgentCore／Gateway／S3／RDS／EC2／公開網站 | 無 | 0 | 否 |

本輪沒有執行 AWS create、deploy、update 或 delete API；因此沒有資源 ID、tags 或
cleanup 對象。

## 測試結果

| 驗證 | 結果 |
|---|---|
| E2E harness focused | `10 passed, 4 subtests passed` |
| Bedrock／live-smoke／E2E focused | `33 passed, 7 subtests passed` |
| AgentRunner／Demo／MCP regression | `29 passed, 11 subtests passed` |
| 完整 `pytest -q` | `166 passed, 19 skipped, 59 subtests passed` |
| 受影響 Ruff | passed |
| 全 repo Ruff | 22 個既有 data-cleaning findings；PR #17 base 同樣為 22，沒有新增 |
| compileall | passed |
| `git diff --check` | passed |
| AWS／HF key 與 private-key pattern scan | 0 matched files |

19 個 skip 是未提供 `TEST_DATABASE_URL`／對應資料環境的既有條件；本輪不改資料庫
契約。短效 AWS credential temp bridge 在 live run 的 `finally` 清除後為 0 個。

PR #18 review 修正後，`PacedModelClient` 拒絕所有低於 1.1 秒的設定；E2E 驗證會依
`ConversationSession` 的 ModelTurn 邊界，確認 form／match 使用的是更早成功
ToolResult 實際回傳的 service／location ID。同一輪預先猜中 Demo ID、錯誤 MCP
結果、`ok=false`、`max_steps` 與未遮罩參數都有 regression tests。

## 尚未證明

- 這是 process-local MCP protocol session，不是 Streamable HTTP、AgentCore Gateway
  或外部 Client；`MCP-001` 仍未完成。
- 使用 `DemoReadRepository` 的明確 synthetic 目錄，不是 PostgreSQL／RDS。
- 只驗證唯讀服務查詢與候選媒合，不建立案件、訂單或真正派單。
- AgentCore Runtime／Gateway、Web Bedrock routing、CloudWatch 與 IAM deployment
  仍未實作。
- 單一固定案例不能代表完整模型品質；仍需正常、模糊、缺地點、多地點與 provider
  error 的評估矩陣。
