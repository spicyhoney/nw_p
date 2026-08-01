# Agent 對話迴圈實作說明

狀態：本機核心迴圈、終端 Demo、Hugging Face 與 Bedrock adapter contract 已驗證；
HF 與 Bedrock 各有 synthetic live smoke，固定 eval 與 AgentCore 部署尚待驗證

最後更新：2026-08-01

## 做了什麼

本模組建立一個不綁定模型與部署平台的 Agent 核心：

| 元件 | 檔案 | 責任 |
|---|---|---|
| `AgentRunner` | `loop.py` | 執行「模型 -> Tool -> 結果回填 -> 模型」迴圈 |
| 對話契約 | `models.py` | 訊息、Tool Call、Tool Result、trace 與停止原因 |
| `ModelClient` / `ToolClient` | `ports.py` | 隔離模型供應商與工具 transport |
| `MCPToolClient` | `mcp_client.py` | 將 MCP `ClientSession` 轉成 Agent 可用的工具介面 |
| `RuleBasedRepairMockModel` | `mock_model.py` | 無 AWS 時可重現的修繕流程替身 |
| `ScriptedModelClient` | `mock_model.py` | 精確控制 Tool Call 的測試替身 |
| `HuggingFaceModelClient` | `huggingface_model.py` | 將對話與工具轉成 Hugging Face chat completion/function calling |
| `HuggingFaceVisionClient` | `huggingface_vision.py` | 將已驗證圖片送到 HF VLM，只回傳待人工確認的結構化建議 |
| `BedrockModelClient` | `bedrock_model.py` | 將相同對話與工具契約轉成 Bedrock Converse／tool use |
| 本機終端 Demo | `demo.py` | 互動或腳本化展示 Agent、MCP 與 Service Layer 閉環 |

它已能保存同一個 session 的多輪訊息、呼叫四個唯讀 MCP Tools、把結果交回
ModelClient，直到模型給出使用者回覆或觸發安全停止。Rule-based Mock 會自動
跑完服務、地點、表單與 synthetic 師傅媒合四個唯讀工具。

## 為什麼現在能做

Agent「部署在哪裡」和「怎麼執行對話迴圈」是兩件事。迴圈可在本機使用
Mock Model 與記憶體內 MCP transport 做 deterministic 驗證，也可用
Hugging Face Inference Providers 與 Amazon Bedrock 可驗證真正的語意理解與
tool calling；之後把同一個 `AgentRunner` 放進 AgentCore Runtime，不必重寫流程。

## 本機終端 Demo

先安裝應用與開發依賴：

```powershell
python -m pip install -e ".[app,dev]"
```

以固定三輪情境執行，適合快速 smoke test 或投影展示：

```powershell
python -m home_repair_agent.agent.demo --scripted
```

互動操作：

```powershell
python -m home_repair_agent.agent.demo
```

也可在 editable install 後使用 `home-repair-agent-demo`。互動模式支援
`/help`、`/reset` 與 `/quit`。預設會顯示每次 MCP Tool 的名稱、參數與
成功／失敗結果，方便人工驗證 Agent 沒有自行捏造服務或地點 ID。

此 Demo 使用 `DemoReadRepository` 的合成服務、兩個行政區、縮短表單與兩位
synthetic 師傅候選，所有資料都只存在程序記憶體。它不讀主辦方資料集、不連
PostgreSQL、不連 AWS，也不寫入、不保留時段或建立案件。Hugging Face mode
只會把對話、system prompt 與唯讀 Tool schema／結果送到所選 hosted provider；
不會上傳資料庫或主辦方檔案。

兩個 synthetic 時段會依 Demo 啟動時間產生在下一個仍屬未來的星期六；測試可
注入固定 `reference_time`，因此不依賴系統日期，也不會在寫死日期後失效。

目前 Rule-based Mock 會保存「星期六下午」等回答，但不會把它解析成精確、
含時區的媒合時間窗；媒合呼叫只傳正式 `service_id`、`location_id` 與
`limit`，因此 Demo 會排序該地點的所有 synthetic 可用時段。Hosted model
也被明確禁止把相對日期自行換成年月日；只有使用者提供完整、含時區的開始與
結束時間時，才可傳 `preferred_start` / `preferred_end`。

## Hugging Face 模型模式

安裝 `app` extra 後，在 Hugging Face 建立具有 Inference Providers 權限的
token。token 只放在目前 shell，不要寫入程式、commit 或對話：

```powershell
$env:HF_TOKEN = "hf_..."
python -m home_repair_agent.agent.demo --model-provider huggingface
```

可選設定：

| 環境變數 | 預設 | 用途 |
|---|---|---|
| `HF_MODEL_ID` | `Qwen/Qwen3-4B-Instruct-2507` | 支援 function calling 的模型 |
| `HF_PROVIDER` | `auto` | 由 Hugging Face router 選擇可用 provider，或指定 provider |
| `HF_MAX_TOKENS` | `512` | 單次模型輸出的 token 上限 |
| `HF_TIMEOUT_SECONDS` | `60` | hosted inference 單次請求的最長等待秒數 |

`HuggingFaceModelClient` 做四件事：

1. 將內部 user／assistant／tool result 對話轉為 chat-completion messages。
2. 將 MCP `ToolDefinition` 轉為 OpenAI-compatible function schema。
3. 將模型文字轉為 `ModelTurn.answer()`。
4. 驗證 tool call ID、名稱與 JSON object 參數，再轉為
   `ModelTurn.use_tools()`。

provider 錯誤與不合法回覆會轉成固定 adapter error，再由 `AgentRunner` 顯示
安全訊息。CLI 的 `mock` 與 `huggingface` 是顯式選擇；缺少 token、套件或錯誤
設定時 Hugging Face mode 會 fail fast，不會偷偷 fallback；外部服務未回覆時
也會在設定的 timeout 後停止。預設 open model 與 provider 可替換，模型品質
仍需用固定 eval cases 實測，不能以 adapter 單元測試代替。

### Hugging Face 圖片分析

Web 的可選圖片流程使用 `HuggingFaceVisionClient`，預設
`Qwen/Qwen3-VL-30B-A3B-Instruct` 與 `HF_VL_PROVIDER=auto`。這個組合已用無個資的
synthetic 水漬圖片完成一次 live smoke。它只輸出
`service_query`、問題摘要、安全提醒、confidence 與 uncertain；不得產生
`service_id`、建案或派單。使用者可先修改結果，明確確認後 Web 才會透過既有
`search_services` 唯讀 Tool 重新驗證服務類別。Mock 模式沒有圖片假結果，也不會
在 HF 失敗時 fallback。

圖片會送往 Hugging Face Inference Provider；UI 必須先取得該次外部處理同意，
且 Demo 只允許 synthetic／公開測試圖片。設定使用 `HF_TOKEN`、
`HF_VL_MODEL_ID`、`HF_VL_PROVIDER`、`HF_VL_MAX_TOKENS`、
`HF_VL_TIMEOUT_SECONDS`。provider 可用性仍會改變，部署環境應重跑有效 token 與
synthetic 圖片 smoke；adapter contract test 不等於 provider 可用性保證。

參考：[Hugging Face function calling 指南](https://huggingface.co/docs/inference-providers/guides/function-calling)、
[InferenceClient API](https://huggingface.co/docs/huggingface_hub/en/package_reference/inference_client)、
[Qwen3-4B-Instruct-2507 model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)。

## 資料流

```text
文字輸入
  -> AgentRunner.run_turn()
  -> ModelClient.complete()
  -> 結構化 ToolCall
  -> MCPToolClient
  -> FastMCP Server
  -> ReadServiceLayer
  -> PostgreSQL agent.* views
  -> ToolResult 回填 ModelClient
  -> 最終文字回覆
```

模型不會取得資料庫連線，也不能送任意 SQL。

## 每一輪如何停止

一輪最多允許：

- 8 次 ModelClient 呼叫。
- 每次模型回覆最多 4 個 Tool Calls。
- 僅執行 MCP catalog 中標示 `readOnlyHint=true` 的工具。
- 可再用 `allowed_tool_names` 縮小白名單。

模型給出文字回覆時正常停止；超過步數、工具過多、模型故障或工具 catalog
故障時，回傳固定安全訊息，不把 provider、Gateway、資料庫或憑證細節顯示給
使用者。

## Mock Model 能證明什麼

`RuleBasedRepairMockModel` 可以：

1. 以使用者描述呼叫 `search_services`。
2. 從標準臺灣縣市與行政區文字呼叫 `resolve_location`。
3. 呼叫 `get_consultation_form`。
4. 依表單的必填 topic 一次追問一題。
5. 保存同一個 session 後續回答。
6. 必填資訊完成後呼叫 `match_service_providers`。
7. 顯示 synthetic 首選、時段與分數，並明示尚未建立案件或保留時段。

它只能證明 Agent 與 MCP 編排可運作，不能證明真正 LLM 的分類、抽取與回答
品質。Mock 使用規則與固定格式，刻意不冒充 Bedrock。

## 安全與合規

- 目前只把 `readOnlyHint=true` 的工具交給模型。
- `create_order` 等未確認的寫入 Tool 即使出現在 MCP catalog，也會被隱藏並拒絕。
- 模型要求不存在或不允許的工具時回 `UNKNOWN_TOOL`。
- Tool Client 例外統一轉成 `TOOL_CLIENT_ERROR`，不洩漏原始錯誤。
- 超過最大步數會回 `max_steps`，避免模型與工具無限互相呼叫。
- 目前 session 只存在 Python 記憶體，不含永久個資儲存。

未來開放寫入前，必須另外實作使用者確認 token、冪等 key、狀態驗證與 audit
log，不能只把 `readOnlyHint` 改成 `false` 就直接開放。

## 語音怎麼接

語音不是另一套 Agent：

```text
麥克風
  -> Speech-to-Text
  -> user_text
  -> AgentRunner.run_turn()
  -> reply
  -> Text-to-Speech（選配）
```

瀏覽器 Web Speech API 或 Amazon Transcribe 只負責把聲音變成文字。朋友之後做
語音時，只需把辨識結果送進相同的 `run_turn()`；文字版測試仍然有效。

## Bedrock 模型模式

`BedrockModelClient` 已實作相同的 `ModelClient.complete()`：

1. 把 `ConversationMessage` 轉成 Bedrock Converse messages。
2. 把 `ToolDefinition` 轉成 Bedrock `toolConfig`。
3. 將 Bedrock 文字結果轉成 `ModelTurn.answer()`。
4. 將 Bedrock `toolUse` 轉成 `ModelTurn.use_tools()`。
5. 驗證 tool arguments 是可序列化的 JSON object，拒絕 list、scalar、NaN 與 bytes。
6. 只有 `stopReason=end_turn` 接受文字、`stopReason=tool_use` 接受工具呼叫；
   `max_tokens`、`malformed_tool_use`、context overflow、filter 或未知原因都安全失敗。

AgentRunner、MCPToolClient、Service Layer 與 PostgreSQL 不需要修改。AWS
credentials 由標準 credential provider chain 或 IAM role 提供，不得寫入程式。
Region 與 model ID 必須明確設定，錯誤時不 fallback 到 Mock 或 Hugging Face：

```powershell
$env:BEDROCK_REGION = "us-west-2"
$env:BEDROCK_MODEL_ID = "amazon.nova-lite-v1:0"
python scripts/bedrock_live_smoke.py
```

`BEDROCK_REGION` 只接受比賽允許的 `us-east-1`／`us-west-2`；另可設定
`BEDROCK_MAX_TOKENS` 與 `BEDROCK_TIMEOUT_SECONDS`。SDK client 沒有 credentials 時
在建立階段停止；權限、model ID 或 provider 請求失敗時只拋固定的安全錯誤，不記錄
credential、完整 provider payload 或對話內容，也不做隱藏 retry／provider 切換。
回應解析同樣 fail closed：不把 token 截斷的 partial text 當完成回答，也不執行
Bedrock 標示為 malformed 的 tool use。

2026-08-01 已以 `us-west-2` 的 `amazon.nova-lite-v1:0` 執行兩輪 synthetic live
smoke：第一輪回 `resolve_location({county_name: 台北市, district_name: 大安區})`，
第二輪在回填 synthetic 結果後產生文字。時間、redacted I/O 與資源盤點見
[AWS POC 證據](../../../docs/ENGINEER_LOG-aws-bedrock-agentcore-poc.md)。

## 測試

執行：

```powershell
python -m pytest tests/test_bedrock_model.py tests/test_agent_loop.py tests/test_agent_demo.py tests/test_mcp_tools.py -q
```

Bedrock fake-client contract tests 涵蓋：

- 缺 Region、model ID、credentials 與競賽外 Region 的 fail-fast。
- system/user/assistant/tool-use/tool-result 與 Tool schema 的雙向轉換。
- 文字回答、tool-use、JSON object 與非 JSON nested value 驗證。
- provider 錯誤與 response error 遮罩，且 traceback 不串出底層 provider context。
- explicit Region/model routing，沒有 Mock／HF fallback。
- `stopReason` 白名單：只接受 `end_turn` 文字與 `tool_use` 工具；截斷、filter、
  malformed tool use、reason/content 不一致都拒絕。

Hugging Face adapter 新增的測試涵蓋：

- 環境設定、預設模型與缺 token fail-fast。
- timeout 設定驗證，且設定值確實傳入真實 SDK constructor。
- system/user/assistant/tool messages 與 function schema 的轉換。
- 文字回覆、結構化 tool call、JSON argument 驗證。
- provider 錯誤遮罩，且不把 token 放入物件 repr。
- Demo provider routing 不會靜默 fallback。

既有 Agent／Demo 測試涵蓋：

- 一句話依序呼叫三個真實 MCP Tools。
- scripted model 與 Rule-based Mock 都能呼叫第四個唯讀媒合 Tool。
- 缺少地點時，下一輪補充後繼續而不重查服務。
- 行政區查詢失敗時，可在下一輪更正地點並繼續流程。
- 更正句同時包含新、舊地點時不猜測，要求單一新地點後再繼續。
- 表單答案跨輪保存，完成後查詢 synthetic 師傅；空結果不捏造人選。
- 查無服務與行政區錯誤時不猜 ID。
- 行政區查詢失敗後，下一輪可改用使用者最新提供的地點。
- 腳本化終端 Demo 可走完四個真實 MCP Tools、多輪追問與候選摘要。
- synthetic 時段永遠落在下一個未來星期六，且測試時間必須含時區。
- 寫入 Tool 從模型可見 catalog 移除並拒絕執行。
- 未知 Tool、Tool 例外與 catalog 例外的安全處理。
- 重複 Tool Call 在最大步數停止。

完整 test suite 的數字取決於本機是否具備主辦方資料集與
`TEST_DATABASE_URL`。2026-07-26 在有主辦方資料集、未設定測試資料庫的
工作區為 44 passed、9 skipped、40 subtests passed；本次修正工作區為
65 passed、9 skipped、40 subtests passed，9 個 skipped 都需要
`TEST_DATABASE_URL`。團隊 handoff 紀錄已有一次使用 synthetic prompt 的
Hugging Face 四工具 live smoke；本次修正環境沒有 `HF_TOKEN`，沒有重跑 live，
也仍不宣稱模型品質或完成固定 eval。

2026-08-01 Bedrock POC：adapter focused `15 passed`，AgentRunner／Demo regression
`22 passed`，MCP protocol `7 passed, 11 subtests passed`，完整 suite
`148 passed, 19 skipped, 52 subtests passed`。受影響 Ruff、compileall、diff check 與
secret pattern scan 通過；全 repo Ruff 的 22 個 findings 與 base 相同。Nova Lite
synthetic live tool-use 已通過，細節見 AWS POC 證據。

2026-08-01 PR #17 review 修正：Bedrock／live-smoke focused
`23 passed, 3 subtests passed`，Agent／Demo／MCP 合併 focused
`52 passed, 14 subtests passed`，完整 suite
`156 passed, 19 skipped, 55 subtests passed`。四個 Bedrock 新檔已通過 Ruff check 與
format check，且納入 PostgreSQL CI targeted list；Nova Lite live smoke 在
`stopReason` 白名單後重新成功。

## 尚未做

- 可重複的 Hugging Face 固定 LLM tool-selection eval、延遲與額度紀錄。
- 可重複的 Bedrock 固定 tool-selection eval、延遲與額度紀錄。
- AgentCore Runtime / Gateway 部署與 IAM 驗證。
- FastAPI／瀏覽器 Demo UI、Speech-to-Text、Text-to-Speech 與前端麥克風。
- 回答自動對映到任意表單 topic 的 LLM slot filling。
- Rule-based Mock 尚未把表單自由文字自動轉成含時區的媒合參數。
- 建立案件、保留時段、確認媒合與訂單寫入。
- session 的 PostgreSQL / Redis 永久保存。

下一階段應把既有 synthetic live smoke 整理成可重複 eval，記錄工具選擇、
參數與成本／延遲，再以同一組 cases 接 Bedrock 比較；寫入功能要等確認與
冪等契約完成後再加入。
