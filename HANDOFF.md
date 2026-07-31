# HANDOFF：居家修繕 Agent（nw_p）

## 最新狀態（2026-08-01）

- `MEDIA-001` 已由使用者授權直接整合至 `main`（未開 PR）；完成 HF 圖片分析、私有
  local media storage、人工確認、case memory／PostgreSQL 欄位、消費者／廠商 UI
  與授權圖片 endpoint。
- `TASKS.md` 已把 MEDIA-001 移至本檔與實作索引，並保留使用者要求的「為什麼需要」欄位。
- Terra subagent 的 PR-ready review 為 `Approve`；完整本機驗證與 live HF smoke 均通過。
- 格式修正 `5410e75` 後，[PostgreSQL CI Run #16](https://github.com/spicyhoney/nw_p/actions/runs/30645834182)
  已在 PostgreSQL 16.14 套用 migration 001–003 並完成真實 repository／全套測試。

> 更新者：Codex
> 規則：全文維持 150 行內；只描述現在。

## 1. 閱讀順序

1. [專案白話指南](docs/project-guide.md)
2. [待辦清單](TASKS.md)
3. [實作索引](docs/implementation-index.md)
4. [Web README](src/home_repair_agent/web/README.md)
5. [資料政策](docs/data-policy.md)與[廠商流程](docs/provider-workflow.md)

## 2. MEDIA-001 已實作契約

消費者：

1. 只有 `WEB_MODEL_PROVIDER=huggingface` 可使用圖片分析；Mock 明確不可用，失敗不
   fallback。
2. 一個 session／case 最多一張實際可解碼 JPEG／PNG／WebP，輸入上限 8 MiB。
3. 使用者須勾選同意把圖片送至 Hugging Face；Demo 只允許 synthetic／公開測試圖。
4. 圖片重新編碼移除 metadata，寫到 `MEDIA_ROOT`（預設 `var/media`、不進 Git）。
5. VLM 只回服務查詢、摘要、安全提醒、confidence、uncertain；不產生 service ID、
   不建案、不派單。
6. 結果可修改；人工確認後仍須由既有 `search_services` 唯讀 Tool 唯一驗證，才會
   影響後續表單／媒合。未確認時訊息、表單與派單均被擋下。
7. 未建案圖片在 remove／reset／上傳或 VLM 失敗時清除。

廠商／資料：

- case memory 與 PostgreSQL 保存 server-relative `image_path` 及已確認
  `image_analysis`；圖片 bytes 不進 DB、audit、log 或例外。
- Browser API 只回 `has_image`，不回內部 `image_path`。
- 指派廠商在 pending／accepted 可用帶 `X-Demo-Provider-Id` 的受控 GET 讀圖片；
  unassigned／rejected／missing 回 404。response 為正確 MIME、inline、no-store。
- 圖片目前保留原 `sessions/{session_id}/{media_id}.{ext}` 相對 key，即使建案後也不
  移動；reset 在建案後已被禁止，因此不會誤刪案件圖片。未來 object storage adapter
  可在同一 `MediaStorage` contract 下改成 case key。
- MCP 仍是四個唯讀 Tools；沒有新增寫入或圖片 MCP。

## 3. 主要檔案

- `agent/huggingface_vision.py`：HF VLM adapter 與嚴格 JSON contract。
- `backend/media_storage.py`：Pillow 解碼／正規化、safe path、讀取與刪除 rollback。
- `backend/case_models.py`、`case_services.py`、`postgres_case_repository.py`：案件欄位。
- `sql/migrations/003_case_media_contract.sql`：nullable path／JSONB 與 constraints。
- `web/service.py`、`web/app.py`、`web/models.py`：流程、API 與授權。
- `web/static/`：消費者上傳／確認與廠商授權預覽。
- `tests/test_media_*.py`、`tests/test_huggingface_vision.py`：新測試。
- `docs/ENGINEER_LOG-media-*.md`：四個子工作與主整合紀錄。

## 4. 執行設定

```powershell
$env:WEB_MODEL_PROVIDER = "huggingface"
$env:HF_TOKEN = "<只放 shell，不寫進 repo>"
$env:HF_MODEL_ID = "Qwen/Qwen3-4B-Instruct-2507"
$env:HF_VL_MODEL_ID = "Qwen/Qwen3-VL-30B-A3B-Instruct"
$env:HF_PROVIDER = "auto"
$env:HF_VL_PROVIDER = "auto"
python -m home_repair_agent.web.app
```

- 對話模型與 VLM 是兩個獨立 model ID，共用 `HF_TOKEN`。
- 已用無個資、無 EXIF 的 synthetic 水漬圖片完成 live smoke；
  `Qwen/Qwen3-VL-30B-A3B-Instruct` 搭配 `novita` 與 `auto` 都成功。原先的 Qwen 2.5 VL
  對此帳號已啟用的 provider 不可用。部署時仍需重跑，因 provider availability 可能改變。

## 5. 不可破壞邊界

1. 消費者明確確認後才建立案件；模型不得自行媒合／派單。
2. 只有指派廠商可讀案件；pending contact 遮罩，accepted 才完整揭露，rejected
   永不揭露 contact 或圖片。
3. 寫入具確認、冪等、audit、合法狀態轉換；SQL 只在 repository。
4. 四個 MCP Tools 維持唯讀；Agent 不得改 Checklist 或建立案件。
5. synthetic 必須標示；不得上傳／記錄真實個資、token、絕對路徑或圖片 bytes。
6. Demo header 不是正式 authentication；正式圖片功能前仍需 auth、加密、保存期限與
   刪除政策。

## 6. 驗證與下一步

- MEDIA focused Web／a11y：`40 passed`。
- VLM／storage／case focused：`33 passed, 7 skipped, 12 subtests passed`。
- JavaScript `node --check` 與受影響 Python Ruff 通過。
- 本機完整：`134 passed, 18 skipped, 52 subtests passed`；compileall、兩支
  JavaScript `node --check`、受影響 Python Ruff 與 `git diff --check` 通過。
- Terra subagent 獨立 PR-ready review 結論為 `Approve`，focused `65 passed, 8 skipped,
  12 subtests passed`，full suite 結果相同，secret pattern scan 無命中。
- 全 repo Ruff 仍有 data-cleaning baseline 的 16 個既有 finding；本輪未擴張修改。
- PostgreSQL CI Run #16：`151 passed, 1 skipped, 52 subtests passed`；Ruff／format、
  compileall、JavaScript 與 checklist concurrency 均通過，migration 003 已真實驗證。
- 瀏覽器 `1280x720`／`390x844`：無水平 overflow／console error；圖片同意列
  44px；Mock 清楚停用；廠商圖片使用授權 fetch 與受限尺寸。

下一步：

1. 從 `TASKS.md` 選下一個單一任務；目前未授權部署、AWS 寫入或正式個資處理。

## 7. 既有團隊決策

- 本機案件可暫用 RAM；不做 JSON 案件持久化。
- Hugging Face 是 hosted model 基線；Mock 只供離線測試與 CI。
- Kiro 加分暫不投入；寫入 MCP 只有外部 Agent 真有需求才設計。
- AWS／Bedrock／AgentCore／RDS 等待主辦方帳號、Region、權限與額度。
- 是否合併 PR 永遠由人類決定。
