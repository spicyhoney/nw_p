# HANDOFF：居家修繕 Agent（nw_p）

> 更新：2026-07-26 19:28 +08:00　更新者：Codex　機器：Windows / Asia-Taipei
> 規則：全文 ≤150 行；只描述現在；接手者先以本檔為準，再按連結讀細節。

## 1. 目前狀態（3 行內）

PR #4 `feature/agent-prototype` 已補上地點更正 bug 修正與回歸測試，最新
commit 為 `36fd1e2`，PR 仍是 Draft、尚未合併。Mock Agent 與唯讀 MCP 閉環
可測；真實 Bedrock、寫入/媒合服務與 Demo UI 尚未完成。

## 2. 本次 session 完成（帶證據）

- PR #4 bug 已修正：失敗的行政區可在下一輪更正，不會被舊訊息遮蔽
  （程式：`src/home_repair_agent/agent/mock_model.py`；測試：
  `tests/test_agent_loop.py`）。
- 驗證：Agent 測試 `11 passed`；完整測試 `36 passed, 9 skipped,
  25 subtests passed`；Agent 範圍 Ruff 通過。
- 修正細節與重現步驟：
  `docs/ENGINEER_LOG-pr4-location-fix.md`。
- PR #4 已留下審查、bug、修正 commit 與測試結果紀錄：
  https://github.com/spicyhoney/nw_p/pull/4

## 3. 下一步（具體到第一個動作）

1. 先同步並驗證 PR #4：
   `git switch feature/agent-prototype && git pull --ff-only &&`
   `.\.venv\Scripts\python.exe -m pytest -q`
   預期：`36 passed, 9 skipped, 25 subtests passed`。
2. 組員審查 `36fd1e2` 與 PR 內的 model-mode 提案，決定是否採用
   `auto / bedrock / local / mock` provider routing。
3. 若提案通過，先在最新 `main` 建立獨立分支，再修改
   `src/home_repair_agent/agent/`；不要把 provider routing 混進
   matching-service 分支。
4. 若提案未通過，維持現有 `ModelClient` port，Bedrock adapter 與本機
   Demo 各自顯式選擇 provider，不做自動 fallback。

## 4. 條目（全部為 active）

### User decisions（照做，不重新問）

- [active] `docs/` 多數內容是早期 brainstorm 遺留資料；兩份 PDF 是比賽方
  提供的正式資訊（原話，2026-07-26）。實作狀態以
  `docs/implementation-index.md` 和程式/測試為準。
- [active] 先完成組員對 PR #4 的要求：審查、測試、修 bug、留下可追溯紀錄
  （原話：「我們先把對方的要求完成」，2026-07-26）。
- [active] 向組員提議：AWS 未設定時顯示清楚提示，並可切換到以開源模型
  驅動的第二種模式（原話，2026-07-26）。這是「提出討論」，不是已核准實作。

### Agent assumptions（可質疑）

- [active] 建議 provider mode 為：
  - `bedrock`：強制使用 AWS；設定或憑證不足時 fail fast。
  - `local`：使用本機開源模型 adapter；不得冒充 Bedrock。
  - `auto`：Bedrock 設定完整才使用 AWS，否則顯示
    `AWS 未啟用，目前使用 local mode` 後切到 `local`。
  - `mock`：保留目前 deterministic rule-based client，只供測試與固定 Demo。
- [active] 不建議在 `bedrock` mode 靜默降級，否則正式 Demo 可能在不知情下
  使用不同模型；fallback 必須在 log、CLI/UI 與回應 metadata 可見。
- [active] 本機開源模型應實作成新的 `ModelClient` adapter，重用既有
  `AgentRunner` 與 MCP tool loop；實際 runtime/model（例如本機相容 API）
  尚未選定。
- [active] PR #4 暫留 Draft 等組員最後審查；未取得明確指示前不合併。

### Open issues（待決）

- [active] 組員是否同意四種 provider mode？需要在 PR #4 回覆。
- [active] `auto` 是否允許自動 fallback，或必須由使用者確認後才切換？
- [active] 本機開源模型 runtime、model 尺寸、硬體需求及 tool-calling
  相容性尚未評估。
- [active] 真實 Bedrock adapter 由誰實作、何時能取得 AWS 環境仍待確認。
- [active] matching service 的 API、資料模型、寫入確認與冪等邊界尚未定案。

## 5. 目前架構與工作邊界

- 已完成：資料清洗、PostgreSQL schema/loader、唯讀 Service Layer、三個唯讀
  MCP Tools、Mock Agent tool loop。
- 未完成：真實 Bedrock/AgentCore、FastAPI/Demo UI、案件寫入、媒合、確認與
  訂單。
- Agent 介面：`src/home_repair_agent/agent/models.py` 的 `ModelClient` /
  `ToolClient`；設計說明見 `src/home_repair_agent/agent/README.md`。
- 現有 Agent 只允許 read-only tools；不要在未做確認、冪等與授權設計前開放
  寫入 tool。
- `feature/agent-terminal-demo`（`2ae5ada`）與
  `feature/bedrock-adapter`（`446fb84`）是本機未推送的實驗分支，不是遠端
  canonical 狀態；使用前必須重新審查並 rebase 最新基底。

## 6. 環境快照

- Repo：`C:\Users\water\Desktop\AI\claude\hack松\nw_p`
- 當前分支：`feature/agent-prototype`，追蹤
  `origin/feature/agent-prototype`。
- Python：`.venv` / Python 3.14.5。
- 還在跑的 process：無本次工作啟動的長時間 process。
- 主要證據：`docs/implementation-index.md`、
  `docs/ENGINEER_LOG-pr4-location-fix.md`、PR #4。
- 危險區：不要 force-push、不要直接改/刪使用者的兩個本機實驗分支、不要在
  沒有明確授權時將 PR 改 Ready 或合併。

## 7. 授權狀態

- 使用者已授權：建立並提交本 handoff；在 PR #4 向組員提出 AWS/local mode
  架構討論（2026-07-26）。
- 未授權：合併 PR #4、啟用寫入 MCP Tools、部署 AWS 資源或選定特定本機模型。
