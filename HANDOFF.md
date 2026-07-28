# HANDOFF：居家修繕 Agent（nw_p）

> 更新：2026-07-29　更新者：Codex
> 規則：全文 ≤150 行；只描述現在；接手者只讀本檔也能開始下一步。

## 1. 目前狀態（active）

- 穩定 `main`：`479e48f`；HF AI mode 與 Web P0 已完成。
- PR #10 `codex/provider-dashboard-p0`：Draft，reviewed head `547a3e2`。
- 正式 review 結論：**Changes requested**；目前有 3 個技術 finding 與
  3 個 merge conflicts，尚不可合併。
- PR #10 的派單／廠商工作台方向正確；不需要重做。

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

## 3. Review findings（active open issues）

### P1：派單時沒有重新驗證時段

- `FormSubmitRequest`／`WebSessionService.submit_form()` 只在表單送出時驗證未來時間；
  使用者若稍後才確認派單，`dispatch_case()` 與 `CaseWorkflowService.submit_case()`
  不會再次檢查。
- 實測 `CaseWorkflowService` 接受「已在昨天開始、長達 24 小時」的時段並建立
  `pending_provider` 案件。
- 修正：在案件建立當下驗證 `preferred_start > now`、結束晚於開始、
  最長 12 小時與 `Asia/Taipei +08:00`；補「表單完成後時間已過期」測試。
- 檔案：`backend/case_models.py`、`backend/case_services.py`、`web/service.py`。

### P2：狀態 filter 可能保留不相符的案件詳情

- `provider.js` 切換 filter 時只重畫左側列表；右側仍可能顯示被篩掉的 pending
  案件與接受／拒絕按鈕。
- 修正：filter 改變後，若目前案件不在結果內，清空詳情或改選第一筆可見案件；
  補前端狀態／瀏覽器驗收。
- 檔案：`src/home_repair_agent/web/static/provider.js`。

### P2：App factory 可注入兩個不同 workflow

- 同時傳入 `session_service=A`、`case_workflow=B` 時，消費者派單寫入 A，
  provider API 卻讀 B；實測兩端不共享 workflow。
- 修正：禁止不一致組合，或在有 `session_service` 時一律使用
  `session_service.case_workflow`；補 factory 測試。
- 檔案：`src/home_repair_agent/web/app.py`、`tests/test_web_app.py`。

### Merge conflicts

- PR #10 從 `ec6d741` 開出，尚未包含 `e486499`、`479e48f`。
- 衝突：`HANDOFF.md`、`docs/implementation-index.md`、
  `src/home_repair_agent/web/README.md`。
- 解衝突時必須保留本檔的 reviewed SHA／findings、HF live eval、AI mode 與
  HF token 安全設定；不可退回「正式 Demo 使用 mock」。

## 4. 驗證證據（reviewed SHA `547a3e2`）

- Focused：`26 passed`。
- 完整 suite：`90 passed, 10 skipped, 40 subtests passed`。
- Ruff、format、`node --check`（`app.js`、`provider.js`）與
  `git diff --check` 通過。
- 10 skipped 是缺 PostgreSQL／選配 live 環境；不是本 PR regression。
- PR 文件的 `91 passed, 9 skipped` 是另一個 optional 環境結果。
- 測試全綠不解除第 3 節 findings；P1 已用額外 probe 重現。

## 5. 組員下一步（第一個 command 可直接執行）

1. 執行 `git switch codex/provider-dashboard-p0`。
2. 執行 `git pull --ff-only origin codex/provider-dashboard-p0`。
3. 執行 `git fetch origin`，再執行 `git merge origin/main`。
4. 依第 3 節修正三項 finding 與三個文件衝突，不要另開 PR。
5. 驗證：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest -q tests/test_case_workflow.py tests/test_web_app.py
   .\.venv\Scripts\python.exe -m pytest -q
   node --check src/home_repair_agent/web/static/app.js
   node --check src/home_repair_agent/web/static/provider.js
   git diff --check
   ```

6. 更新 HANDOFF 的 PR head SHA／測試結果，push 同一分支，將 PR #10 改成
   Ready for review，再通知我們複審；**不要自行 merge**。

## 6. 人類決策門檻（active）

- 上述三項都是技術修正，現在不需要人類產品決策。
- 若修正會改變個資揭露、正式 authentication、AWS 權限、產品 scope、
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
