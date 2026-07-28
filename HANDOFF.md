# HANDOFF：居家修繕 Agent（nw_p）

> 更新：2026-07-28　更新者：Codex
> 規則：全文 ≤150 行；只描述現在；接手者先讀本檔，再按連結讀細節。

## 1. 目前狀態

- 穩定 `main`：`ec6d741`，PR #9 已合併。
- 工作分支：`codex/provider-dashboard-p0`，目前尚未 commit／push／建立 PR。
- 本機消費者與廠商雙端 P0 已完成實作、文件、自動測試與瀏覽器驗收。
- 尚未公開部署，也未連 PostgreSQL 寫入、正式登入、Bedrock 或 AWS。

## 2. 本分支完成

- 新增 `CaseWorkflowService` 與嚴格案件／命令／view models。
- 新增 process-local `DemoCaseWorkflowRepository`。
- 消費者完成媒合後，可選擇廠商並明確確認派單。
- 新增 `/provider` 廠商工作台：案件列表、狀態篩選、詳情、audit、接單／拒絕。
- 只有 assigned provider 能看案件；其他 Demo provider 列表為空、詳情回 404。
- pending 只回遮罩 contact；accepted 才回完整 synthetic contact；rejected 不揭露。
- accepted 建立 `SYN-ORDER-*`；rejected 後可改派其他未拒絕候選。
- 寫入有 confirmation、idempotency、payload fingerprint、audit 與原子狀態轉換。
- 已有 audit 的 session 不能用 reset 擦除。
- 消費者頁每 3 秒輪詢 pending 案件，取得 accepted／rejected 結果。
- 修正候選與確認派單按鈕在非同步更新後仍停用的前端問題。
- 靜態 CSS／JS 加版本 query，避免瀏覽器沿用舊快取。
- 更新架構 SVG、Web README、實作索引、測試說明與本交接文件。

## 3. 五項不可破壞規則

1. 消費者明確確認後才建立案件。
2. 只有指派廠商可讀案件。
3. pending 廠商只能看到遮罩聯絡資料。
4. accepted 才揭露完整 synthetic contact；rejected 永不揭露。
5. 所有寫入必須有確認、冪等、稽核與合法原子狀態轉換。

完整契約：[docs/provider-workflow.md](docs/provider-workflow.md)。

## 4. 驗證證據

- Workflow + Web focused：`26 passed`。
- 完整 suite：`91 passed, 9 skipped, 40 subtests passed`。
- 9 skipped 是缺測試 PostgreSQL／選配 live 環境時依設計略過。
- 受影響 Python：Ruff、format、compileall 通過。
- `app.js`、`provider.js`：Node syntax check 通過。
- 架構 SVG：XML parse 通過。
- 桌機 `1280x720`、手機 `390x844` 均跑通雙端流程。
- 無水平 overflow、console error 或控制項重疊。
- 未指派廠商切換後案件數為 0。
- FastAPI TestClient 有第三方 `httpx2` deprecation warning；目前不影響結果。
- 本次使用 Mock Model，沒有送出 HF token 或對外傳送對話。

主要文件：

- [Web P1 README](src/home_repair_agent/web/README.md)
- [派單／接單 P0](docs/provider-workflow.md)
- [實作索引](docs/implementation-index.md)
- [系統與 AWS 架構](docs/architecture.md)
- [架構 SVG](docs/project-architecture-current.svg)

## 5. 現有邊界

- Web session、案件、訂單、idempotency 與 audit 都只在目前 Python process。
- 重啟後資料消失；沒有真的保留師傅時段。
- 廠商下拉選單與 `X-Demo-Provider-Id` 是身分模擬，不是 authentication。
- 聯絡人、手機、地址、廠商、案件與訂單全部是 synthetic。
- 自由文字仍可能被使用者輸入真實個資；UI 已警告，但 P0 沒有萬用個資偵測器。
- 四個 MCP Tools 仍全部唯讀；本分支沒有寫入 MCP Tool。
- 派單／接單按鈕由 FastAPI 直接呼叫 `CaseWorkflowService`，不經 LLM。
- `CaseWorkflowService` 沒有 SQL；正式寫入 SQL 必須放 PostgreSQL repository。
- 原始資料不可覆寫；不明代碼不可猜；Agent 不得執行任意 SQL。
- token、密碼、AWS 金鑰、`.env` 與含 token transcript 不得提交。

## 6. 下一步

1. 組員 review 本分支的五項規則、API contract 與 Demo 文案。
2. 修正 review findings 後 commit、push 並建立 PR。
3. 建立 PostgreSQL case／order／idempotency／audit migrations 與 constraints。
4. 實作 transaction-based `CaseWorkflowRepository` 和真實 PostgreSQL 整合測試。
5. 將 Demo provider header 換成正式登入與 RBAC。
6. 加入時段保留及同一師傅排程衝突控制。
7. 用固定案例做 Hugging Face／Bedrock tool-selection eval。
8. 拿到 AWS 環境後替換 model、tool transport、repository adapters 並部署。
9. 外部 Agent 確實需要寫入時，才設計少量受限 MCP Tools。

## 7. 團隊分工

- 使用者／Codex：消費者與廠商 Web、FastAPI、Case Service、資料／權限邊界。
- 組員：模型固定 eval、語音、Bedrock／AWS 部署準備。
- 共同：review 五項規則、驗收 Demo、決定正式 authentication 與部署方案。
- 避免兩邊同時修改 `src/home_repair_agent/web/`；先在 PR 留言協調。

## 8. 環境快照

- Repo：`https://github.com/spicyhoney/nw_p`
- Python：`>=3.11`；本機驗證使用 `.venv`。
- 預設 Model：`mock`。
- 啟動：`home-repair-web`
- 消費者：`http://127.0.0.1:8080/`
- 廠商：`http://127.0.0.1:8080/provider`

## 9. 授權狀態

- 使用者與組員已同意五項規則並授權本分支開始實作。
- 已授權本地實作、測試與文件更新。
- 尚未在本次請求中授權 commit、push、PR、AWS 部署或任何金鑰操作。
