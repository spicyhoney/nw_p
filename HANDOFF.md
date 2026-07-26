# HANDOFF：居家修繕 Agent（nw_p）

> 更新：2026-07-26　更新者：Codex
> 規則：全文 ≤150 行；只描述現在；接手者先以本檔為準，再按連結讀細節。

## 1. 目前狀態（3 行內）

PR #4 已以 squash commit `0bb0920` 合併到 `main`。目前在
`feature/matching-service` 完成第四個唯讀 MCP Tool 與可解釋 synthetic
師傅媒合；真實 Bedrock、案件／訂單寫入、FastAPI 與 Demo UI 尚未完成。

## 2. 本次 session 完成（帶證據）

- 新增 `ReadServiceLayer.match_service_providers`：硬性過濾服務、地點與時段，
  再依 `matching_v1` 透明規則排序並去除同師傅重複時段。
- 新增第四個唯讀 MCP Tool `match_service_providers`；結果與候選都標示為
  `synthetic`，查無候選時回空清單，不保留空檔或寫入資料。
- 新增 Service、MCP、Agent 與 PostgreSQL 案例；無 `TEST_DATABASE_URL` 的
  本工作區為 `44 passed, 9 skipped, 40 subtests passed`。
- 實作與限制：`docs/matching-service.md`。新增 PostgreSQL 媒合案例本次因無
  測試資料庫而 skip，不宣稱已完成真實 PostgreSQL 複驗。

## 3. 下一步（具體到第一個動作）

1. 推送 `feature/matching-service` 並建立 Draft PR，請組員複查契約、權重、
   synthetic 標籤與 PostgreSQL 案例。
2. 有測試 PostgreSQL 時設定 `TEST_DATABASE_URL`，執行完整 suite 複驗媒合 SQL。
3. 顯式 `bedrock / local / mock` provider routing 另開獨立分支，再修改
   `src/home_repair_agent/agent/`；不要把 provider routing 混進
   matching-service 分支。

## 4. 條目（全部為 active）

### User decisions（照做，不重新問）

- [active] `docs/` 多數內容是早期 brainstorm 遺留資料；兩份 PDF 是比賽方
  提供的正式資訊（原話，2026-07-26）。實作狀態以
  `docs/implementation-index.md` 和程式/測試為準。
- [active] 向組員提議：AWS 未設定時顯示清楚提示，並可切換到以開源模型
  驅動的第二種模式（原話，2026-07-26）。這是「提出討論」，不是已核准實作。
- [active] 已授權實作唯讀 matching service、建立新分支與 Draft PR
  （原話：「行那你就幫我弄吧」，2026-07-26）。

### Agent assumptions（可質疑）

- [active] 審查建議的顯式 provider mode 為：
  - `bedrock`：強制使用 AWS；設定或憑證不足時 fail fast。
  - `local`：使用本機開源模型 adapter；不得冒充 Bedrock。
  - `mock`：保留目前 deterministic rule-based client，只供測試與固定 Demo。
- [active] 目前不建議實作 `auto`。若未來加入，必須由設定明確啟用，且
  fallback 必須在 log、CLI/UI 與回應 metadata 可見；`bedrock` mode 不得
  靜默降級。
- [active] 本機開源模型應實作成新的 `ModelClient` adapter，重用既有
  `AgentRunner` 與 MCP tool loop；實際 runtime/model（例如本機相容 API）
  尚未選定。

### Open issues（待決）

- [active] 顯式 `bedrock / local / mock` provider routing 何時實作、由誰負責？
- [active] 未來是否需要 `auto` fallback，以及是否必須由使用者確認後切換？
- [active] 本機開源模型 runtime、model 尺寸、硬體需求及 tool-calling
  相容性尚未評估。
- [active] 真實 Bedrock adapter 由誰實作、何時能取得 AWS 環境仍待確認。
- [active] `matching_v1` 權重需組員複查；真實資料接入前不得宣稱媒合準確率。
- [active] 案件、保留時段、確認媒合與訂單的寫入／冪等邊界尚未定案。

## 5. 目前架構與工作邊界

- 已完成：資料清洗、PostgreSQL schema/loader、四個唯讀 Service／MCP
  Tools、`matching_v1` synthetic 媒合、Mock Agent tool loop。
- 未完成：真實 Bedrock/AgentCore、FastAPI/Demo UI、案件寫入、時段保留、
  確認媒合與訂單。
- Agent 介面：`src/home_repair_agent/agent/ports.py` 的 `ModelClient` /
  `ToolClient`；設計說明見 `src/home_repair_agent/agent/README.md`。
- 現有 Agent 只允許 read-only tools；不要在未做確認、冪等與授權設計前開放
  寫入 tool。
- 未推送的本機實驗分支不屬於可重現的團隊狀態，不作為接手依據。

## 6. 環境快照

- Repo：`https://github.com/spicyhoney/nw_p`
- 當前分支：`feature/matching-service`，由最新 `main` 建立。
- Python：專案要求 `>=3.11`；使用各自工作區的 `.venv` 驗證。
- 主要證據：`docs/implementation-index.md`、`docs/matching-service.md`、
  程式與測試。
- 危險區：不要 force-push；不要把 synthetic 師傅說成真實合作廠商；不要在
  此分支加入寫入 Tool。

## 7. 授權狀態

- 使用者已授權：PR #4 squash merge；實作、測試、提交並為
  `feature/matching-service` 建立 Draft PR（2026-07-26）。
- 未授權：合併 matching-service PR、啟用寫入 MCP Tools、部署 AWS 資源或
  選定特定本機模型。
