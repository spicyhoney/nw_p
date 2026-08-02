# 實作索引

最後更新：2026-08-02

本頁只列已完成且有程式或驗證證據的功能。尚未完成的工作在
[TASKS](../TASKS.md)；早期構想不能覆蓋本頁、測試或模組 README 的目前契約。

## 已驗證功能

| 功能 | 狀態 | 主要位置 | 詳細說明／證據 |
|---|---|---|---|
| B+ 資料清洗與品質閘門 | 已驗證 | `src/home_repair_agent/data_cleaning/` | [清洗手冊](data-cleaning-runbook.md)、[資料政策](data-policy.md)、`reports/data_quality.md` |
| PostgreSQL schema、migration、loader | PostgreSQL 16 驗證 | `sql/`、`data_cleaning/postgres.py` | [SQL README](../sql/README.md)、[資料字典](data-dictionary.md) |
| 服務／行政區／表單／媒合 Service | 已驗證 | `src/home_repair_agent/backend/` | [Service Layer](service-layer.md)、[媒合服務](matching-service.md) |
| 派單／接單狀態機 | memory 與 async PostgreSQL 已驗證 | `backend/case_*`、`backend/postgres_case_repository.py` | [派單流程](provider-workflow.md)、[案件持久化](postgres-case-persistence.md) |
| 四個唯讀 MCP Tools | protocol 與 Agent loop 已驗證 | `src/home_repair_agent/mcp_server/` | [MCP README](../src/home_repair_agent/mcp_server/README.md) |
| Agent 核心迴圈 | Mock／HF／Bedrock adapters 已驗證 | `src/home_repair_agent/agent/` | [Agent README](../src/home_repair_agent/agent/README.md) |
| 引導式水電修繕 | 五分支、單一 Active Task、人工確認已驗證 | `backend/repair_conversation.py`、`web/` | [Web README](../src/home_repair_agent/web/README.md) |
| 消費者 Web | 動態表單、Checklist、摘要、媒合、派單已驗證 | `src/home_repair_agent/web/` | [Web README](../src/home_repair_agent/web/README.md)、[無障礙基線](consumer-accessibility.md) |
| 廠商工作台 | pending／accepted／rejected、遮罩與授權已驗證 | `web/static/provider.*`、`CaseWorkflowService` | [派單流程](provider-workflow.md) |
| 修繕圖片建議 | HF VLM、EXIF 清除、人工確認、branch binding 已驗證 | `agent/huggingface_vision.py`、`backend/media_storage.py`、`web/` | [Media integration](ENGINEER_LOG-media-integration.md) |
| 台語／國語語音輸入 | HF-only ASR adapter 與 Web 回填契約已驗證 | `web/speech.py`、`web/static/app.js` | [Web README](../src/home_repair_agent/web/README.md) |
| Bedrock Nova Lite | Converse tool-use、fail-closed、request pacing 已驗證 | `agent/bedrock_model.py`、`scripts/bedrock_*.py` | [Bedrock POC](ENGINEER_LOG-aws-bedrock-agentcore-poc.md)、[MCP E2E](ENGINEER_LOG-aws-bedrock-mcp-e2e.md) |
| AgentCore Remote MCP | SigV4、initialize/list/call、四工具 Browser 閉環曾 live 驗證 | `agent/agentcore_mcp_client.py`、`agentcore_remote_mcp_entrypoint.py` | [Remote MCP evidence](ENGINEER_LOG-agentcore-remote-mcp-demo.md)、`reports/agentcore_remote_mcp_demo.json` |
| PostgreSQL CI | PR／main／手動觸發 | `.github/workflows/postgresql-ci.yml` | PostgreSQL 16 service、全庫 Ruff／format、compileall、JavaScript、完整 pytest |
| 作品集整理 | README、截圖、現況文件與全庫品質閘門已更新 | `README.md`、`docs/assets/`、`HANDOFF.md`、`TASKS.md` | [整理紀錄](portfolio-release.md) |

## 可執行閉環

### 1. 預設本機 Demo

```text
消費者 Web
  -> FastAPI / WebSessionService
  -> AgentRunner + MockModelClient
  -> local MCP client / FastMCP
  -> 四個唯讀 Tools
  -> ReadServiceLayer / DemoReadRepository
  -> 人工填表、確認摘要、選擇 synthetic 廠商
  -> CaseWorkflowService
  -> memory repository
  -> 廠商接受／拒絕與消費者狀態更新
```

這條路不需要 token、AWS 或 PostgreSQL，是 README 的可重現快速啟動基線。

### 2. PostgreSQL 案件持久化

```text
FastAPI
  -> CaseWorkflowService
  -> async PostgresCaseWorkflowRepository
  -> transaction: case + order + idempotency + audit
```

案件、訂單、冪等鍵與 audit 可在重啟後讀回。Web 對話、Active Task 與 Checklist 仍是
process-local；設定 `WEB_CASE_REPOSITORY=postgres` 不會自動把唯讀 Demo repository
切成 PostgreSQL。

### 3. 比賽期間 AWS 文字路徑

```text
Browser -> FastAPI -> AgentRunner -> Amazon Bedrock Nova Lite
  -> SigV4 AgentCore Remote MCP client
  -> AgentCore Runtime /mcp
  -> 四個唯讀 Tools -> ReadServiceLayer -> DemoReadRepository
```

2026-08-02 曾以 synthetic service 17、臺北市大安區、`repair_form_v1` 與兩位候選完成
live 驗證；報告已遮罩 account、ARN、credential 與完整 payload。這是歷史技術證據，
不是目前可用的公開 endpoint，也不代表 Gateway、RDS 或網站部署已完成。

## 最近驗證

作品集整理基線：

- Python 3.12：`327 passed, 17 skipped, 168 subtests passed`。
- `ruff check .` 與 `ruff format --check .`：passed。
- `compileall`、兩支 JavaScript syntax check、兩支 Node regression：passed。
- 消費者／廠商頁面在 `1280x720` 與 `390x844` 無水平 overflow；首頁無 console error。
- current-tree secret pattern、Markdown link、`git diff --check`：passed。

17 個 skip 是未提供測試 PostgreSQL 或外部 provider 時的條件式測試，不得寫成 live
成功證據。更早的分功能數字與 live run 細節保留於 `docs/ENGINEER_LOG-*.md` 和
`reports/`，不再堆進本索引。

## 固定邊界

- 產品範圍是 `service_id=17` 水電修繕，不宣稱支援所有生活服務。
- 四個 MCP Tools 皆唯讀；模型不能確認、建案、派單或執行任意 SQL。
- Demo 師傅、聯絡資料、時段、案件與訂單皆為 synthetic。
- 沒有正式登入、RBAC、付款、通知、真實時段保留、RDS 或長期公開 hosting。
- AWS `ExpiresAt` 標籤不會自動刪除資源；帳號 cleanup audit 狀態見 [TASKS](../TASKS.md)。
