# B+ 資料清洗操作手冊

## 目的

這條管線把主辦方範例資料轉成可以安全接到修繕小隊長 MVP 的資料層。它不會
覆寫原始檔，也不會把無法證明的 ID 自動猜成另一個服務。

## 資料流

```text
主辦方原始檔
  -> 解析與型別統一
  -> 關聯、狀態、雙來源與個資檢查
  -> core / quarantine
官方行政區 API
  -> 固定版本快照
  -> core.location
團隊水電表單
  -> curated_config
Demo 師傅、時段、案件、訂單
  -> synthetic
core + demo
  -> agent schema 安全檢視
  -> Service Layer
  -> FastAPI / MCP Tools
```

## B+ 如何處理問題

| 原始問題 | B+ 處理 |
|---|---|
| JSON 檔含多個文件與說明文字 | 用解析器拆開並保留檔案雜訊警告 |
| 行政區只有 200 筆 | 與國土測繪中心快照對照，補齊至 368 筆並標記來源 |
| `service_id=7` | 保留為 unresolved；17 只記為語意候選，絕不直接改值 |
| `service_id=18`、`vendor_id=15` | 保留 unresolved 並隔離相關訂單 |
| `order_type=07` | 因 schema 未定義而隔離，不自行發明狀態規則 |
| JSON 與 CSV 都有訂單 | 逐欄語意比較；一致後只用 JSON 作權威來源 |
| 訂單項目有多種 JSON 形狀 | 正規化為共同 item list，原形狀另存標記 |
| 諮詢範例關聯斷裂且含個資 | 全份範例不供 Agent 使用，只留下問題索引 |
| 缺少師傅、時段與完整流程 | 新建 synthetic Demo 資料，不修改成官方資料 |

## 產出

可提交且不含範例會員個資：

- `data/reference/taiwan_admin_areas.json`
- `data/processed/core_service_catalog.json`
- `data/processed/core_locations.json`
- `data/processed/curated_repair_form.json`
- `data/processed/demo_seed.json`
- `data/processed/source_mappings.json`
- `data/processed/data_quality_summary.json`
- `reports/data_quality.md`

只留在本機：

- `data/processed/_local_historical_orders_redacted.json`
- `data/quarantine/_local_quarantine_index.json`
- 主辦方原始資料目錄

## 執行

使用 Python 3.11 以上：

```powershell
python .\scripts\fetch_admin_reference.py
python .\scripts\clean_data.py --reference-date 2026-08-01
```

`reference-date` 是 Demo 時段的固定日期。固定它可以確保兩位隊員重跑時得到
相同的模擬案例，不代表真實預約日期。

## 載入 PostgreSQL

安裝資料套件並啟動 PostgreSQL 後：

```powershell
pip install -e ".[data]"
docker compose up -d postgres
$env:DATABASE_URL="postgresql://home_repair:home_repair@localhost:5432/home_repair"
python .\scripts\clean_data.py --reference-date 2026-08-01
```

資料會經由 `sql/migrations/001_b_plus_schema.sql` 建表並 upsert。若電腦沒有
Docker，也能先完成 JSON 清洗；等團隊有可用的 PostgreSQL 後再執行載入。

## 團隊接手規則

- 不直接編輯 `data/processed/*.json`，應修改規則後重跑。
- 不把主辦方原始資料、`.env` 或本機隔離輸出加入 Git。
- 新增模擬資料時，ID 使用 `SYN-` 前綴且 `source_type=synthetic`。
- 新增團隊表單時提升版本號，並使用 `source_type=curated_config`。
- Agent 與 MCP Tool 只查 `agent` views，不查 raw 或 quarantine。
