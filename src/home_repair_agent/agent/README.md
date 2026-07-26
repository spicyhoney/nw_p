# Agent 對話迴圈實作說明

狀態：本機核心迴圈已驗證，尚未串接真正 LLM 與 AWS

最後更新：2026-07-26

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

它已能保存同一個 session 的多輪訊息、呼叫四個唯讀 MCP Tools、把結果交回
ModelClient，直到模型給出使用者回覆或觸發安全停止。Rule-based Mock 會自動
跑前三個諮詢工具；第四個媒合 Tool 已由 scripted model 驗證可通過相同迴圈。

## 為什麼現在能做

Agent「部署在哪裡」和「怎麼執行對話迴圈」是兩件事。迴圈可以先在本機使用
Mock Model 與記憶體內 MCP transport 驗證；之後只要新增
`BedrockModelClient`，並把同一個 `AgentRunner` 放進 AgentCore Runtime，不必
重寫流程。

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
6. 必填資訊完成後停在確認前，不建立案件。

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

## Bedrock 怎麼接

下一個模型 adapter 需實作 `ModelClient.complete()`：

1. 把 `ConversationMessage` 轉成 Bedrock Converse messages。
2. 把 `ToolDefinition` 轉成 Bedrock `toolConfig`。
3. 將 Bedrock 文字結果轉成 `ModelTurn.answer()`。
4. 將 Bedrock `toolUse` 轉成 `ModelTurn.use_tools()`。

AgentRunner、MCPToolClient、Service Layer 與 PostgreSQL 不需要修改。AWS
credentials 由標準 credential provider chain 或 IAM role 提供，不得寫入程式。

## 測試

執行：

```powershell
python -m pytest tests/test_agent_loop.py -q
```

2026-07-26 結果：13 passed。涵蓋：

- 一句話依序呼叫三個真實 MCP Tools。
- scripted model 能看見並呼叫第四個唯讀媒合 Tool。
- 缺少地點時，下一輪補充後繼續而不重查服務。
- 行政區查詢失敗時，可在下一輪更正地點並繼續流程。
- 更正句同時包含新、舊地點時不猜測，要求單一新地點後再繼續。
- 表單答案跨輪保存，最後停在確認前。
- 查無服務與行政區錯誤時不猜 ID。
- 寫入 Tool 從模型可見 catalog 移除並拒絕執行。
- 未知 Tool、Tool 例外與 catalog 例外的安全處理。
- 重複 Tool Call 在最大步數停止。

完整 test suite 的數字取決於本機是否具備主辦方資料集與
`TEST_DATABASE_URL`。2026-07-26 在有主辦方資料集、未設定測試資料庫的
工作區為 44 passed、9 skipped、40 subtests passed；9 個 skipped 是
PostgreSQL 整合測試。乾淨 checkout 若沒有主辦方資料集，會再跳過 1 個
資料清洗整合測試。

## 尚未做

- `BedrockModelClient` 與真實 LLM tool-selection eval。
- AgentCore Runtime / Gateway 部署與 IAM 驗證。
- Speech-to-Text、Text-to-Speech 與前端麥克風。
- 回答自動對映到任意表單 topic 的 LLM slot filling。
- Rule-based Mock 尚未把表單自由文字自動轉成含時區的媒合參數。
- 建立案件、保留時段、確認媒合與訂單寫入。
- session 的 PostgreSQL / Redis 永久保存。

下一階段應先接 Bedrock adapter 並以固定 eval cases 比較 Tool 選擇；寫入功能
要等確認與冪等契約完成後再加入。
