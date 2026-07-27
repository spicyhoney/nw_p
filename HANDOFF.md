# HANDOFF：居家修繕 Agent（nw_p）

> 更新：2026-07-27　更新者：Codex
> 規則：全文 ≤150 行；只描述現在；接手者先以本檔為準，再按連結讀細節。

## 1. 目前狀態（3 行內）

PR #5 仍為 Ready for review、尚未合併；HF stacked branch 已修正 SDK 版本、
request timeout、相對日期防猜測與 Demo 過期時段。團隊紀錄已有一次四工具
synthetic live smoke；固定 eval 與 Web vertical slice 尚待後續完成。

## 2. 本次 session 完成（帶證據）

- 團隊紀錄的 HF live run 已以 `Qwen/Qwen3-4B-Instruct-2507` 成功呼叫
  `search_services`、`resolve_location`、`get_consultation_form`、
  `match_service_providers`；尚未形成固定 eval，不宣稱模型品質。
- Review 修正：`huggingface_hub>=1.24,<2`；`HF_TIMEOUT_SECONDS=60`；相對日期
  不得由模型自行轉換；Demo slots 由可注入時鐘產生在下一個未來星期六。
- 驗證：focused 34 passed；完整 suite 65 passed、9 skipped、40 subtests
  passed；Mock 四工具 smoke、scoped Ruff、compileall、diff check 通過。
- 本次修正環境沒有 `HF_TOKEN`，未重跑 live，也未對外傳送對話。
- 模型輸出的 Markdown `☐` 不是 UI；目前 `AgentTurnResult` 只有 reply/trace，
  沒有可供前端渲染的 form/session view model，也未保存 validated form answers。
- 主辦方 PDF 明定彈性諮詢單、服務廠商管理者後台／操作介面，決賽需交
  Live Demo 部署網址；完成度評分包含使用體驗。因此 CLI 只保留工程 smoke。
- HF token 曾出現在使用者提供的終端 transcript；使用者已撤銷／refresh。
  不保留或記錄新 token，該 transcript 不可提交或再次分享。
- 已在 PR #5 提出 Web scope／分工與驗收標準，待組員回覆：
  `https://github.com/spicyhoney/nw_p/pull/5#issuecomment-5084536753`。

## 3. 下一步（具體到第一個動作）

1. 先等組員在 PR #5 討論串確認 Web scope／分工；今天不開始 UI 實作。
2. 同意後第一個動作：
   `git fetch origin --prune`，確認 PR #5 與 stacked branches 狀態；再從團隊同意
   的最新整合基線建立 `feature/web-demo-vertical-slice`，不要再盲目疊分支。
3. P0 consumer vertical slice TODO（依序）：
   - FastAPI session/message/form-submit API；前端不直接呼叫 HF／Bedrock。
   - 消費者頁：聊天、真正可操作的動態表單、進度 checklist、候選卡與 reset。
   - 結構化 session state：service/location/form answers/time window/candidates。
   - `single_select` 用 radio；日期時間由 UI 產生 Asia/Taipei aware ISO window。
   - 必填完成且時間驗證通過後才媒合；禁止模型捏造日期、修改偏好或替換服務。
   - provider label／debug trace 可見；切 HF→Bedrock 時 UI/API contract 不變。
4. P1 TODO：最小服務廠商後台（案件列表、摘要、狀態）；需先完成有確認與冪等的
   case submission contract。語音、登入、付款、真實師傅、照片、完整後台、
   AWS 部署皆不納入 P0。
5. P0 驗收：需求文字 → 三個真 Tool → 手動完成欄位 → validated matching Tool
   → 顯示 tool result 的 synthetic 候選；換 `ModelClient` 時前端零修改。

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
- [active] 下一步改為可操作 UI＋正確模型 Demo，並保持日後串 AWS 只需替換
  adapter；今天先列 TODO、更新 handoff、徵求組員同意，明天再做
  （使用者原話，2026-07-27）。
- [active] HF token 已 refresh；舊 token 視為失效，不重新要求或記錄新 token。
- [active] 已授權修正 HF branch review findings、測試、提交並推送，讓對方排程
  AI 定時檢查與更新（原話：「好 那你幫我修正吧」，2026-07-27）。

### Agent assumptions（可質疑）

- [active] terminal Demo 已採顯式 `mock / huggingface`；`bedrock` 日後獨立
  加入。`huggingface` 是 hosted open model，不等於本機離線 runtime。
- [active] 目前不建議跨 ModelClient 的自動 fallback。HF SDK 的
  `provider=auto` 只負責在 HF Inference Providers 內路由，不等於
  `huggingface -> mock` fallback；`bedrock` mode 不得靜默降級。
- [active] Hugging Face adapter 重用既有 `ModelClient`、`AgentRunner` 與 MCP
  tool loop；live 已證明 transport 可用，但尚未完成固定 eval。
- [active] P0 建議同 repo 以 FastAPI＋輕量 web frontend 提供單一部署網址，
  但 React/Vite 或無 build 的 HTML/CSS/JS 尚待組員確認。
- [active] UI state 應由 deterministic backend view model 驅動；LLM reply
  只作說明，不作 checkbox、日期或 business state 的 source of truth。

### Open issues（待決）

- [active] 組員是否同意 P0/P1 scope、技術棧與分工？
- [active] Web branch 要等 PR #5 合併後從 main 開，還是暫時以整合分支開工？
- [active] consultation session state P0 存 memory；何時切 PostgreSQL？
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
  目前不傳 `preferred_start` / `preferred_end`，只排序該地點所有未來空檔；
  hosted model 也不得自行把相對日期換成年月日。
- [active] 案件、保留時段、確認媒合與訂單的寫入／冪等邊界尚未定案。

## 5. 目前架構與工作邊界

- 已完成：資料清洗、PostgreSQL schema/loader、四個唯讀 Service／MCP
  Tools、`matching_v1` synthetic 媒合、Mock terminal Demo、HF live adapter。
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
- 已授權本次：修正 HF adapter review findings、測試、提交並推送；UI 不在
  本次 scope。
- 未授權：合併 matching-service PR、今天開始 UI、啟用寫入 MCP Tools、
  部署 AWS 資源或選定特定本機模型。
