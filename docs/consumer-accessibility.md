# 消費者 Checklist 與無障礙 UI P0

最後更新：2026-07-30

## 1. 做了什麼

本階段完成消費者端第一版可驗證的高齡／無障礙體驗：

- 三項人工 Checklist：服務需求、地點、諮詢內容與希望時段。
- 系統只回傳 `suggested` 提示；只有使用者操作受限 `PUT` API 才能改 `checked`。
- checked 保存在目前 process-local Web session，重畫與案件 polling 後仍保留。
- 未建案時 Reset 清空同一 session；已有案件時前端建立新 session，預設亦全未勾。
- 原生 checkbox 支援滑鼠與 Space，另補 Enter 操作、label、checked 與 live feedback。
- 放大主要文字與表單，主要互動有效觸控範圍至少約 `44x44px`。
- 加入高對比 focus、狀態文字、live region、錯誤欄位關聯與 reduced-motion。
- 重新整理 `1280x720` 與 `390x844` 版面，保留 Mock／Hugging Face provider routing。

刻意沒做：

- Checklist 不會取代派單的 `confirmed=true`，也不會自動建立案件。
- Checklist 不寫入案件 PostgreSQL repository，程式重啟後仍會隨 Web session 消失。
- 沒有新增寫入 MCP Tool、正式 authentication、AWS、RDS 或真實個資處理。
- 本輪沒有 HF token，因此沒有重跑 hosted model live case。

## 2. 為什麼這樣設計

Checklist 是使用者的 UI 核對狀態，不是模型推論或案件事實。`SessionView` 同時回傳：

- `suggested`：後端已有結構化資料，可以請使用者核對。
- `checked`：使用者已主動勾選；Agent、tool trace 與模型回覆都不能修改。

更新採 `PUT /api/sessions/{id}/checklist/{key}`，重送相同值結果相同，因此 polling
不需要依賴瀏覽器暫存，也不會混入需要 audit 的案件 repository。真正派單仍走既有
`DispatchRequest(confirmed, idempotency_key)` 與 `CaseWorkflowService`。

## 3. 資料流

```text
User click / Space / Enter
  -> PUT /api/sessions/{id}/checklist/{service|location|consultation}
  -> WebSessionService + session lock
  -> process-local checklist state
  -> SessionView.checked
  -> rerender / GET polling 維持

Agent / MCP result
  -> structured service, location or answers
  -> SessionView.suggested=true
  -X-> 不修改 checked

Reset before dispatch
  -> 清除 conversation、structured state 與 checklist
```

## 4. 安全與不可破壞邊界

- 消費者仍須在候選確認區明確按「確認派單」才建案。
- pending contact 仍為遮罩；accepted 才回完整 synthetic contact。
- confirmation、idempotency、audit、合法狀態轉換與 repository 切換均未改。
- 四個 MCP Tools 維持唯讀；Checklist API 不暴露給 Agent。
- Mock 與 Hugging Face provider routing 維持，測試不需要 `HF_TOKEN`。
- HTML 以原生語意控制呈現，動態文字仍使用 `textContent`。

## 5. 驗證結果

自動測試（本機未提供 `TEST_DATABASE_URL`）：

- Web／workflow／repository focused：`39 passed, 6 skipped, 3 subtests passed`。
- 完整 pytest：`104 passed, 15 skipped, 43 subtests passed`。
- 15 skipped 為 PostgreSQL integration；Draft PR 的 PostgreSQL 16 CI 會另行補跑。
- 受影響檔案 Ruff、format、compileall、JavaScript syntax 與 `git diff --check` 通過。

瀏覽器人工驗收（Mock mode，無 HF token）：

- `1280x720`：完成需求、Enter／Space 勾選、表單、媒合、派單與廠商接單。
- `390x844`：同一流程可操作，返回可關閉確認區，派單按鈕完整顯示。
- 兩尺寸均無水平 overflow；可見控制的有效目標沒有小於 `44x44px`。
- 手機表單控制未超出 viewport；兩個確認按鈕皆為 `157x48px`。
- focus 為 `3px solid rgb(0, 95, 204)`；初始、媒合與確認畫面 AA 掃描無 finding。
- `prefers-reduced-motion: reduce` 實測生效；桌機與手機 console／page error 均為 0。
- pending API 實測 `masked / 0912***678`；accepted 後才為 `full / 0912-345-678`。

## 6. 待辦與風險

- Web session 仍是 process-local；若未來要持久化 Checklist，需先定保存期限與刪除同意。
- 尚未執行正式螢幕閱讀器人工測試；本輪以語意、live region 與鍵盤驗收為基線。
- 正式 authentication、語音輸入、使用者字級偏好與公開 HTTPS 部署仍未開始。
- HF live eval 與 PostgreSQL integration 結果以 Draft PR checks 為準。
