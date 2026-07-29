# HANDOFF：居家修繕 Agent（nw_p）

## 最新狀態（2026-07-29）

- PR #10 reviewed head `7ed7667` 已通過複審並合併至 `main`。
- merge commit：`7bca6565aaa8d27f72a0fc1bdde9045d753d0a44`。
- 派單／廠商工作台 P0 現已是 `main` 的有效基線。
- 本機：focused `30 passed, 3 subtests`；完整 `95 passed, 9 skipped, 43 subtests`。

> 更新：2026-07-29　更新者：Codex
> 規則：全文 ≤150 行；只描述現在；接手者先讀本檔，再按連結讀細節。

## 1. 目前狀態（active）

- `main` 已包含 PR #10 merge commit `7bca656`。
- 三項 review finding 與三份文件衝突均已修正並通過複審。
- 派單／廠商工作台方向與五項規則未改。
- 尚未公開部署，也未連 PostgreSQL 寫入、正式登入、Bedrock 或 AWS。

## 2. PR #10 完成內容

- 消費者完成 synthetic 媒合後，可選廠商並明確確認派單。
- 新增 `/provider` 廠商工作台：案件列表、狀態篩選、詳情、audit、接單／拒絕。
- 只有 assigned provider 能讀案件；其他 Demo provider 詳情回 404。
- pending 只回遮罩 contact；accepted 才回完整 synthetic contact；
  rejected 不揭露。
- accepted 建立 `SYN-ORDER-*`；rejected 後可改派其他未拒絕候選。
- `CaseWorkflowService` 提供 confirmation、idempotency、payload fingerprint、
  audit 與原子狀態轉換。
- 寫入由 FastAPI → Case Service 執行；LLM 與四個 MCP Tools 仍不能寫入。
- repository、案件、訂單、idempotency 與 audit 只存在目前 Python process。

主要文件：

- [派單／接單 P0](docs/provider-workflow.md)
- [Web README](src/home_repair_agent/web/README.md)
- [實作索引](docs/implementation-index.md)
- [系統與 AWS 架構](docs/architecture.md)
- [架構 SVG](docs/project-architecture-current.svg)

## 3. 五項不可破壞規則

1. 消費者明確確認後才建立案件。
2. 只有指派廠商可讀案件。
3. pending 廠商只能看到遮罩聯絡資料。
4. accepted 才揭露完整 synthetic contact；rejected 永不揭露。
5. 所有寫入必須有確認、冪等、稽核與合法原子狀態轉換。

## 4. Review finding 修正

### P1：派單時重新驗證時段

- `CaseSubmissionCommand` 與 `CaseWorkflowService.submit_case()` 均檢查
  `Asia/Taipei +08:00`、結束晚於開始及最長 12 小時。
- 真正建案時再次要求 `preferred_start > now`；已成功建立的冪等重試仍回原結果。
- `WebSessionService.dispatch_case()` 會提早拒絕表單完成後已過期的時段。
- 測試涵蓋「媒合後時間才過期」及繞過 model validation 的三種錯誤時段。

### P2：狀態 filter 與案件詳情一致

- `provider.js` 以同一份 visible cases 同步列表與 selection。
- 目前案件被 filter 排除時，改選第一筆可見案件；沒有結果時清空詳情與操作按鈕。
- polling／案件狀態轉換後也會重新套用相同規則。

### P2：App factory workflow 一致

- 同時注入 `session_service` 與不同的 `case_workflow` 時立即丟出 `ValueError`。
- 合法注入一律由消費者與 provider API 共用 `session_service.case_workflow`。
- 已補 factory regression test。

### Merge conflicts

- 已整合 `HANDOFF.md`、`docs/implementation-index.md`、
  `src/home_repair_agent/web/README.md`。
- 保留 HF live eval、AI mode、HF token 安全設定與 provider workflow 現況。
- 不再使用「服務廠商後台尚未完成」或「正式 Demo 使用 mock」等過時敘述。

## 5. 驗證證據

- Workflow + Web focused：`30 passed, 3 subtests passed`。
- 完整 suite：`95 passed, 9 skipped, 43 subtests passed`。
- 9 skipped 是缺測試 PostgreSQL／選配 live 環境；不是 regression。
- 受影響 Python：Ruff 與 format check 通過。
- `app.js`、`provider.js`：Node syntax check 通過。
- FastAPI TestClient 仍有第三方 `httpx2` deprecation warning；不影響結果。
- 原 PR 瀏覽器驗收：桌機 `1280x720`、手機 `390x844` 雙端流程通過。
- 本輪另驗收 filter 切換時不保留被排除案件的詳情／決策按鈕。

## 6. 現有邊界

- Web session 與寫入資料重啟即消失；沒有真的保留師傅時段。
- `X-Demo-Provider-Id` 與廠商選單只是 synthetic 身分模擬，不是 authentication。
- 聯絡人、手機、地址、廠商、案件與訂單全部是 synthetic。
- 自由文字仍可能含真實個資；UI 有警告，但沒有萬用個資偵測器。
- 四個 MCP Tools 全部唯讀；沒有寫入 MCP Tool。
- Case Service 沒有 SQL；正式 SQL 必須放 PostgreSQL repository。
- token、密碼、AWS 金鑰、`.env` 與含 token transcript 不得提交。

## 7. AI mode 與環境

- 團隊整合／Demo 基線：Hugging Face AI mode；mock 只供離線測試。
- 模型：`Qwen/Qwen3-4B-Instruct-2507`；`HF_PROVIDER=auto`。
- `HF_TOKEN` 是每位開發者自己的 account token，不是模型專屬 token。
- 專案不會自動載入 `.env`；啟動前需載入 token 並設定：

  ```powershell
  $env:HF_MODEL_ID = 'Qwen/Qwen3-4B-Instruct-2507'
  $env:HF_PROVIDER = 'auto'
  $env:WEB_MODEL_PROVIDER = 'huggingface'
  .\.venv\Scripts\python.exe -m home_repair_agent.web.app
  ```

- 消費者：`http://127.0.0.1:8080/`；廠商：`http://127.0.0.1:8080/provider`。
- 沒有自己的 token 時，不得宣稱正在跑 AI mode。

## 8. AWS 持久化決策（不可遺漏）

- 目前 process-local repository 只供本機 Demo；暫時保留是團隊接受的取捨。
- **不要**新增 JSON 檔案作為派工單持久化或開機載入方案。
- 只把現有程式部署到 AWS 不會自動持久化；Lambda、ECS 或容器重啟仍會遺失 RAM 資料。
- 下一階段先在本機實作 PostgreSQL transaction repository，保存 case、order、
  idempotency 與 audit，並建立 migrations、constraints 及整合測試。
- 正式環境以連線設定切換到 RDS PostgreSQL／相容 Aurora PostgreSQL；FastAPI 與
  `CaseWorkflowService` 契約維持不變，以 dependency injection 替換 repository。
- SQL 只能放 repository；密碼、RDS URL、AWS 金鑰與 `.env` 不得提交。

## 9. 下一步

1. 現在先完成 PostgreSQL case workflow repository、migration 與整合測試。
2. 保留 process-local repository 作為本機快速 Demo 的顯式選項。
3. 再完成消費者介面與高齡／無障礙體驗。
4. 取得 AWS 環境後建立 RDS，套用相同 migration 並切換連線設定。
5. 將 Demo provider header 換成正式登入與 RBAC。
6. 加入時段保留及同一師傅排程衝突控制。
7. 把單一 HF live case 擴成固定案例矩陣；live 測試不進預設 CI。
8. 最後替換 Bedrock／AgentCore adapters 並公開部署。

## 10. User decisions

- **2026-07-28**：人工 HF Demo 良好；整合／Demo 以 HF AI mode 為基線。
- **2026-07-29**：每 3 小時檢查 PR；技術 finding 可直接修正，以本檔交接。
- **2026-07-29**：本機 Demo 可暫用 RAM；不做 JSON 持久化。PostgreSQL
  repository 現在先實作，RDS／相容 Aurora 等取得 AWS 環境後再連接。
- 是否合併 PR 永遠由人類決定；Agent 不得自行 merge。
