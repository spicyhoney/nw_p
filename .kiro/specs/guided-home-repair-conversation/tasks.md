# Implementation Plan

- [x] 1. Faucet leak 可操作 vertical slice
  - [x] 1.1 讓 DemoReadRepository 使用 `repair_form_v1` 與五個受控 branch，加入版本化欄位適用性 config
  - [x] 1.2 新增 deterministic Repair Branch routing contract 與單一 Active Task state/view
  - [x] 1.3 在既有 messages API 加入 branch proposal、明確確認與 no-guess 跨輪流程
  - [x] 1.4 依 confirmed branch 投影表單；表單提交只保存答案並顯示可修改摘要
  - [x] 1.5 新增 summary confirmation gate，確認後才呼叫既有 matching
  - [x] 1.6 完成 `faucet_leak` HTTP E2E 到既有 dispatch
  - _Requirements: 1, 2, 3, 4, 5, 7, 8, 11_

- [x] 2. Electrical issue vertical slice 與欄位適用性
  - [x] 2.1 從版本化 config 排除 `electrical_issue` 的 `water_shutoff`
  - [x] 2.2 驗證 form、summary、matching answers 與 case payload 都不包含該欄位
  - [x] 2.3 完成 `electrical_issue` HTTP E2E 到既有 dispatch
  - _Requirements: 7, 8, 9, 11_

- [x] 3. 全五分支、other 與 branch switch
  - [x] 3.1 為五個 branch 完成 routing、驗證及確認 tests
  - [x] 3.2 `other` 強制追問並驗證 `issue_description`，不建立新 branch
  - [x] 3.3 多需求只顯示 alternatives；branch switch 先確認並清除不適用答案
  - _Requirements: 2, 3, 4, 6, 11_

- [x] 4. Web task/summary 呈現與修改
  - [x] 4.1 顯示 confirmed/pending branch、已收集欄位、待補欄位與摘要
  - [x] 4.2 提供摘要確認按鈕，維持鍵盤、live region、reduced-motion 基線
  - [x] 4.3 驗證未確認摘要無法 matching、建案或 dispatch
  - _Requirements: 4, 5, 8_

- [x] 5. 照片與安全邊界 regression
  - [x] 5.1 照片只綁 active repair task/branch，切換時排除不適用分析
  - [x] 5.2 驗證危險電路情境安全文案、PII/no-guess 與既有照片 consent
  - _Requirements: 9, 10_

- [x] 6. 完整驗證與實作文件
  - [x] 6.1 執行 focused Web/backend tests、兩條 HTTP E2E、Node concurrency regression；2026-08-01 結果為 `59 passed, 50 subtests passed`，Node syntax/concurrency 通過
  - [x] 6.2 執行完整 pytest、Ruff check/format check，修正所有本分支引入問題；full checks 已執行，完整 pytest 為 `162 passed, 18 skipped, 102 subtests passed`（skip 不算成功），功能變更 Python diagnostics、Ruff check、Ruff format check 與 `git diff --check` 通過；全庫 Ruff check 的 15 個既有非本功能 finding 及全庫 format check 的既有未格式化檔案保留為 baseline debt
  - [x] 6.3 更新 Web 模組 README 與 `docs/implementation-index.md`；文件記錄預算／緊急程度缺答為 `skipped`、可 `declined_to_answer`、`urgency` 僅接受 `normal|urgent` 加上述 answer states，且不改 `matching_v1`；依本輪範圍不修改共享 `HANDOFF.md` 或頂層 `TASKS.md`
  - _Requirements: 11, 12_
