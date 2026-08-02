# AgentCore Remote MCP Demo — Design

## 資料流

```text
Python MCP Client
  -> IAM SigV4 authenticated AgentCore invocation URL
  -> AgentCore Runtime :8000/mcp
  -> SyntheticOnlyMcpGuard (ASGI)
  -> existing FastMCP server (stateless Streamable HTTP)
  -> existing ReadServiceLayer
  -> existing DemoReadRepository (synthetic, process-local)
```

## Runtime entrypoint

`agentcore_remote_mcp_entrypoint.py` 只負責 composition：建立 `ReadServiceLayer(DemoReadRepository())`、呼叫既有 `create_mcp_server(...)`，再將 `streamable_http_app()` 包在 synthetic-only ASGI guard。Uvicorn 直接載入匯出的 `app`；不使用既有一般 HTTP POC 的 `BedrockAgentCoreApp` handler。

Guard 僅檢查 HTTP `POST /mcp`：限制 body 大小、要求合法 JSON object/batch 與 MCP method、檢查 `tools/call.arguments` 的 key/value。它拒絕 binary／圖片欄位、聯絡資訊與精確門牌樣式，然後以原 body 重放給 FastMCP；不 log body、不改 Tool schema、不替代 Service Layer validation。健康檢查及 lifespan 原樣轉送。

## Remote protocol client

client 使用 `mcp.client.streamable_http.streamablehttp_client`。自訂 `httpx.Auth` 取得 boto3 standard credential chain 的 frozen credentials，以 botocore `SigV4Auth` 對每個 request（含 body）簽署，service 名稱為 `bedrock-agentcore`。URL、headers、ARN 與 account ID 不輸出。

四工具流程：

1. `search_services` 搜尋 synthetic 修繕需求並從 structured ToolResult 解析唯一 service ID。
2. `resolve_location` 解析 synthetic 縣市／行政區並從結果解析 location ID。
3. `get_consultation_form` 使用步驟 1 的 service ID。
4. `match_service_providers` 使用步驟 1、2 的 IDs 與 synthetic fixture。

Evidence recorder 只寫 tool 名稱、status、elapsed_ms，以及「ID 是否源自前序結果」布林值。

## Deploy／cleanup

以既有 POC 的 boto3 adapter 與 direct-code ZIP 流程為基礎，但建立獨立 purpose-scoped state：

- private S3 bucket：Block Public Access、SSE、短效 lifecycle；只放 deploy ZIP。
- execution role：只含 Runtime 寫入專用 log／metrics 所需權限，不含模型 invocation。
- Runtime：`protocolConfiguration.serverProtocol=MCP`、`PUBLIC` network、指定 entrypoint／requirements。
- log group：purpose-scoped、短 retention。
- tags：`Project=nw_p`、`Purpose=agentcore-remote-mcp-demo`、`DataClassification=synthetic-only`、`ManagedBy=kiro`、共同 `ExpiresAt`。

本機 state file 不含 credentials，只保存 cleanup 必需的 identifiers；其內容不得進 Git/evidence。cleanup 先驗證 state schema、purpose、expiry 與遠端 tags，再依 Runtime → log group／role policy／role → artifact object／bucket 的順序清除。deploy／remote invoke 的 exception path 必定呼叫 cleanup；成功則保留至共同 expiry，供人工 Console 查看。

## 安全與失敗處理

- 缺 credential、SDK、Region 或權限時 fail fast，不 fallback。
- provider error 僅輸出安全 error code／stage，不輸出 response payload。
- client timeout、非法 ToolResult、空結果或歧義都判定 P0 failed，觸發 cleanup。
- ChatGPT Developer Mode 不具 IAM SigV4 相容驗證時，P1 狀態為 blocked；不變更 Runtime authentication。
- cleanup 若部分失敗，列出遮罩後的 resource type 與 retry command，絕不聲稱已清除。

## 測試策略

- ASGI／HTTP protocol test：ephemeral Uvicorn + MCP Streamable HTTP client，驗證 initialize/list/call 與 provenance。
- guard tests：非法 JSON、oversize、PII-like／image arguments 被 HTTP 邊界拒絕；合法 synthetic arguments 可通過。
- deploy unit tests：fake AWS clients 驗證 MCP protocol、固定 tags、共同 expiry、最小權限、failure cleanup 與 evidence redaction。
- AWS smoke 僅在本機全綠後執行，且只使用 synthetic fixture。
