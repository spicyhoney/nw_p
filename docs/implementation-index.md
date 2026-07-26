# 實作索引

最後更新：2026-07-27

這是目前程式狀態的入口。競賽構想文件描述「可能要做什麼」；本頁與各功能
README 描述「現在真的做了什麼」。新功能完成時必須更新本頁。

| 階段 | 狀態 | 主要程式 | 實作說明 | 驗證 |
|---|---|---|---|---|
| B+ 資料清洗 | 已驗證 | `src/home_repair_agent/data_cleaning/` | [清洗手冊](data-cleaning-runbook.md) | Python 測試、品質報告 |
| PostgreSQL schema / loader | 已驗證 | `sql/`、`data_cleaning/postgres.py` | [SQL README](../sql/README.md) | PostgreSQL 16.14 整合測試 |
| 唯讀 Service Layer | 已驗證；媒合 SQL 待 PostgreSQL 複驗 | `src/home_repair_agent/backend/` | [Service Layer](service-layer.md)、[媒合服務](matching-service.md) | 單元測試；既有 PostgreSQL 整合測試 |
| 四個唯讀 MCP Tools | 已驗證 | `src/home_repair_agent/mcp_server/` | [MCP README](../src/home_repair_agent/mcp_server/README.md) | 7 個 MCP protocol tests |
| 寫入 Service / MCP Tools | 未開始 | 尚無 | 預計拆成案件、確認媒合、訂單 | 尚無 |
| Agent 核心迴圈 | 已驗證 Mock 與 HF adapter contract | `src/home_repair_agent/agent/` | [Agent README](../src/home_repair_agent/agent/README.md) | Agent / MCP / provider tests |
| 本機終端 Demo | 已驗證四工具閉環與顯式 provider routing | `src/home_repair_agent/agent/demo.py` | [Agent README](../src/home_repair_agent/agent/README.md#本機終端-demo) | 腳本化 Mock smoke、Demo tests |
| Hugging Face Model adapter | contract 已驗證；live token 待驗 | `src/home_repair_agent/agent/huggingface_model.py` | [HF 模型模式](../src/home_repair_agent/agent/README.md#hugging-face-模型模式) | request/response、tool call、錯誤遮罩測試 |
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
  -> match_service_providers
  -> ReadServiceLayer
  -> PostgresReadRepository
  -> PostgreSQL agent.* views
```

這個閉環目前只讀。它能多輪保存本機 session、回答「支援什麼服務、地點對應
哪個代碼、該服務要填哪些諮詢欄位」，並查詢可解釋的 synthetic 師傅候選；
但還不能永久保存 session、建立案件、保留時段或下單。Rule-based Mock 會在
表單必填資訊完成後呼叫媒合；尚未把「星期六下午」等自由文字轉成時區化
`preferred_start` / `preferred_end`，所以 Demo 目前查詢該地點的所有空檔。
CLI 可顯式切換到 Hugging Face hosted open model 做真實 tool calling；沒有
`HF_TOKEN` 時會停止並提示，不會靜默切回 Mock。

## 最近驗證

- 2026-07-27：新增 Hugging Face Inference Providers adapter、function/tool
  schema 轉換、顯式 `mock / huggingface` CLI routing 與 fail-fast 設定檢查；
  真實 `huggingface_hub 1.24.0` API 已確認；完整 suite 為 60 passed、
  10 skipped、40 subtests passed。因未設定 `HF_TOKEN` 尚未做 live provider
  call。
- 2026-07-27：本機終端 Demo 自動走完四個唯讀 MCP Tools，顯示有來源標籤的
  synthetic 候選、時段與分數；完整 suite 為 48 passed、10 skipped、
  40 subtests passed。
- 2026-07-26：Mock Agent 多輪、行政區更正、多地點安全重試、MCP tool loop
  與安全停止測試。
- 2026-07-26：新增 `matching_v1` 唯讀媒合、第四個 MCP Tool 與 Agent
  tool-loop 測試；本工作區無 `TEST_DATABASE_URL` 時為
  44 passed、9 skipped、40 subtests passed。
- 2026-07-26：新增 PostgreSQL 媒合案例，但本次因無測試資料庫而 skip；
  不宣稱新增 SQL 已完成真實 PostgreSQL 複驗。
- 2026-07-26：MCP SDK `v1.x` 記憶體內 Client/Server protocol tests。
- 2026-07-25：原生 Windows PostgreSQL 16.14 migration、loader 與 constraints。

## 文件維護

實作文件的必要段落與完成標準請見 [AGENTS.md](../AGENTS.md)；新增文件時可複製
[實作文件模板](implementation-template.md)。規劃文件若與實作衝突，以程式測試、
本索引及模組 README 記錄的目前契約為準。
