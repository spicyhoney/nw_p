# PostgreSQL 16 整合測試報告

測試日期：`2026-07-26`

## 環境

- PostgreSQL：16.14，EDB Windows x86-64 binary ZIP
- 啟動方式：原生 Windows `initdb` / `pg_ctl`
- 監聽範圍：僅 `127.0.0.1`，使用非預設暫時連接埠
- Python：專案 `.venv`
- Driver：psycopg 3.3.4
- 資料庫編碼：UTF-8
- Locale：`C`
- Docker、WSL、Hyper-V：未使用

PostgreSQL binary 與 data directory 使用純英文暫存路徑，避免 Windows
PostgreSQL post-bootstrap 在含中文路徑下發生編碼錯誤。

## 載入結果

Migration `sql/migrations/001_b_plus_schema.sql` 成功執行，loader 共處理 812 筆：

| 資料表 | 筆數 |
|---|---:|
| `core.service_vendor` | 6 |
| `core.service` | 8 |
| `core.location` | 368 |
| `core.source_mapping` | 24 |
| `core.data_issue` | 280 |
| `core.form_template` | 1 |
| `core.form_topic` | 8 |
| `core.form_option` | 14 |
| `quarantine.source_record` | 87 |
| `demo.provider` | 3 |
| `demo.provider_service_area` | 6 |
| `demo.provider_availability` | 3 |
| `demo.consultation_case` | 1 |
| `demo.match_result` | 1 |
| `demo.service_order` | 1 |
| `demo.order_item` | 1 |

## Agent Views

| View | 筆數 |
|---|---:|
| `agent.service_catalog` | 8 |
| `agent.location_catalog` | 368 |
| `agent.form_template` | 1 |
| `agent.form_topic` | 8 |
| `agent.form_option` | 14 |
| `agent.available_provider_slot` | 6 |
| `agent.consultation_case` | 1 |
| `agent.service_order` | 1 |

`service_id=7/18` 沒有出現在 `agent.service_catalog`；所有 unresolved mapping
均為 `agent_eligible=false`。

## 安全規則

測試以交易方式故意提交違規修改，資料庫均正確拒絕並 rollback：

1. 將 agent-eligible 行政區改成 `quality_status=review`。
2. 將已驗證 mapping 改成 unresolved 但仍保持 agent-eligible。
3. 將 quarantine `raw_payload_included` 改成 `true`。
4. 將 synthetic provider 指向不存在的 `service_id`。
5. 將 synthetic provider 偽裝成 `official_repaired`。

## 其他驗證

- Schema、table、重要 column 與 Agent view 的 `COMMENT ON` 可由 PostgreSQL 查詢。
- 第二次套用 migration 與 loader 成功。
- 重跑前後各資料表筆數一致。
- `search_services` 能從完整句子中的「水龍頭漏水」找到
  `service_id=17 / 水電修繕`。
- `resolve_location("台北", "大安")` 唯一解析為
  `ORG-01-007 / 台北市大安區`。
- `get_consultation_form(17)` 回傳 `repair_form_v1`、8 題與 14 個選項；
  沒有表單的服務不會被套用水電表單。
- 完整測試套件 28 項全部通過，其中 8 項為 PostgreSQL 整合測試。
- 測試後已使用 fast shutdown 停止伺服器，連接埠確認不再回應；可攜 binary、
  data directory 與下載 ZIP 均已刪除。

## 尚未涵蓋

- 正式雲端 PostgreSQL／RDS 權限與網路設定。
- Agent 專用唯讀資料庫角色及 `GRANT`。
- 多使用者併發、效能與備份還原。
- FastAPI／MCP adapter 對只讀 Service Layer 的端到端呼叫。
- 建案、預約與訂單等寫入 Service Layer 的交易與使用者確認。
