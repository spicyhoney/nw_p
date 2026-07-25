# 修繕小隊長

2026 雲湧智生：臺灣生成式 AI 應用黑客松的雙人團隊專案。

目前的 MVP 聚焦在「居家水電修繕」：使用者用自然語言描述問題後，AI Agent
將需求結構化、查詢服務與行政區、追問缺少資訊、建立諮詢案件，並在使用者
確認後完成服務媒合與訂單建立。

## MVP 情境

輸入：

> 台北市大安區水龍頭漏水，週六下午可以來嗎？

預期流程：

1. 辨識地點、問題與期望時間。
2. 查詢水電修繕服務與行政區代碼。
3. 取得對應諮詢單，僅追問缺少的欄位。
4. 建立諮詢案件。
5. 依服務區域與可用時段配對模擬服務商。
6. 經使用者確認後建立訂單。
7. 提供案件與訂單狀態查詢。

## 技術方向

- Agent：Amazon Bedrock / AgentCore
- Tool protocol：MCP
- Backend：Python、FastAPI
- Database：PostgreSQL
- Data pipeline：Python、Pydantic、pandas、SQLAlchemy
- Test：pytest

主辦方資料不會用來重新訓練基礎模型。Agent 會透過受控的 MCP Tools 或 API
查詢清洗後的 PostgreSQL。

## 專案結構

```text
src/home_repair_agent/
  data_cleaning/  原始資料解析、清洗與驗證
  backend/        API、資料存取與商業規則
  agent/          Prompt、工具定義與 Agent 流程
sql/              PostgreSQL migration 與資料庫說明
data/             資料目錄與來源政策
tests/            自動化測試
reports/          資料品質與評估報告
docs/             架構、計畫與競賽文件
```

## 分支規則

- `main`：已確認、可重現的穩定版本。
- `feature/data-cleaning`：資料解析、清洗、驗證與匯入。
- `feature/agent-prototype`：使用模擬工具結果開發 Agent 對話流程。
- `feature/backend-mcp`：PostgreSQL、FastAPI 與 MCP Tools。
- `feature/demo-ui`：Demo 使用者介面。
- `docs/submission`：簡報、Demo 腳本與繳交文件。
- `fix/*`：針對明確錯誤的短期修正分支。

功能在獨立分支完成並通過測試後，透過 Pull Request 合併回 `main`。

## 資料原則

- 原始檔保持不變，不在清洗時覆寫。
- 不明代碼與斷裂關聯不得自行猜測，先進入隔離區。
- 外部補充資料與合成資料必須標示來源。
- 個資、密碼、金鑰與 `.env` 不得提交到 GitHub。
- Agent 只能透過範圍明確的工具存取資料，不能執行任意 SQL。

詳細規則請見 [資料政策](docs/data-policy.md) 與
[系統架構](docs/architecture.md)。

## 目前狀態

- [x] 完成官方資料集初步稽核
- [x] 建立專案與協作骨架
- [ ] 建立可重複執行的資料清洗流程
- [ ] 建立 PostgreSQL clean schema
- [ ] 完成 MCP Tools
- [ ] 串接 Agent 與 Demo UI

