# 修繕小隊長｜Repair Captain AI 作品集版本整理紀錄

最後更新：2026-08-03

## 做了什麼

- 以比賽最終 `integration/final-demo` 為基線，而不是桌機上較舊的 `main`。
- 將 README 改為可在數分鐘內理解、啟動與驗證的作品集入口。
- 新增消費者與廠商工作台實際 Mock Demo 截圖，並人工驗收手機版。
- 將 HANDOFF、TASKS、實作索引與架構從比賽現場狀態改為賽後長期維護狀態。
- 移除失效 tunnel、PID、筆電絕對路徑與「正在等隊友」等不可重現資訊。
- 清除全庫 Ruff／format baseline debt，並讓 CI 檢查完整 Python tree 與全部 JavaScript。
- 修正 `.env.example` 重複與過時設定，補齊實際 adapter 環境變數。

## 刻意沒做什麼

- 沒有把比賽期間的 live AWS endpoint、ARN、account 或 credential 放進 repo。
- 沒有把 synthetic 廠商、時段、聯絡資料或訂單改寫成真實商業資料。
- 沒有為了作品集外觀新增未驗證功能、正式登入、付款、通知或第二服務。
- 沒有合併較早、與最終 Remote MCP 架構重複的 direct-code AgentCore POC。

## 為什麼這樣整理

履歷專案的第一要求是可信：訪客應能從 `main` 看見真正最終程式，用 Mock 模式在沒有
雲端憑證時重現核心流程，並從測試與文件分辨「目前可執行」、「過去 live 驗證」和
「未來構想」。因此整理重點是單一穩定入口、證據可追溯、限制誠實，而不是增加功能數。

## 資料流與安全邊界

```text
Web -> FastAPI -> AgentRunner -> ModelClient
                        -> ToolClient -> read-only MCP -> Service Layer -> Repository
Web confirmation -> CaseWorkflowService -> memory / PostgreSQL -> audit
```

- 模型沒有資料庫連線，也沒有寫入 Tool。
- FastAPI／MCP 只做 adapter，商業規則留在 Service Layer。
- 原始資料不覆寫；不明 mapping 隔離；synthetic 明確標示。
- hosted provider 設定缺失時 fail closed，不偷偷切回 Mock。

## 驗證結果

- 帳號持有人已於 2026-08-03 完成比賽 AWS 帳號的資源與 Billing 收尾檢查。
- 完整 pytest：`327 passed, 17 skipped, 168 subtests passed`。
- 全庫 Ruff check 與 format check：passed。
- Python compileall、JavaScript syntax、Checklist／media Node regressions：passed。
- `1280x720` 與 `390x844` 的消費者／廠商 Mock 頁面無水平 overflow。
- Markdown 相對連結、SVG XML、secret patterns 與 `git diff --check`：passed。

條件式 skip 不算 live provider 或 PostgreSQL 成功；外部整合證據仍以各 ENGINEER LOG
和遮罩報告為準。

## 待辦與風險

- 正式部署、登入／RBAC、真實個資政策、時段鎖與 notification 都仍是產品化工作。
- 外部 HF／AWS provider 的可用性、費用與延遲不由本 repo 保證。
