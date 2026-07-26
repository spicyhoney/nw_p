# HANDOFF：居家修繕 Agent（nw_p）

> 更新：2026-07-27　更新者：Codex
> 規則：全文 ≤150 行；只描述現在；接手者先以本檔為準，再按連結讀細節。

## 1. 目前狀態（3 行內）

PR #5 仍為 Ready for review、尚未合併。其上的 terminal Demo 再疊出
`feature/huggingface-model-adapter`，已完成 Hugging Face hosted open-model
adapter 與顯式 provider routing；live token、Bedrock、寫入與 UI 尚待完成。

## 2. 本次 session 完成（帶證據）

- 新增 `HuggingFaceModelClient`，完成 chat messages、function schema、文字／
  tool-call response 轉換與安全錯誤遮罩；不改 `AgentRunner` 或 MCP 契約。
- terminal Demo 新增 `--model-provider mock|huggingface`。Hugging Face mode
  從環境讀 `HF_TOKEN`、`HF_MODEL_ID`、`HF_PROVIDER`、`HF_MAX_TOKENS`；
  缺設定時 fail fast，不靜默 fallback。
- 預設 `Qwen/Qwen3-4B-Instruct-2507`、provider `auto`；使用 hosted
  Inference Providers，不下載模型權重。token 不進 Git／log／repr。
- 已核對 `huggingface_hub 1.24.0` 真實 API；focused tests 30 passed，
  完整 suite `60 passed, 10 skipped, 40 subtests passed`，Mock 四工具 smoke、
  scoped Ruff、format、`compileall`、`pip check`、`git diff --check` 通過。
- 功能 commit：`d2e953c`；遠端分支已推送。
- 無 `HF_TOKEN`，所以 live provider call 未執行，不宣稱真實模型已端到端完成。
  全 repo Ruff 另有 22 個未改動的既有 data-cleaning／script 問題。
- 已在 PR #5 更新分工以避免隊友重複實作：
  `https://github.com/spicyhoney/nw_p/pull/5#issuecomment-5084377900`。

## 3. 下一步（具體到第一個動作）

1. 使用者在自己的 PowerShell session 設定有 Inference Providers 權限的
   `HF_TOKEN`，執行
   `python -m home_repair_agent.agent.demo --model-provider huggingface`；
   只用 synthetic prompts，記錄 tool selection、參數、延遲與額度。
2. 組員先審查／合併 PR #5。其 squash merge 後同步 `main`，在 Demo 分支執行
   `git rebase --onto origin/main 55110e3 feature/matching-terminal-demo`，
   重跑完整測試後再建立 Demo PR。
3. Demo rebase 後，重疊 HF-only commit：
   `git rebase --onto feature/matching-terminal-demo ab9fe49 feature/huggingface-model-adapter`；
   重跑測試，再建立獨立 PR。不要 force-push 未協調的共享分支。

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
- [active] 已授權在通知組員下一步前再完成一段工作；本次選擇只讀 terminal
  matching Demo（原話：「多做一點再跟他說接下來我們要做甚麼」，2026-07-27）。
- [active] 已授權串接 Hugging Face 模型（原話：「幫我做一件事情，就是串一下
  huggingface的模型來做這件問題」，2026-07-27）。

### Agent assumptions（可質疑）

- [active] terminal Demo 已採顯式 `mock / huggingface`；`bedrock` 日後獨立
  加入。`huggingface` 是 hosted open model，不等於本機離線 runtime。
- [active] 目前不建議實作 `auto`。若未來加入，必須由設定明確啟用，且
  fallback 必須在 log、CLI/UI 與回應 metadata 可見；`bedrock` mode 不得
  靜默降級。
- [active] Hugging Face adapter 重用既有 `ModelClient`、`AgentRunner` 與 MCP
  tool loop；default model 可替換，尚未以 live eval 鎖定競賽用模型。

### Open issues（待決）

- [active] Hugging Face live eval 的 token、額度、模型品質與延遲尚未驗證。
- [active] Bedrock provider routing 何時實作、由誰負責？
- [active] 未來是否需要 `auto` fallback，以及是否必須由使用者確認後切換？
- [active] 若要完全離線的本機 open model，runtime、模型尺寸、硬體與
  tool-calling 相容性仍未評估；目前 HF adapter 是 hosted API。
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
  Tools、`matching_v1` synthetic 媒合、Mock terminal Demo、HF adapter contract。
- 未完成：真實 Bedrock/AgentCore、FastAPI/Demo UI、案件寫入、時段保留、
  確認媒合與訂單。
- Agent 介面：`src/home_repair_agent/agent/ports.py` 的 `ModelClient` /
  `ToolClient`；設計說明見 `src/home_repair_agent/agent/README.md`。
- 現有 Agent 只允許 read-only tools；不要在未做確認、冪等與授權設計前開放
  寫入 tool。
- 未推送的本機實驗分支不屬於可重現的團隊狀態，不作為接手依據。

## 6. 環境快照

- Repo：`https://github.com/spicyhoney/nw_p`
- 當前分支：`feature/huggingface-model-adapter`，stacked on terminal Demo
  與 PR #5，尚未建立 PR。
- Python：專案要求 `>=3.11`；使用各自工作區的 `.venv` 驗證。
- 主要證據：`docs/implementation-index.md`、`docs/matching-service.md`、
  程式與測試。
- 危險區：不要 force-push；不要把 synthetic 師傅說成真實合作廠商；不要在
  此分支加入寫入 Tool。

## 7. 授權狀態

- 使用者已授權：PR #4 squash merge；實作、測試、提交、審查並將 PR #5
  改為 Ready；完成只讀 matching terminal Demo 與 Hugging Face adapter
  （2026-07-26～27）。
- 未授權：合併 matching-service PR、啟用寫入 MCP Tools、部署 AWS 資源或
  選定特定本機模型。
