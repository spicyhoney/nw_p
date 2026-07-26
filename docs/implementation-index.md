# 實作索引

最後更新：2026-07-26

這是目前程式狀態的入口。競賽構想文件描述「可能要做什麼」；本頁與各功能
README 描述「現在真的做了什麼」。新功能完成時必須更新本頁。

| 階段 | 狀態 | 主要程式 | 實作說明 | 驗證 |
|---|---|---|---|---|
| B+ 資料清洗 | 已驗證 | `src/home_repair_agent/data_cleaning/` | [清洗手冊](data-cleaning-runbook.md) | Python 測試、品質報告 |
| PostgreSQL schema / loader | 已驗證 | `sql/`、`data_cleaning/postgres.py` | [SQL README](../sql/README.md) | PostgreSQL 16.14 整合測試 |
| 唯讀 Service Layer | 已驗證 | `src/home_repair_agent/backend/` | [Service Layer](service-layer.md) | 單元與 PostgreSQL 整合測試 |
| 三個唯讀 MCP Tools | 已驗證 | `src/home_repair_agent/mcp_server/` | [MCP README](../src/home_repair_agent/mcp_server/README.md) | MCP 記憶體內協定測試 |
| 寫入 Service / MCP Tools | 未開始 | 尚無 | 預計拆成案件、媒合、確認訂單 | 尚無 |
| Agent 核心迴圈 | 已驗證 Mock 版本 | `src/home_repair_agent/agent/` | [Agent README](../src/home_repair_agent/agent/README.md) | 12 個 Agent / MCP 測試 |
| Bedrock Model adapter | 未開始 | 尚無 | [Agent 規劃](mcp_agent_plan.md) | 等待 AWS 環境 |
| FastAPI / Demo UI | 未開始 | 尚無 | [系統架構](architecture.md) | 尚無 |
| AWS adapters / 部署 | 等待環境 | 尚無 | [AWS 架構](architecture.md) | 無主辦方憑證 |

## 目前可執行的閉環

```text
MCP Client / 測試 Agent
  -> AgentRunner + MockModelClient
  -> search_services
  -> resolve_location
  -> get_consultation_form
  -> ReadServiceLayer
  -> PostgresReadRepository
  -> PostgreSQL agent.* views
```

這個閉環目前只讀。它能多輪保存本機 session、回答「支援什麼服務、地點對應
哪個代碼、該服務要填哪些諮詢欄位」，但還不能永久保存 session、建立案件、
媒合或下單。Mock Model 只驗證編排，不代表真實 LLM 品質。

## 最近驗證

- 2026-07-26：Mock Agent 多輪、行政區更正、多地點安全重試、MCP tool loop
  與安全停止測試。
- 2026-07-26：有主辦方資料集、無 `TEST_DATABASE_URL` 的本工作區為
  38 passed、8 skipped、25 subtests passed；缺少主辦方資料集時會再跳過
  1 個資料清洗整合測試。
- 2026-07-26：MCP SDK `v1.x` 記憶體內 Client/Server protocol tests。
- 2026-07-25：原生 Windows PostgreSQL 16.14 migration、loader 與 constraints。

## 文件維護

實作文件的必要段落與完成標準請見 [AGENTS.md](../AGENTS.md)；新增文件時可複製
[實作文件模板](implementation-template.md)。規劃文件若與實作衝突，以程式測試、
本索引及模組 README 記錄的目前契約為準。
