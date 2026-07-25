# SQL

此目錄將保存 PostgreSQL migrations、constraints 和 reference data seeds。

主辦方 SQL 只作為來源規格，不直接視為可執行的最終 migration。正式 migration
必須通過語法檢查，並對 `core` 資料加入必要的外鍵、唯一鍵與代碼限制。

`migrations/001_b_plus_schema.sql` 建立四個 schema：

- `core`：可追蹤來源的服務、行政區、表單、映射與品質問題。
- `quarantine`：只保存問題索引，不複製含個資的原始 payload。
- `demo`：明確標示為 synthetic 的師傅、時段、案件、媒合與訂單。
- `agent`：只呈現 verified 且 agent-eligible 資料的安全檢視。

清洗命令若取得 `DATABASE_URL`，會自動套用 migration 並執行可重複的
upsert。MCP Tools 與 FastAPI 應查詢 `agent` views 或由 Service Layer
存取指定表格，不提供任意 SQL 給模型。
