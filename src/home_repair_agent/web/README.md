# Web：引導式單一修繕對話與服務廠商 Demo

## 1. 做了什麼

這個模組把單一修繕任務的引導式對話、既有唯讀 Agent／MCP 查詢、照片流程、
synthetic 媒合與受控案件 workflow 組成 FastAPI Web Demo。

消費者端 `/` 現在支援：

- 每個 process-local session 同時只有一個 Active Task，不會在背景拆成多個案件。
- 以 deterministic、closed-world router 提出五種 `repair_form_v1` 分支建議：
  `faucet_leak`、`toilet_issue`、`pipe_issue`、`electrical_issue`、`other`。
- 分支只是一項 proposal；不論信心高低，使用者都必須透過
  `POST /branch/confirm` 明確確認。確認時後端會重新驗證 canonical
  `service_id=17`、`repair_form_v1` 版本及分支適用性，不能採信模型文字或舊畫面。
- 一則訊息含多項需求時只顯示受控 alternatives，請使用者先選一項，不自動建立
  多任務。切換分支也要再次確認，並清除舊分支答案、舊圖片分析及有衝突的地點。
- 分支確認前可跨輪補齊縣市、行政區與問題描述；這些文字只作後續唯讀查詢輸入，
  不會提前驗證 service／location。matching 前若明確更正地點，舊 location/form
  provenance 與 summary identity 會失效，重新查證後仍須重新提交表單與確認摘要。
- 依已確認分支投影表單。`water_shutoff` 只適用於 `faucet_leak`、
  `toilet_issue`、`pipe_issue`；`electrical_issue` 不會在 form、summary、matching
  answers 或 case payload 中帶入該欄位；`other` 必須填寫具體
  `issue_description`。
- `POST /form` 只驗證並保存答案／`+08:00` 希望時段，產生版本化、可修改且
  尚未確認的摘要；不會立即媒合。
- 只有使用者明確確認最新摘要版本後，`POST /summary/confirm` 才呼叫既有
  `match_service_providers`。舊版本摘要不能觸發媒合或派單。
- 選擇 synthetic 候選並再次確認後，才透過 `CaseWorkflowService` 建立
  `pending_provider` 案件；既有 confirmation、idempotency、transaction 與 audit
  邊界維持不變。建案後表單與摘要鎖定。
- 保留人工 Checklist、鍵盤操作、live region、清楚 focus、reduced-motion 與
  polling／stale response 防護基線。對話欄只有一個內容捲動區，composer 是獨立
  底列，不會被 media、表單或摘要推出可操作範圍。
- Bedrock 模式可透過既有 `BedrockModelClient` 執行文字對話與 process-local 唯讀
  MCP Tools；請求由 production pacing wrapper 保持至少 1.1 秒的啟動間隔。
- HF 模式可上傳一張 JPEG／PNG／WebP synthetic／公開測試圖片。既有安全儲存、
  VLM 建議、人工修正／確認及服務目錄重驗管線不變；圖片會綁定 active branch，
  移除圖片會使現有摘要版本失效。
- HF 模式的 composer 可用同一顆按鈕開始／停止最多 30 秒的台語或國語錄音；錄音
  只在使用者停止後送到外部 Hugging Face Space 的 Breeze-ASR-26，回傳文字只會填入
  既有輸入框，必須由使用者確認／修改後自行送出，不會自動建案、媒合或派單。

廠商端 `/provider` 維持既有受控流程：

- 切換兩個 synthetic Demo 廠商身分，只列出指派給目前身分的案件。
- 依 `pending_provider / accepted / rejected` 篩選並查看授權後的案件詳情。
- 待回覆時只見遮罩 contact；明確接受後才顯示完整 synthetic contact，並建立
  `SYN-ORDER-*`。拒絕不會建立訂單。
- pending／accepted 的指派廠商可查看案件圖片；未指派或 rejected 一律 404。
- 頁面使用自然垂直捲動與單欄 reflow；案件 answers 只顯示受控中文 metadata，
  `preferred_time` 不重複顯示原始值，日期與區間固定以 `Asia/Taipei` 呈現。

案件狀態機與授權詳情請見
[服務廠商派單／接單](../../../docs/provider-workflow.md)；無障礙與前端競態基線請見
[消費者 Checklist 與無障礙 UI](../../../docs/consumer-accessibility.md)。
引導式對話的需求範圍見
[guided-home-repair-conversation requirements](../../../.kiro/specs/guided-home-repair-conversation/requirements.md)。

刻意沒做：

- 沒有 AWS hosting、AgentCore、RDS、S3 adapter 或公開部署；Bedrock 目前僅作為
  既有 provider-neutral port 的文字模型 adapter。
- 本功能沒有改動 `AgentRunner`、`ToolClient` 或四個唯讀 MCP Tool schemas，也沒有
  新增寫入 MCP Tool。
- 沒有擴充到居家清潔等其他服務類別；canonical service 仍只有水電修繕
  `service_id=17`。
- 沒有多任務拆分、跨次持久化或多個 Active Task；Web session 重啟後不能恢復。
- 沒有正式 PII、authentication、authorization、RBAC 或多租戶隔離；只允許
  synthetic contact 與 synthetic／公開測試圖片。
- 沒有正式時段保留、付款、通知或取消／退款流程；媒合候選不代表已保留時段。
- 沒有把 Web 唯讀服務資料切到 PostgreSQL；`WEB_CASE_REPOSITORY=postgres` 只切換
  案件、訂單、idempotency 與 audit repository。

## 2. 為什麼這樣設計

FastAPI route 只做 HTTP validation 與 adapter。主要責任分工如下：

- `backend/repair_conversation.py`：五分支 deterministic proposal、安全提示及
  closed-world contract；只提議，不修改 workflow。
- `WebSessionService`：單一 Active Task、分支確認、表單投影、摘要版本、照片綁定、
  Agent／Tool 編排及 matching gate。
- `AgentRunner`：在分支確認後執行既有 model-to-read-tool loop；模型仍不能把服務、
  地點、表單或候選當作業務事實。
- `ReadServiceLayer`：服務、行政區、表單與媒合規則。
- `CaseWorkflowService`：派單確認、冪等、授權、audit 與案件狀態轉換。
- `DemoCaseWorkflowRepository`／`PostgresCaseWorkflowRepository`：memory 或 async
  PostgreSQL 案件 persistence adapter。
- `LocalMediaStorage`：實際解碼、重新編碼移除 metadata、安全相對路徑與刪除。
- `HuggingFaceVisionClient`：外部 VLM 結構化建議；不診斷、不選分支、不媒合、不派單。
- `HuggingFaceGradioSpeechToTextClient`：驗證短音訊並呼叫受限的 `hf.space` ASR
  endpoint；只回傳 provider-neutral transcript，不保存錄音、不送出對話、不 fallback。

分支 router 與表單 applicability 都是可測試的結構化規則，不由 prompt 或前端字串
決定。分支確認時再查一次服務目錄與表單，可以阻擋 stale proposal、錯誤 service ID、
錯誤 form version 或不包含該分支的 form。地點仍由既有 `resolve_location` 查詢；缺
縣市、互相矛盾、無結果或不唯一時必須補問，不能預設臺北市。

表單保存與媒合刻意拆成兩個 API。每次修改表單都產生新的摘要版本，只有最新版本的
明確確認能進入 matching；模型文字、Checklist 或舊摘要都不能代替這個 gate。派單再
使用另一個明確按鈕，並沿用 `CaseWorkflowService`，避免把副作用搬進 LLM、MCP 或
JavaScript。

## 3. 輸入、輸出與資料流

### 分支提議、確認與補問

```text
Browser POST /messages
  -> deterministic route_repair_branch
  -> one pending branch or controlled alternatives
  -> safety reminder / safety stop when applicable
  -> no service, form, matching or case mutation yet

Browser POST /branch/confirm (confirm=true)
  -> WebSessionService revalidates service_id=17
  -> revalidates repair_form_v1 version and branch applicability
  -> AgentRunner + existing read-only tools collect service/location/form
  -> missing or ambiguous county/city/district is asked again
  -> projected branch form becomes editable
```

若訊息同時包含水龍頭與插座等多項需求，只能從 alternatives 選一項。已有 confirmed
branch 時，新訊息最多建立 replacement proposal；明確確認切換後才清除舊分支答案、
不適用圖片分析與衝突地點。無衝突的共用資料可保留，但送出前仍需重新核對。

### 表單、摘要、媒合與派單

```text
Browser POST /form
  -> validate projected fields, branch applicability and +08:00 future window
  -> save answers only
  -> create summary version N (confirmed=false)
  -> user may edit and save again as version N+1

Browser POST /summary/confirm with latest version + confirm=true
  -> revalidate current task and summary version
  -> match_service_providers read-only MCP Tool
  -> synthetic candidates or explicit empty result
  -> no case and no time reservation yet

Browser POST /dispatch with provider + confirmed=true + idempotency key
  -> CaseWorkflowService
  -> memory or PostgreSQL CaseWorkflowRepository transaction
  -> pending_provider + audit
  -> form/summary become immutable for this audited case
```

### 圖片建議（HF only）

```text
Browser explicit external-processing consent + multipart image
  -> LocalMediaStorage validates actual JPEG/PNG/WebP, <= 8 MiB
  -> normalize/re-encode and strip metadata under MEDIA_ROOT
  -> HuggingFaceVisionClient returns suggestion only
  -> image is associated with the current active branch
  -> user edits and explicitly confirms
  -> search_services revalidates canonical service_id=17
  -> confirmed relative image path + structured analysis enter case on dispatch
```

圖片分析失敗會移除本次新檔並回傳安全錯誤，不會 fallback 到 Mock。未確認建議不能
設定服務或觸發 matching／dispatch。Browser 只取得 `has_image`／受控圖片 endpoint，
不會取得 server `image_path`。上傳、替換、確認或刪除圖片都會使先前摘要失效；切換
branch 時不沿用不相符的圖片分析。

### 台語／國語語音輸入（HF only）

```text
Browser 使用者按「語音」並允許麥克風
  -> MediaRecorder 最多錄製 30 秒
  -> 使用者再按一次停止
  -> POST multipart audio + explicit external-processing consent
  -> 後端驗證 MIME、檔案簽章與 6 MiB 上限
  -> configurable hf.space Gradio endpoint
  -> MediaTek-Research/Breeze-ASR-26 transcript
  -> 只回填原本 composer textarea
  -> 使用者確認／修改後才自行按送出
```

預設端點是社群維護的 `LiaoZike/breeze-asr-api`，只作非個資黑客松 Demo；模型本身為
Apache-2.0，但 Space 沒有 SLA。兩筆相鄰的 live probe 總耗時為 52.586 秒與
48.276 秒，其中 upload／enqueue 合計僅 1.636 秒與 2.061 秒，外部 queue＋inference
佔 50.950 秒與 46.215 秒。因此前端每 15 秒顯示實際等待時間與 45–60 秒預期，並可
取消等待後改用文字；取消只保證結果不套用到對話，不宣稱能撤回已送至 Space 的音訊。
本功能不假裝是本機上傳變慢，也不送額外暖機請求。錄音只在記憶體與外部 Space 暫存，不寫入
`MEDIA_ROOT`、PostgreSQL、案件、audit 或 log。Mock／Bedrock 模式不顯示語音按鈕，
外部失敗會明確回報且不改用 Mock。這不是安全關鍵逐字稿；漏電、冒煙等字詞仍必須由
使用者確認後，才會進入既有文字安全規則。

### 廠商接受／拒絕

```text
Assigned provider explicit decision
  -> POST /api/provider/cases/{case_id}/decision
  -> CaseWorkflowService
  -> one transaction updates case, order, audit and idempotency
  -> accepted + SYN-ORDER-* + full synthetic contact
     or rejected + unavailable contact
  -> consumer polling reflects terminal state
```

## 4. API

| Method | Path | 用途 |
|---|---|---|
| `GET` | `/api/health` | 回傳模式與服務健康狀態 |
| `POST` | `/api/sessions` | 建立單一 Active Task 的 consumer session |
| `GET` | `/api/sessions/{id}` | 取得最新 task、摘要、候選與案件狀態 |
| `POST` | `/api/sessions/{id}/messages` | 提出或補充一項水電需求；只產生受控 proposal／補問 |
| `POST` | `/api/sessions/{id}/branch/confirm` | 明確確認初始或 replacement branch，並重驗 service/form |
| `POST` | `/api/sessions/{id}/form` | 保存表單與希望時段，產生新版可修改摘要；不媒合 |
| `POST` | `/api/sessions/{id}/summary/confirm` | 明確確認最新摘要版本後才執行媒合 |
| `POST` | `/api/sessions/{id}/dispatch` | 明確確認並以 idempotency key 建立 pending 案件 |
| `POST` | `/api/sessions/{id}/image` | 每次明確同意後上傳並執行 HF 圖片分析 |
| `GET` | `/api/sessions/{id}/image` | 讀取目前 session 私有圖片預覽 |
| `DELETE` | `/api/sessions/{id}/image` | 未建案前移除圖片並使摘要版本失效 |
| `POST` | `/api/sessions/{id}/image/confirm` | 人工更正／確認圖片建議並重驗 service_id=17 |
| `POST` | `/api/sessions/{id}/speech/transcribe` | HF-only 短錄音轉文字；不修改 session、不送出訊息 |
| `PUT` | `/api/sessions/{id}/checklist/{key}` | 人工勾選／取消單一核對項目 |
| `POST` | `/api/sessions/{id}/reset` | 未建案前重設；已有 audit 時拒絕清除 |
| `GET` | `/api/provider/identities` | 列出 synthetic Demo 身分 |
| `GET` | `/api/provider/cases` | 列出目前身分被指派的案件 |
| `GET` | `/api/provider/cases/{case_id}` | 取得依授權投影的案件詳情 |
| `GET` | `/api/provider/cases/{case_id}/image` | 指派且非 rejected 廠商讀取案件圖片 |
| `POST` | `/api/provider/cases/{case_id}/decision` | 明確接受或拒絕案件 |

廠商 API 以 `X-Demo-Provider-Id` 傳入模擬身分。正式環境不得把這個 header 當成
authentication。

## 5. 安全與資料邊界

- canonical service 固定為已驗證目錄中的 `service_id=17`；router、模型與 Browser
  都不能生成或更換 service ID。
- `repair_form_v1` 五分支都需明確確認；branch confirm 會重驗 service、form key、
  version、欄位 applicability 與分支 option。
- 不完整地點不猜測。`我家水龍頭一直漏水，在大安區` 只會停在缺縣市補問，必須再
  提供完整縣市＋行政區。
- 多 intent 不拆成多 task；使用者先選一項。branch switch 未確認前不能沿用新分支，
  確認後清除舊分支資料及衝突地點。
- `water_shutoff` 只允許水龍頭、馬桶、水管三分支；電路分支的 form、summary、
  matching answers 與 case payload 全部排除。
- `other` 不能只填「其他」；必須提供可理解的具體 `issue_description`。
- 單獨的「冒火花」會顯示保守安全提醒，但固定 synthetic E2E 仍可在使用者確認後
  繼續；包含「漏電、觸電、起火、火災、瓦斯、人身危險、焦味」時立即停止一般
  matching／dispatch，不能確認分支、表單或摘要。系統不假裝已通知真人或保證救援。
- 表單保存不等於同意媒合；只有最新摘要版本的 `confirm=true` 能呼叫 matching。
  圖片變更會使摘要失效；建案或已有 audit 後不能改寫表單。
- 寫入仍需 dispatch `confirmed=true`、合法候選、idempotency key 與
  `CaseWorkflowService` 狀態驗證；相同 key 不得搭配不同 payload。
- 所有廠商、聯絡資料、案件與訂單都標示 `synthetic`。目前不得收真實門牌、電話、
  Email、臉孔、證件或可識別住家照片。
- 圖片每次外送 Hugging Face 前都要明確同意；binary 不進 PostgreSQL、audit、log
  或 API model。拒絕 traversal、symlink、偽 MIME、損壞檔與超過 8 MiB。
- 語音錄製必須由使用者手勢啟動；只接受實際簽章相符的 WebM／Ogg／MP4／WAV／MP3，
  最大 6 MiB、30 秒。每次停止錄音即代表本次明確外送，UI 會持續揭露外部處理；
  transcript 不自動送出。一般 `HF_TOKEN` 不會轉送到社群 Space，private Space 只能用
  獨立的 `HF_ASR_TOKEN`。
- pending provider 只見遮罩 contact；只有已指派且 accepted 的 synthetic provider
  可見完整 synthetic contact。未指派或 rejected 圖片請求回 404。
- Agent 只看三個查詢 Tool；matching 由摘要確認後端呼叫。四個 MCP Tools 仍唯讀，
  Browser 不直連模型、MCP 或資料庫，route 不含 SQL。
- API response 使用 `Cache-Control: no-store`，頁面有 CSP、`nosniff`、frame 與
  referrer headers；前端以 `textContent` 顯示模型／Tool 文字。

## 6. 執行方式

安裝：

```powershell
python -m pip install -e ".[app,dev]"
```

使用 deterministic Mock Model：

```powershell
home-repair-web
```

預設網址：

```text
消費者端：http://127.0.0.1:8080/
廠商端：http://127.0.0.1:8080/provider
```

也可直接啟動：

```powershell
python -m home_repair_agent.web.app
```

Windows 的 psycopg async 需要 Selector event loop；上述兩個專案入口會自動設定。
Windows PostgreSQL 模式不要改用裸 `python -m uvicorn ...` 啟動。Linux／AWS 不受此
限制。

| 變數 | 預設 | 用途 |
|---|---|---|
| `WEB_MODEL_PROVIDER` | `mock` | `mock`、`huggingface` 或 `bedrock` |
| `WEB_CASE_REPOSITORY` | `memory` | `memory` 或 `postgres`；只影響 case workflow |
| `DATABASE_URL` | 無 | PostgreSQL case 模式必填；不得提交正式密碼 |
| `WEB_HOST` | `127.0.0.1` | Web bind host |
| `WEB_PORT` | `8080` | Web port |
| `HF_TOKEN` 等 | 見 `.env.example` | Hugging Face 模式；缺少時 fail fast |
| `BEDROCK_REGION` | 無 | Bedrock 模式必填，例如 `us-west-2` |
| `BEDROCK_MODEL_ID` | 無 | Bedrock 模式必填，例如 `amazon.nova-lite-v1:0` |
| `AWS_PROFILE` | AWS SDK 預設鏈 | 本機可指定 named profile；不得寫入程式或提交 credential |
| `HF_VL_MODEL_ID` | `Qwen/Qwen3-VL-30B-A3B-Instruct` | 圖片分析模型 |
| `HF_VL_PROVIDER` | `auto` | 圖片模型的 Inference Provider |
| `MEDIA_ROOT` | `var/media` | 私有本機圖片根目錄；不進 Git |
| `HF_ASR_SPACE_URL` | `https://liaozike-breeze-asr-api.hf.space` | HF-only 語音 Demo endpoint；只允許 HTTPS `*.hf.space` |
| `HF_ASR_API_NAME` | `transcribe` | Gradio named endpoint |
| `HF_ASR_AUDIO_PARAMETER` | `audio` | Gradio 音訊參數名稱 |
| `HF_ASR_MODEL_ID` | `MediaTek-Research/Breeze-ASR-26` | 公開回應與證據使用的模型標籤 |
| `HF_ASR_TIMEOUT_SECONDS` | `90` | upload／queue／inference timeout |
| `HF_ASR_EXTRA_INPUTS_JSON` | `{}` | 其他 endpoint 必要的純量參數；最多 10 個 |
| `HF_ASR_TOKEN` | 無 | 只供 private ASR Space；絕不隱含重用 `HF_TOKEN` |

`WEB_MODEL_PROVIDER=huggingface` 會把對話與 Tool schema 傳到 hosted provider；沒有
必要設定時不會靜默切回 Mock。`WEB_MODEL_PROVIDER=bedrock` 會使用
`BEDROCK_REGION`／`BEDROCK_MODEL_ID` 建立文字 client，並可由本機標準 AWS credential
chain（例如 `AWS_PROFILE`）取得授權，同樣不會 fallback。圖片分析仍只在 Hugging Face
模式可用，Bedrock 文字模式不會建立或改用 HF VLM。使用者每次勾選外部處理同意並
上傳圖片時，正規化後的圖片 bytes 也會送到所選 HF VLM provider。請只使用
synthetic／公開測試內容。

### HF 多輪 synthetic eval（明確 opt-in）

`scripts/huggingface_web_eval.py` 會以與 Web 相同的 `WebSessionService`、
`AgentRunner`、三個模型可見唯讀 Tools 及 process-local MCP transport，逐案執行七個
synthetic 文字情境：完整需求、跨輪地點、地點更正、問題更正、模糊問題、多地點及
provider failure。它不測圖片 bytes，也不會建立案件、媒合、派單或持久資源。

腳本沒有預設 CI 入口，也不會隱含送出 hosted request；必須由人類建立一枚新的、未曾
貼在聊天／文件／截圖中的 HF token，只放在目前 shell，並加上 `--live`：

```powershell
$env:HF_TOKEN = "<new shell-only token>"
$env:HF_MODEL_ID = "Qwen/Qwen3-4B-Instruct-2507"
$env:HF_PROVIDER = "auto"
python scripts/huggingface_web_eval.py --live
```

缺 token 或錯誤設定會 fail fast，不會切到 Mock。第七案使用可重現的 timeout 注入驗證
相同 no-fallback 邊界，不會故意讓 hosted provider 超時。輸出的
`hf_web_eval_v1` JSON 只含 case label／字數、stop reason、Web session state、受控 Tool
參數及結果狀態；不含 raw user／assistant messages、token、完整 provider payload、Tool
完整結果或本機路徑。任一品質／契約 check 失敗時，仍先輸出完整七案的去識別 evidence，
再以 non-zero exit code 結束；失敗不可改寫成通過。

## 7. 測試與實際結果

主要回歸位置：

- `tests/test_repair_conversation.py`：五分支、multi-intent、unsupported 與安全提示。
- `tests/test_repair_form_configuration.py`：`repair_form_v1` 版本與欄位 applicability。
- `tests/test_web_app.py`：branch／summary gates、版本失效、no-guess、兩條 HTTP E2E、
  dispatch／provider workflow。
- `tests/test_media_web.py`：圖片 active branch、summary invalidation 與案件圖片權限。
- `tests/test_consumer_accessibility.py`、`tests/test_media_frontend.py`：HTML／JS 靜態契約。
- `tests/test_huggingface_speech.py`、`tests/test_speech_web.py`、
  `tests/test_voice_frontend.py`：ASR adapter、no-fallback API、HF-only 與 composer 回填契約。
- `tests/test_checklist_concurrency.js`：前端反序回應與 session generation regression。

常用驗證命令：

```powershell
python -m pytest tests/test_repair_conversation.py tests/test_repair_form_configuration.py -q
python -m pytest tests/test_web_app.py tests/test_media_web.py -q
python -m pytest tests/test_huggingface_web_eval.py tests/test_huggingface_model.py tests/test_huggingface_vision.py -q
python -m pytest -q
python .\scripts\hf_asr_latency_probe.py <public-or-synthetic-audio.mp3>
node --check .\src\home_repair_agent\web\static\app.js
node --check .\src\home_repair_agent\web\static\provider.js
node .\tests\test_checklist_concurrency.js
```

2026-08-02 HF 語音輸入 POC 驗證：

- 新增 adapter／API／前端 focused：`17 passed, 10 subtests passed`。
- 連同 PR #20 Web／圖片／viewport focused：
  `114 passed, 2 skipped, 58 subtests passed`。
- 完整 pytest：`265 passed, 21 skipped, 132 subtests passed`；21 個 skip 是條件式環境
  未提供，不算成功證據。
- Changed-file Ruff／format、compileall、Node syntax、PR #20 checklist concurrency、
  `git diff --check` 通過。
- 真瀏覽器 `1280x720`：HF 語音按鈕 `64x48`，composer、輸入框與送出按鈕均可見，
  無水平 overflow／console error。手機與真麥克風仍需人工作最後 smoke；自動化沒有錄取
  現場環境聲音，避免把非 synthetic 音訊送到外部。
- Breeze-ASR-26 live：公開教育部短音訊「這條水管破去矣」辨識為「這條水管破了」。
  兩筆相鄰 probe 為 52.586 秒與 48.276 秒；queue＋inference 分別佔 50.950 秒與
  46.215 秒，證明瓶頸在外部執行面而非 19 KB／17 KB 上傳。probe 只輸出 phase、耗時、
  HTTP status 與 transcript 字數，不輸出音訊或逐字稿。這證明閉環可行，不代表
  production latency／品質。

2026-08-01 已記錄的驗證證據：

- 預算與緊急程度是選填的共用 answers，不是 `repair_form_v1` topics；未回答時保存
  `skipped`，也接受 `declined_to_answer`。`urgency` 只接受 `normal`、`urgent` 或上述
  answer states，且兩者都不改 `matching_v1` 權重。
- focused guided tests：`59 passed, 50 subtests passed`。
- 完整 pytest：`162 passed, 18 skipped, 102 subtests passed`。18 個 skip 是環境條件
  未提供，不算成功證據。
- Node.js syntax 與 checklist concurrency regression 通過。
- 本功能異動 Python 檔案的 diagnostics、Ruff check、Ruff format check，以及
  `git diff --check` 通過。
- 全庫 Ruff check 已執行，但仍有 15 個既有、位於非本功能檔案的 finding；全庫
  Ruff format check 也受既有未格式化檔案阻擋。兩者保留為 baseline debt，不能宣稱
  全庫 Ruff／format 通過，也沒有在本功能順手修改那些檔案。
- 本輪沒有執行真瀏覽器 smoke，因此不能把 HTTP／Node／source-string tests 宣稱為
  guided flow 的 browser 驗收。

兩條固定 FastAPI HTTP E2E 都由實際 API 走到
`summary -> matching -> dispatch_pending`：

1. `我家水龍頭一直漏水，在大安區`：初次不猜縣市；補上`臺北市大安區`後繼續，
   最終 case 保留適用的 `water_shutoff`。
2. `家裡插座一直冒火花`：先顯示安全提醒；補上完整地點後繼續，且
   `electrical_issue` 的 form、summary、matching answers 與 case payload 全程沒有
   `water_shutoff`。

這些 E2E 使用 synthetic repository／contact，不是 hosted model 品質、正式服務商、
正式時段保留或瀏覽器可用性的證據。

## 8. 下一階段

1. 以真瀏覽器在桌機與手機重跑上述 faucet／electrical 兩條 guided flow，包含鍵盤、
   focus、live region、錯誤復原、overflow 與 console 檢查。
2. 若要支援多任務，另行設計每個 task 的 ID、狀態、確認、取消、持久化與授權；不要
   在目前單一 Active Task 上直接堆疊。
3. 決定 Web session／summary 的保存、刪除與同意政策，再考慮跨次 persistence。
4. 加入正式 authentication／authorization、RBAC、多租戶隔離及 PII 加密／保存政策
   後，才評估真實 contact 或住家照片。
5. 另行設計正式時段保留、通知、取消／退款及競態控制；目前 matching 仍只讀。
6. 由人審核安全文案、官方緊急聯絡與真人出口；目前 safety stop 不代表已完成真人
   轉接。
7. AWS、公開部署或外部 MCP Gateway 僅在帳號、Region、權限、預算與驗收方式確認後
   實作 adapter；維持既有 domain／service contracts。
