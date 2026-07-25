# 系統架構

## 線上流程

```text
使用者介面
  -> AgentCore Runtime / Bedrock Model
  -> AgentCore Gateway / MCP
  -> FastAPI 或 Lambda Tools
  -> Service Layer
  -> PostgreSQL
```

語言模型負責理解需求與選擇工具，後端負責驗證參數、執行商業規則和查詢資料庫。
Agent 不直接連線資料庫，也不會取得可執行任意 SQL 的工具。

## 離線資料流程

```text
主辦方原始 SQL / JSON / CSV
  -> raw：唯讀保存
  -> staging：格式與型別標準化
  -> core：通過關聯與商業規則驗證
  -> PostgreSQL
  -> MCP Tools / API
```

無法確認的資料會進入 `quarantine`，不提供給正式 Agent。外部參考資料與合成資料
必須保留來源標籤，不能偽裝成主辦方資料。

## MVP Tools

| Tool | 作用 | 副作用 |
|---|---|---|
| `search_services` | 依使用者描述查詢服務 | 無 |
| `resolve_location` | 將縣市、行政區名稱轉成代碼 | 無 |
| `get_consultation_form` | 取得服務需要詢問的題目 | 無 |
| `create_consultation_case` | 建立諮詢案件 | 需使用者確認 |
| `match_service_providers` | 依地區、服務與時段配對 | 無 |
| `confirm_booking` | 確認媒合結果 | 需使用者確認 |
| `get_order_status` | 查詢案件或訂單狀態 | 無 |

在 PostgreSQL 完成前，Agent 可以使用相同輸入輸出格式的 Mock Tools 開發。

