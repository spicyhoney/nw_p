# AI 資料檢查清單

## 檢查範圍

檢查 `feature/data-cleaning` 相對於 `main` 的 B+ 資料清洗變更。先讀：

1. `docs/data-policy.md`
2. `docs/data-cleaning-runbook.md`
3. `docs/data-dictionary.md`
4. `reports/data_quality.md`
5. `sql/migrations/001_b_plus_schema.sql`

不要把主辦方原始資料貼到外部服務，也不要在回覆中輸出明文聯絡資料。

## 必查項目

### 原始資料

- 原始檔是否保持不變且被 Git 忽略。
- JSON 與 CSV 訂單是否逐欄語意比較，而不是只比較檔案大小。
- 碎片化 JSON 的非 JSON 文字是否留下可追蹤警告。

### 映射政策

- `service_id=7` 是否仍為 unresolved。
- `candidate_canonical_id=17` 是否沒有被當成 `canonical_id`。
- `service_id=18`、`service_vendor_id=15`、`order_type=07` 是否未被猜測補值。
- unresolved mapping 是否全部 `agent_eligible=false`。

### 來源與品質

- 正式、外部、團隊設定與 synthetic 資料是否有不同 `source_type`。
- 每筆可用資料是否有 `source_file`、`source_record_id` 與 `cleaning_rule`。
- 所有 `agent_eligible=true` 紀錄是否同時為 `quality_status=verified`。
- 搜尋別名是否標記為 `curated_config`。

### 個資

- 可提交的 processed data 是否不含 `member_name`、`member_phone`、
  `member_email` 或原始 `feedback_content`。
- `quarantine.source_record.raw_payload_included` 是否被限制為 `false`。
- 歷史訂單是否完全不出現在 `agent` views。

### Synthetic Demo

- provider、service area、availability、case、match、order、order item 是否形成
  完整且外鍵一致的鏈。
- synthetic 紀錄是否使用 `SYN-` ID、`source_type=synthetic`。
- Demo 是否只使用正式存在的 `service_id=17` 與已驗證行政區。
- 文件是否明確說明 synthetic 不代表真實營運資料。

### PostgreSQL

- migration 是否可重複執行。
- 主鍵、外鍵、唯一鍵、狀態與金額 constraint 是否合理。
- `agent` views 是否只呈現 verified 且 agent-eligible 資料。
- MCP/FastAPI 是否預計透過 Service Layer 查詢，不開放任意 SQL。

## 執行驗證

```powershell
python .\scripts\clean_data.py --reference-date 2026-08-01
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

本機有 PostgreSQL 時，再執行 migration 與 loader，確認所有外鍵、constraint、
view 和 `COMMENT ON` 都能成功建立。

可使用獨立測試資料庫執行 PostgreSQL 整合測試：

```powershell
$env:TEST_DATABASE_URL="postgresql://home_repair:home_repair@127.0.0.1:55432/home_repair"
python -m unittest tests.test_postgres_integration -v
```

## 回報格式

AI 應先列問題，再列摘要。每項問題包含：

- 嚴重度：P0、P1、P2 或 P3
- 檔案與行號
- 會造成的錯誤或資料風險
- 最小修正建議

沒有發現問題時，也要說明尚未執行的測試與剩餘風險，特別是 PostgreSQL
migration 是否已在真實 PostgreSQL 16 上驗證。

## 可直接交給 AI 的提示詞

```text
請先閱讀 docs/data-policy.md、docs/data-cleaning-runbook.md、
docs/data-dictionary.md、docs/ai-data-review-checklist.md 與
reports/data_quality.md，接著 review main...feature/data-cleaning。

優先找會讓不明 ID 被誤映射、個資外洩、synthetic 被誤認為官方資料、
agent_eligible 閘門失效、PostgreSQL 外鍵/constraint/loader 失敗的問題。
請不要直接修改程式，先依 P0-P3 列出 findings，附檔案與行號；若沒有問題，
請清楚列出已執行的檢查與尚未驗證的風險。
```
