---
inclusion: always
---
# 專案結構與依賴規則

## 主要目錄

```text
src/home_repair_agent/
  data_cleaning/   原始資料解析、清洗、品質、來源與 PostgreSQL loader
  backend/         domain models、ports、商業規則、repository adapters
  mcp_server/      FastMCP adapter 與 MCP response contracts
  agent/           Agent loop、ports、模型／MCP client adapters、CLI Demo
  web/             FastAPI composition、Web application service、靜態消費者／廠商 UI
sql/migrations/    依序套用的 PostgreSQL DDL／constraints／views
tests/             unit、contract、protocol、HTTP、filesystem、PostgreSQL integration
scripts/           薄 CLI wrappers；不放商業規則
data/              processed／reference／quarantine 與資料來源說明
reports/           可重現的資料品質／整合結果
docs/              架構、模組實作契約、競賽與操作文件
.kiro/steering/    跨 Spec 的穩定產品、技術、安全與競賽脈絡
```

## 模組責任

### `data_cleaning`

- 解析主辦方／參考資料、保留原始值與 provenance、正規化、品質檢查、隔離不可確認資料。
- 可輸出 processed JSON 並選擇性載入 PostgreSQL。
- 不做 Agent 對話、HTTP、MCP 或案件狀態規則。

### `backend`

- `services.py`：服務、行政區、表單、媒合等唯讀商業規則。
- `case_services.py`：確認、冪等、授權投影、案件狀態、order、audit。
- `*_models.py`／`*_ports.py`：跨 adapter 的穩定 contracts。
- `postgres_*_repository.py`：固定參數化 SQL 與 transaction 實作。
- `media_storage.py`：媒體安全儲存 contract／本機 adapter。
- 商業規則只能在這層；repository 不替模型猜資料，route 不自行重作規則。

### `mcp_server`

- 將有限的 Service Layer 能力暴露為標準 MCP Tools。
- 只做協定、schema、domain error envelope 與非預期錯誤遮罩。
- 不放 SQL、matching 權重、確認或案件狀態機。

### `agent`

- `loop.py` 控制 model -> tool -> model、步數、工具數與白名單。
- `ports.py` 隔離模型與工具 transport；provider adapter 留在本模組。
- `mock_model.py` 只供 deterministic demo／tests；不得含正式商業真值。
- `huggingface_model.py`／`huggingface_vision.py` 只負責 provider translation。
- Agent 不直接 import PostgreSQL repository，不執行 SQL，不自行建立案件／訂單。

### `web`

- `app.py`：composition root、FastAPI routes、HTTP validation、headers、dependency wiring。
- `service.py`：目前 consumer session、Agent／MCP／表單／媒合／照片／派單 orchestration。
- `demo_*_repository.py`：明確標示 synthetic、process-local adapters。
- `static/`：無 build 的消費者與廠商 UI；Browser 不直接連模型、MCP 或 DB。
- route 保持薄；若規則可被 CLI、MCP 或其他 API 共用，應下沉 `backend` Service Layer。

## 依賴方向

允許的主路徑：

```text
Browser / CLI / external Agent
  -> Web / Agent / MCP adapters
  -> application or domain Service
  -> repository / storage / provider ports
  -> concrete adapters
  -> PostgreSQL / filesystem / hosted provider
```

具體規則：

- `backend` 的 domain／service 不依賴 FastAPI、MCP、瀏覽器或特定模型 SDK。
- MCP 與 FastAPI 可依賴 backend contracts；backend 不反向依賴 adapter。
- SQL 只存在 repository／migration；Service、MCP、Agent、route 與前端不得拼 SQL。
- 模型輸出不是業務事實；只有通過 schema、Service 規則與必要人工確認的結構化資料可進 workflow。
- 前端不得成為確認、授權、冪等、媒合或狀態轉換的唯一執行者。
- 同一規則只實作一次；FastAPI、MCP、未來 Lambda／AgentCore 都呼叫相同 Service。

## 新功能應放置的位置

| 功能 | 放置原則 |
|---|---|
| 台語／國語 STT、台語 TTS | 先在 Spec 定義 provider-neutral ports 與 consent；小型 adapter 可置於 `agent/`，若形成完整音訊 pipeline 才新增聚焦的 `speech/`。不得把音訊 SDK 寫進 `web/service.py` 商業規則。 |
| 引導式補問／多任務 | 可驗證的 task／slot state models 與轉換規則放 `backend`；Web 只做 session orchestration 與呈現；需要持久化時新增 repository port／adapter。 |
| 真人轉接 | handoff 狀態、同意與資料最小化規則放 `backend`；HTTP UI 在 `web`；客服／通知供應商整合為 adapter。 |
| 師傅語言能力媒合 | 欄位 contract、資格與 matching policy version 放 `backend`；migration／repository 在 `sql` 與 repository；UI 在 `web`。 |
| 照片對話整合 | 重用 `backend/media_storage.py`、`agent/huggingface_vision.py` 與現有 Web API；只擴充 orchestration／state，不另建第二套分析器。 |
| 點數 | 先完成倫理、濫用、隱私與可撤銷規格；規則與 ledger 放 `backend`／repository，模型與前端不得自行計點。 |
| Bedrock／AgentCore／S3 | 實作既有或新定義的 ports；AWS SDK 留在 adapter／composition root，不能把 provider-specific 型別傳入 domain。 |
| 新 MCP Tool | 薄 adapter 放 `mcp_server`；先在 backend 建立可直接測試的 Service contract；寫入 Tool 必須另做安全設計。 |
| 新 API／頁面 | route／static 放 `web`；跨入口規則不得留在 route 或 JavaScript。 |

上表是架構落點，不代表功能已獲准或設計已定案。

## 測試位置

- Service／matching／case rules：`tests/test_read_services.py`、`tests/test_case_workflow.py` 或同層新測試。
- MCP schema／annotations／錯誤：必須放 protocol-level MCP Client／Server tests。
- Model provider adapter：fake client contract tests；live smoke 另行隔離，不進預設 CI。
- FastAPI／Web workflow：TestClient／HTTP integration tests。
- 瀏覽器競態與無障礙：Node regression、靜態 contract，加上必要的真瀏覽器驗收。
- PostgreSQL：`TEST_DATABASE_URL` 隔離 integration tests；不得連正式資料庫。
- Filesystem／media：temporary directory、實際 decode、traversal／symlink／cleanup tests。

## 文件與變更規則

- 每個完成功能都要更新模組 README 或 `docs/` 實作文件，以及 `docs/implementation-index.md`。
- 功能契約、環境變數、資料流或執行方式改變時，同一變更同步文件。
- `TASKS.md` 只放未完成工作；`HANDOFF.md` 只描述目前接手狀態。這兩檔本輪不得修改。
- 歷史 brainstorm、ENGINEER_LOG 與 `docs/mcp_agent_plan.md` 的候選設計只供脈絡，不是現行 API／Tool contract。
