# HANDOFF：居家修繕 Agent（nw_p）

> 更新：2026-07-27　更新者：Codex
> 規則：全文 ≤150 行；只描述現在；接手者先以本檔為準，再按連結讀細節。

## 1. 目前狀態（3 行內）

PR #5 已於 2026-07-27 以 merge commit `73a6e45` 合併至 `main`。本分支完成
可人工操作的四工具 synthetic 媒合 Demo，正準備建立後續 Draft PR；其上的
Hugging Face adapter 仍在獨立 stacked branch，尚未進入 `main`。

## 2. 本次 session 完成（帶證據）

- 移植既有 terminal demo，並讓 `RuleBasedRepairMockModel` 在表單必填回答完成後
  呼叫 `match_service_providers`；顯示 synthetic 候選、時段與分數。
- Demo 使用記憶體合成資料，不連 AWS/PostgreSQL、不寫資料、不保留時段或建單；
  詳見 `docs/ENGINEER_LOG.md` 與 `src/home_repair_agent/agent/README.md`。
- 腳本化 smoke：`python -m home_repair_agent.agent.demo --scripted` 成功；
  2026-07-27 重新驗證完整 suite 為
  `49 passed, 9 skipped, 40 subtests passed`。9 個 skip 均需測試資料庫。
- 功能 commit：`4d1a8e1`。無 `TEST_DATABASE_URL`，不可宣稱媒合 SQL 已在真實
  PostgreSQL 複驗。
- 已在 PR #5 留下下一階段分工：
  `https://github.com/spicyhoney/nw_p/pull/5#issuecomment-5084316544`。

## 3. 下一步（具體到第一個動作）

1. 建立本分支到 `main` 的 Draft PR；組員審查 terminal flow、synthetic
   標示、無寫入邊界與腳本化 Demo，不自動合併。
2. Hugging Face adapter 已在 `feature/huggingface-model-adapter`，先以本分支
   為 base 建立 stacked Draft PR；本 PR 合併後再將其 base 改為 `main`。
3. 兩個 PR 通過後再開始 Web Demo vertical slice；不要重做既有
   `ModelClient`、`AgentRunner` 或 MCP tool loop。

## 4. 條目（全部為 active）

### User decisions（照做，不重新問）

- [active] `docs/` 多數內容是早期 brainstorm 遺留資料；兩份 PDF 是比賽方
  提供的正式資訊（原話，2026-07-26）。實作狀態以
  `docs/implementation-index.md` 和程式/測試為準。
- [active] 向組員提議：AWS 未設定時顯示清楚提示，並可切換到以開源模型
  驅動的第二種模式（原話，2026-07-26）。這是「提出討論」，不是已核准實作。
- [active] 已授權實作唯讀 matching service、建立新分支與 Draft PR
  （原話：「行那你就幫我弄吧」，2026-07-26）。
- [active] PR #5 已由 `y-row` 合併；本次已授權同步最新交接紀錄並建立
  terminal／Hugging Face 後續 PR，不自動合併（原話：「好那你幫我弄」，
  2026-07-27）。
- [active] 已授權在通知組員下一步前再完成一段工作；本次選擇只讀 terminal
  matching Demo（原話：「多做一點再跟他說接下來我們要做甚麼」，2026-07-27）。

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
- [active] `matching_v1` 已通過本機程式審查，但是否符合產品偏好仍由組員
  決定；真實資料接入前不得宣稱媒合準確率。
- [active] PostgreSQL repository 先取 100 個 slot 再排名／去重，真實規模下
  可能讓多早期空檔的單一師傅佔滿候選池；目前 3 位 synthetic Demo 不受影響。
- [active] Rule-based Mock 尚未把「星期六下午」轉成含時區時間窗；Demo
  目前不傳 `preferred_start` / `preferred_end`，只排序該地點所有空檔。
- [active] 案件、保留時段、確認媒合與訂單的寫入／冪等邊界尚未定案。

## 5. 目前架構與工作邊界

- 已完成：資料清洗、PostgreSQL schema/loader、四個唯讀 Service／MCP
  Tools、`matching_v1` synthetic 媒合、Mock Agent tool loop 與 terminal Demo。
- 未完成：真實 Bedrock/AgentCore、FastAPI/Demo UI、案件寫入、時段保留、
  確認媒合與訂單。
- Agent 介面：`src/home_repair_agent/agent/ports.py` 的 `ModelClient` /
  `ToolClient`；設計說明見 `src/home_repair_agent/agent/README.md`。
- 現有 Agent 只允許 read-only tools；不要在未做確認、冪等與授權設計前開放
  寫入 tool。
- 未推送的本機實驗分支不屬於可重現的團隊狀態，不作為接手依據。

## 6. 環境快照

- Repo：`https://github.com/spicyhoney/nw_p`
- `main`：`73a6e45`（PR #5 merge commit）。
- 當前分支：`feature/matching-terminal-demo`，由 PR #5 head 延伸，正準備
  建立到 `main` 的 Draft PR。
- Python：專案要求 `>=3.11`；使用各自工作區的 `.venv` 驗證。
- 主要證據：`docs/implementation-index.md`、`docs/matching-service.md`、
  程式與測試。
- 危險區：不要 force-push；不要把 synthetic 師傅說成真實合作廠商；不要在
  此分支加入寫入 Tool。

## 7. 授權狀態

- 使用者已授權：PR #4 squash merge；完成 matching service 與只讀 terminal
  Demo；同步最新文件並建立 terminal／Hugging Face Draft PR（2026-07-26～27）。
- 未授權：自動合併後續 PR、啟用寫入 MCP Tools、部署 AWS 資源或開始 Web UI。
