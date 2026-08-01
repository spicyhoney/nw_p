# AWS Bedrock／AgentCore POC 證據

最後更新：2026-08-01

## 範圍與基底

- 目標分支：`feature/aws-bedrock-agentcore-poc`。
- 開始時 GitHub／本機都沒有這個分支；從最新 `origin/main` 建立隔離 worktree。
- branch base：`cadc8f5383e14a5c42dce595265f1eb8f45798d3`。
- 建立分支時相對 `origin/main` 的 commits 與 diff 都是 0；repo 內沒有既有 Bedrock
  adapter、AgentCore deployment artifact 或 AWS live evidence 可接續。
- 原本 `main` worktree 的未提交內容未被帶入或修改。

本 POC 只新增 `BedrockModelClient`、fake-client tests、可重跑的 synthetic smoke 與
證據文件。沒有修改 `AgentRunner`、`ToolClient`、Service Layer、MCP schema、Web、
派單／slot state、`HANDOFF.md`、`TASKS.md`、`app.py`、`pyproject.toml` 或 Kiro specs。

## Bedrock adapter 契約

`src/home_repair_agent/agent/bedrock_model.py` 實作既有
`ModelClient.complete(messages, tools) -> ModelTurn`：

1. provider-neutral user／assistant／assistant tool calls／tool result 轉成 Converse
   messages。
2. `ToolDefinition` 轉成 `toolConfig.tools[].toolSpec`。
3. text blocks 轉成 `ModelTurn.answer()`；`toolUse` 轉成
   `ModelTurn.use_tools()`。
4. tool arguments 必須是可序列化 JSON object；list、scalar、NaN、bytes 等拒絕。
5. `BEDROCK_REGION` 與 `BEDROCK_MODEL_ID` 必填；比賽 Region 只接受
   `us-east-1`／`us-west-2`；SDK credential chain 無身分時在建立 client 前停止。
6. Converse 沒有 adapter-level retry；權限、model、transport 或 provider 失敗只回固定
   `BedrockRequestError`，並 suppress 底層 traceback context。沒有 Mock／HF fallback，
   沒有 log request／response body。

Converse schema 與 tool-use／tool-result 格式依
[Boto3 Converse API](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse.html)
及 [Amazon Nova tool use](https://docs.aws.amazon.com/nova/latest/userguide/tool-use.html)。

## Bedrock live invocation

| 欄位 | 證據 |
|---|---|
| 時間 | `2026-08-01T03:46:05+00:00`（臺北 `2026-08-01 11:46:05+08:00`） |
| Region | `us-west-2` |
| model ID | `amazon.nova-lite-v1:0` |
| redacted input | `[synthetic repair request with public location names]` |
| tool-use trace | `resolve_location({"district_name":"大安區","county_name":"台北市"})` |
| redacted output | `[synthetic confirmation reply; no provider payload retained]` |
| output evidence | final text character count `116` |
| 結果 | `passed` |

執行命令：

```powershell
$env:BEDROCK_REGION = "us-west-2"
$env:BEDROCK_MODEL_ID = "amazon.nova-lite-v1:0"
python scripts/bedrock_live_smoke.py
```

實際流程是兩次 Converse：第一輪要求 tool use，回填標示
`source_type=synthetic` 的假 location result，等待 1.1 秒後第二輪取得文字；符合比賽
Bedrock 每秒最多一個 request。第一次以另一個本機 Python runtime 嘗試時在 TLS
handshake 被本機連線重設，沒有 provider response；換回已驗證可連外的專案 runtime
後成功。此失敗未觸發 adapter retry 或 fallback。

Workshop credentials 只存在於瀏覽器記憶體、一次性 child process environment 與短效
temp bridge；每次呼叫的 `finally` 都移除檔案與環境變數，完成後掃描為
`AWS_CREDENTIAL_TEMP_FILES=0`。repo、輸出證據與 log 都沒有 credential 或完整
provider payload。

## AgentCore Runtime 決策與盤點

沒有執行 deploy／invoke／log／cleanup，原因是：

1. branch base 沒有 AgentCore entrypoint、runtime packaging、execution role 或 deployment
   state，沒有「既有 Runtime POC」可補完。
2. AWS 官方 direct-code 流程會建立 zip archive 並上傳 S3；官方 custom runtime 流程則
   需要 ARM64 container／registry 與 execution role。這不是 Bedrock adapter 的小幅補齊。
3. 本工作的明確限制是不建立 S3，且 `pyproject.toml` 也禁止修改；因此沒有為了取得
   deploy 截圖擴大成新的 infrastructure 工作線。

依據：[Python direct code deployment](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html)、
[custom runtime deployment](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-custom.html)。

只讀盤點結果：

```text
AGENTCORE_RUNTIMES[us-east-1]=0
AGENTCORE_RUNTIMES[us-west-2]=0
```

因此沒有 AgentCore endpoint／session／CloudWatch log 可 invoke、檢查或 cleanup；也沒有
Runtime 持續計費。若後續明確允許短效 S3 artifact（或另開 container／IAM 工作線），
再依官方流程 deploy → invoke → log → stop session → delete runtime／artifact，並於每步
留下 resource ID、tags 與刪除後 list=0 證據。

## AWS 資源與計費狀態

| 項目 | Region | tags | 本輪建立 | 目前持續計費 |
|---|---|---|---|---|
| Bedrock on-demand Converse | `us-west-2` | 不適用 | 無持久資源；成功 2 requests | 否；只有已完成 inference 的一次性用量 |
| AgentCore Runtime | `us-east-1`／`us-west-2` | 無 | 0 | 否 |
| Gateway／RDS／S3／公開網站／GPU | 無 | 無 | 0 | 否 |

## 驗證結果

| 驗證 | 結果 |
|---|---|
| 修改前完整 `pytest -q` | `133 passed, 19 skipped, 52 subtests passed` |
| Bedrock focused | `15 passed` |
| AgentRunner／Demo regression | `22 passed` |
| MCP protocol | `7 passed, 11 subtests passed` |
| 修改後完整 `pytest -q` | `148 passed, 19 skipped, 52 subtests passed` |
| `compileall -q src tests scripts` | passed |
| 受影響檔 Ruff | passed |
| 全 repo Ruff | 22 個既有 data-cleaning findings；base 同樣是 22，沒有新增 |
| `git diff --check` | passed |
| AWS／HF key 與 private-key pattern scan | 0 matched files |

PostgreSQL tests 的 19 個 skip 仍是未提供 `TEST_DATABASE_URL`／對應環境的既有條件；
本 POC 未修改資料庫契約。

## 尚未完成與 reviewer 起點

- 尚未做固定案例矩陣、Bedrock 品質／延遲／token／成本比較。
- 尚未把 Web／Demo provider routing 擴充到 Bedrock；本 POC 只交付 ModelClient adapter，
  避免修改禁改的 `app.py` 與 Web shared files。
- AgentCore Runtime／Gateway 仍未實作，原因見上節。
- 尚未驗證 Runtime IAM role、CloudWatch log 與 cleanup automation。

Reviewer 建議先看 `src/home_repair_agent/agent/bedrock_model.py`，第一個 command：

```powershell
python -m pytest tests/test_bedrock_model.py -q
```
