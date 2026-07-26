# Service Layer 第一階段

## 第一階段為什麼先做三個只讀功能

這三個功能不是 Service Layer 的全部，而是第一條可以安全驗證的查詢鏈：

```text
找出服務
  -> 解析服務地點
  -> 取得該服務的諮詢表單
```

使用者輸入「台北市大安區水龍頭漏水」時，系統至少要先回答：

1. 這是什麼正式服務？
2. 地點在資料庫中是哪一筆？
3. 這項服務需要詢問哪些欄位？

這三步不會新增案件、修改訂單或接觸聯絡資料，所以適合先用來建立 Service Layer
骨架。等 FastAPI、MCP 與 Agent 接上後，仍會繼續新增媒合與寫入功能。

## 程式分層

```text
FastAPI endpoint / MCP Tool
            |
            v
      ReadServiceLayer
  輸入正規化、商業規則、不猜測
            |
            v
       ReadRepository
       固定且參數化的 SQL
            |
            v
 PostgreSQL agent.* 安全 views
```

主要檔案：

| 檔案 | 用途 |
|---|---|
| `backend/models.py` | 穩定、可轉 JSON 的輸出資料模型 |
| `backend/errors.py` | API 與 MCP 可共用的錯誤格式 |
| `backend/ports.py` | Service Layer 要求的 Repository 介面 |
| `backend/services.py` | 四個查詢的輸入驗證、商業規則與透明媒合計分 |
| `backend/postgres_repository.py` | 只查 `agent.*` views 的參數化 SQL |

FastAPI 與 MCP 未來只能呼叫 Service Layer，不在 adapter 中複製 SQL 或規則。

## 第一階段三個功能

### `search_services`

用途：把問題描述對應到 Agent 可使用的正式服務。

| 項目 | 內容 |
|---|---|
| 輸入 | `query`、`limit` |
| 資料來源 | `agent.service_catalog` |
| 搜尋依據 | 正式名稱、服務類型、團隊標記的 aliases、受控 search text |
| 安全規則 | view 已排除 unresolved 與 `agent_eligible=false` 資料 |
| 無結果 | 回傳空清單，不自行創造服務 |

真實 PostgreSQL 範例：

```text
query = 台北市大安區水龍頭漏水
result = service_id 17 / 水電修繕
```

### `resolve_location`

用途：把使用者縣市與行政區文字解析成唯一正式地點。

| 項目 | 內容 |
|---|---|
| 輸入 | `county_name`、`district_name` |
| 資料來源 | `agent.location_catalog` |
| 正規化 | 空白、全形字元、`台` / `臺`、可省略縣市區鄉鎮後綴 |
| 無結果 | `LOCATION_NOT_FOUND` |
| 多筆結果 | `LOCATION_AMBIGUOUS`，列出候選 ID，不自行選擇 |

真實 PostgreSQL 範例：

```text
county_name = 台北
district_name = 大安
result = ORG-01-007 / 台北市大安區
```

### `get_consultation_form`

用途：取得某項服務目前可供 Agent 使用的最新版表單、題目與選項。

| 項目 | 內容 |
|---|---|
| 輸入 | 正整數 `service_id` |
| 資料來源 | `agent.form_template`、`agent.form_topic`、`agent.form_option` |
| 版本規則 | 選唯一的最高版號 |
| 沒有表單 | `FORM_NOT_FOUND`，不套用其他服務的表單 |
| 同版多份 | `FORM_AMBIGUOUS`，不自行選擇 |

目前只有團隊正式設定的水電修繕表單：

```text
service_id = 17
form = repair_form_v1
topics = 8
options = 14
```

例如 `service_id=2` 是洗衣機清洗，但目前沒有通過政策的對應表單，因此會回
`FORM_NOT_FOUND`，不會拿水電表單代替。

## `match_service_providers`

用途：依正式服務、正式行政區與選填偏好時段，查詢並排序可用的 synthetic
師傅候選。

| 項目 | 內容 |
|---|---|
| 輸入 | `service_id`、`location_id`、選填含時區時段、`limit` |
| 資料來源 | `agent.available_provider_slot` |
| 硬性條件 | 服務、行政區相同；時段狀態 available；指定時段時必須重疊 |
| 排序 | `matching_v1`：時段 40%、評分 35%、經驗 20%、相對費用 5% |
| 可解釋性 | 回傳四項分數明細與中文理由 |
| 資料標籤 | 結果與每位候選均標示 `synthetic` |
| 無結果 | 成功回傳空陣列，不自行建立或替換師傅 |

同一師傅若有多個可用時段只回傳最高分的一個。本功能不保留時段、不建立案件
或訂單；完整契約、安全界線與測試結果見
[唯讀師傅媒合服務](matching-service.md)。

## 穩定錯誤格式

Service Layer 的預期錯誤可直接由 FastAPI 或 MCP adapter 轉成 JSON：

```json
{
  "ok": false,
  "error": {
    "code": "LOCATION_NOT_FOUND",
    "message": "找不到可供 Agent 使用的縣市與行政區組合。",
    "details": {
      "county_name": "臺北市",
      "district_name": "不存在區"
    }
  }
}
```

Agent 應依 `code` 決定要追問使用者，不能從錯誤訊息猜一筆資料繼續執行。

## Python 使用方式

```python
from home_repair_agent.backend import (
    PostgresReadRepository,
    ReadServiceLayer,
)

repository = PostgresReadRepository(database_url)
services = ReadServiceLayer(repository)

service_result = services.search_services(
    "台北市大安區水龍頭漏水",
    limit=5,
)
location = services.resolve_location(
    county_name="台北",
    district_name="大安",
)
form = services.get_consultation_form(service_id=17)
```

目前這個 Python 內部介面已由四個 FastMCP Tools 共用；實作與契約請見
[MCP Server README](../src/home_repair_agent/mcp_server/README.md)。FastAPI
read endpoints 尚未實作，未來也必須呼叫同一個 `ReadServiceLayer`，不可複製
規則或 SQL。

## 測試

不啟動 PostgreSQL 時：

```powershell
python -m unittest discover -s tests -v
```

設定獨立測試資料庫後：

```powershell
$env:TEST_DATABASE_URL="postgresql://home_repair@127.0.0.1:55434/home_repair"
python -m unittest discover -s tests -v
```

2026-07-26 已在真實 PostgreSQL 16.14 完成原有查詢測試；新增媒合後，
無測試資料庫的完整 suite 為 44 passed、9 skipped、40 subtests passed。
新增媒合 SQL 案例需要再次提供 `TEST_DATABASE_URL` 才會執行。驗證包含：

- 查詢文字中的 alias 能找出 `service_id=17`。
- `台北`、`大安` 能唯一解析為 `ORG-01-007`。
- 水電表單能組成 8 題與 14 個選項。
- 沒有表單與結果不唯一時不猜測。
- Repository SQL 只引用 `agent.*` views。
- 媒合輸入、空結果、透明排序、同師傅去重與 MCP structured content。

## 下一階段

1. 使用 `TEST_DATABASE_URL` 複驗新增媒合 SQL。
2. 加入 FastAPI read endpoints，和 MCP 共用同一層。
3. 將已完成的 Mock Agent 迴圈替換為 BedrockModelClient 並做 tool-selection eval。
4. 設計使用者確認契約後，才實作建案與建單等寫入 Service。
