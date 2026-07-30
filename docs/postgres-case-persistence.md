# PostgreSQL 案件持久化

最後更新：2026-07-30

## 1. 做了什麼

本階段將既有 `CaseWorkflowRepository` 實作為可切換的 PostgreSQL 寫入層：

- `sql/migrations/002_case_workflow.sql` 建立 `workflow` schema。
- `PostgresCaseWorkflowRepository` 保存案件、訂單、冪等紀錄與 audit。
- `CaseWorkflowService` 讓一次命令的檢查與寫入共用同一 transaction。
- Repository 契約與 Service 呼叫全面 async，PostgreSQL 使用
  `psycopg.AsyncConnection`，不阻塞 FastAPI event loop。
- PostgreSQL advisory transaction lock 依 idempotency key 與 session 序列化建案。
- 廠商決策使用 `SELECT ... FOR UPDATE`，另以 `version` 防止遺失更新。
- Web 以 `WEB_CASE_REPOSITORY=memory|postgres` 顯式切換。
- Migration runner 會依檔名順序套用所有 `sql/migrations/*.sql`。
- `.github/workflows/postgresql-ci.yml` 在乾淨 PostgreSQL 16.14 service 上驗證
  migration、repository 與完整測試，並支援手動重跑。

刻意沒做：

- 沒有建立或連接 AWS RDS；目前只驗證相同 PostgreSQL 16.14 契約。
- 沒有保存 Web 對話 session，因此程式重啟後消費者聊天畫面仍不能直接恢復。
- 沒有正式登入、時段保留、付款、通知、正式個資或寫入 MCP Tool。
- 沒有用 JSON 檔案作為持久化備援。

## 2. 為什麼這樣設計

部署到 Lambda、ECS 或 EC2 不會讓 Python RAM 自動持久化。Repository 必須先把
商業狀態寫進 PostgreSQL，未來才可只替換 `DATABASE_URL` 指向 RDS。

Service Layer 保留確認、授權、狀態轉換與聯絡資料揭露規則；SQL 只存在
Repository。`workflow` 表使用 `service_case` 等通用名稱，服務名稱、表單、
地點、廠商與回答保存建立當下快照，不把水電題目寫死在 SQL。

FastAPI route、Service Layer 與 repository 共用 async 呼叫鏈。同步 loader
仍只用於離線 migration／資料清洗；每次 HTTP 案件讀寫都走
`psycopg.AsyncConnection`，不把同步資料庫 I/O 放在 Web event loop。

## 3. 完整資料流

```text
FastAPI
  -> CaseWorkflowService
  -> CaseWorkflowRepository transaction
     -> lock idempotency key
     -> lock session 或 case row
     -> 驗證現有狀態
     -> 寫入 service_case
     -> 寫入 service_order（accepted 才建立）
     -> 寫入 case_audit_event
     -> 寫入 idempotency_record
  -> commit
```

任一步驟失敗會 rollback 整筆命令，不留下只有案件但沒有冪等或 audit 的半套資料。

## 4. Schema 與一致性

| Table | 用途 |
|---|---|
| `workflow.service_case` | 通用服務案件、指派快照、synthetic contact 與版本 |
| `workflow.service_order` | 廠商接受後建立的一案一單 |
| `workflow.case_audit_event` | 派單、接受、拒絕與 contact 揭露事件 |
| `workflow.idempotency_record` | 寫入命令 fingerprint 與原案件結果 |

資料庫 constraints 另保證：

- 同一 session 最多一筆 `pending_provider` 或 `accepted` 案件。
- `accepted` 必須有 `order_no`；其他狀態不能有訂單編號。
- 希望時段結束晚於開始且不超過 12 小時。
- 一個案件最多一張訂單。
- source type 固定為 `synthetic`，audit event 與 actor type 使用白名單。

## 5. 設定與執行

預設仍使用不需資料庫的快速 Demo：

```powershell
$env:WEB_CASE_REPOSITORY = "memory"
home-repair-web
```

PostgreSQL 模式必須先套用 migrations，並提供連線：

```powershell
$env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST:PORT/DATABASE"
python .\scripts\clean_data.py --reference-date 2026-08-01
$env:WEB_CASE_REPOSITORY = "postgres"
home-repair-web
```

Windows 上的 psycopg async 需要 Selector event loop；請用 `home-repair-web`
或 `python -m home_repair_agent.web.app` 啟動。專案啟動器會自動選用相容 loop。
Linux／AWS 不需要額外設定。不要在 Windows PostgreSQL 模式改用裸
`python -m uvicorn ...` 指令，因為該入口不會套用本專案的 loop factory。

正式密碼、RDS URL、AWS 金鑰與 `.env` 不得提交。應由環境變數或未來的
Secrets Manager 注入。

## 6. 安全與資料邊界

- 目前 contact、廠商、案件與訂單全部是 synthetic，不能宣稱為真實資料。
- pending contact 雖保存於資料庫，仍只由 Service Layer 回傳遮罩 view。
- 未指派廠商查詢維持 404；模型與四個 MCP Tools 不能讀寫 `workflow` schema。
- PostgreSQL 帳號最小權限、RDS encryption、備份與正式個資政策留待 AWS 階段。
- Web session 仍是 process-local；PostgreSQL 目前只恢復案件與訂單業務狀態。

## 7. 測試與實際結果

不需要 PostgreSQL 的回歸測試：

```powershell
python -m pytest -q tests/test_case_workflow.py tests/test_web_app.py
```

真實 PostgreSQL：

```powershell
$env:TEST_DATABASE_URL = "postgresql://.../TEST_DATABASE"
python -m pytest -q `
  tests/test_postgres_integration.py `
  tests/test_postgres_case_repository.py
```

2026-07-30 已在原生 Windows PostgreSQL 16.14 驗證：

- 無資料庫 focused：`33 passed, 6 skipped, 3 subtests passed`。
- 新舊 PostgreSQL integration：`15 passed`。
- 完整 suite（提供測試 PostgreSQL）：`113 passed, 43 subtests passed`。
- Repository 重建後仍能讀取案件、接單、訂單與三筆 audit。
- idempotency 跨 Repository 實例仍只建立一案。
- 強制 idempotency 寫入失敗時，案件與 audit 全部 rollback。
- 兩個獨立 worker 同時接受／拒絕，只有一個 terminal transition 成功。
- 封鎖同步 `psycopg.connect` 後，async repository 仍可建案與讀回。
- Windows 以專案入口實際啟動 FastAPI + PostgreSQL，已完成 session、需求解析、
  表單媒合與 `dispatch_pending` 建案 smoke。

GitHub Actions 的 `PostgreSQL CI` 在 PR、`main` push 時自動執行，也可在
Actions 頁面用 `Run workflow` 手動重跑。每次 job 都建立新的
`postgres:16.14-alpine` service，不依賴開發者電腦、Docker Desktop 或正式 RDS。
Loader integration 會由已提交的品質摘要建立暫時、metadata-only quarantine
fixture，因此乾淨 checkout 不需要被忽略的 `_local_*` 檔案，也不會把 raw
主辦方資料加入 Git。

## 8. 下一階段

1. 將 Web session／Agent 記憶另行持久化；不可與正式訂單來源混為一談。
2. 將 Demo provider header 換成 authentication、RBAC 與資料庫最小權限角色。
3. 加入時段 hold／book 與同一廠商排程衝突控制。
4. 取得 AWS 環境後建立 RDS，套用相同 migration 並以 Secrets Manager 注入連線。
