# HANDOFF：居家修繕 Agent（nw_p）

> 更新：2026-07-26　更新者：Codex
> 規則：全文 ≤150 行；只描述現在；接手者先以本檔為準，再按連結讀細節。

## 1. 目前狀態（3 行內）

PR #4 `feature/agent-prototype` 的地點更正、多地點安全重試與回歸測試已由
雙方複查通過，進入 Ready / merge 交接，但尚未合併。Mock Agent 與唯讀 MCP
閉環可測；真實 Bedrock、寫入/媒合服務與 Demo UI 尚未完成。

## 2. 本次 session 完成（帶證據）

- PR #4 地點流程已強化：失敗的行政區可在下一輪更正；同一句含新、舊地點時
  不猜測，會要求只輸入更正後地點（程式：
  `src/home_repair_agent/agent/mock_model.py`；測試：
  `tests/test_agent_loop.py`）。
- 驗證：Agent 測試 `12 passed`；本工作區有主辦方資料集、未設定
  `TEST_DATABASE_URL` 時，完整測試為 `38 passed, 8 skipped,
  25 subtests passed`。另一個無主辦方資料集的乾淨工作區複查為
  `37 passed, 9 skipped, 25 subtests passed`；Agent 範圍 Ruff 通過。
- 修正細節與重現步驟：
  `docs/ENGINEER_LOG-pr4-location-fix.md`。
- PR #4 已留下審查、bug、修正 commit 與測試結果紀錄：
  https://github.com/spicyhoney/nw_p/pull/4

## 3. 下一步（具體到第一個動作）

1. 等 PR #4 合併通知；合併後第一個動作：
   `git switch main && git pull --ff-only origin main`。
2. 從最新 `main` 建立 `feature/matching-service`，先定義 matching service
   的唯讀候選查詢契約與測試，不直接開放案件／訂單寫入。
3. 顯式 `bedrock / local / mock` provider routing 另開獨立分支，再修改
   `src/home_repair_agent/agent/`；不要把 provider routing 混進
   matching-service 分支。

## 4. 條目（全部為 active）

### User decisions（照做，不重新問）

- [active] `docs/` 多數內容是早期 brainstorm 遺留資料；兩份 PDF 是比賽方
  提供的正式資訊（原話，2026-07-26）。實作狀態以
  `docs/implementation-index.md` 和程式/測試為準。
- [active] 先完成組員對 PR #4 的要求：審查、測試、修 bug、留下可追溯紀錄
  （原話：「我們先把對方的要求完成」，2026-07-26）。
- [active] 向組員提議：AWS 未設定時顯示清楚提示，並可切換到以開源模型
  驅動的第二種模式（原話，2026-07-26）。這是「提出討論」，不是已核准實作。
- [active] PR #4 複查通過，可改為 Ready；仍不直接合併
  （原話：「好 那你做吧」，2026-07-26；承接「確認複查通過並改 Ready」）。

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
- [active] matching service 的 API、資料模型、寫入確認與冪等邊界尚未定案。

## 5. 目前架構與工作邊界

- 已完成：資料清洗、PostgreSQL schema/loader、唯讀 Service Layer、三個唯讀
  MCP Tools、Mock Agent tool loop。
- 未完成：真實 Bedrock/AgentCore、FastAPI/Demo UI、案件寫入、媒合、確認與
  訂單。
- Agent 介面：`src/home_repair_agent/agent/ports.py` 的 `ModelClient` /
  `ToolClient`；設計說明見 `src/home_repair_agent/agent/README.md`。
- 現有 Agent 只允許 read-only tools；不要在未做確認、冪等與授權設計前開放
  寫入 tool。
- 未推送的本機實驗分支不屬於可重現的團隊狀態，不作為接手依據。

## 6. 環境快照

- Repo：`https://github.com/spicyhoney/nw_p`
- 當前分支：`feature/agent-prototype`，追蹤
  `origin/feature/agent-prototype`。
- Python：專案要求 `>=3.11`；使用各自工作區的 `.venv` 驗證。
- 主要證據：`docs/implementation-index.md`、
  `docs/ENGINEER_LOG-pr4-location-fix.md`、PR #4。
- 危險區：不要 force-push；PR #4 已授權改 Ready，但未授權直接合併。

## 7. 授權狀態

- 使用者已授權：建立並提交本 handoff；在 PR #4 向組員提出 AWS/local mode
  架構討論；複查通過後將 PR 改 Ready（2026-07-26）。
- 未授權：合併 PR #4、啟用寫入 MCP Tools、部署 AWS 資源或選定特定本機模型。
