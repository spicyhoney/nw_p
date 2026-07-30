# HANDOFF：居家修繕 Agent（nw_p）

## 最新狀態（2026-07-30）

- PR #11、#12 已合併；本階段從 `main@9177a880cad503bcf71e515c90a4f3672e46fc5a`
  建立 `codex/consumer-accessibility-ui`。
- 已完成消費者人工 Checklist、高齡／無障礙 UI 與桌機／手機驗收。
- PR #13 review 指出的 checklist 反序競態已修正。等待對方重新 review，
  人類決定是否合併，Agent 不得自行 merge。

> 更新：2026-07-30　更新者：Codex
> 規則：全文 ≤150 行；只描述現在；接手者先讀本檔，再按連結讀細節。

## 1. 本階段完成內容

- 三項人工 Checklist：服務需求、地點、諮詢內容與希望時段。
- `suggested` 只表示系統已有資料可核對；`checked` 只能由使用者修改。
- 新增 `PUT /api/sessions/{id}/checklist/{service|location|consultation}`。
- checked 保存在 process-local Web session；rerender／GET polling 不會消失。
- response sequence／session generation 阻擋 stale SessionView；最後 GET 對齊伺服器。
- checklist 寫入／同步期間鎖住 Reset 與其他 session mutation。
- 失敗會恢復 checkbox、解除 disabled，並把焦點放回原項目。
- 未建案 Reset 清空同一 session；已有案件時前端建立全新 session。
- 原生 checkbox 支援 click／Space，另補 Enter、label、checked 與 live feedback。
- 放大文字／表單，互動有效目標約 `44x44px` 以上，高對比 focus、合理 Tab 順序。
- error、loading、派單與廠商狀態使用 `alert/status` live region。
- 狀態不只用顏色；支援 `prefers-reduced-motion`，色彩以 WCAG AA 為目標。
- `1280x720` 與 `390x844` 不會水平捲動或遮住派單／返回按鈕。

詳細文件：

- [消費者 Checklist 與無障礙 UI](docs/consumer-accessibility.md)
- [Web README](src/home_repair_agent/web/README.md)
- [派單／接單契約](docs/provider-workflow.md)
- [實作索引](docs/implementation-index.md)
- [系統與 AWS 架構](docs/architecture.md)

## 2. Checklist 邊界

```text
User click / Space / Enter
  -> idempotent PUT
  -> WebSessionService session lock
  -> process-local checked state
  -> reject stale response -> final GET sync
  -> SessionView -> rerender / polling

Agent / Tool structured result -> suggested=true
Agent / Model / MCP -X-> checked
```

- Checklist 是 UI 核對紀錄，不是案件事實，也不取代派單 `confirmed=true`。
- Checklist 不進 memory／PostgreSQL CaseWorkflowRepository，程式重啟仍會消失。
- Checklist API 沒有暴露為 MCP Tool；四個 MCP Tools 仍全部唯讀。

## 3. 五項不可破壞規則

1. 消費者明確確認後才建立案件。
2. 只有指派廠商可讀案件。
3. pending 廠商只能看到遮罩聯絡資料。
4. accepted 才揭露完整 synthetic contact；rejected 永不揭露。
5. 案件寫入具確認、冪等、稽核與合法原子狀態轉換。

本階段沒有修改 `CaseWorkflowService`、案件 repository、migration 或四個 MCP Tools。

## 4. 驗證證據

- focused：`40 passed, 6 skipped, 3 subtests passed`。
- 本機完整：`105 passed, 15 skipped, 43 subtests passed`。
- 15 skipped 是本機未提供 `TEST_DATABASE_URL`；PR #13 必須以 PostgreSQL CI 補跑。
- 受影響檔案 Ruff／format、compileall、JavaScript syntax、diff check 通過。
- 全 repo Ruff 仍有既有 data-cleaning 規則債；本 PR 沒有修改那些檔案。

瀏覽器 Mock mode（無 HF token）：

- 桌機 `1280x720`、手機 `390x844` 均完成需求、Checklist、表單、媒合與派單。
- pending 實測 `masked / 0912***678`；accepted 才為 `full / 0912-345-678`。
- 兩尺寸均無水平 overflow；可見控制有效目標無小於 `44x44px`。
- 手機確認區返回與派單按鈕皆完整可見；返回會關閉確認區。
- focus 為 3px 高對比藍框；初始／媒合／確認畫面 AA 掃描零 finding。
- reduced-motion 實測生效；桌機／手機 console 與 page error 均為 0。
- 反序 PUT 最終 UI／API 一致；寫入時 Reset 鎖定；人為 500 後狀態與焦點復原。

## 5. 現有雙端與持久化

- 消費者完成 structured consultation、synthetic 媒合、選擇與明確確認派單。
- `/provider` 可依 synthetic Demo 身分看指派案件並接受／拒絕。
- pending 遮罩 contact；accepted 建立 `SYN-ORDER-*` 並揭露 synthetic contact。
- `WEB_CASE_REPOSITORY=memory|postgres`；PostgreSQL repository 全程 async。
- PostgreSQL 保存 case、order、idempotency 與 audit，不保存聊天／Checklist。
- SQL 只在 repository；FastAPI 與 MCP 是 adapter，商業規則在 Service Layer。

## 6. AI mode 與環境

- 團隊 Demo 基線仍為 Hugging Face；mock 供離線開發與 CI。
- 模型：`Qwen/Qwen3-4B-Instruct-2507`；`HF_PROVIDER=auto`。
- 沒有 `HF_TOKEN` 時不得宣稱正在跑 AI mode；本階段未跑 HF live。
- 本機：消費者 `http://127.0.0.1:8080/`；廠商 `http://127.0.0.1:8080/provider`。
- token、`DATABASE_URL`、AWS 金鑰、`.env` 與真實個資不得提交。

## 7. 尚未完成

- Web session／Checklist 持久化、保存同意、保存期限與刪除機制。
- 正式 authentication／authorization、廠商帳號、RBAC 與多租戶隔離。
- 時段保留、排程衝突、付款、通知、照片、語音與正式個資處理。
- RDS／AWS／Bedrock／AgentCore、公網 HTTPS 與正式監控。
- 正式螢幕閱讀器人工測試；目前是語意、鍵盤、對比與瀏覽器驗收基線。
- 固定 HF live eval 矩陣；live 測試不進預設 CI。

## 8. 下一步

1. 推送 PR #13 checklist race 修正，等待 PostgreSQL CI 與對方重新 review。
2. 修正完成前不得 merge；是否合併永遠由人類決定。
3. 決定下一個本機功能：正式身分 adapter 或時段保留／衝突控制。
4. 取得 AWS 環境後建立 RDS，套用現有 migration，切換 repository 連線。
5. 最後替換 Bedrock／AgentCore adapters 並公開部署。

## 9. User decisions

- 2026-07-28：整合／Demo 以 HF AI mode 為基線；mock 只供離線測試。
- 2026-07-29：本機 Demo 可暫用 RAM；不做 JSON 持久化。
- 2026-07-30：PR #11、#12 已合併；下一階段先完成消費者 Checklist 與無障礙 UI。
- 是否合併 PR 永遠由人類決定；Agent 不得自行 merge。
