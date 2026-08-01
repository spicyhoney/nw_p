# AWS AgentCore Runtime 短效 POC 證據

最後更新：2026-08-01

## 範圍與基底

- 分支：`feature/aws-agentcore-runtime-poc`。
- branch base：`1183a155b2d9e31fbb538a168abacd071ed93709`（PR #18 merge commit）。
- 目標：把 PR #18 已驗證的 `BedrockModelClient → AgentRunner → process-local MCP →
  ReadServiceLayer → DemoReadRepository` synthetic 閉環放進 AgentCore Runtime。
- 不建立 Gateway、RDS、EC2、公開網站、公開 S3、GPU、正式資料庫或圖片儲存。
- 不修改 AgentRunner、MCPToolClient、Service Layer、MCP schema、Web、派單／slot
  state 或 Kiro specs。

## 實作與安全閘門

- `agentcore_runtime_entrypoint.py` 只接受
  `{"scenario":"synthetic_repair_v1"}`；任意 prompt 或多餘欄位直接拒絕。
- Runtime 內部建立固定、無個資的 synthetic prompt；模型仍只能看到四個唯讀 MCP
  Tools，不能建案、派單、預約或保留時段。
- `scripts/agentcore_runtime_poc.py` 執行 ARM64 package、deploy、invoke、log 檢查及
  `finally` cleanup；狀態檔不含 credential。
- direct-code artifact 使用 Python 3.12、`bedrock-agentcore 1.19.0`、
  `boto3 1.43.62`、`mcp 1.29.0` 與 `pydantic 2.13.4`，大小 25,879,185 bytes。
- artifact 不含 `.env`／`.git`／credentials；AWS key、HF token、private key 與本機
  絕對路徑掃描皆為 0。
- IAM trust policy 限定 `bedrock-agentcore.amazonaws.com`、本帳號與 `us-west-2`
  AgentCore ARN；execution policy 只允許指定 Nova Lite 與 Runtime 專用 log／metric。
- S3 開啟四項 Block Public Access 與 SSE-S3；Runtime 採 IAM SigV4、PUBLIC network
  mode 只提供受控服務連線，不是匿名公開網站。
- lifecycle：idle timeout 60 秒、max lifetime 300 秒；無 AgentCore Memory。

## Live deploy／invoke

| 欄位 | 證據 |
|---|---|
| 全流程 UTC | `2026-08-01T08:58:53+00:00` 至 `09:00:00+00:00` |
| invoke 臺北時間 | `2026-08-01T16:59:47+08:00` |
| Region | `us-west-2` |
| model ID | `amazon.nova-lite-v1:0` |
| Runtime ID | `nw_p_runtime_poc-u4UhS4EYaz` |
| redacted input | `[synthetic repair request with public location names]` |
| redacted output | `[synthetic service/location/form/provider summary; no case or booking created]` |
| stop reason | `completed` |
| Bedrock requests | `4` |
| request intervals | `1.303`、`1.102`、`1.102` 秒 |
| output character count | `154` |
| 結果 | `passed` |

遮罩後 tool trace：

```text
search_services(query=[synthetic repair issue]) -> ok, count=1
resolve_location(county_name=台北市, district_name=大安區) -> ok
get_consultation_form(service_id=17) -> ok
match_service_providers(service_id=17, location_id=DEMO-63000030)
  -> ok, count=2, data_source=synthetic
```

service／location ID 仍由更早的成功 ToolResult 提供；同輪猜 ID 的 PR #18 regression
tests 仍通過。Runtime invocation 自身沒有建立其他 AWS 資源。

## CloudWatch 證據

- log group：`/aws/bedrock-agentcore/runtimes/nw_p_runtime_poc-u4UhS4EYaz-DEFAULT`。
- cleanup 前讀到 passed marker；本輪 log delivery 只回一個已聚合事件，因此 started
  marker 未單獨出現，不把它誤報為已觀測。
- credential／private-key pattern：`0`。
- `toolConfig`、`output.message`、`inputText` 等完整 provider payload marker：`0`。
- 讀取證據後已刪除此 log group。

## 建立與 cleanup

短效建立的資源：

| 資源 | Region | tags／控制 | cleanup |
|---|---|---|---|
| AgentCore Runtime | `us-west-2` | `Project=nw_p`、`Purpose=agentcore-runtime-poc`、短 lifecycle | 已刪除 |
| workload identity | `us-west-2` | Runtime 自動建立 | 已不存在 |
| S3 artifact bucket | `us-west-2` | private、Block Public Access、SSE-S3 | object 與 bucket 已刪除 |
| IAM execution role | global | 最小 Bedrock／CloudWatch policy | inline policy 與 role 已刪除 |
| CloudWatch log group | `us-west-2` | Runtime 專用 | 證據讀取後已刪除 |

腳本 cleanup：無錯誤，Runtime count `0`、bucket 不存在、role 不存在。再以獨立 AWS
CLI 驗證：Runtime `0`、workload identity `0`、POC bucket `0`、POC log group `0`，
IAM `GetRole` 回 `NoSuchEntity`。因此沒有仍在運行或持續儲存的 POC 資源；只可能有
已完成的短效 Runtime／Bedrock request 用量。

Workshop credential 只存在活動頁、單次 child-process environment 與短效 temp
bridge。完成後 temp bridge `exists=False`，瀏覽器暫存字串已清空；repo、報告與
deployment artifact 都沒有 credential。

## 驗證

| 驗證 | 結果 |
|---|---|
| Runtime／policy／Bedrock E2E focused | `38 passed, 7 subtests passed` |
| 完整 `pytest -q` | `175 passed, 19 skipped, 59 subtests passed` |
| 受影響 Ruff／format | passed |
| `git diff --check` | passed |
| ARM64 artifact secret／absolute-path scan | 0 matched files |
| 真實 deploy／invoke／log／cleanup | passed |

19 個 skip 仍是未提供 `TEST_DATABASE_URL`／對應外部環境的既有條件。兩個 warning
來自 AgentCore SDK 的 Pydantic deprecation 與既有 FastAPI／Starlette 相依套件，
不是本 POC failure。

## 尚未證明

- AgentCore Gateway、Streamable HTTP MCP 與外部 Client。
- PostgreSQL／RDS、Web Bedrock routing、正式登入或公開 HTTPS Demo。
- 真實案件、圖片、個資、建案、派單、預約與訂單寫入。
- 固定 Bedrock eval matrix、長時間負載、成本與延遲比較。

完整機器可讀證據在 `reports/agentcore_runtime_poc.json`。官方依據：
[direct-code deployment](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html)、
[Runtime IAM permissions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html)、
[lifecycle settings](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html)。
