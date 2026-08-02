# AgentCore Remote MCP Demo 實作與遮罩證據

最後更新：2026-08-02

## 範圍與基底

- branch：`feature/agentcore-remote-mcp-demo`
- exact base：`a0406c2a0936d966976a6aaf5fcc50762856d497`
- 目標：外部 Python MCP Client 經 authenticated AgentCore Runtime Streamable HTTP，呼叫既有四個唯讀 FastMCP Tools。
- 資料：只使用 `DemoReadRepository` 的 synthetic 資料；沒有真實姓名、電話、Email、門牌或圖片。

本工作沒有修改 `AgentRunner`、四個 Tool schema、`ReadServiceLayer` 商業規則、Web、案件／派單／預約／訂單流程、`HANDOFF.md` 或 `TASKS.md`，也沒有建立 Gateway、ECS、ECR、ALB、RDS 或網站。

## 已實作資料流

```text
Python MCP Client
  -> IAM SigV4 authenticated AgentCore Runtime invocation
  -> Streamable HTTP /mcp
  -> SyntheticOnly MCP ASGI guard
  -> existing FastMCP tools
  -> existing ReadServiceLayer
  -> existing DemoReadRepository
```

Runtime 監聽 `0.0.0.0:8000`，AgentCore protocol 設為 `MCP`，FastMCP 使用 stateless HTTP。對外只列出：

1. `search_services`
2. `resolve_location`
3. `get_consultation_form`
4. `match_service_providers`

client 先從搜尋與地點 ToolResult 解析 service/location ID，再傳給後續表單與媒合呼叫；空結果、歧義、錯誤結果或 provenance 不一致皆 fail closed。

## 輸入與安全邊界

`agentcore_remote_mcp_entrypoint.py` 的 ASGI guard：

- 限制 `POST /mcp` request body 為 64 KiB。
- 驗證 JSON-RPC object／batch、method、四工具名稱與既有參數白名單。
- 拒絕額外參數、圖片／binary、Email、電話、明示姓名與門牌樣式。
- 不記錄 request body，不在錯誤回應回顯輸入。

這是 Demo 的 synthetic-only 邊界，不宣稱為正式 DLP 或個資治理能力。正式個資、住家照片、RBAC、加密、保存與刪除政策仍未完成。

Remote client 使用 boto3 standard credential chain 與 SigV4；缺 ARN、Region、credential、initialize 失敗或遠端錯誤時停止，不 fallback 到 local MCP、Mock 或 Hugging Face。Runtime ARN、invocation URL、Authorization 與 provider payload不進 report 或 log。

## 短效 AWS 資源與 cleanup

部署腳本只管理下列 purpose-scoped 資源類型：

- AgentCore Runtime
- Runtime auto-created workload identity
- 專用 IAM execution role
- private、Block Public Access、AES256 direct-code S3 artifact bucket/object
- 專用短 retention CloudWatch log group

所有資源使用共同 tags：`Project=nw_p`、`Purpose=agentcore-remote-mcp-demo`、`DataClassification=synthetic-only`、`ManagedBy=kiro` 與共同 `ExpiresAt`。execution role 只有 Runtime log／metric 權限，不含 Bedrock model invocation。

local state 位於 ignored `var/agentcore-remote-mcp/state.json`，只供安全 cleanup；不得提交或顯示。cleanup 會先驗證 state、caller boundary、精確名稱與 purpose／owner tags。deploy 或 invoke 失敗會自動 cleanup；本次成功後依明確指示保留供人工 Demo，尚未執行 cleanup。

```powershell
$Env:AWS_PROFILE="hackathon"
$Env:AWS_DEFAULT_REGION="us-west-2"
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
& "var\agentcore-remote-mcp\test-venv\Scripts\python.exe" `
  scripts\agentcore_remote_mcp_demo.py cleanup
```

## Remote P0 遮罩證據

機器可讀 evidence：`reports/agentcore_remote_mcp_demo.json`

| 驗收 | 結果 |
|---|---|
| Runtime status | `READY` |
| MCP initialize | passed |
| tools/list exact set | 四個唯讀 tools，passed |
| 四個 tools/call | 全部 passed |
| service/location provenance | 全部 passed |
| provider data source | `synthetic` |
| business write side effects | 0 |
| retained resource types | Runtime、workload identity、log group、IAM role、S3 bucket |
| failure stage/type | `null`／`null` |
| expiry | `2026-08-02T07:27:49+00:00` |

遮罩 trace 只保存 tool name、status、elapsed milliseconds 與 provenance label；不保存完整 prompt、arguments、ToolResult、ARN、account、URL、credential 或 provider payload。

## 本機驗證

- focused AgentCore／MCP：`33 passed, 36 subtests passed`
- 乾淨 Python 3.11 完整 suite：`202 passed, 18 skipped, 84 subtests passed`
- 新增檔 Ruff check／format：passed
- compileall、Node checklist concurrency、diff check：passed
- 新增行與 1,033-entry deployment ZIP credential／PII pattern scan：passed
- 全域 Ruff 的 22 個 findings 都位於 exact base 已有且未修改的 data-cleaning 檔案；本工作沒有跨界修正。

skip 仍代表環境條件未提供，不列為成功證據。AWS P0 成功不代表模型品質、網站部署、正式服務可用性或長期額度。

## 刻意未做與下一步

- 沒有驗證 ChatGPT Developer Mode；Python MCP Client 成功不得稱為 ChatGPT 已串接。
- 沒有關閉 IAM authentication 或建立匿名 endpoint。
- 若未來需要 ChatGPT OAuth 相容入口，AgentCore Gateway＋OAuth 只能作為另行審查的候選，不在本工作建立。
- Web 尚未改用 remote ToolClient；應以獨立 provider-neutral adapter 與 FastAPI lifespan wiring 完成，不把 provider response 擴散到 Web service。
- 這是 AgentCore Runtime MCP 後端，不是網站 hosting。

## 官方參考

- [Host MCP servers in AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp.html)
- [Invoke an AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-invoke-agent.html)

以上官方內容已重新表述，未複製長段原文。Content was rephrased for compliance with licensing restrictions.
