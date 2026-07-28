# HANDOFF：居家修繕 Agent（nw_p）

> 更新：2026-07-29　更新者：Codex
> 規則：全文 ≤150 行；只描述現在；接手者只讀本檔也能開始下一步。

## 1. 目前狀態（active）

- PR #10 `codex/provider-dashboard-p0`：Ready for review；reviewed head
  `7ed7667a7512f800d1e746c789ccb32bad964dce`。
- 正式 review 結論：**Approve**；先前 3 個 finding 與 3 個 merge conflicts
  均已修正，沒有新的 actionable finding。
- GitHub 顯示 Open、Ready to merge、無 base conflict；0 checks、0 reviews／留言，
  目前等待 `y-row` 的 requested review。
- Agent 不得自行 merge；下一步只剩人類決定是否接受並合併 PR #10。

## 2. PR #10 已完成內容（active）

- 消費者完成 synthetic 媒合後，可選廠商並明確確認派單。
- 新增 `/provider` 廠商工作台、案件列表／詳情、接單、拒絕與重新派單。
- pending 聯絡資料遮罩；accepted 才揭露完整 synthetic contact 並建立
  `SYN-ORDER-*`；rejected 不揭露。
- `CaseWorkflowService` 已有確認、冪等、audit 與 process-local 狀態轉換。
- 寫入由 FastAPI → Case Service 執行；LLM 與四個 MCP Tools 仍不能寫入。
- repository、案件、訂單與 audit 只存在目前 Python process，重啟即消失。
- `X-Demo-Provider-Id` 只是 synthetic 身分模擬，不是 authentication。

主要文件：

- `docs/provider-workflow.md`
- `src/home_repair_agent/backend/case_services.py`
- `src/home_repair_agent/web/app.py`
- `src/home_repair_agent/web/static/provider.js`
- `tests/test_case_workflow.py`
- `tests/test_web_app.py`

## 3. Review findings（resolved）

### P1：派單時重新驗證時段

- `CaseSubmissionCommand` 與 `CaseWorkflowService.submit_case()` 均檢查
  `Asia/Taipei +08:00`、結束晚於開始、最長 12 小時。
- 真正建案時再次要求 `preferred_start > now`；已成功建立的冪等重試仍回原結果。
- `WebSessionService.dispatch_case()` 也會提早拒絕媒合後才過期的時段。

### P2：狀態 filter 與案件詳情一致

- `provider.js` 用同一份 visible cases 同步列表與 selection。
- 目前案件被 filter 排除時，改選第一筆可見案件；沒有結果時清空詳情與操作按鈕。
- polling 與案件狀態轉換後也會重新套用相同規則。

### P2：App factory workflow 一致

- 同時注入 `session_service` 與不同 `case_workflow` 時立即丟出 `ValueError`。
- 合法注入一律由消費者與 provider API 共用 `session_service.case_workflow`。
- 已補 factory regression test。

### Merge conflicts

- 已整合 `HANDOFF.md`、`docs/implementation-index.md`、
  `src/home_repair_agent/web/README.md`。
- HF live eval、AI mode、HF token 安全設定與 provider workflow 均保留。

## 4. 驗證證據（reviewed SHA `7ed7667`）

- Focused：`30 passed, 3 subtests passed`。
- 完整 suite：`94 passed, 10 skipped, 43 subtests passed`。
- 10 skipped：1 個缺本機 organizer/NLSC dataset，9 個缺
  `TEST_DATABASE_URL`／`psycopg`；不是本 PR regression。
- 受影響 Python 的 Ruff／format、compileall、`app.js`／`provider.js`
  Node syntax、`git diff --check` 均通過。
- 全 repo Ruff 仍會指出未受本 PR 影響的既有 `data_cleaning` lint debt。
- PR 作者環境為 `95 passed, 9 skipped`，差異是 optional dataset 是否存在。
- GitHub 沒有 CI checks；上述結果是本機對 PR merge-ready head 的實測。

## 5. 下一步

1. 人類／組員查看 PR #10 reviewed head `7ed7667` 與本檔結論。
2. 若接受此 review，**由人類合併 PR #10**；Agent 不得代為 merge。
3. 合併後雙方執行 `git switch main`、`git pull --ff-only origin main`。
4. 在最新 `main` 重跑 focused tests，確認派單與 provider workflow。
5. 下一個工程 P1：PostgreSQL case／order／idempotency／audit migrations 與
   repository；開始前先確認正式 authentication／RBAC 與 AWS 權限。

## 6. 人類決策門檻（active）

- 當前唯一待決策事項：是否合併 PR #10。
- 後續若會改變個資揭露、正式 authentication、AWS 權限、產品 scope、
  寫入型 MCP 或是否接受風險，立即停止，只提出一個決策問題等待使用者。
- 是否合併 PR 永遠由人類決定；Agent 不得自行 merge。

## 7. 不可破壞邊界（active）

- synthetic 資料須保留來源標籤，不得宣稱是真實合作廠商。
- Agent 不得執行任意 SQL；FastAPI/MCP 是 adapter，規則放 Service，
  SQL 放 repository。
- token、`.env`、AWS 金鑰與含 token transcript 不得提交或輸出。
- 四個 MCP Tools 保持唯讀；未授權寫入 MCP、正式案件或 AWS 部署。
- 不要 force-push、reset、刪除或覆蓋隊友修改。

## 8. AI mode 與環境（active）

- 團隊整合／Demo 基線：Hugging Face AI mode；mock 只供離線測試。
- 模型：`Qwen/Qwen3-4B-Instruct-2507`；`HF_PROVIDER=auto`。
- `HF_TOKEN` 是每位開發者自己的 account token，不是模型專屬 token。
- 專案不會自動載入 `.env`；啟動前需把 `HF_TOKEN` 載入目前 shell，再設：

  ```powershell
  $env:HF_MODEL_ID = 'Qwen/Qwen3-4B-Instruct-2507'
  $env:HF_PROVIDER = 'auto'
  $env:WEB_MODEL_PROVIDER = 'huggingface'
  .\.venv\Scripts\python.exe -m home_repair_agent.web.app
  ```

- Web：`http://127.0.0.1:8080/`；provider：`http://127.0.0.1:8080/provider`。
- 沒有自己的 token 時，不得宣稱正在跑 AI mode。

## 9. User decisions（active）

- **2026-07-28**：人工 HF Demo 結果良好；整合／Demo 以 HF AI mode 為基線。
- **2026-07-29**：每 3 小時檢查新／更新 PR；需要人類決策時停止，否則
  完成 review／授權內小修正並以 HANDOFF 交代組員下一步。
