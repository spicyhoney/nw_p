# 專案待辦

最後更新：2026-08-01

本檔只記錄尚未完成的工作。已完成且通過驗證的功能移到
[實作索引](docs/implementation-index.md)，目前接手狀態則記在
[HANDOFF](HANDOFF.md)。

## 使用規則

- 優先級：`P0` 是下一個可交付基線，`P1` 是核心產品補強，`P2` 是延伸體驗。
- 狀態只使用 `Todo`、`In progress`、`Blocked`。
- 開始工作前先填負責人；完成條件沒有證據時不得結案。
- PR 合併後，從本檔移除已完成項目，並把程式、文件與驗證結果寫入實作索引。
- 任務範圍或優先級改變時，同一個 commit 必須更新本檔。

## P0

| ID | 狀態 | 工作 | 為什麼需要 | 負責人 | 依賴 | 完成條件 |
|---|---|---|---|---|---|---|
| DATA-001 | Todo | 讓 Web 讀取路徑可選 Demo 或 PostgreSQL repository | 目前 Web 的查詢資料來自 Demo repository；接上清洗後的正式資料才能證明相同服務契約可支援持久化與部署環境 | 未分配 | 已載入 clean schema 的測試 PostgreSQL | `WEB_READ_REPOSITORY=demo\|postgres` 有明確 fail-fast 設定；Web 的服務、地點、表單與媒合能以相同契約查 PostgreSQL |
| AI-001 | Todo | 建立固定 Hugging Face 評估矩陣 | 單次成功對話不足以判斷模型可靠度；固定案例可在更換 prompt、模型或 provider 時發現服務辨識與 Tool Call 的退化 | 未分配 | 可用的 `HF_TOKEN`，live 測試不進預設 CI | 正常需求、模糊服務、缺地點、多地點及 provider error 都有可重跑結果與報告 |
| MCP-001 | Todo | 驗證 Streamable HTTP MCP 的外部 Client 流程 | 命題希望智慧管家可調用生活服務工具；目前的 process-local MCP 尚不能證明 Kiro、AgentCore 或其他外部 Client 能互通 | 未分配 | 本機 PostgreSQL 測試資料庫或受控測試 repository | 外部 Client 完成 `tools/list` 與四個唯讀 `tools/call`，留下命令、結果與錯誤案例 |
| AWS-001 | In progress | 完成 AgentCore Gateway／外部 MCP 整合 | Bedrock ModelClient 與可清理的 AgentCore Runtime synthetic POC 已完成；仍需證明受管理 Runtime 可透過標準 MCP endpoint 使用既有工具 | Codex（Runtime POC） | MCP-001、Gateway 權限與部署架構決策 | Runtime 證據已留存且資源已清除；Gateway 可呼叫標準 MCP endpoint，且不改既有 Agent／Tool／Service 契約 |
| DEPLOY-001 | Todo | 準備可攜式部署與公開 HTTPS 操作手冊 | 評審與組員需要在非開發者電腦上重現 Demo；部署、健康檢查與回復程序可避免作品只在單一本機可用 | 未分配 | 最終部署環境規格 | 有可重跑的 build、啟動、health check、環境變數與 rollback 步驟；不提交密鑰 |

## Blocked

| ID | 狀態 | 工作 | 為什麼需要 | 負責人 | 阻擋條件 | 完成條件 |
|---|---|---|---|---|---|---|
| AWS-002 | Blocked | 建立正式 RDS、IAM 與 CloudWatch 雲端基線 | Runtime POC 已驗證短效執行角色與安全 log，但正式案件仍需要持久化、最小權限與可觀測性 | 未分配 | AWS 網路、角色、RDS 建立權限與正式部署架構 | migration 可套用至測試 RDS，服務採最小權限，log 不含密鑰或完整個資 |

## P1

| ID | 狀態 | 工作 | 為什麼需要 | 負責人 | 依賴 | 完成條件 |
|---|---|---|---|---|---|---|
| AUTH-001 | Todo | 正式登入、廠商帳號、RBAC 與多租戶隔離 | Demo header 可被任意冒用；真實案件含聯絡資訊與廠商資料，必須確認身分並隔離不同消費者及廠商的資源 | 未分配 | 身分提供者與部署環境決策 | 不再信任 Demo header；消費者與廠商只能讀取授權資源 |
| SCHED-001 | Todo | 保留服務時段並處理排程衝突 | 現有媒合只推薦可用時段，尚未形成真正預約；鎖定與衝突處理可避免同一廠商時段被重複承接 | 未分配 | 正式廠商與時段資料模型 | 並行預約同一時段只能有一筆成功，失敗可安全重試 |
| PRIV-001 | Todo | 真實個資加密、同意、保存期限與刪除政策 | 目前只使用 synthetic contact；改收真實姓名、電話與地址前，必須具備同意、加密、最少保存與可刪除機制 | 未分配 | 金鑰管理與法遵決策 | AES-256-GCM／查詢 hash、金鑰不入庫，且保存與刪除行為有測試及文件 |
| PROVIDER-001 | Todo | 廠商回覆紀錄與服務進度追蹤 | 目前廠商接受案件後流程即停止；命題要求案件狀態、回覆與服務進度，這項功能才能形成接案後的服務閉環 | 未分配 | 狀態機與通知範圍決策 | 指派廠商可新增受控回覆與進度，消費者可查看完整歷程 |

## P2

| ID | 狀態 | 工作 | 為什麼需要 | 負責人 | 依賴 | 完成條件 |
|---|---|---|---|---|---|---|
| SESSION-001 | Todo | 持久化 Web 對話與人工 Checklist | 目前重啟程式就會遺失諮詢進度；經使用者同意後保存 session，才能支援跨次追蹤且仍可完整刪除 | 未分配 | 保存同意、期限與刪除政策 | 程式重啟後可恢復已同意保存的 session，Reset／刪除不留下孤兒資料 |
| A11Y-001 | Todo | 語音操作與使用者字級偏好 | 命題允許語音互動並鼓勵高齡友善；語音與可調字級能降低輸入及閱讀門檻，但需防止轉寫錯誤與版面破壞 | 未分配 | 語音服務與隱私決策 | 語音轉寫須回顯確認；字級設定在桌機與手機不造成 overflow |
| FORM-001 | Todo | 擴充更多服務類型的彈性諮詢表單 | 命題涵蓋餐廳、購物與社區服務；只有修繕表單尚不足以證明系統能依場景產生真正彈性的留資流程 | 未分配 | 第二個服務場景決策與可信資料 | 至少一個非修繕服務可完成服務辨識、專屬表單與安全結束流程 |

## 暫不投入

- Kiro 加分：團隊目前決定不投入，不建立回溯性或不實的使用紀錄。
- 寫入 MCP Tool：只有 Lumine one 或其他外部 Agent 確定需要完整建案時，才另開
  任務設計確認、身分、冪等、稽核及最小權限；現有四個 Tool 維持唯讀。
