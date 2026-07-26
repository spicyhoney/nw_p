# AI 協作入口

這份文件是給新加入的隊友與 AI 的最短閱讀入口。請先理解現況與資料邊界，
再修改程式；不要只根據單一聊天紀錄推測架構。

## 專案目標

本專案參加 2026 雲湧智生黑客松「AI 生活管家」命題。MVP 是居家水電修繕
Agent：理解需求、確認行政區、取得諮詢表單、追問缺漏資訊、媒合服務商，最後
在使用者確認後建立訂單。

## 建議閱讀順序

1. [README.md](README.md)：MVP、技術棧與目前狀態。
2. [docs/implementation-index.md](docs/implementation-index.md)：哪些功能已完成、
   程式與驗證放在哪裡。
3. [docs/architecture.md](docs/architecture.md)：本機、MCP、FastAPI 與 AWS 的關係。
4. [docs/data-policy.md](docs/data-policy.md)：正式、隔離、人工設定與模擬資料規則。
5. [docs/data-dictionary.md](docs/data-dictionary.md)：PostgreSQL schema 與欄位。
6. 正在修改之模組內的 `README.md`。

## 不可破壞的邊界

- 原始資料不可覆寫；不明代碼與斷裂關聯不可猜測。
- 模擬資料必須帶來源標籤，不得偽裝成主辦方真實資料。
- Agent 不得執行任意 SQL，只能呼叫範圍明確的 Service / MCP Tool。
- MCP 與 FastAPI 只做 adapter；商業規則放在 Service Layer，SQL 放在 repository。
- 個資、密碼、AWS 金鑰、資料庫密碼與 `.env` 不得提交。
- 寫入操作必須有確認、冪等與稽核設計；目前三個 MCP Tools 全部唯讀。

## 每次實作的文件規則

每個功能必須有一份模組 `README.md` 或 `docs/` 實作文件，並更新
[實作索引](docs/implementation-index.md)。至少說明：

1. 做了什麼，以及刻意沒做什麼。
2. 為什麼採用這個設計。
3. 輸入、輸出與完整資料流。
4. 安全、資料來源與不可猜測邊界。
5. 測試方式與實際結果。
6. 待辦、風險與下一階段。

新文件可從 [實作文件模板](docs/implementation-template.md) 開始。若程式契約、
環境變數或執行方式改變，要在同一個 commit 更新文件，不能只寫 PR 說明。

## 驗證原則

- 先跑受影響模組測試，再跑完整測試。
- MCP 必須透過 MCP Client/Server 協定測試，不能只直接呼叫 Python 函式。
- PostgreSQL 整合測試只在提供測試資料庫時執行；不得連正式資料庫。
- 完成標準、測試命令與最近結果以
  [實作索引](docs/implementation-index.md)及各模組 README 為準。
