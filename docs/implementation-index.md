# 實作索引

最後更新：2026-08-02

這是目前程式狀態的入口。競賽構想文件描述「可能要做什麼」；本頁與各功能
README 描述「現在真的做了什麼」。新功能完成時必須更新本頁。

| 階段 | 狀態 | 主要程式 | 實作說明 | 驗證 |
|---|---|---|---|---|
| B+ 資料清洗 | 已驗證 | `src/home_repair_agent/data_cleaning/` | [清洗手冊](data-cleaning-runbook.md) | Python 測試、品質報告 |
| PostgreSQL schema / loader | 已驗證 | `sql/`、`data_cleaning/postgres.py` | [SQL README](../sql/README.md) | PostgreSQL 16.14 整合測試 |
| Service Layer | 唯讀、媒合、派單／接單與 async PostgreSQL 寫入均已驗證 | `src/home_repair_agent/backend/` | [Service Layer](service-layer.md)、[媒合服務](matching-service.md)、[派單／接單](provider-workflow.md) | 單元測試與 PostgreSQL 16.14 整合測試 |
| 引導式單一修繕對話 | 已驗證單一 Active Task；五分支均需明確確認 | `backend/repair_conversation.py`、`web/`、`data/processed/curated_repair_form.json` | [Web 引導式流程](../src/home_repair_agent/web/README.md)；Kiro spec 路徑為 `.kiro/specs/guided-home-repair-conversation/requirements.md`，待該目錄整合 | focused `59 passed, 50 subtests passed`；兩條 FastAPI HTTP E2E |
| 四個唯讀 MCP Tools | 已驗證；本次未改 schema | `src/home_repair_agent/mcp_server/` | [MCP README](../src/home_repair_agent/mcp_server/README.md) | 7 個 MCP protocol tests |
| 寫入 Service / MCP Tools | memory／async PostgreSQL Service 已驗證；寫入 MCP 未開始 | `backend/case_*.py`、`backend/postgres_case_repository.py` | [案件持久化](postgres-case-persistence.md)、[派單／接單](provider-workflow.md) | workflow unit、rollback、非阻塞契約與跨 worker 整合測試 |
| Agent 核心迴圈 | 已驗證 Mock、HF 與 Bedrock adapter contract；本次未改 AgentRunner／ToolClient port | `src/home_repair_agent/agent/` | [Agent README](../src/home_repair_agent/agent/README.md) | Agent / MCP / provider tests |
| AgentCore Remote MCP ToolClient | 已接入 Web 並完成真實 Browser → Bedrock → AgentCore 四工具閉環；初始化或憑證失敗時 fail closed | `src/home_repair_agent/agent/agentcore_mcp_client.py`、`src/home_repair_agent/web/app.py` | [AgentCore Remote MCP ToolClient](../src/home_repair_agent/agent/README.md#agentcore-remote-mcp-toolclient)、[AWS 架構](architecture.md) | adapter／composition tests 與 Browser live smoke；遮罩證據見 `reports/agentcore_remote_mcp_demo.json` |
| 本機終端 Demo | 已驗證四工具閉環與顯式 provider routing | `src/home_repair_agent/agent/demo.py` | [Agent README](../src/home_repair_agent/agent/README.md#本機終端-demo) | 腳本化 Mock smoke、Demo tests |
| Hugging Face Model adapter | contract 與單一 Web 三工具 live case 已驗證；七案 opt-in harness 已建立，本輪 live 矩陣待新 token | `src/home_repair_agent/agent/huggingface_model.py`、`scripts/huggingface_web_eval.py` | [HF 模型模式](../src/home_repair_agent/agent/README.md#hugging-face-模型模式)、[Web Demo 收尾](ENGINEER_LOG-web-demo-viewport-hf-testability.md) | request/response、tool call、timeout、錯誤遮罩、offline 七案 contract、歷史 Qwen3 live |
| 圖片上傳與 HF VLM | 已整合；完成本機、live HF、PostgreSQL 16.14 驗證，guided flow 綁 active branch 並在圖片變更時使摘要失效 | `agent/huggingface_vision.py`、`backend/media_storage.py`、`web/` | [Web 圖片流程](../src/home_repair_agent/web/README.md#圖片建議hf-only)、[資料政策](data-policy.md#圖片與外部模型) | VLM／storage／API／provider access／前端／migration 003／branch binding／summary invalidation tests |
| HF 台語／國語語音輸入 | 已完成 HF-only Web POC；錄音只回填 composer、需人工確認，不保存、不自動送出、不 fallback | `web/speech.py`、`web/app.py`、`web/static/` | [Web 語音流程](../src/home_repair_agent/web/README.md#台語國語語音輸入hf-only) | fake HTTP／API／前端契約；公開教育部短音訊 Breeze-ASR-26 live smoke |
| Bedrock Model adapter | contract、synthetic tool-use smoke 與四工具 MCP live 閉環已驗證 | `src/home_repair_agent/agent/bedrock_model.py`、`scripts/bedrock_*.py` | [Agent README](../src/home_repair_agent/agent/README.md#bedrock-模型模式)、[AWS POC](ENGINEER_LOG-aws-bedrock-agentcore-poc.md)、[MCP E2E](ENGINEER_LOG-aws-bedrock-mcp-e2e.md) | fake-client contract、Nova Lite Converse、AgentRunner × MCP 四工具 live |
| FastAPI / Demo UI | 已驗證 guided 單一修繕、跨輪地點／更正、單一內容捲動、廠商 reflow 與受控答案顯示；唯讀服務資料仍是 Demo repository | `src/home_repair_agent/web/` | [Web README](../src/home_repair_agent/web/README.md)、[無障礙 UI](consumer-accessibility.md)、[Web Demo 收尾](ENGINEER_LOG-web-demo-viewport-hf-testability.md) | HTTP／a11y／Node regression；桌面／手機與等效 125%／200% viewport smoke |
| 最終 Web rich-media 整合 | 已整合圖片入口、人工確認與 HF 台語／國語 STT；STT 只回填、不自動送出 | `web/speech.py`、`web/service.py`、`web/static/` | [Web README](../src/home_repair_agent/web/README.md)、[AWS 架構與整合邊界](architecture.md) | 自動 focused tests 已通過；實體麥克風 smoke 由隊友進行中；TTS 未整合 |
| Web → AgentCore remote ToolClient | 已完成 AWS text Demo；Browser 經 Bedrock Nova Lite 與 AgentCore Remote MCP 取得兩位 synthetic 候選 | `web/app.py`、`agent/agentcore_mcp_client.py` | [AWS 架構](architecture.md) | service 17、臺北市大安區、`repair_form_v1`、matching live 通過；未選廠商、未建案 |
| Web 讀取 adapter | 待辦：服務、地區、表單與媒合可設定切換 Demo／PostgreSQL repository | 尚無 | [TASKS `DATA-001`](../TASKS.md) | 尚未驗證 |
| PostgreSQL CI | 已建立，可自動或手動重跑 | `.github/workflows/postgresql-ci.yml` | [案件持久化](postgres-case-persistence.md) | PostgreSQL 16.14 service、Ruff、compileall、完整 pytest |
| 專案地圖與任務文件 | 已驗證 | `TASKS.md`、`HANDOFF.md`、`docs/` | [專案白話指南](project-guide.md)、[文件整理紀錄](project-map-and-backlog-plan.md) | 21 份異動 Markdown 相對連結、4 個 Mermaid、SVG XML／視覺、secret pattern、diff check 與完整 pytest |
| AgentCore Runtime / Gateway 部署 | Runtime synthetic direct-code POC 與 authenticated remote MCP P0 已驗證；Gateway 待做 | `agentcore_*_entrypoint.py`、`scripts/agentcore_*.py` | [AWS 架構](architecture.md)、[Runtime POC 證據](ENGINEER_LOG-aws-bedrock-agentcore-poc.md)、[Remote MCP 證據](ENGINEER_LOG-agentcore-remote-mcp-demo.md) | Runtime READY；SigV4 Streamable HTTP initialize／list／四工具 passed；短效資源保留至 expiry，cleanup command 已驗證 |

## 目前可執行的閉環

獨立 Agent／MCP 唯讀閉環維持不變：

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

四個 MCP Tools 仍全部唯讀。上圖是獨立 MCP Server 的預設組裝，以及
`PostgresReadRepository` 整合測試所對應的路徑。Web app 與 Terminal Demo 的
in-process MCP Server 建立
`DemoReadRepository`，不會因 `WEB_CASE_REPOSITORY=postgres` 自動改查 PostgreSQL。

AWS text Demo 使用已和 Web 組裝、並完成 live 驗證的 Remote MCP 路徑：

```text
SigV4 remote client
  -> AgentCore Runtime /mcp
  -> initialize + tools/list
  -> search_services
  -> resolve_location
  -> get_consultation_form（service_id 來自先前 ToolResult）
  -> match_service_providers（service_id / location_id 來自先前 ToolResult）
  -> ReadServiceLayer
  -> DemoReadRepository（synthetic-only）
```

2026-08-02 的遮罩 evidence 顯示四工具皆通過；Browser live 也實際完成
Bedrock → AgentCore → service/location/form/matching，並顯示兩位 synthetic 候選。
網站本身仍只在本機，沒有公開 AWS Web URL，也沒有 Gateway 或 RDS。

Web 現在另有一條 deterministic、單一 Active Task 的引導式閉環：

```text
一項水電需求
  -> deterministic 五分支 proposal（不是診斷或業務事實）
  -> 使用者明確確認 branch
  -> 重驗 canonical service_id=17 + repair_form_v1 version/applicability
  -> 既有 AgentRunner／唯讀 Tools 補齊服務、完整地點與表單
  -> POST /form 只保存答案並產生摘要版本
  -> 使用者明確確認最新摘要
  -> match_service_providers
  -> synthetic candidates
```

五分支為 `faucet_leak`、`toilet_issue`、`pipe_issue`、`electrical_issue`、`other`。
多 intent 只顯示 alternatives 並要求先選一項，不會建立多 task。branch switch 也需
確認，並清除舊分支資料、不相符圖片分析及衝突地點。`water_shutoff` 只存在於水龍頭、
馬桶、水管三分支；`other` 必須有具體描述。

表單保存不再直接媒合。每次保存都建立新的可修改摘要版本；只有最新版本透過
`POST /summary/confirm` 明確確認後才呼叫 matching。圖片沿用既有 storage／VLM／人工
確認／服務目錄重驗管線並綁 active branch，移除圖片會使摘要失效。建案後表單鎖定。

地點仍不猜測：固定 HTTP E2E 的 `我家水龍頭一直漏水，在大安區` 會先要求完整縣市，
補上 `臺北市大安區` 才繼續。`家裡插座一直冒火花` 會顯示安全提醒；補齊地點後可走完
summary、matching 與 dispatch，而 electrical form、summary、matching answers、case
payload 全程沒有 `water_shutoff`。包含漏電、觸電、起火、火災、瓦斯、人身危險或焦味
時則安全停止一般媒合。

Web 的受控寫入閉環仍不經 LLM 或 MCP：

```text
消費者確認派單
  -> FastAPI
  -> CaseWorkflowService
  -> memory 或 PostgreSQL CaseWorkflowRepository
  -> transaction：case + order + idempotency + audit
  -> 指派廠商 pending 案件（遮罩 contact）
  -> 廠商確認接受／拒絕
  -> accepted 時建立 synthetic Demo 訂單並揭露 synthetic contact
  -> 消費者輪詢取得結果
```

PostgreSQL 模式以 async I/O 在程式重啟後重新讀取案件、訂單、idempotency 與 audit；
Web session／Active Task 仍不能恢復，也不會真的保留師傅時段。廠商 header 只是 Demo
身分模擬，不是正式登入；目前沒有正式 PII、authentication、多任務、清潔服務或寫入
MCP Tool。AgentCore remote ToolClient 已成為 AWS text Demo 的可選 transport。CLI 與 Web
可顯式切換到 Hugging Face hosted model；缺少
`HF_TOKEN` 時會停止並提示，不會靜默切回 Mock。

另有一條真實 Bedrock、但仍為 process-local MCP 的 synthetic 閉環：

```text
Amazon Nova Lite -> AgentRunner -> MCPToolClient -> FastMCP Server
  -> ReadServiceLayer -> DemoReadRepository -> ToolResult -> Nova Lite final answer
```

2026-08-01 這次 process-local live run 實際完成四個唯讀 Tool 並取得 synthetic
候選；該次執行本身沒有使用外部 Streamable HTTP，也不會建立案件、訂單或保留時段。
外部 AgentCore Runtime 的 Remote MCP 證據是上方另列的 2026-08-02 路徑；兩者都沒有
使用 AgentCore Gateway。

相同閉環也已在短效 AgentCore Runtime 執行：

```text
IAM-authenticated invoke -> AgentCore Runtime -> Nova Lite -> AgentRunner
  -> process-local MCP -> DemoReadRepository -> redacted result -> cleanup
```

Runtime 只接受固定 synthetic scenario；deploy 後完成四工具與 CloudWatch 檢查，
隨即刪除 Runtime、workload identity、S3、IAM role 與 log group。它仍不是 Gateway、
Streamable HTTP、RDS 或正式 Web 部署。

另有一條不呼叫模型的 authenticated remote MCP 閉環：

```text
External Python MCP Client -> IAM SigV4 -> AgentCore Runtime /mcp
  -> existing FastMCP tools -> ReadServiceLayer -> DemoReadRepository
```

2026-08-02 live P0 的 Runtime 為 `READY`，initialize、exact tools/list 與四工具 call
全數通過；form／matching IDs 皆可追溯到前序 ToolResult。資源依 Demo 指示暫時保留至
共同 expiry，機器 evidence 不含 account、ARN、URL、credential 或完整 payload。
這不等於網站已部署，也未驗證 ChatGPT Developer Mode。

## 最近驗證

- 2026-08-02：完成最終 AWS text 組裝。Browser → Bedrock Nova Lite →
  `AgentRunner` → `AgentCoreMCPToolClient` → AgentCore Runtime → 四個唯讀 Tools
  真實走完 service 17、臺北市大安區、`repair_form_v1` 與 matching，顯示 synthetic
  A／B 組（94%／81%），未選廠商、未建立案件。整合驗證為 `182 passed, 90 subtests`；
  Ruff、format、compileall、Node syntax、diff check 與 secret scan 通過。遮罩 evidence
  位於 `reports/agentcore_remote_mcp_demo.json`；短效資源保留至
  `2026-08-02T09:09:06Z` 標籤，標籤不會自動刪除，Demo 後必須執行 cleanup。
- 2026-08-02：整合 HF 圖片與台語／國語 STT Web Demo。圖片只提出建議且須人工確認；
  Breeze ASR 結果只回填輸入框、不自動送出。自動測試已通過，實體麥克風 smoke 由隊友
  進行中；公開 HF Space 無 SLA，台語 TTS 未整合。HF rich-media 與 AWS text 目前是
  兩種分開的 Demo mode。
- 2026-08-02：`AgentCoreMCPToolClient` 使用 standard credential chain、refreshable SigV4
  與 Streamable HTTP；credential refresh 不阻塞 event loop，transport log 遮罩 Runtime
  識別，startup cancellation 會釋放已開啟 contexts。缺設定、credential 或 remote
  initialize／transport 失敗時一律 fail closed，不 fallback 到 local、HF 或 Mock。
- 2026-08-01：完成 guided single-repair conversation。canonical `service_id=17`、
  `repair_form_v1` 五分支、deterministic proposal、branch／summary 明確確認、確認時
  service/form 重驗、版本化可修改摘要、field applicability、branch switch、single
  Active Task、multi-intent 選一項、照片 branch binding／summary invalidation、安全
  reminder／stop 與建案後表單鎖定均有回歸。預算與緊急程度維持非表單 topic 的選填
  共用 answers：缺答保存 `skipped`、可 `declined_to_answer`，`urgency` 僅接受
  `normal|urgent` 加上述 answer states，且不改 `matching_v1`。faucet 與 electrical 兩條
  固定 FastAPI HTTP E2E 均在補齊完整地點後走完
  `summary -> matching -> dispatch_pending`，且 electrical 全程沒有 `water_shutoff`。
  focused guided tests 為 `59 passed, 50 subtests passed`；完整 pytest 為
  `162 passed, 18 skipped, 102 subtests passed`，18 個 skip 不算成功證據。Node syntax
  與 concurrency regression 通過；本功能異動 Python diagnostics、Ruff check、Ruff
  format check 及 `git diff --check` 通過。全庫 Ruff check 已執行但保留 15 個既有、
  非本功能檔案 finding；全庫 format check 也受既有未格式化檔案阻擋，兩者是
  baseline debt，不能宣稱全庫通過。本輪沒有執行真瀏覽器 smoke。
- 2026-08-01：依 PR #17 review 將 Bedrock `stopReason` 改為 fail-closed；只有
  `end_turn` 接受文字、`tool_use` 接受工具呼叫，截斷、filter、malformed 與
  reason/content 不一致都拒絕。格式化兩個新檔，並將四個 Bedrock Python 檔納入
  PostgreSQL CI targeted Ruff check／format check。focused
  `52 passed, 14 subtests passed`，完整 `156 passed, 19 skipped,
  55 subtests passed`；Nova Lite synthetic live smoke 重新通過。

- 2026-08-01：新增 `scripts/bedrock_mcp_e2e.py` 與 contract tests；Nova Lite 經
  未修改的 `AgentRunner`、`MCPToolClient`、process-local MCP protocol 與
  `ReadServiceLayer`，實際完成服務、行政區、表單與 synthetic 候選四工具閉環。
  4 次 Bedrock request 的 start interval 為 1.797／1.110／1.437 秒，沒有 AWS
  持久資源。PR review 後加入 1.1 秒設定下限與跨 ModelTurn ToolResult ID
  provenance 驗證；同輪猜 ID、MCP error、`ok=false`、`max_steps` 與 evidence
  redaction regression 均通過。focused `33 passed, 7 subtests passed`，完整
  `166 passed, 19 skipped, 59 subtests passed`。

- 2026-08-01：新增 `BedrockModelClient`，沿用 provider-neutral messages／tools 與
  `ModelTurn`，完成 Converse text／tool-use／tool-result 轉換、JSON object 驗證、
  explicit Region／model／credential fail-fast 與 provider error 遮罩；沒有修改
  AgentRunner、MCP 或 Service Layer。fake-client focused `15 passed`，完整
  `148 passed, 19 skipped, 52 subtests passed`。`us-west-2` 的
  `amazon.nova-lite-v1:0` synthetic live tool-use 成功；兩個允許 Region 的
  AgentCore Runtime count 均為 0，本輪未建立任何持久 AWS 資源。

- 2026-07-31：實作 MEDIA-001：一張 JPEG／PNG／WebP、8 MiB、實際解碼與 EXIF
  清除、安全相對路徑、HF VLM 結構化建議、人工更正／確認、服務目錄重驗、
  memory／PostgreSQL case 欄位與廠商受控圖片 endpoint。Mock 與 HF error 都不
  fallback；未確認不影響表單／媒合／派單；Browser 不取得 `image_path`。圖片
  focused Web／a11y 驗證 `40 passed`，JavaScript syntax 與 Python Ruff 通過；
  本機完整 `134 passed, 18 skipped, 52 subtests passed`；compileall、兩支 JS
  syntax、受影響 Python Ruff 與 diff check 通過。格式修正 `5410e75` 後，
  [PostgreSQL CI Run #16](https://github.com/spicyhoney/nw_p/actions/runs/30645834182)
  以 PostgreSQL 16.14 完整執行 migration 001–003 與 repository／constraint cases，
  結果 `151 passed, 1 skipped, 52 subtests passed`。`1280x720`／`390x844` 瀏覽器無水平
  overflow／console error，圖片同意列具 44px 觸控範圍。另以無個資 synthetic 水漬
  圖片完成 Hugging Face live smoke：`Qwen/Qwen3-VL-30B-A3B-Instruct` 在
  `HF_VL_PROVIDER=novita` 與 `auto` 均回傳合約內的繁中結構化結果。
- 2026-07-30：完成 PR #13 checklist race review：完整 SessionView 使用
  request sequence／session generation 阻擋 stale response，一批 PUT 完成後 GET
  對齊；寫入期間鎖住其他 session mutation，失敗時恢復 checked／disabled／focus。
  Node regression 刻意反序回應並覆蓋 Reset／新 session。focused
  `40 passed, 6 skipped, 3 subtests`；本機完整 `105 passed, 15 skipped,
  43 subtests`；瀏覽器反序與 500 故障注入通過，無 console／page error。
- 2026-07-30：新增 process-local 人工 Checklist 的冪等 `PUT`、suggested／checked
  分離、polling 保留與 Reset 清除；完成 live regions、44px 目標、高對比 focus、
  reduced-motion 與 `1280x720`／`390x844` 響應式驗收。兩尺寸零
  overflow／console error，AA 對比掃描零 finding。
- 2026-07-30：PR #12 同步 `main@33f66fe`；案件 repository 契約、Service 與
  memory／PostgreSQL adapters 全面 async，並以封鎖同步 `psycopg.connect`
  的 regression test 驗證 Web 路徑。新增可由 PR、`main` push 或手動 dispatch
  重跑的 PostgreSQL CI。無資料庫 focused `33 passed, 6 skipped, 3 subtests`；
  原生 PostgreSQL 16.14 integration `15 passed`；完整 suite
  `113 passed, 43 subtests passed`。
- 2026-07-29：新增 `workflow` schema、PostgreSQL transaction repository、
  migration runner 與 `memory|postgres` Web 設定。無資料庫 focused
  `33 passed, 5 skipped, 3 subtests passed`；原生 PostgreSQL 16.14 新舊
  integration `14 passed`，涵蓋重啟後讀回、rollback、資料庫 constraint、
  持久化冪等與兩個獨立 worker 同時接受／拒絕。完整 suite（含測試資料庫）
  `112 passed, 43 subtests passed`。
- 2026-07-29：完成 PR #10 review 修正：建案時重驗 `+08:00`、未來時間、
  先後順序與 12 小時上限；provider filter 與詳情同步；App factory 拒絕不同
  workflow。Workflow + Web focused `30 passed, 3 subtests passed`；完整 suite
  `95 passed, 9 skipped, 43 subtests passed`；Ruff／format 與 JavaScript syntax
  通過。三份文件衝突已整合並保留 HF AI mode、live eval 與 token 安全設定。
- 2026-07-28：新增消費者明確派單、process-local `CaseWorkflowService`、
  idempotency／audit、廠商工作台、指派隔離、pending 遮罩、接單後揭露、
  拒絕改派與 synthetic Demo 訂單。原始瀏覽器驗收在 `1280x720` 與
  `390x844` 跑通雙端流程，無 console error 或水平 overflow。
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
[實作文件模板](implementation-template.md)。第一次接手先讀
[專案白話指南](project-guide.md)、[HANDOFF](../HANDOFF.md) 與
[TASKS](../TASKS.md)。規劃文件若與實作衝突，以程式測試、HANDOFF、本索引及
模組 README 記錄的目前契約為準。
