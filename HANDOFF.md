# HANDOFF：居家修繕 Agent（nw_p）

> 更新：2026-07-27　更新者：Codex
> 規則：全文 ≤150 行；只描述現在；接手者先以本檔為準，再按連結讀細節。

## 1. 目前狀態

PR #9 已以 merge commit `ec6d741` 合併至 `main`；本機唯讀 Web vertical
slice 與 review 修正均已進入穩定基線，並在最新 `main` 重跑安裝、測試與啟動
smoke。尚未公開部署。
單一固定 HF Web live case 已通過；多案例 eval、Bedrock/AWS、案件寫入與
服務廠商後台尚未完成。

## 2. 目前完成

- 新增 FastAPI `session / message / form / reset` API。
- 新增 deterministic `SessionView`，保存 service、location、form answers、
  preferred window、candidates；LLM reply 不作 business state。
- 需求文字仍由 `AgentRunner` 呼叫前三個 MCP Tools；表單通過伺服器驗證後，
  `WebSessionService` 才呼叫第四個 `match_service_providers` Tool。
- 動態表單支援 `single_select` radio、文字欄位與 `datetime_range`。
- 希望時段由 UI 送出 `Asia/Taipei +08:00` ISO 8601；後端重驗時區、順序與
  12 小時上限，模型不得自行換算相對日期。
- 消費者頁含進度、聊天、表單、候選卡、Tool 查詢紀錄與 reset。
- 桌面三欄、手機三分頁；候選與素材皆明確標示 synthetic。
- 前端不直接呼叫 HF／Bedrock、MCP、Service Layer、SQL 或資料庫。
- CSP、no-store、禁止 iframe、`textContent` rendering 與安全 API errors 已加入。
- 專案專用修繕 workbench 圖由 built-in ImageGen 產生並壓成 30 KB WebP。
- Review 修正：Web 對話只向模型公開前三個 Tool；模型即使自行要求媒合也會被
  Runner 白名單與 session workflow 雙層拒絕。
- 媒合完成後拒絕重送表單；reset 原地清空 record，保留同一把 session lock。
- 前端送出前檢查必填 radio／multi-select／文字與時段，伺服器仍會再次驗證。

## 3. 驗證證據

- `tests/test_web_app.py`：13 passed；Web + Agent loop focused：27 passed。
- 完整 suite：77 passed、10 skipped、40 subtests passed。
- 最新 `main` `ec6d741` 另重跑 `pip install -e ".[app,dev]"` 成功，
  `tests/test_web_app.py` 為 13 passed。
- `python -m home_repair_agent.web.app` 啟動後，`/api/health` 與首頁均回 200；
  smoke 結束後已關閉 process，8080 沒有留下本次背景服務。
- 真實 HF Web live：`Qwen/Qwen3-4B-Instruct-2507`、`provider=auto`，
  synthetic「台北市大安區水龍頭漏水」於 7.41 秒依序成功呼叫
  `search_services`、`resolve_location`、`get_consultation_form`，得到
  水電修繕、臺北市大安區與 `demo_repair_form_v1`，狀態為 `awaiting_form`。
- Windows PowerShell 將 here-string pipe 給 Python 時可能把中文變成 `?`；
  live harness 必須用 UTF-8 檔案或 Unicode escape，且先驗證輸入 code points。
- 10 skipped 是缺少測試 PostgreSQL／選配 live 環境時依設計略過。
- 受影響檔案 Ruff、format、compileall、JavaScript syntax、diff check 通過。
- 全 repo Ruff 仍會指出既有 `data_cleaning` 格式／lint debt；本分支未擴改。
- 真實瀏覽器桌面與 `390x844` 均完成：
  需求 → 三個 Tool → 動態表單 → `+08:00` 時段 → 媒合 Tool → 兩位候選。
- 手機無水平 overflow，三分頁與 reset 正常；全流程無 console error。
- FastAPI TestClient 有第三方 `httpx2` 遷移 deprecation warning；不影響結果。
- live case 只向 HF hosted inference 傳送 synthetic 文字與唯讀 Tool schema；
  token 未輸出、未提交。

主要文件：

- `src/home_repair_agent/web/README.md`
- `docs/implementation-index.md`
- `docs/architecture.md`
- `tests/test_web_app.py`

## 4. 下一步

1. 把單一 HF live case 擴成可重跑的固定案例矩陣：正常、模糊服務、缺地點、
   多地點與 provider error；live 測試不得進預設 CI。
2. 決定決賽 Demo hosting，提供可公開存取的 HTTPS 網址。
3. P1 前先設計 case submission contract：
   明確確認、idempotency key、授權、交易與 audit event。
4. contract 完成後才做最小服務廠商後台：案件列表、摘要與狀態。

## 5. 團隊分工

- 使用者／Codex：Web P0、FastAPI session/view model、資料與 Service/MCP 邊界。
- 組員：模型固定 eval、語音、Bedrock/AWS 部署準備。
- 共同：驗收 Web 對話與 Agent/MCP 串接、決定 Demo 文案與部署方案。
- 不要讓兩邊同時修改 `src/home_repair_agent/web/`；需調整先在 PR 討論。

## 6. 現有架構

已完成：

- B+ 資料清洗、PostgreSQL schema/loader 與資料來源政策。
- 四個唯讀 Service／MCP Tools 與 `matching_v1` synthetic 媒合。
- Mock Agent loop、terminal Demo、Hugging Face hosted adapter。
- 本機唯讀 FastAPI/Web P0。

尚未完成：

- PostgreSQL session persistence。
- 案件、時段保留、確認媒合與訂單寫入。
- 最小服務廠商後台。
- Bedrock adapter、AgentCore、RDS、S3 與 CloudWatch。
- 語音與公開部署。

## 7. 不可破壞邊界

- 原始資料不可覆寫；不明代碼與斷裂關聯不可猜測。
- synthetic 資料必須保留來源標籤，不得宣稱是真實合作廠商。
- Agent 不得執行任意 SQL，只能呼叫白名單 Service／MCP Tool。
- FastAPI 與 MCP 是 adapter；商業規則放 Service，SQL 放 repository。
- token、密碼、AWS 金鑰、`.env` 與含 token 的 transcript 不得提交。
- 目前四個 MCP Tools 全部唯讀；沒有確認、冪等、授權與 audit 前不得加寫入。
- Hugging Face 是外部 hosted API，不是本機模型；不得靜默 fallback。
- 不要 force-push 或刪除隊友分支。

## 8. 環境快照

- Repo：`https://github.com/spicyhoney/nw_p`
- PR #9 merge baseline：`ec6d741`；目前 `main` 另含本段驗證紀錄。
- 目前本機分支：`main`。
- Python：`>=3.11`；本機驗證使用 `.venv`。
- Web：`http://127.0.0.1:8080`，預設 `WEB_MODEL_PROVIDER=mock`。
- 本機 `.env` 受 `.gitignore` 保護，含 HF live 所需設定；不得顯示或提交。
- Web session 只在記憶體；process 重啟即消失。
- 本機 Demo repository 不連 PostgreSQL、AWS，也不寫資料。

## 9. 授權狀態

- 使用者與組員已確認 Web P0 分工並授權開始實作。
- 已授權本分支完成實作、測試、文件與 PR。
- 未授權啟用寫入 MCP Tool、建立正式案件、部署 AWS 資源或提交任何金鑰。
