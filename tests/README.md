# Tests

測試至少涵蓋：

- JSON、CSV 與 SQL 來源可被解析。
- 清洗流程可重複執行且結果一致。
- 主鍵、外鍵和代碼驗證。
- 個資不會出現在 Agent-facing 輸出。
- Service Layer 的輸入正規化、唯一性與不猜測規則。
- PostgreSQL Repository 只查 `agent.*` 安全 views。
- 服務搜尋、行政區解析、表單組裝與 synthetic 師傅媒合的 PostgreSQL 查詢。
- MCP Client 能透過記憶體內協定列出並呼叫四個唯讀 Tool。
- MCP Tool annotations、structured content、domain error 與錯誤遮罩符合契約。
- Agent 能完成多步 Tool loop、跨輪保存訊息並停在寫入確認前。
- 媒合規則的資格篩選、透明分數、同師傅去重與空結果不猜測。
- Agent 只看見唯讀 Tool，且未知 Tool、外部錯誤與無限迴圈會安全停止。
- Hugging Face adapter 能轉換多輪訊息與 function schema、解析 tool call，
  並在缺 token、provider 錯誤、不合法回覆或請求逾時時 fail safe。
- Demo synthetic 時段由可注入時鐘產生在下一個未來星期六，不會因寫死日期
  過期。
- FastAPI Web session、三個初始查詢 Tool、動態表單、`+08:00` 時段驗證、
  第四個媒合 Tool、synthetic 候選、reset、安全 header 與未知欄位拒絕。
- 建立案件與訂單前必須取得使用者確認。
