# AgentCore Remote MCP Demo — Requirements

**狀態：** Quick Spec（timeboxed）
**基底：** `a0406c2a0936d966976a6aaf5fcc50762856d497`
**資料界線：** synthetic-only

## 目前已有

- `create_mcp_server(ReadServiceLayer(...))` 已暴露四個唯讀 FastMCP Tools：`search_services`、`resolve_location`、`get_consultation_form`、`match_service_providers`。
- `DemoReadRepository` 提供 process-local synthetic 資料。
- 既有 AgentCore POC 已驗證一般 HTTP Runtime 的 deploy／invoke／cleanup，但尚未證明 MCP Streamable HTTP。

## 本次新增

1. **Remote MCP Runtime**：程序必須監聽 `0.0.0.0:8000`，MCP endpoint 為 `/mcp`，使用 `stateless_http=True`，Runtime protocol 設為 `MCP`。
2. **協定能力**：authenticated external Python MCP Client 必須完成 `initialize`、`tools/list` 與四個 `tools/call`；`tools/list` 僅可出現既有四工具。
3. **既有規則重用**：entrypoint 只組裝 `ReadServiceLayer(DemoReadRepository())` 與既有 FastMCP server；不得複製 Tool schema、matching 或 Service Layer 商業規則。
4. **結果 provenance**：後續 form／matching 使用的 service ID 與 location ID 必須由先前 ToolResult 解析取得，不可由 client fixture 硬編碼或猜測。
5. **synthetic-only guard**：HTTP 邊界拒絕過大、無效 JSON-RPC、圖片／binary 欄位，以及疑似真實姓名、電話、Email、完整門牌地址等輸入；不得記錄 request body。此 guard 是 Demo 資料邊界，不宣稱為通用 DLP。
6. **Authentication**：remote P0 使用既有安全 AWS session 的 IAM credentials，以 SigV4 簽署 AgentCore invocation；不得建立匿名 endpoint。若 ChatGPT Developer Mode 不支援該驗證方式，只記錄 blocker 與 Gateway＋OAuth 候選下一步。
7. **短效資源**：只可建立一個 Runtime、專用最小權限 execution role、private encrypted direct-code artifact storage 與專用 log group。所有資源使用相同且不超過六小時的 expiry 與指定 tags。
8. **失敗 cleanup**：deploy 或 invoke 任一步驟失敗，必須立即嘗試 cleanup；cleanup 可獨立執行，且刪除前驗證 owner／purpose，避免碰觸非本 Demo 資源。
9. **遮罩證據**：只保存時間、延遲、狀態、tool 名稱、provenance pass/fail、commit 與 cleanup metadata；不得保存完整 prompt／ToolResult、Authorization、ARN、account ID、credential 或真實個資。
10. **無副作用**：不得建立案件、派單、預約、訂單、寫入 MCP Tool 或持久化使用者輸入。

## 刻意不做

- 不修改 AgentRunner、MCP Tool schema、Service Layer 或 Web 工作線。
- 不建立 AgentCore Gateway、ECS、ECR、ALB、RDS、網站或公開匿名 endpoint。
- 不宣稱 Python MCP Client 成功等於 ChatGPT 已串接；不宣稱 Runtime MCP 等於網站已部署。
- 不使用真實姓名、電話、Email、精確地址、照片或其他個資。

## 驗收條件

### 本機

- 真實 Streamable HTTP client/server protocol 測試通過 initialize、精確四工具 list 與四次 call。
- 測試證明 service/location ID 來自前序 ToolResult、非法／非 synthetic 輸入被拒絕、沒有 workflow 副作用。
- focused tests、完整 pytest、Ruff check/format、compileall、diff check 與 credential／PII scan 通過。

### AWS P0

- Console 可見 authenticated AgentCore Runtime，狀態可接受 invocation。
- remote Python MCP Client 完成 initialize、精確四工具 list 與四次 call。
- 產生遮罩 evidence、Console 截圖清單、expiry 與可單獨執行的 cleanup command。
- 若 deploy／invoke 失敗，evidence 記錄遮罩錯誤分類並確認 cleanup 結果，不得改用匿名或假成功。
