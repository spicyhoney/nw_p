# Tests

測試至少涵蓋：

- JSON、CSV 與 SQL 來源可被解析。
- 清洗流程可重複執行且結果一致。
- 主鍵、外鍵和代碼驗證。
- 個資不會出現在 Agent-facing 輸出。
- Service Layer 的輸入正規化、唯一性與不猜測規則。
- PostgreSQL Repository 只查 `agent.*` 安全 views。
- 服務搜尋、行政區解析與表單組裝的真實 PostgreSQL 查詢。
- MCP Tool 輸入輸出符合固定 schema。
- 建立案件與訂單前必須取得使用者確認。
