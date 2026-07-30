# HANDOFF：居家修繕 Agent（nw_p）

## 最新狀態（2026-07-30）
- PR #11 已合併至 `main`，merge commit `33f66fe`。
- PR #12 分支已合併最新 `main`，仍為待複查 Draft；不得自行 merge。
- PR #12 review 三項要求已處理：Web PostgreSQL I/O 全面 async、可重跑
  PostgreSQL CI、交接與測試證據更新。
- 本機：focused `33 passed, 6 skipped, 3 subtests`；PostgreSQL integration
  `15 passed`；完整 `113 passed, 43 subtests`。

> 更新：2026-07-30　更新者：Codex
> 規則：全文 ≤150 行；只描述現在；接手者先讀本檔，再按連結讀細節。

## 1. 目前狀態（active）

- `main` 已包含 PR #11 merge commit `33f66fe`。
- PR #12 已同步該基線；等待對方依新 head SHA 重新 review。
- 派單／廠商工作台方向與五項規則未改。
- 本分支已新增可選的 async PostgreSQL 寫入與 GitHub CI；尚未連 RDS、
  公開部署、正式登入、Bedrock 或其他 AWS 服務。

## 2. PR #10 完成內容

- 消費者完成 synthetic 媒合後，可選廠商並明確確認派單。
- 新增 `/provider` 廠商工作台：案件列表、狀態篩選、詳情、audit、接單／拒絕。
- 只有 assigned provider 能讀案件；其他 Demo provider 詳情回 404。
- pending 只回遮罩 contact；accepted 才回完整 synthetic contact；
  rejected 不揭露。
- accepted 建立 `SYN-ORDER-*`；rejected 後可改派其他未拒絕候選。
- `CaseWorkflowService` 提供 confirmation、idempotency、payload fingerprint、
  audit 與原子狀態轉換。
- 寫入由 FastAPI → Case Service 執行；LLM 與四個 MCP Tools 仍不能寫入。
- Web 預設仍用 memory repository；設定 `WEB_CASE_REPOSITORY=postgres` 後，案件、
  訂單、idempotency 與 audit 會在同一 PostgreSQL transaction 保存。

主要文件：

- [派單／接單 P0](docs/provider-workflow.md)
- [Web README](src/home_repair_agent/web/README.md)
- [實作索引](docs/implementation-index.md)
- [系統與 AWS 架構](docs/architecture.md)
- [PostgreSQL 案件持久化](docs/postgres-case-persistence.md)
- [架構 SVG](docs/project-architecture-current.svg)

## 3. 五項不可破壞規則

1. 消費者明確確認後才建立案件。
2. 只有指派廠商可讀案件。
3. pending 廠商只能看到遮罩聯絡資料。
4. accepted 才揭露完整 synthetic contact；rejected 永不揭露。
5. 所有寫入必須有確認、冪等、稽核與合法原子狀態轉換。

## 4. PR #12 review 修正

### Async Web PostgreSQL

- `CaseWorkflowRepository` 契約、memory adapter、Service Layer 與 PostgreSQL
  repository 全部改為 async／await。
- PostgreSQL 使用 `psycopg.AsyncConnection`；Web event loop 不再執行同步
  `psycopg.connect`。
- 回歸測試會把同步 `psycopg.connect` 改成必定失敗，仍可完成建案與讀回。
- Windows 啟動器使用 Selector event loop，符合 psycopg async 的平台需求；
  AWS/Linux 不需此相容設定。

### 可重跑 PostgreSQL CI

- 新增 `.github/workflows/postgresql-ci.yml`。
- PR、`main` push 會自動跑；`workflow_dispatch` 可由 Actions 頁面手動重跑。
- CI 啟動固定 PostgreSQL `16.14-alpine` service，執行 Ruff、format、
  compileall 與含真實 PostgreSQL 的完整 pytest。
- CI 只使用暫時測試資料庫，沒有正式憑證或 RDS 連線。

## 5. 驗證證據

- 無資料庫 focused：`33 passed, 6 skipped, 3 subtests passed`。
- 原生 PostgreSQL 16.14 新舊 integration：`15 passed`。
- 完整 suite（含測試 PostgreSQL）：`113 passed, 43 subtests passed`。
- 6 skipped 是 focused run 未提供測試 PostgreSQL；不是 regression。
- 受影響 Python：Ruff 與 format check 通過。
- Windows 實際啟動 async Web + PostgreSQL，已走到 `dispatch_pending` 建案成功。
- FastAPI TestClient 仍有第三方 `httpx2` deprecation warning；不影響結果。
- CI workflow 可由 PR、`main` push 或手動 dispatch 重新建立乾淨資料庫驗證。

## 6. 現有邊界

- Web session 重啟仍會消失；PostgreSQL 模式的案件寫入可讀回，但沒有真的保留
  師傅時段。memory 模式的案件資料重啟仍會消失。
- `X-Demo-Provider-Id` 與廠商選單只是 synthetic 身分模擬，不是 authentication。
- 聯絡人、手機、地址、廠商、案件與訂單全部是 synthetic。
- 自由文字仍可能含真實個資；UI 有警告，但沒有萬用個資偵測器。
- 四個 MCP Tools 全部唯讀；沒有寫入 MCP Tool。
- Case Service 沒有 SQL；正式 SQL 必須放 PostgreSQL repository。
- token、密碼、AWS 金鑰、`.env` 與含 token transcript 不得提交。

## 7. AI mode 與環境

- 團隊整合／Demo 基線：Hugging Face AI mode；mock 只供離線測試。
- 模型：`Qwen/Qwen3-4B-Instruct-2507`；`HF_PROVIDER=auto`。
- `HF_TOKEN` 是每位開發者自己的 account token，不是模型專屬 token。
- 專案不會自動載入 `.env`；啟動前需載入 token 並設定：

  ```powershell
  $env:HF_MODEL_ID = 'Qwen/Qwen3-4B-Instruct-2507'
  $env:HF_PROVIDER = 'auto'
  $env:WEB_MODEL_PROVIDER = 'huggingface'
  .\.venv\Scripts\python.exe -m home_repair_agent.web.app
  ```

- 消費者：`http://127.0.0.1:8080/`；廠商：`http://127.0.0.1:8080/provider`。
- 沒有自己的 token 時，不得宣稱正在跑 AI mode。

## 8. AWS 持久化決策（不可遺漏）

- process-local repository 保留為本機快速 Demo 的顯式選項。
- **不要**新增 JSON 檔案作為派工單持久化或開機載入方案。
- 只把現有程式部署到 AWS 不會自動持久化；Lambda、ECS 或容器重啟仍會遺失 RAM 資料。
- 本分支已實作 PostgreSQL transaction repository，保存 case、order、
  idempotency 與 audit，並以 migrations、constraints 及整合測試驗證。
- 正式環境以連線設定切換到 RDS PostgreSQL／相容 Aurora PostgreSQL；FastAPI 與
  `CaseWorkflowService` 契約維持不變，以 dependency injection 替換 repository。
- SQL 只能放 repository；密碼、RDS URL、AWS 金鑰與 `.env` 不得提交。

## 9. 下一步

1. 依 PR #12 新 head SHA 複查 async repository 與 PostgreSQL CI；由人類決定
   是否合併，Agent 不得自行 merge。
2. 完成消費者介面與高齡／無障礙體驗。
3. 取得 AWS 環境後建立 RDS，套用相同 migration 並切換連線設定。
4. 將 Demo provider header 換成正式登入與 RBAC。
5. 加入時段保留及同一師傅排程衝突控制。
6. 評估是否持久化 Web 對話 session；不得與案件資料混為一談。
7. 把單一 HF live case 擴成固定案例矩陣；live 測試不進預設 CI。
8. 最後替換 Bedrock／AgentCore adapters 並公開部署。

## 10. User decisions

- **2026-07-28**：人工 HF Demo 良好；整合／Demo 以 HF AI mode 為基線。
- **2026-07-29**：每 3 小時檢查 PR；技術 finding 可直接修正，以本檔交接。
- **2026-07-29**：本機 Demo 可暫用 RAM；不做 JSON 持久化。PostgreSQL
  repository 已在本分支實作，RDS／相容 Aurora 等取得 AWS 環境後再連接。
- **2026-07-30**：PR #12 必須同步 `main@33f66fe`、修正 async I/O、提供
  可重跑 PostgreSQL CI 並更新測試證據後，再交由對方重新 review。
- 是否合併 PR 永遠由人類決定；Agent 不得自行 merge。
