# 專案待辦

最後更新：2026-08-02

本檔只保留尚未完成的工作；已完成項目移至
[實作索引](docs/implementation-index.md)。狀態只使用 `Todo`、`In progress`、
`Blocked`，優先級依序為 `P0`、`P1`、`P2`。

## P0：立即風險

| ID | 狀態 | 工作 | 負責人 | 依賴 | 完成條件 |
|---|---|---|---|---|---|
| AWS-AUDIT-001 | Blocked | 登入比賽使用的 AWS 帳號，確認最終 Remote MCP Demo 沒有殘留計費資源 | 帳號持有人 | 當時的 AWS 登入權限 | AgentCore Runtime、S3 artifact、IAM role／workload identity、CloudWatch log group 皆已刪除；Billing 無非預期持續用量，留下不含 ARN／account 的確認紀錄 |

## P1：產品化缺口

| ID | 狀態 | 工作 | 負責人 | 依賴 | 完成條件 |
|---|---|---|---|---|---|
| DEPLOY-002 | Todo | 建立可重現的公開 HTTPS 部署 | 未分配 | hosting 與預算決策 | Mock Demo 可由公開 URL 開啟；secret 由平台管理；health check、部署與回滾有文件 |
| AUTH-001 | Todo | 正式登入、消費者／廠商 RBAC | 未分配 | 身分提供者與資料政策 | 使用者只能讀寫授權案件；Demo header／下拉身分不再作為權限依據 |
| PRIV-001 | Todo | 真實個資同意、加密、保存期限與刪除 | 未分配 | 法遵、KMS／secret manager、刪除政策 | 真實資料全程有同意、加密、最小揭露、到期刪除與測試 |
| SLOT-001 | Todo | 實作真實時段保留與衝突控制 | 未分配 | 真實廠商與排程來源 | 併發選擇不能超賣；保留、逾時、取消與 audit 均有測試 |
| DATA-001 | Todo | 讓 Web 唯讀查詢可切 Demo／PostgreSQL repository | 未分配 | 已載入 clean schema 的測試資料庫 | fail-fast 設定與 service／location／form／matching 契約在兩種 repository 一致 |

## P2：延伸功能

| ID | 狀態 | 工作 | 負責人 | 依賴 | 完成條件 |
|---|---|---|---|---|---|
| SESSION-001 | Todo | 持久化 Web 對話、Active Task 與人工 Checklist | 未分配 | 保存同意與刪除政策 | 可恢復獲准 session；Reset／刪除不留孤兒資料；舊回應不能覆蓋新 session |
| PROVIDER-001 | Todo | 廠商回覆、服務進度與通知 | 未分配 | 正式身分與狀態機決策 | 指派廠商可新增受控歷程，消費者可查詢且 audit 完整 |
| EVAL-001 | Todo | 建立固定 HF／Bedrock 品質與延遲評估 | 未分配 | provider 額度與測試資料政策 | 固定 synthetic cases、可重跑報告、失敗不放寬 no-guess gate |
| VOICE-002 | Todo | 完成實體台語／國語麥克風評估與可選 TTS | 未分配 | 模型授權與母語者評估 | 記錄原句、轉寫、延遲；TTS 若加入須可理解且標示模型限制 |
| SERVICE-002 | Todo | 用同一表單／Service 契約擴充第二種服務 | 未分配 | 真實產品需求與資料品質 | 不複製整套流程；新增服務有 curated schema、來源標籤、測試與安全分支 |

## 刻意不做

- 不開放寫入 MCP Tool，除非未來外部 Agent 有明確需求且能滿足確認、授權、冪等與 audit。
- 不把 synthetic 師傅、聯絡資料、時段或訂單包裝成真實商業服務。
- 不為了增加功能數量而一次支援所有主辦方服務類型；先維持可驗證的水電修繕深度。
