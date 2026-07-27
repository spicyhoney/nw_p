# Web P0：消費者修繕 Demo

## 1. 做了什麼

這個模組把既有的本機 Agent、四個唯讀 MCP Tools 與 synthetic Demo repository
包成可操作的 FastAPI Web Demo。第一版包含：

- `POST /api/sessions`：建立記憶體內諮詢 session。
- `POST /api/sessions/{id}/messages`：把自然語言需求交給 `AgentRunner`。
- `POST /api/sessions/{id}/form`：驗證動態諮詢單與希望時段，再呼叫
  `match_service_providers` MCP Tool。
- `POST /api/sessions/{id}/reset`：清除本次記憶體狀態。
- 消費者頁：處理進度、聊天、動態表單、媒合候選、查詢紀錄與 reset。
- 桌面三欄與手機三分頁版面。

刻意沒做：

- 不建立案件、不保留時段、不建立訂單。
- 不加入登入、付款、照片、語音或服務廠商後台。
- 不連正式 PostgreSQL、AWS、Bedrock 或 AgentCore。
- 不讓瀏覽器直接呼叫 Hugging Face、MCP 或資料庫。

## 2. 為什麼這樣設計

聊天文字和商業狀態不能混為一體。LLM 回覆只負責說明與追問；畫面上的服務、
地點、表單、答案、時間與候選，全部來自後端的結構化 `SessionView`。

FastAPI route 只做 HTTP adapter。`WebSessionService` 負責 session workflow、
表單驗證與安全狀態轉換；既有 `AgentRunner` 負責模型與 Tool loop；實際服務與
媒合規則仍在 Service Layer。日後把 Mock／Hugging Face 換成 Bedrock 時，
Web API 與前端不需改契約。

P0 使用無 build 的 HTML/CSS/JavaScript，原因是：

- 本機與比賽環境都可直接由 FastAPI 提供同一個網址。
- 沒有 Node build artifact 或第二個開發伺服器，部署面較小。
- 目前互動規模不需要引入前端框架；若後台與寫入流程擴大，再評估元件框架。

## 3. 輸入、輸出與完整資料流

```text
瀏覽器
  -> FastAPI message API
  -> WebSessionService
  -> AgentRunner
  -> Mock / Hugging Face ModelClient
  -> MCPToolClient
  -> search_services
  -> resolve_location
  -> get_consultation_form
  -> ReadServiceLayer
  -> synthetic Demo repository
  -> SessionView
  -> 瀏覽器動態表單

瀏覽器確認表單與 +08:00 時段
  -> FastAPI form API
  -> WebSessionService 驗證欄位、選項與時區
  -> MCPToolClient
  -> match_service_providers
  -> ReadServiceLayer matching_v1
  -> synthetic candidates
  -> SessionView
  -> 候選卡
```

表單欄位來自 `ConsultationForm.topics`：

- `single_select` 以 radio 呈現，答案必須是 Tool 回傳的 option value。
- `multi_select` 僅接受 Tool 回傳的 option values。
- 文字欄位上限 1000 字元。
- `preferred_time` 使用 `datetime_range` config，前端送出具 `+08:00` 的
  ISO 8601；後端再次驗證時區、先後順序與最長 12 小時。
- 未定義欄位一律拒絕，不猜測 service ID、topic key 或 option value。

## 4. 安全與資料邊界

- session 只存在目前 Python process 的記憶體，重新啟動就消失。
- API 不回傳內部對話 Tool payload，只回傳必要的安全 view model。
- `MCPToolClient` 仍透過真實 MCP Client/Server 協定呼叫 Tool。
- 所有候選都必須通過 `ProviderMatchResult` 驗證，且來源固定為 `synthetic`。
- Model provider 錯誤不會靜默切回其他模型。
- API response 使用 `Cache-Control: no-store`；頁面加上 CSP、禁止 iframe、
  MIME sniffing 與跨站 referrer。
- 前端以 `textContent` 呈現 Agent 與 Tool 文字，不把模型輸出插入 HTML。
- 此模組沒有 SQL、資料庫憑證、AWS 金鑰或寫入 Tool。

## 5. 執行方式

安裝應用依賴：

```powershell
python -m pip install -e ".[app,dev]"
```

使用 Mock Model 啟動：

```powershell
home-repair-web
```

預設網址：

```text
http://127.0.0.1:8080
```

也可以直接啟動：

```powershell
python -m uvicorn home_repair_agent.web.app:app --host 127.0.0.1 --port 8080
```

可用環境變數：

| 變數 | 預設 | 用途 |
|---|---|---|
| `WEB_MODEL_PROVIDER` | `mock` | `mock` 或 `huggingface` |
| `WEB_HOST` | `127.0.0.1` | Web bind host |
| `WEB_PORT` | `8080` | Web port |
| `HF_TOKEN` 等 | 見 `.env.example` | Hugging Face 模式 |

`WEB_MODEL_PROVIDER=huggingface` 會把對話與 Tool schema 送到外部 hosted API；
沒有 `HF_TOKEN` 時啟動會直接失敗，不會降級成 Mock。

## 6. 測試與實際結果

聚焦測試：

```powershell
python -m pytest -q tests/test_web_app.py
```

涵蓋首頁、素材、安全 header、health、session、三個初始 MCP Tools、動態表單、
未知欄位拒絕、`+08:00` 驗證、第四個媒合 Tool、synthetic 候選、reset 與安全 404。

2026-07-27 實際結果：

- Web focused：`11 passed`。
- 完整 suite：`76 passed, 9 skipped, 40 subtests passed`。
- Ruff、Python compileall、JavaScript syntax check 通過。
- 實際瀏覽器在 `1280x720` 與 `390x844` 完成完整流程。
- 兩個 viewport 均無 console error、無文字或控制項重疊。

測試環境會出現 FastAPI `TestClient` 對未來 `httpx2` 遷移的第三方
deprecation warning；目前不影響功能或測試結果。

## 7. 待辦與下一階段

P0 尚需：

- 組員 review Web PR，確認文案與分工。
- 用有效 `HF_TOKEN` 跑一次固定 Web eval，不只做人工 smoke。
- 決定 Demo 部署環境並提供公開網址。

P1 才做：

- 有確認、冪等、授權與稽核的案件提交 contract。
- 最小服務廠商後台與案件狀態。
- PostgreSQL session persistence。
- Bedrock adapter、AgentCore、RDS 與正式 AWS 部署。
