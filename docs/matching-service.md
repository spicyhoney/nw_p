# 唯讀師傅媒合服務

狀態：已完成本機單元、MCP protocol 與 Agent tool-loop 驗證；PostgreSQL
整合案例已加入，等待提供 `TEST_DATABASE_URL` 後執行。

最後更新：2026-07-26

## 做了什麼

`ReadServiceLayer.match_service_providers()` 會依正式 `service_id`、正式
`location_id` 與選填的偏好時段，從 `agent.available_provider_slot` 查出
可服務的 synthetic 師傅和空檔，再以固定 `matching_v1` 規則排序。

同一份功能也包成第四個唯讀 MCP Tool `match_service_providers`。它只推薦候選，
不保留時段、不建立案件、不建立訂單，也不接收姓名、電話或地址。

## 輸入與輸出

輸入：

| 欄位 | 規則 |
|---|---|
| `service_id` | 必須是 `search_services` 回傳的正整數 |
| `location_id` | 必須是 `resolve_location` 回傳的非空 ID |
| `preferred_start` | 選填；提供時必須含時區 |
| `preferred_end` | 必須與 start 同時提供、含時區且較晚 |
| `limit` | 1 到 10，預設 3 |

輸出包含候選師傅、空檔、評分、完成件數、基本勘驗費、`match_score`、
四項分數明細、可讀推薦理由，以及 `source_type=synthetic`。查無候選時成功
回傳 `count=0` 與空陣列，不自行建立或替換師傅。

## 資料流

```text
Agent / 未來 FastAPI
  -> match_service_providers MCP Tool
  -> ReadServiceLayer.match_service_providers
  -> PostgresReadRepository.list_available_provider_slots
  -> agent.available_provider_slot
  -> 硬性資格篩選
  -> matching_v1 可解釋排序
  -> 唯讀候選結果
```

Repository 使用固定參數化 SQL，且只查 `agent.*` 安全 view。Service Layer 會再
防禦性確認每筆資料的 service、location 與時段重疊，避免 adapter 或替身資料
繞過商業規則。

## 資格與計分

以下是硬性資格，不符合就不進候選：

1. `service_id` 完全相同。
2. `location_id` 完全相同。
3. 資料庫時段狀態為 `available`。
4. 有指定偏好時段時，兩個時段必須有重疊。

通過資格後才套用 `matching_v1`：

| 分數 | 權重 | 算法 |
|---|---:|---|
| 時段適合度 | 40% | 重疊時間除以使用者要求時間；未指定時段時皆為 1 |
| 評分 | 35% | `rating / 5` |
| 經驗 | 20% | 完成件數除以本次候選最大完成件數 |
| 費用 | 5% | 本次候選中的相對低費用分數 |

總分為四項加權和，四捨五入到小數四位。同一師傅若有多個時段，只回傳排名
最高的一個。分數相同時再依評分、完成件數、費用、開始時間與 ID 做固定排序，
確保測試與 Demo 可重現。

這是團隊定義的透明 Demo 政策，不是由主辦方資料訓練出的模型，也不能用來宣稱
媒合準確率、市場供給或真實服務品質。之後若調整權重，必須建立新的 policy
version 與對應測試，不能悄悄改變 `matching_v1`。

## 安全與資料政策

- 師傅、服務區與時段來自 `demo.*` synthetic 資料，經
  `agent.available_provider_slot` 暴露。
- MCP Tool 標示 `readOnlyHint=true`、`destructiveHint=false`、
  `idempotentHint=true`、`openWorldHint=false`。
- 時段必須同時提供且含時區，範圍不得超過 31 天。
- Repository 最多取 100 個空檔，Service 最多回傳 10 位不同師傅。
- 查無候選不是系統錯誤；Agent 必須說明目前沒有資料，不能生成師傅。
- 本功能不寫資料，所以尚未需要確認 token、冪等 key 或訂單狀態驗證。

## 測試

```powershell
python -m pytest tests/test_read_services.py -q
python -m pytest tests/test_mcp_tools.py -q
python -m pytest tests/test_agent_loop.py -q
python -m pytest -q
```

2026-07-26 本工作區結果：

- Service Layer：`16 passed, 25 subtests passed`。
- MCP protocol：`7 passed, 11 subtests passed`。
- Agent：`13 passed`。
- 完整 suite：`44 passed, 9 skipped, 40 subtests passed`。

9 個 skipped 是需要 `TEST_DATABASE_URL` 的 PostgreSQL 整合測試；其中已包含
「大安區回傳兩位 synthetic 候選、板橋區回空清單」的新案例。本次未宣稱該
新增 SQL 已在真實 PostgreSQL 執行。

## 尚未做

- `RuleBasedRepairMockModel` 尚未把表單自由文字自動轉成時區化媒合參數；目前由
  scripted Agent 測試證明第四個 Tool 可通過安全迴圈。
- 不保留空檔、不建立諮詢案件、不確認媒合、不建立訂單。
- 尚無 FastAPI endpoint、Demo UI、真實 Bedrock tool-selection eval。
- 真實廠商資料接入前必須重新檢查授權、欄位契約與排序政策。
