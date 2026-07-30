# 專案待辦

最後更新：2026-07-30

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

| ID | 狀態 | 工作 | 負責人 | 依賴 | 完成條件 |
|---|---|---|---|---|---|
| DOC-001 | In progress | 建立專案地圖、文件分工與真實 backlog | Codex | 無 | 專案指南、架構圖、HANDOFF、索引及歷史文件標記經 review 後合併 |
| DATA-001 | Todo | 讓 Web 讀取路徑可選 Demo 或 PostgreSQL repository | 未分配 | 已載入 clean schema 的測試 PostgreSQL | `WEB_READ_REPOSITORY=demo|postgres` 有明確 fail-fast 設定；Web 的服務、地點、表單與媒合能以相同契約查 PostgreSQL |
| AI-001 | Todo | 建立固定 Hugging Face 評估矩陣 | 未分配 | 可用的 `HF_TOKEN`，live 測試不進預設 CI | 正常需求、模糊服務、缺地點、多地點及 provider error 都有可重跑結果與報告 |
| MCP-001 | Todo | 驗證 Streamable HTTP MCP 的外部 Client 流程 | 未分配 | 本機 PostgreSQL 測試資料庫或受控測試 repository | 外部 Client 完成 `tools/list` 與四個唯讀 `tools/call`，留下命令、結果與錯誤案例 |
| DEPLOY-001 | Todo | 準備可攜式部署與公開 HTTPS 操作手冊 | 未分配 | 最終部署環境規格 | 有可重跑的 build、啟動、health check、環境變數與 rollback 步驟；不提交密鑰 |

## Blocked

| ID | 狀態 | 工作 | 負責人 | 阻擋條件 | 完成條件 |
|---|---|---|---|---|---|
| AWS-001 | Blocked | 實作 Bedrock ModelClient 與 AgentCore Gateway／Runtime adapter | 未分配 | 主辦方 AWS 帳號、Region、模型權限與額度 | Agent 透過 Bedrock 選擇既有工具，Gateway 可呼叫標準 MCP endpoint |
| AWS-002 | Blocked | 建立 RDS、IAM 與 CloudWatch 雲端基線 | 未分配 | AWS 網路、角色與 RDS 建立權限 | migration 可套用至測試 RDS，服務採最小權限，log 不含密鑰或完整個資 |

## P1

| ID | 狀態 | 工作 | 負責人 | 依賴 | 完成條件 |
|---|---|---|---|---|---|
| AUTH-001 | Todo | 正式登入、廠商帳號、RBAC 與多租戶隔離 | 未分配 | 身分提供者與部署環境決策 | 不再信任 Demo header；消費者與廠商只能讀取授權資源 |
| SCHED-001 | Todo | 保留服務時段並處理排程衝突 | 未分配 | 正式廠商與時段資料模型 | 並行預約同一時段只能有一筆成功，失敗可安全重試 |
| PRIV-001 | Todo | 真實個資加密、同意、保存期限與刪除政策 | 未分配 | 金鑰管理與法遵決策 | AES-256-GCM／查詢 hash、金鑰不入庫，且保存與刪除行為有測試及文件 |
| MEDIA-001 | Todo | 實作照片上傳、保存與影像分析 | 未分配 | Object storage 與模型決策 | 檔案型別／大小受限，私有保存，模型結果須由使用者確認 |
| PROVIDER-001 | Todo | 廠商回覆紀錄與服務進度追蹤 | 未分配 | 狀態機與通知範圍決策 | 指派廠商可新增受控回覆與進度，消費者可查看完整歷程 |

## P2

| ID | 狀態 | 工作 | 負責人 | 依賴 | 完成條件 |
|---|---|---|---|---|---|
| SESSION-001 | Todo | 持久化 Web 對話與人工 Checklist | 未分配 | 保存同意、期限與刪除政策 | 程式重啟後可恢復已同意保存的 session，Reset／刪除不留下孤兒資料 |
| A11Y-001 | Todo | 語音操作與使用者字級偏好 | 未分配 | 語音服務與隱私決策 | 語音轉寫須回顯確認；字級設定在桌機與手機不造成 overflow |
| FORM-001 | Todo | 擴充更多服務類型的彈性諮詢表單 | 未分配 | 第二個服務場景決策與可信資料 | 至少一個非修繕服務可完成服務辨識、專屬表單與安全結束流程 |

## 暫不投入

- Kiro 加分：團隊目前決定不投入，不建立回溯性或不實的使用紀錄。
- 寫入 MCP Tool：只有 Lumine one 或其他外部 Agent 確定需要完整建案時，才另開
  任務設計確認、身分、冪等、稽核及最小權限；現有四個 Tool 維持唯讀。
