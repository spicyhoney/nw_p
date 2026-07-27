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
| Hugging Face Model adapter | contract 與單一 Web 三工具 live case 已驗證；固定案例矩陣待做 | `src/home_repair_agent/agent/huggingface_model.py` | [HF 模型模式](../src/home_repair_agent/agent/README.md#hugging-face-模型模式) | request/response、tool call、timeout、錯誤遮罩、Qwen3 live |
| Bedrock Model adapter | 未開始 | 尚無 | [Agent 規劃](mcp_agent_plan.md) | 等待 AWS 環境 |
| FastAPI / Demo UI | 已驗證本機唯讀 P0；尚未公開部署 | `src/home_repair_agent/web/` | [Web P0 README](../src/home_repair_agent/web/README.md) | 13 個 API tests、桌面／手機瀏覽器 E2E |
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

這個閉環目前只讀。Terminal Demo 能多輪回答「支援什麼服務、地點對應哪個
代碼、該服務要填哪些諮詢欄位」；Web P0 另提供記憶體 session、結構化
`SessionView`、動態表單與 synthetic 候選卡。Web 的日期時間由使用者在 UI
確認，送出 `Asia/Taipei` aware ISO window，後端驗證後才呼叫媒合 Tool；模型
只看得到前三個查詢 Tool，不能繞過人工表單直接媒合。

目前仍不能永久保存 session、建立案件、保留時段或下單。CLI 與 Web 可顯式
切換到 Hugging Face hosted open model；沒有 `HF_TOKEN` 時會停止並提示，不會
靜默切回 Mock。Demo synthetic 時段依啟動時間產生在下一個未來星期六；
hosted model 不得自行把相對日期換成具體年月日。

## 最近驗證

- 2026-07-27：真實 HF Web fixed case 使用
  `Qwen/Qwen3-4B-Instruct-2507`、`provider=auto`；synthetic「台北市大安區
  水龍頭漏水」於 7.41 秒依序完成三個查詢 Tool，取得水電修繕、臺北市大安區與
  `demo_repair_form_v1`，並停在 `awaiting_form`。Windows PowerShell 臨時 harness
  必須以 Unicode-safe 方式傳入中文；先前 `?` 輸入的結果不算模型 eval。
- 2026-07-27：完成 Web P0 review：限制模型 Tool 白名單、拒絕重複媒合表單、
  reset 保留 session lock，並補前端必填驗證。Web focused 13 passed；完整
  suite 77 passed、10 skipped、40 subtests passed；受影響檔案 Ruff／format、
  compileall、JavaScript syntax 通過；桌面與 `390x844` 人工流程無 console
  error，手機無水平 overflow。
- 2026-07-27：新增 FastAPI Web P0：session/message/form/reset API、結構化
  view model、動態諮詢單、`+08:00` 時段驗證、四個 MCP Tools、進度與
  synthetic 候選卡。Web focused 11 passed；完整 suite 76 passed、9 skipped、
  40 subtests passed；Ruff、compileall、JavaScript syntax 通過；實際瀏覽器
  在 1280x720 與 390x844 完成流程且無 console error。
- 2026-07-27：修正 HF adapter review findings：將 SDK 下限對齊已驗證的
  `huggingface_hub 1.24`、新增預設 60 秒 request timeout、禁止模型自行換算
  相對日期，並將 Demo 時段改成可注入時鐘的下一個未來星期六。focused
  34 passed；完整 suite 65 passed、9 skipped、40 subtests passed；Mock
  四工具 smoke 通過。本次沒有 token，因此沒有重跑 live。
- 2026-07-27：新增 Hugging Face Inference Providers adapter、function/tool
  schema 轉換、顯式 `mock / huggingface` CLI routing 與 fail-fast 設定檢查；
  真實 `huggingface_hub 1.24.0` API 已確認；初始完整 suite 為 60 passed、
  10 skipped、40 subtests passed。後續團隊 handoff 記錄一次 synthetic
  四工具 live smoke 成功，但尚未形成可重複的固定 eval。
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
