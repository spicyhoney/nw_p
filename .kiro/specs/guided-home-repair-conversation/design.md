# Design Document

## 1. 目標與限制

本設計只實作 `service_id=17` 水電修繕與 `repair_form_v1` 的五個受控 `issue_category`。每個 Web session 以既有 `_SessionRecord` 作為唯一 Active Consultation Task，不新增多任務容器。不得修改 AgentRunner、ToolClient、MCP Tool schema 或 AWS 工作線。

## 2. 重用的既有流程

```text
Browser
  -> FastAPI existing session routes
  -> WebSessionService (新增 task/routing/summary orchestration)
  -> existing AgentRunner + read-only MCP tools
  -> ReadServiceLayer / DemoReadRepository
  -> existing matching_v1
  -> CaseWorkflowService / dispatch / idempotency / audit
```

照片仍走 Existing Photo Flow。模型或 Runtime 不建立 service ID、Repair Branch、表單欄位、服務商、時段或媒合結果。

## 3. Active Task 與 API View

`_SessionRecord` 增加單一修繕 task 所需欄位：原始需求文字、目前 routing result、待確認分支、已確認分支、待確認分支切換、選填 slot 狀態、摘要確認狀態。既有 service/location/form/answers/time/candidates/media 繼續作為同一 task 的資料，不建立第二份平行狀態。

`SessionView` 增加 provider-neutral 的 task view：

- `repair_routing`: `confidence`、validated alternatives、unsupported、clarification question、pending/confirmed branch。
- `active_task`: collected fields、missing fields、branch、summary、summary confirmation state。
- `can_confirm_summary` 與 `can_submit_form` 分開。

Active task 在 session reset、確認分支取代或成功 dispatch 後不再接受另一項並行需求；既有案件稽核仍保留。

## 4. Repair Branch Routing

新增聚焦的 backend routing module，唯一 branch allowlist 為：

- `faucet_leak`
- `toilet_issue`
- `pipe_issue`
- `electrical_issue`
- `other`

自然語言只產生候選；候選必須存在於 `repair_form_v1` 的 `issue_category` options 才可呈現。`confidence` 僅為 `high | medium | low`：單一明確詞彙為 high，多個候選為 medium，缺少足夠線索為 low。任何等級均需使用者確認；medium/low 顯示 alternatives 或 clarification。非水電需求與無有效候選回 Unsupported。

使用者同時描述多個分支時只保存 alternatives，要求先選一項，不拆 task。`other` 維持既有 branch，並要求有效 `issue_description`，不得衍生新 branch。

## 5. 跨輪流程

1. 首輪文字先由現有 `search_services` 驗證可對應 `service_id=17`，再由受控 router 產生 branch proposal。
2. Web 顯示 proposal/alternatives；使用者以後續訊息明確確認 branch。
3. branch 確認後，將原始需求送入既有 AgentRunner，讓既有工具流程處理 service、no-guess location 與 form retrieval。
4. 缺完整縣市/行政區時沿用既有追問，不預設臺北市。
5. `repair_form_v1` 依 branch 產生受控 projection；使用者可修改表單答案。
6. 表單提交只驗證並保存答案/時段，轉為 `awaiting_summary_confirmation`，不呼叫 matching。
7. UI 顯示 collected/missing fields 與摘要。獨立 summary-confirm API 在 `confirmed=true` 時才呼叫既有 matching。
8. 選擇候選後，既有 dispatch API、CaseWorkflowService、idempotency 與 audit 維持不變。

## 6. Branch-specific Field Applicability

`repair_form_v1` topic config 保存人工 review、版本化的 `applicable_issue_categories`。未設定代表五分支皆適用。`water_shutoff` 只適用 `faucet_leak`、`toilet_issue`、`pipe_issue`；`electrical_issue` 與 `other` 的 form projection、驗證、摘要及 dispatch answers 均排除該欄位。

表單 projection 仍保留原 `form_key`、service ID 與 version。Web 已有獨立 location、datetime-range、photo controls，因此 projection 不重複顯示 `service_location`、`preferred_date`、`photos`；`preferred_time` 仍映射既有 datetime-range control。

## 7. Branch 切換

表單尚未送出前，若使用者提出另一個 validated branch，系統先回顯影響並等待確認。確認後：

- 保持同一 Active Task。
- 更新 confirmed branch。
- 清除 branch-specific answers、candidates、摘要確認及不適用照片分析參照。
- 保留不矛盾的 location、排程與 synthetic contact，並在摘要重新顯示。
- 重新取得/投影同版表單。

## 8. 選填與安全

預算與緊急程度不阻擋完整性；未回答可標為 `skipped`，拒答為 `declined_to_answer`。P0 的 `urgent` 只回顯，不改 `matching_v1`。漏電、火災、瓦斯或人身危險使用人工核准的安全停止文案，不承諾一般媒合速度。

照片只綁目前 session/task 與適用 branch；分支切換時不再適用的分析不得進入新摘要或案件。媒體實體檔案仍由既有 storage/reset/case retention 規則管理。

## 9. 驗證

- 五分支：routing、form option validation、明確確認。
- `other`：必須有 `issue_description`。
- `electrical_issue`：所有 API view、表單、答案、摘要與案件都沒有 `water_shutoff`。
- no-guess：只有「大安區」時追問縣市。
- branch switch：清除不適用答案且不建立第二 task。
- summary gate：未確認不得 matching/dispatch。
- HTTP E2E：`faucet_leak`、`electrical_issue` 完整到 dispatch。

## 10. Timeboxed Assumptions

- Router 採 deterministic、可測試詞彙規則；hosted model 仍可產生文字，但不授權 branch 業務事實。
- `repair_form_v1` 是唯一有效表單版本；若工具回傳其他 service/form 或缺資料，安全停止。
- P0 使用既有 process-local session 與 synthetic contact，不新增持久化 session 或正式 PII。
