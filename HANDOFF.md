# HANDOFF：居家修繕 Agent（nw_p）

> 更新：2026-08-02 11:55（Asia/Taipei）　更新者：Codex　機器：MSI/water
> 規則：全文 ≤150 行；只描述現在；真實 ARN、account、token 與個資不得入檔。

## 1. 目前狀態

- [active] 本機整合分支 `integration/final-demo` 已把 Web 圖片／台語 STT、Bedrock、
  AgentCore Remote MCP 與安全修正組合完成；尚未 push、開 PR 或 merge。
- [active] AWS text Demo 已真實跑通 Browser → Bedrock Nova Lite → AgentCore Runtime →
  四個唯讀 Tools，並在 Web 顯示 2 位 synthetic 師傅。
- [active] HF rich-media 與 AWS text 是兩個獨立 Demo 模式；目前不宣稱同一 session 同時
  支援圖片／語音與 Bedrock。
- [active] HF rich-media 與 AWS text 各有一個 Quick Tunnel 公開網址；8 個大會 IP 採
  精確 allowlist，其他來源回 403。`hackathon` credential 已更新，兩個模式都正在跑。

## 2. 本次完成與證據

- [active] 整合 teammate snapshot `cea076c`，另補圖片 `safety_warnings` 在人工確認前即套用
  hard-stop（commit `e3ec81b`）。
- [active] 整合 AgentCore Runtime snapshot、Remote MCP ToolClient 與 Web transport selector：
  `4385975`、`8157cca`、`c001736`、`135cd3c`。
- [active] `TOOL_TRANSPORT=local|agentcore_remote_mcp`；Remote 初始化或憑證失敗會阻止
  Web 啟動，絕不 fallback。AgentRunner 與 WebSessionService 共用同一 client；案件／派單
  仍由本機 `CaseWorkflowService` 控制。
- [active] AgentCore adapter 已把 credential refresh 移出 event loop、遮罩 transport log 的
  Runtime 識別、並在 startup cancellation 時關閉已進入的 contexts。
- [active] 本機驗證：182 passed、90 subtests；Ruff、format、compileall、Node syntax、
  diff check 與 secret scan 通過。
- [active] Remote invoke：initialize、tools/list、`search_services`、`resolve_location`、
  `get_consultation_form`、`match_service_providers` 全部通過；ID 來自較早 ToolResult。
  遮罩證據：[AgentCore report](reports/agentcore_remote_mcp_demo.json)。
- [active] Browser live：Bedrock、service 17、臺北市大安區、`repair_form_v1`、matched；候選
  為 synthetic A 組 94% 與 B 組 81%。未選廠商，未建立案件。

## 3. Demo 模式

### HF rich-media（圖片＋台語／國語 STT）

- `WEB_MODEL_PROVIDER=huggingface`、`TOOL_TRANSPORT=local`。
- 本機：`http://127.0.0.1:8093/`；公開：
  `https://peter-scotland-gospel-graham.trycloudflare.com`。
- Process：launcher PID 11428、server PID 40676、cloudflared PID 35296。
- allowlist commit `e2cf9b1`；外部非核准來源實測 403，本機模擬評審 IP 實測 200。
- 圖片只提出建議且須人工確認；STT 只回填繁中輸入框，須由使用者確認後送出。
- 隊友正在做實體麥克風 smoke；應回報原句、辨識結果、延遲、是否可接受。

### AWS text（正在跑）

- 本機：`http://127.0.0.1:8094/`；公開：
  `https://markers-encouraged-stack-mating.trycloudflare.com`。
- Process：launcher PID 50632、server PID 39264、cloudflared PID 17068；非核准來源
  實測 403，本機模擬評審 IP 實測 200。
- 設定：`WEB_MODEL_PROVIDER=bedrock`、`TOOL_TRANSPORT=agentcore_remote_mcp`。
- 最穩定操作：輸入「臺北市大安區水龍頭漏水」→確認分支；若仍追問地點，輸入
  「服務地點是臺北市大安區，請查詢此行政區」。
- 希望時段必須和 Runtime synthetic availability 重疊；本次可用
  `2026-08-08 13:00–17:00`。摘要確認後會顯示 2 位候選。
- 停在候選畫面最能證明 AWS no-write 路徑；按「選擇此廠商」才會建立本機案件。

## 4. 下一步

1. [active] 等隊友完成實體台語語音 smoke，將四項結果補到
   `docs/implementation-index.md`；不要再加功能或改 STT adapter。
2. [active] 人工 review `integration/final-demo` 相對 `origin/main` 的完整 diff；確認後再由
   使用者決定是否 push／開 PR／merge。
3. [active] 請大會網路實際開啟兩個公開 URL，確認指定來源 IP 能看到頁面；目前只完成
   非核准來源 403 與本機模擬評審 IP 200。Quick Tunnel 無 SLA，評審前須再檢查。
4. [active] Demo 結束先關閉 cloudflared PID 35296／17068、HF PID 11428／40676、
   AWS Web PID 50632／39264，
   再於本 worktree 設定
   `AWS_PROFILE=hackathon`、`AWS_DEFAULT_REGION=us-west-2`，以
   `var\agentcore-remote-mcp\test-venv\Scripts\python.exe` 依序執行
   `scripts\agentcore_remote_mcp_demo.py cleanup` 與 `status`；後者必須為
   `not-deployed`。cleanup 若為 partial 不得宣稱成功。
5. [open issue] Nova 對單獨「臺北市大安區」有一次只追問而未 tool call；受控 gate 無誤，
   但 prompt 穩定性需另做 5 次 synthetic eval。比賽前可先用上方穩定語句。

## 5. User decisions（照做，不重新問）

- [active] 產品只做 service_id=17 水電修繕；以五個 repair branches 展示，不擴清潔／
  第二服務。（2026-08-01）
- [active] 不再新增功能；先完成整合、流程圖、專案介紹與可重跑 Demo。（2026-08-02）
- [active] 隊友負責實體台語語音測試；Codex 負責 AWS 文字整合與最後驗收。（2026-08-02）
- [active] AWS 是評分重點；要能證明真實 Bedrock 與 AgentCore，不可只寫架構宣稱。
- [active] 模型不得改 checklist、建案或派單；四個 MCP Tools 維持唯讀。

## 6. 不可破壞邊界

1. 所有 service/location/form/provider 業務事實都須來自既有 Tool／Service Layer；模型不得猜。
2. 分支、圖片、摘要與派單都需人工確認；synthetic 必須清楚標示。
3. 不記錄真實個資、AWS credential、Runtime ARN、完整 provider payload 或圖片 bytes。
4. Remote MCP 失敗不得切 Mock、HF 或 local MCP；寫入仍不得放進 AgentCore Tools。
5. 不 force/reset、不改寫隊友 branch；未經人類決定不得 merge。

## 7. 環境快照

- Worktree：`C:\Users\water\Desktop\AI\claude\hack松\nw_p_final_integration`。
- AWS Web：PID 50632／39264，port 8094；必須保留
  `PYTHONPATH=<final-integration>\src`，否則共享 editable venv 會載入錯 worktree。
- HF Web：PID 11428／40676，port 8093；Quick Tunnel PID 35296；AWS Quick Tunnel
  PID 17068。Quick Tunnel 無 SLA，電腦／網路／process 中斷即失效，不能保證整整
  24 小時；正式評審前須重點檢查。
- AgentCore：`us-west-2`、synthetic-only、短效資源；到期標籤
  `2026-08-02T09:09:06Z`（臺北 17:09:06）。state 在 ignored
  `var/agentcore-remote-mcp/state.json`，只能從本 worktree cleanup。
- `ExpiresAt` 只是追蹤標籤，不會自動刪除 AWS 資源；Demo 後仍須執行上述 cleanup。
- 公開頁面未部署到 AWS；目前是兩個短效 Quick Tunnel 連本機 Web，其中 AWS text Web
  再連 Bedrock 與 AgentCore 後端。
