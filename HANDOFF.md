# HANDOFF：居家修繕 Agent（nw_p）

## 最新狀態（2026-07-30）

- PR #14 已由隊友合併為
  `main@9729fadbf5315cc08eb71a071d8e8bc4d3573533`；專案地圖、文件分工與
  真實 backlog 已完成，DOC-001 已從待辦移到實作索引。
- 目前產品基線包含 PR #13 的消費者 Checklist、無障礙雙端 UI、派單／接單與
  async PostgreSQL repository；尚未選定下一個進行中的產品任務。

> 更新者：Codex
> 規則：全文維持 150 行內；只描述現在。接手者先讀本檔，再按下列順序閱讀。

## 1. 接手閱讀順序

1. [專案白話指南](docs/project-guide.md)：系統流程、重要模組與常見邊界。
2. [待辦清單](TASKS.md)：尚未完成的工作、優先級、依賴與驗收。
3. [實作索引](docs/implementation-index.md)：已完成程式、位置與驗證。
4. [系統與 AWS 架構](docs/architecture.md)：本機與未來雲端元件。
5. 正在修改之模組 README 與 [資料政策](docs/data-policy.md)。

## 2. 目前可執行流程

消費者端 `/`：

- 自然語言需求經 Agent 查詢服務、行政區與彈性諮詢單。
- 人工 Checklist 只能由使用者 click／Space／Enter 修改；模型只能提出提示。
- 使用者填表後執行 synthetic 媒合，選擇候選並明確確認才建立案件。
- 消費者輪詢廠商狀態，accepted 後看到 `SYN-ORDER-*` Demo 訂單。

廠商端 `/provider`：

- 切換 synthetic Demo 廠商身分，只能查看指派給目前身分的案件。
- pending 只見遮罩 contact；接受後才見完整 synthetic contact。
- 廠商可接受或拒絕；拒絕後消費者可改派下一位候選。

資料與 Agent：

```text
Web／Terminal message -> AgentRunner -> Mock／Hugging Face ModelClient
                     -> MCPToolClient -> 四個唯讀 MCP Tools
                     -> ReadServiceLayer -> DemoReadRepository

Standalone MCP server -> ReadServiceLayer -> PostgresReadRepository
                      -> PostgreSQL agent.* views

Web confirmed buttons -> CaseWorkflowService
                      -> memory／async PostgreSQL CaseWorkflowRepository
```

## 3. 不可破壞契約

1. 消費者明確確認後才建立案件。
2. 只有指派廠商可讀案件；未指派身分回 404。
3. pending 只能看到遮罩 contact。
4. accepted 才揭露完整 synthetic contact；rejected 永不揭露。
5. 寫入具確認、冪等、audit 與合法原子狀態轉換。
6. Agent 不得執行任意 SQL；SQL 只在 repository。
7. 四個 MCP Tools 維持唯讀，不得由模型修改 Checklist 或建立案件。
8. 原始資料不可覆寫；不明代碼不可猜測；synthetic 必須保留來源標籤。

## 4. 目前持久化邊界

- `WEB_CASE_REPOSITORY=memory|postgres`。
- PostgreSQL 保存案件、訂單、idempotency 與 audit，使用 async I/O。
- Web 與 Terminal Demo 的服務、地區、表單與媒合固定使用
  `DemoReadRepository`；獨立 MCP Server 與 PostgreSQL 整合測試使用
  `PostgresReadRepository`。Web 讀取 adapter 切換列為 P0，不要誤認
  `WEB_CASE_REPOSITORY` 會切換這些唯讀資料。
- Web 對話 session 與人工 Checklist 仍在 process memory，重啟後不會恢復。
- PostgreSQL 模式不是 AWS RDS；目前只驗證相同 PostgreSQL 16.14 契約。
- 廠商 header 是 Demo 身分模擬，不是 authentication 或 RBAC。
- Demo contact 為 synthetic；正式個資加密、同意、期限及刪除政策尚未完成。

## 5. AI 與 MCP 狀態

- 團隊 Demo 基線可選 Hugging Face；Mock 供離線開發與 CI。
- 模型：`Qwen/Qwen3-4B-Instruct-2507`，`HF_PROVIDER=auto`。
- 沒有 `HF_TOKEN` 時不得宣稱執行 AI mode，也不會靜默切回 Mock。
- 真實 HF 目前只有單一固定 Web case；完整 eval 矩陣仍是 P0 待辦。
- FastMCP 支援 stdio 與 Streamable HTTP `/mcp`，但外部 HTTP Client 驗證仍待做。
- Bedrock、AgentCore Gateway／Runtime、RDS、IAM 與 CloudWatch 均未實作。

## 6. 最近驗證基線

PR #14 最終 head `76ac2148d26401da9197669aa5b9e8b10867675e`，已合併為
`main@9729fadbf5315cc08eb71a071d8e8bc4d3573533`：

- review 後直接修正 `git diff --check` 尾端空白及 DOC-001 合併後狀態。
- 本機完整：`104 passed, 16 skipped, 43 subtests passed`。
- 21 份異動 Markdown 相對連結、4 個 Mermaid、SVG XML 與 `1600x1080` 視覺
  檢查、secret pattern scan 及 `git diff --check` 通過。
- PR 最終 docs-only head 的 GitHub PostgreSQL CI 為 1/1 通過。本次狀態修正
  只異動 HANDOFF，不重跑產品 Demo 或完整 pytest。

## 7. PR #14 文件成果

- 新增 `TASKS.md`，把未完成工作集中成可驗收 backlog。
- 新增 `docs/project-guide.md`，用白話與 Mermaid 說明三條主要資料流。
- 更新目前架構 SVG、文件索引與 AI 閱讀順序。
- 將舊構想文件標示為歷史規劃，不再冒充目前成果。
- 修正簡報策略中的錯誤筆數及尚未實作宣稱。

詳細範圍見[文件整理計畫](docs/project-map-and-backlog-plan.md)。

## 8. 下一步

1. 接手時先同步最新 `main`，確認本檔與 GitHub 的已合併狀態一致。
2. 從 `TASKS.md` 的 P0 任務中選一項開始，不同時展開多項，也不從歷史規劃
   文件猜測目前狀態。

## 9. 團隊決策

- 本機 Demo 可暫用 RAM；不做 JSON 案件持久化。
- Hugging Face 是目前 hosted model 基線；Mock 只供離線測試。
- Kiro 加分目前不投入，不建立回溯性紀錄。
- 寫入 MCP Tool 只有在外部 Agent 確有完整建案需求時才設計。
- 是否合併 PR 永遠由人類決定。
