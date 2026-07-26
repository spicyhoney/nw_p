# HANDOFF：居家修繕 Agent（nw_p）

> 更新：2026-07-26　更新者：Codex
> 規則：全文 ≤150 行；只描述現在；接手者先以本檔為準，再按連結讀細節。

## 1. 目前狀態（3 行內）

PR #5（`feature/matching-service`）已完成本機審查並改為 Ready for review；
沒有發現 merge blocker，尚未合併。第四個唯讀 MCP Tool 與可解釋 synthetic
師傅媒合已完成；真實 Bedrock、寫入流程、FastAPI 與 Demo UI 尚未完成。

## 2. 本次 session 完成（帶證據）

- 審查 PR #5 head `703d4cb`：契約、查無候選、`matching_v1` 實作與文件、
  result/candidate 的 synthetic 標籤均一致，未發現阻塞問題。
- 本機完整 suite：`43 passed, 10 skipped, 40 subtests passed`；比作者工作區
  多一個 skip 是因本機沒有 organizer dataset。Scoped Ruff、`compileall` 與
  `git diff --check` 通過；repo-wide format check 仍含既有未格式化檔案。
- PR 審查紀錄：`https://github.com/spicyhoney/nw_p/pull/5#issuecomment-5084270645`；
  PR 已由 Draft 改為 Ready for review，未執行 merge。
- 無 `TEST_DATABASE_URL`，所以 PostgreSQL 媒合案例仍為 skip；不可宣稱 SQL
  已在真實 PostgreSQL 複驗。

## 3. 下一步（具體到第一個動作）

1. 組員閱讀 PR #5 審查紀錄並決定是否合併；合併前若能取得隔離的測試
   PostgreSQL，設定 `TEST_DATABASE_URL` 後執行 `python -m pytest -q`。
2. 真實供應商資料接入前，調整 PostgreSQL 候選池：目前先按開始時間取 100
   個 slot，再由 Service 排名／去重；大量時段可能降低候選師傅多樣性。
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
- [active] 已授權審查 PR #5、必要時修正、留下審查紀錄並改為 Ready；
  尚未授權 merge（原話：「好 請吧」，2026-07-26）。

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
- 當前分支：`feature/matching-service`，PR #5 Ready for review，尚未合併。
- Python：專案要求 `>=3.11`；使用各自工作區的 `.venv` 驗證。
- 主要證據：`docs/implementation-index.md`、`docs/matching-service.md`、
  程式與測試。
- 危險區：不要 force-push；不要把 synthetic 師傅說成真實合作廠商；不要在
  此分支加入寫入 Tool。

## 7. 授權狀態

- 使用者已授權：PR #4 squash merge；實作、測試、提交、審查並將
  `feature/matching-service` PR #5 改為 Ready for review（2026-07-26）。
- 未授權：合併 matching-service PR、啟用寫入 MCP Tools、部署 AWS 資源或
  選定特定本機模型。
