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

- Model：Amazon Bedrock Converse API
- Agent hosting：Amazon Bedrock AgentCore Runtime（比賽環境）
- Agent tool gateway：AgentCore Gateway / MCP
- Backend：Python、FastAPI
- Database：PostgreSQL；正式環境目標為 Amazon RDS for PostgreSQL
- Object storage：Amazon S3（報修照片，選配）
- Observability / permission：CloudWatch、IAM
- Data pipeline：Python、Pydantic、pandas、SQLAlchemy
- Test：pytest

主辦方資料不會用來重新訓練基礎模型。Agent 會透過受控的 MCP Tools 或 API
查詢清洗後的 PostgreSQL。

目前尚無比賽 AWS 憑證，因此先以 Mock Model、本機 MCP Tools 與本機 PostgreSQL
開發。拿到憑證後才替換為 Bedrock、AgentCore Gateway / Runtime、RDS 與 S3
adapter，資料清洗與 Service Layer 不需重寫。各 AWS 服務的角色、聊天與按鈕的
完整呼叫路徑，請見 [系統與 AWS 架構](docs/architecture.md)。

## 專案結構

```text
src/home_repair_agent/
  data_cleaning/  原始資料解析、清洗與驗證
  backend/        資料存取與共用商業規則
  mcp_server/     將 Service Layer 暴露成標準 MCP Tools
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
- [x] 建立可重複執行的 B+ 資料清洗流程
- [x] 建立 PostgreSQL clean schema 與 Agent 安全檢視
- [x] 在原生 Windows PostgreSQL 16.14 完成 migration、loader 與 constraints 測試
- [x] 完成唯讀 Service Layer：服務、行政區、諮詢表單、synthetic 師傅媒合
- [x] 完成四個唯讀 MCP Tools 與 protocol tests
- [x] 完成可替換模型的 Agent 核心迴圈與 Mock 多輪測試
- [ ] 完成 Bedrock adapter、案件／訂單寫入 Service Layer、Demo UI
- [ ] 取得比賽 AWS 環境後串接 Bedrock 與 AgentCore

## 執行資料清洗

第一次執行時，先取得並固定官方行政區參考資料：

```powershell
python .\scripts\fetch_admin_reference.py
```

接著執行 B+ 清洗：

```powershell
python .\scripts\clean_data.py --reference-date 2026-08-01
```

安全的核心資料會寫入 `data/processed/`，詳細檢查結果在
`reports/data_quality.md`。含歷史訂單分析與隔離索引的本機輸出不會提交至
GitHub。完整操作與資料流請見
[資料清洗操作手冊](docs/data-cleaning-runbook.md)、
[資料字典](docs/data-dictionary.md)與
[AI 資料檢查清單](docs/ai-data-review-checklist.md)。

## AI 與實作文件

隊友或 AI 請先讀 [AI 協作入口](AGENTS.md) 與
[實作索引](docs/implementation-index.md)。每次新增功能都必須留下「做了什麼、
為什麼、資料流、安全邊界、測試、下一步」，並在同一個 commit 更新索引。

## 執行唯讀 MCP Server

安裝應用與資料庫依賴：

```powershell
python -m pip install -e ".[data,app,dev]"
```

設定測試用 PostgreSQL 的 `DATABASE_URL` 後，以 stdio 啟動：

```powershell
home-repair-mcp
```

或設定 `MCP_TRANSPORT=streamable-http`，endpoint 會位於
`http://127.0.0.1:8000/mcp`。工具契約與安全設計請見
[MCP Server 實作說明](src/home_repair_agent/mcp_server/README.md)。

Agent 的模型／工具介面、多輪狀態、安全停止、Mock 限制及語音接法請見
[Agent 對話迴圈實作說明](src/home_repair_agent/agent/README.md)。
