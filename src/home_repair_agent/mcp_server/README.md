# MCP Server 實作說明

## 做了什麼

本模組把既有的 `ReadServiceLayer` 包成三個標準 MCP Tools：

| Tool | 輸入 | 回傳 | 用途 |
|---|---|---|---|
| `search_services` | 問題描述、筆數上限 | 支援的服務清單 | 從「水龍頭漏水」找出正式 `service_id` |
| `resolve_location` | 縣市、行政區 | 唯一行政區 ID | 將「台北市、大安區」對到正式地點 |
| `get_consultation_form` | `service_id` | 最新諮詢單與題目 | 告訴 Agent 接下來該追問哪些欄位 |

## 為什麼這樣做

MCP 層只負責讓 Agent 看得懂並呼叫系統能力。輸入正規化、不可猜測規則、
最新表單判定與 SQL 都仍由 Backend Service Layer 負責。如此一來，未來
FastAPI、AWS Lambda 或 AgentCore Gateway 可以共用同一套規則，不會出現
「網頁查到一種結果、Agent 查到另一種結果」。

## 資料流

```text
Agent
  -> MCP Tool
  -> ReadServiceLayer
  -> PostgresReadRepository
  -> PostgreSQL agent.* 安全檢視
  -> 結構化 ToolResponse
```

MCP Tool 不會接收任意 SQL，也不直接讀取 `core`、`staging` 或 `quarantine`
schema。

## 回傳契約

成功：

```json
{
  "ok": true,
  "data": {},
  "error": null
}
```

可預期且 Agent 能處理的狀況，例如行政區不存在或不唯一：

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "LOCATION_NOT_FOUND",
    "message": "找不到行政區。",
    "details": {}
  }
}
```

這類結果保留為結構化 domain response，讓 Agent 能追問使用者。非預期的
資料庫或程式錯誤則回傳 MCP `isError=true`，且只顯示
`SERVICE_UNAVAILABLE`，避免把連線資訊或內部細節洩漏給 Agent。

## 安全邊界

- 三個 Tool 均標示 `readOnlyHint=true`、`destructiveHint=false`、
  `idempotentHint=true`、`openWorldHint=false`。
- 不建立案件、不建立訂單、不修改資料。
- 不接受任意 SQL、資料表名稱或欄位名稱。
- 找不到或結果不唯一時回傳錯誤碼，不自行猜 ID。
- `DATABASE_URL` 僅由環境變數讀取，不得寫入 Git。

## 本機執行

安裝：

```powershell
python -m pip install -e ".[data,app,dev]"
```

預設以 stdio 執行：

```powershell
$env:DATABASE_URL="postgresql://..."
home-repair-mcp
```

以 Streamable HTTP 執行：

```powershell
$env:MCP_TRANSPORT="streamable-http"
$env:MCP_HOST="127.0.0.1"
$env:MCP_PORT="8000"
home-repair-mcp
```

HTTP MCP endpoint 為 `http://127.0.0.1:8000/mcp`。正式部署到 AWS 時才設定
實際 host、資料庫連線與 Gateway，不需要改 Tool 的商業規則。

## 測試

`tests/test_mcp_tools.py` 使用官方 SDK 的記憶體內 Client/Server 連線，檢查：

1. Agent 能列出三個 Tool 與唯讀 annotations。
2. 三個 Tool 的成功 structured content。
3. 可恢復的 domain error 契約。
4. 非預期錯誤不洩漏內部資訊。
5. 缺少 `DATABASE_URL` 與錯誤 port 設定會提早失敗。

## 尚未做

- 建立諮詢案件、媒合、確認訂單等寫入 Tool。
- MCP HTTP 的 OAuth / Gateway 驗證。
- 真實 Bedrock 模型的 tool-selection 評估。
- AWS AgentCore Gateway、Lambda 與 RDS 部署。

以上項目要等唯讀流程與權限邊界穩定後分階段加入。
