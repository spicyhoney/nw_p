# 專案白話指南

最後更新：2026-07-30

這份文件回答五個問題：我們做了什麼、AI 用在哪裡、資料庫怎麼被查詢、廠商如何
接案，以及想修改某個功能時應先看哪裡。實際完成狀態以
[實作索引](implementation-index.md)為準，未完成工作以
[TASKS](../TASKS.md)為準。

## 30 秒理解

本專案是「居家水電修繕 AI 生活管家」：

1. 消費者用自然語言描述需求。
2. 模型決定要查哪個唯讀工具，但不能直接碰資料庫。
3. MCP Tool 經 Service Layer 查出服務、行政區與彈性諮詢單。
4. 消費者自己填表、核對 Checklist，並選擇 synthetic 服務商。
5. 只有消費者明確確認後，系統才建立案件。
6. 指派廠商在後台接受或拒絕；接案後才揭露完整 synthetic 聯絡資料並建立
   `SYN-ORDER-*` Demo 訂單。

目前本機雙端流程已能執行，案件 repository 可選記憶體或 PostgreSQL。Web 與
Terminal Demo 的服務／地點／表單讀取固定使用 `DemoReadRepository`；獨立 MCP
Server 與 PostgreSQL 整合測試使用 `PostgresReadRepository`，Web 讀取切換列為
P0 待辦。AWS、正式登入、真實個資與真實廠商仍未完成。

## 每一層負責什麼

| 名稱 | 白話說法 | 本專案責任 |
|---|---|---|
| Web UI | 消費者與廠商看到的畫面 | 顯示對話、表單、候選、案件與接案控制 |
| FastAPI | 網頁後端入口 | 接收 HTTP 請求、驗證格式、呼叫共用服務；不寫 SQL |
| AgentRunner | 對話流程控制器 | 把訊息、工具規格與結果交給模型，控制最多呼叫次數與工具白名單 |
| ModelClient | 語言理解 | 目前可選 Mock 或 Hugging Face；未來才是 Bedrock |
| MCP | Agent 的標準工具協定 | 讓模型只能呼叫名稱與參數明確的工具，不接受任意 SQL |
| Service Layer | 商業規則唯一來源 | 查詢、媒合、確認、冪等、權限、稽核與合法狀態轉換 |
| Repository | 資料存取 adapter | 把 Service 的固定操作轉成 SQL 或記憶體操作 |
| PostgreSQL | 保存可驗證事實 | 保存清洗後目錄，以及可選的案件、訂單、冪等與 audit |

關鍵原則：

> 模型理解與選工具；Service Layer 決定能不能做；Repository 存取資料；
> PostgreSQL 保存事實。

## 目前架構

實線是已完成路徑；虛線是未來 AWS／外部整合。

```mermaid
flowchart LR
    Consumer["消費者 Web UI"] --> API["FastAPI adapter"]
    Provider["廠商後台 /provider"] --> API

    API --> Session["WebSessionService"]
    Session --> Agent["AgentRunner"]
    Agent --> Model["Mock / Hugging Face ModelClient"]
    Agent --> Client["MCPToolClient"]
    Client --> MCP["FastMCP Server<br/>四個唯讀 Tools"]
    MCP --> ReadService["ReadServiceLayer"]
    ReadService --> DemoRepo["DemoReadRepository<br/>Web / Terminal Demo"]
    DemoRepo --> DemoCatalog[("synthetic Demo seed<br/>服務／地點／表單")]

    Standalone["獨立 MCP Server<br/>PostgreSQL entrypoint"] --> PgService["ReadServiceLayer"]
    PgService --> PgRepo["PostgresReadRepository"]
    PgRepo --> PgCatalog[("PostgreSQL agent.* views")]

    Session --> CaseService["CaseWorkflowService"]
    API --> CaseService
    CaseService --> CaseRepo["Memory 或 async PostgreSQL<br/>CaseWorkflowRepository"]
    CaseRepo --> Workflow[("案件／訂單／冪等／audit")]

    External["Lumine one／外部 Agent"] -. "尚未完成外部驗證" .-> Gateway["AgentCore Gateway"]
    Gateway -. "未部署" .-> Standalone
    Bedrock["Amazon Bedrock"] -. "未實作 adapter" .-> Agent
```

完整的 AWS 角色與未來部署方式見[系統與 AWS 架構](architecture.md)。

## 消費者流程

聊天查詢與按鈕寫入是兩條不同路徑。模型可以查資料和追問，但不能代替使用者
勾選 Checklist，也不能自己派單。

```mermaid
sequenceDiagram
    actor User as 消費者
    participant Web as Web / FastAPI
    participant Agent as AgentRunner
    participant MCP as MCP Tools
    participant Service as Service Layer
    participant DB as Repository / PostgreSQL

    User->>Web: 描述水電問題與地點
    Web->>Agent: 傳入訊息與 session
    Agent->>MCP: search_services / resolve_location
    MCP->>Service: 結構化查詢
    Service->>DB: 固定 repository 操作
    DB-->>Service: 服務與行政區資料
    Service-->>MCP: 結構化結果
    MCP-->>Agent: Tool result
    Agent->>MCP: get_consultation_form
    MCP-->>Agent: 彈性表單
    Agent-->>Web: 回覆與 structured session
    Web-->>User: 顯示表單與人工 Checklist
    User->>Web: 自行填表並核對
    Web->>MCP: match_service_providers
    MCP-->>Web: synthetic 候選與推薦理由
    User->>Web: 選擇廠商並明確確認派單
    Web->>Service: submit_case confirmed=true
    Service->>DB: transaction 寫入案件、冪等與 audit
    Web-->>User: pending_provider
```

## 廠商接案流程

目前只有被指派的 synthetic 廠商能讀到案件。列表永遠只顯示遮罩聯絡資料；
完整 synthetic contact 只在接受案件後的詳情中出現。

```mermaid
stateDiagram-v2
    [*] --> pending_provider: 消費者確認派單
    pending_provider --> accepted: 指派廠商確認接受
    pending_provider --> rejected: 指派廠商確認拒絕
    accepted --> [*]: 建立 SYN-ORDER-* 並揭露 synthetic contact
    rejected --> [*]: 不揭露 contact，可由消費者改派下一位
```

確認、冪等、指派隔離、audit 及狀態轉換契約見
[派單／接單說明](provider-workflow.md)。

## 資料如何走到 Agent

原始資料永遠不被覆寫。清洗程式只把能確認的資料放進正式目錄；斷裂關聯與
不明代碼留在 quarantine。為了讓 Demo 閉環可執行，人工設定與 synthetic
資料都有明確來源標籤。

```mermaid
flowchart LR
    Raw["主辦方原始檔<br/>唯讀"] --> Pipeline["B+ Python 清洗 pipeline"]
    Reference["官方行政區參考資料"] --> Pipeline
    Pipeline --> Processed["data/processed<br/>品質與來源標籤"]
    Pipeline --> Quarantine["data/quarantine<br/>不可供 Agent 使用"]
    Processed --> Loader["PostgreSQL loader / migrations"]
    Loader --> Core[("core schema")]
    Core --> Views[("agent.* 安全 views")]
    Views --> Repo["PostgresReadRepository"]
    Repo --> Service["ReadServiceLayer"]
    Service --> Tools["四個唯讀 MCP Tools"]
    Tools --> Agent["AgentRunner"]
```

`PostgresReadRepository` 已通過 PostgreSQL 整合測試，獨立 MCP Server 的
entrypoint 預設組裝這個 repository；外部 HTTP Client 尚未端到端驗證。目前
Web app 與 Terminal Demo 建立的 in-process MCP Server 則使用
`DemoReadRepository`。不要因為案件可切到 PostgreSQL，就誤以為 Web 的服務
目錄、地區、表單與媒合也已經自動改查資料庫。

常見來源標籤：

- `official_repaired`：主辦方資料經可追蹤規則修復格式。
- `curated_config`：團隊明確定義的表單、別名或政策設定。
- `synthetic`：只供開發、測試與展示的模擬廠商、時段、案件或聯絡資料。

任何 synthetic 資料都不能宣稱為主辦方真實營運資料。

## 想改功能時先看哪裡

| 想處理的事情 | 先讀 | 主要程式 |
|---|---|---|
| 看目前做到哪裡 | [HANDOFF](../HANDOFF.md)、[實作索引](implementation-index.md)、[TASKS](../TASKS.md) | 不應先猜程式 |
| 改消費者或廠商網頁 | [Web README](../src/home_repair_agent/web/README.md) | `web/app.py`、`web/service.py`、`web/static/` |
| 改模型或多輪 Tool loop | [Agent README](../src/home_repair_agent/agent/README.md) | `agent/loop.py`、`agent/huggingface_model.py` |
| 新增或修改 MCP Tool | [MCP README](../src/home_repair_agent/mcp_server/README.md) | `mcp_server/server.py`、`mcp_server/models.py` |
| 改服務搜尋、地點、表單或媒合 | [Service Layer](service-layer.md) | `backend/services.py`、`backend/postgres_repository.py` |
| 改派單、接單、冪等或 audit | [派單／接單說明](provider-workflow.md) | `backend/case_services.py`、兩種 case repository |
| 改 schema 或資料清洗 | [資料政策](data-policy.md)、[資料字典](data-dictionary.md) | `data_cleaning/`、`sql/migrations/` |
| 檢查行為是否被破壞 | [測試 README](../tests/README.md) | `tests/` |

## 最容易混淆的邊界

- FastAPI 是後端入口，不是前端畫面，也不是 Agent Tool。
- MCP Tool 不是 SQL；它只能呼叫範圍明確的 Service。
- Web session、對話與 Checklist 仍在記憶體；它們不會因案件 repository 使用
  PostgreSQL 就自動持久化。
- Web 與 Terminal Demo 的服務、地區、表單與媒合目前使用
  `DemoReadRepository`；獨立 MCP Server 與 PostgreSQL 整合測試使用
  `PostgresReadRepository`，兩者共用同一份 `ReadServiceLayer` 契約。
- 案件、訂單、冪等與 audit 可切換到 async PostgreSQL repository。
- 四個 MCP Tools 全部唯讀；派單與接案目前由 Web 按鈕直接呼叫
  `CaseWorkflowService`。
- Hugging Face 是目前可用的 hosted model adapter；Bedrock、AgentCore 與 RDS
  雲端環境仍未完成。
- Demo contact 是 synthetic。正式個資加密、同意、保存及刪除政策仍是待辦。

## 目前已完成與尚未完成

已完成：

- B+ 資料清洗、來源標籤、品質報告及 PostgreSQL loader。
- 服務／地點／表單／媒合 Service 與四個唯讀 MCP Tools。
- Mock 與 Hugging Face ModelClient 契約、Agent tool loop。
- 消費者人工 Checklist、動態表單、媒合、明確確認派單。
- 廠商案件列表、遮罩 contact、接受／拒絕與消費者狀態更新。
- memory／async PostgreSQL 案件 repository、冪等、audit 與並行狀態保護。
- 桌機／手機響應式與無障礙基線。

尚未完成：

- 固定 Hugging Face eval 矩陣與外部 HTTP MCP 驗證。
- Web 讀取 repository 的 Demo／PostgreSQL 可設定切換。
- 正式登入、時段保留、真實個資政策、照片、回覆紀錄與通知。
- Bedrock、AgentCore、RDS、IAM、CloudWatch 及公開 HTTPS 部署。

完整優先順序與驗收條件請直接看 [TASKS](../TASKS.md)。
