# 資料政策

## 資料層級

| 層級 | 定義 | 是否供 Agent 使用 |
|---|---|---|
| `raw` | 主辦方原始檔，內容與檔名不修改 | 否 |
| `staging` | 已解析成合法格式並統一型別，但尚未確認關聯 | 否 |
| `core` | 通過主鍵、外鍵、代碼與商業規則驗證 | 是 |
| `quarantine` | 不明代碼、孤兒關聯、狀態矛盾或損壞資料 | 否 |
| `external_reference` | 來自可追蹤公共來源的參考資料 | 視規則 |
| `curated_config` | 團隊依產品需求設計並版本化的設定，例如 MVP 諮詢表單 | 是，需標示 |
| `synthetic` | 為 Demo 建立的模擬服務商、時段與案例 | 是，需標示 |

## 來源標籤

清洗後資料至少保留：

- `source_type`
- `source_file`
- `source_record_id`
- `cleaning_rule`
- `quality_status`

建議的 `source_type`：

- `official_raw`
- `official_repaired`
- `external_reference`
- `curated_config`
- `synthetic`

## B+ 決策

本專案採用 B+：修復可由規則確定的格式與行政區資料，同時為水電修繕 MVP
建立一條可展示的模擬流程。正式資料、團隊設定與模擬資料不能混成同一種來源。

- 主辦方服務主檔中的 `service_id=17` 是水電修繕的正式依據。
- 水電諮詢表單由團隊設計，標記為 `curated_config`，不冒充主辦方原始表單。
- 師傅、服務區域、時段、案件、媒合與 Demo 訂單皆標記為 `synthetic`。
- 原始諮詢範例因關聯斷裂且含明文個資，只保留問題索引，不供 Agent 使用。
- 歷史訂單只做資料品質分析；即使單筆通過格式驗證，也不供 Agent 查詢。

## 不明資料處理

不明代碼不能靠名稱相似度直接改成正式 ID。例如：

- 未定義的 `order_type=07`
- 主檔不存在的 `service_id=18`
- 主檔不存在的 `service_vendor_id=15`
- 回饋資料引用不存在的題目或選項

這些資料先保留原值並移入 `quarantine`。若仍需要展示其統計價值，可透過
`unknown_service` 類別進入分析層，但不得進入會建立案件或訂單的 Agent 工具。

## 可安全修復

以下修復可由確定規則完成：

- 將多個 JSON 文件拆成合法結構。
- 將 JSON 字串解析成 JSON object。
- 保留行政區代碼前導零。
- 將旗標轉成一致的 boolean 或 code。
- 由縣市與行政區產生 `name_with_county`。
- 選定一份訂單格式作為權威來源，另一份只用於一致性驗證。

## 禁止推測補值

下列欄位不得以平均值、隨機值或 LLM 推測：

- 服務與服務商 ID
- 訂單狀態與時間
- 金額、退款與點數
- 題目與選項 ID
- 姓名、電話、Email、地址及密文

需要 Demo 資料時，應建立全新的合成紀錄，不改寫成官方紀錄。

## Agent 資料閘門

任何紀錄必須同時滿足以下條件才可透過 `agent` schema 查詢：

- `quality_status = 'verified'`
- `agent_eligible = true`

`review`、`quarantined`、`unresolved` 與歷史個資資料都不得繞過此條件。

## 個資

- Agent-facing database 不保存範例檔中的明文姓名、電話或 Email。
- 損壞的密文不可還原，清洗後應設為 `NULL` 並記錄原因。
- Demo 使用明確標示的虛構個資。
- 金鑰與資料庫連線字串只能放在 `.env` 或雲端秘密管理服務。
