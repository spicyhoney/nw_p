# 專案地圖與任務管理文件整理計畫

> 狀態：已實作，待 Draft PR 與團隊 review
> 基線：`main@82c910ae1d766399f499ddd8c8f5de7a42d456e6`  
> 工作分支：`codex/project-map-and-backlog`  
> 範圍：只整理文件與流程圖，不修改產品功能、不重跑完整 Demo、不自行合併。

## 目標

建立一套容易由團隊成員與 AI 接手的專案文件結構，讓「目前已完成」、
「接手時要知道的狀態」與「未來待辦」不再混在不同文件中。

固定文件職責：

- `HANDOFF.md`：目前真實狀態、最近驗證與接手注意事項，維持 150 行內。
- `TASKS.md`：尚未完成的工作、優先級、負責人、依賴與驗收條件。
- `docs/implementation-index.md`：已完成且通過驗證的功能紀錄。
- 模組 README：各功能的詳細介面、資料流、安全邊界與測試方式。

## 預定改動

### 1. 新增 `TASKS.md`

- 使用 `P0`、`P1`、`P2` 表示優先級。
- 使用 `Todo`、`Blocked`、`In progress` 表示狀態。
- 每項任務包含任務 ID、目的、負責人、依賴與完成條件。
- 完成的任務移到實作索引，不讓 `TASKS.md` 變成歷史日誌。

### 2. 新增白話版 `docs/project-guide.md`

- 說明使用者、Agent、MCP、Service Layer、Repository 與 PostgreSQL 的關係。
- 畫出消費者諮詢流程、廠商接案流程及資料清洗到查詢流程。
- 以「想修改什麼功能，應先看哪些檔案」介紹重要模組。
- 明確區分目前已完成、模擬資料及未來 AWS 元件。

### 3. 更新流程圖

- Markdown 文件內保留可維護的 Mermaid 圖。
- 同步更新 `docs/project-architecture-current.svg`，補上人工 Checklist、
  無障礙 UI、async PostgreSQL repository 與正確工具名稱。
- 現有功能使用實線；AWS、登入及未實作功能使用虛線。
- 不把規劃中的元件畫成已完成成果。

### 4. 修正文件衝突

- 將 `HANDOFF.md` 更新為 PR #13 已合併，移除「等待 review」。
- 更新架構與實作索引中的過時狀態。
- 將 `docs/README.md` 分成「目前事實」與「歷史規劃」兩區。
- 在舊規劃文件加入醒目的歷史標記。
- 修正簡報策略中未實作的加密、多模態、固定 eval 等宣稱。
- 修正錯誤的 221 筆訂單說法；目前資料集為 99 筆範例訂單。

### 5. 建立後續文件規則

- 在 `AGENTS.md` 閱讀順序加入 `docs/project-guide.md` 與 `TASKS.md`。
- 在 PR 模板加入 `HANDOFF.md`、`TASKS.md` 與實作索引更新檢查。
- 功能完成時，同步更新 HANDOFF、結案 TASKS 任務、實作索引及模組 README。

## 目前缺口

以下項目只會記入 `TASKS.md`，本次不實作：

### P0

- 讓 Web 唯讀資料可設定切換 Demo／PostgreSQL repository。
- 建立固定 Hugging Face 評估案例。
- 驗證外部 HTTP MCP Client 能呼叫現有四個唯讀工具。
- 準備可攜式部署與公開 HTTPS 所需文件和封裝。

### Blocked

- Amazon Bedrock。
- AgentCore Gateway 與 Runtime。
- Amazon RDS for PostgreSQL。
- IAM 與 CloudWatch。

以上項目等待主辦方 AWS 環境、Region、權限與額度。

### P1

- 正式登入、授權與廠商 RBAC。
- 時段保留與排程衝突控制。
- 真實個資加密、保存同意、保存期限與刪除政策。
- 照片實際上傳與影像分析。
- 廠商回覆紀錄與服務進度追蹤。

### P2

- Web 對話與 Checklist 持久化。
- 語音操作與使用者字級偏好。
- 更多服務類型的彈性表單。

### Optional

- 受限寫入 MCP Tool：只有外部 Agent 確定需要完整建案時才實作。
- Kiro 加分：目前依團隊決定不投入。

現有 Service Layer、四個唯讀 MCP Tools、派單／接單狀態機、
PostgreSQL repository、消費者／廠商雙端 UI 與無障礙基線不重做。

## 驗證方式

- 核對圖中的 API、工具名稱和狀態值與程式碼完全一致。
- 驗證 Markdown 相對連結、Mermaid 語法與 SVG XML。
- 視覺檢查更新後 SVG 無裁切、重疊或文字溢出。
- 搜尋並清除「PR #13 尚待審查」及其他已知錯誤宣稱。
- 執行 `git diff --check`。
- 純文件 PR 不要求完整產品 Demo 或完整 pytest。

## 完成與交付

- 所有改動留在 `codex/project-map-and-backlog`。
- 建立 Draft PR，列出文件差異與實際驗證結果。
- 由隊友檢查並決定是否合併；不由 Agent 自行 merge。
