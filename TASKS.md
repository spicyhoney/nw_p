# 專案待辦

最後更新：2026-08-02

本檔只記錄尚未完成的工作。完成項目寫入
[實作索引](docs/implementation-index.md)，當前接手狀態以
[HANDOFF](HANDOFF.md) 為準。

## 使用規則

- 優先級：`P0` 是比賽 Demo／release blocker，`P1` 是核心補強，`P2` 是賽後延伸。
- 狀態只使用 `Todo`、`In progress`、`Blocked`。
- 不再新增產品功能；P0 只收斂整合、人工驗收、版本控制與 AWS cleanup。

## P0

| ID | 狀態 | 工作 | 為什麼需要 | 負責人 | 依賴 | 完成條件 |
|---|---|---|---|---|---|---|
| RELEASE-001 | In progress | Review 並交付 `integration/final-demo` | 目前完整成果只在本機整合 branch；未交付就無法由組員或評審重現 | Codex＋人類 | 隊友語音 smoke 結果、完整 diff 人工核准 | branch 已 push；PR／merge 決定有紀錄；focused tests、secret scan 與兩條 Demo 指南一致 |
| VOICE-001 | In progress | 完成實體麥克風台語／國語 smoke | 自動測試無法證明會場麥克風、瀏覽器權限與實際台語辨識品質 | 隊友 | `fix/voice-image-live-demo`／整合版 HF 模式 | 記錄原句、轉寫、延遲、是否可接受；失敗時 UI 明確改用文字且不 fallback Mock |
| DEPLOY-001 | In progress | 維持評審可連線的公開 HTTPS Web URL | 大會明確要求 Live Demo URL 可由 8 個評審來源 IP 存取 | 人類＋Codex | 電腦不休眠、網路與 Quick Tunnel 持續 | 公開 HF 與 AWS text URL 已建立；非核准來源 403、模擬評審 IP 200；正式評審 IP 實連待確認；若 process 重啟須更新 URL |
| CLEANUP-001 | In progress | Demo 後停止 tunnel／Web 並清除短效 AgentCore 資源 | Runtime、IAM、S3、log group 會持續存在並可能產生成本 | Codex | 使用者完成 live Demo | tunnel 與 Web process 已停；cleanup=`passed`；status=`not-deployed`；無 remaining resources |

## P1

| ID | 狀態 | 工作 | 為什麼需要 | 負責人 | 依賴 | 完成條件 |
|---|---|---|---|---|---|---|
| PROMPT-001 | Todo | 固定 Bedrock 多輪地點 tool-call 評估 | Nova 對單獨地點文字曾只追問而未呼叫 Tool；現場 Demo 需要可預測性 | 未分配 | 可用 Bedrock／AgentCore、synthetic cases | 5 次「臺北市大安區」與 5 次完整地點句均正確 resolve；失敗留下遮罩報告，不放寬 no-guess gate |
| DATA-001 | Todo | 讓 Web 讀取路徑可選 Demo 或 PostgreSQL repository | 正式資料持久化可證明相同服務契約不只依賴 synthetic repository | 未分配 | 已載入 clean schema 的測試 PostgreSQL | fail-fast 選項與相同服務／地點／表單／媒合契約通過 |
| AUTH-001 | Blocked | 正式登入、廠商帳號與 RBAC | Demo header 不足以保護真實案件與圖片 | 未分配 | 身分提供者與部署環境決策 | 消費者與廠商只能讀取授權資源 |
| PRIV-001 | Blocked | 真實個資同意、加密、保存期限與刪除 | 目前只允許 synthetic contact；正式留資前必須先完成隱私基線 | 未分配 | KMS／法遵／刪除政策 | 金鑰不入庫，保存與刪除行為有測試及文件 |

## P2

| ID | 狀態 | 工作 | 為什麼需要 | 負責人 | 依賴 | 完成條件 |
|---|---|---|---|---|---|---|
| CHATGPT-MCP-001 | Todo | 以外部 ChatGPT Developer Mode 驗證 `/mcp` | 可展示相同唯讀生活服務工具能被專案外 Agent 使用 | 未分配 | 核准的 HTTPS tunnel／帳號 | initialize、tools/list、四個 tools/call 通過；無寫入、無真實個資 |
| SESSION-001 | Todo | 持久化 Web 對話與人工 Checklist | 目前重啟會遺失進度；賽後才考慮跨次追蹤 | 未分配 | 保存同意、期限與刪除政策 | 可恢復已同意 session，Reset／刪除不留孤兒資料 |
| PROVIDER-001 | Todo | 廠商回覆與服務進度追蹤 | 現在廠商接受後即停止，尚未形成營運閉環 | 未分配 | 狀態機與通知範圍決策 | 指派廠商可新增受控回覆與進度，消費者可看歷程 |
| TTS-001 | Todo | 驗證並接入真正臺灣台語 TTS | 現階段只有 STT；既有 MMS spike 未經母語者確認且授權有限制 | 未分配 | 模型／授權／母語者評估 | 產生可理解台語、網頁可選播放、標示模型與限制 |

## 已完成並移出待辦

- Bedrock ModelClient、AgentRunner tool-use、request pacing 與 synthetic live evidence。
- AgentCore Remote MCP Runtime、四個唯讀 Tools、SigV4 client 與 Browser composition。
- 評審 IP allowlist；HF 與 AWS text 兩個 Quick Tunnel 已啟動，非核准來源 403、模擬評審 IP 200。
- HF 圖片建議／人工確認與台語／國語 STT Web 入口（仍待實體麥克風 smoke）。
- 手動 Checklist、動態 `repair_form_v1`、摘要確認、synthetic 媒合與本機派單 workflow。

## 暫不投入

- 第二服務／居家清潔／多 active tasks：團隊決定只用五個水電修繕 branches 展示。
- 寫入 MCP Tool、Gateway、RDS、正式網站 auth、點數與 production 真人客服。
- 新 Kiro 規劃；現有 `.kiro` artifacts 保留作比賽協作證據，不再延長規劃階段。
