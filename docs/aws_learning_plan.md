# aws_learning_plan.md — AWS 學習計畫（零經驗、只學必要的）

> 原則：每學一個服務，都必須同時回答「Demo 用在哪」與「簡報架構圖講什麼」。學了但上不了架構圖＝浪費時間。
> 目前沒有比賽 AWS 憑證時，先用 Mock Model、本機 MCP 與本機 PostgreSQL，不建立
> 假金鑰。主辦方提供環境後，優先使用暫時憑證或 IAM Identity Center，確認指定
> Region、模型、額度與 AgentCore 權限。若使用 Anthropic 模型，再完成一次性的
> First Time Use 表單；其他基礎模型在 IAM 權限正確時通常已預設可用。

---

## P0 必學（不會就無法交付）

### 1. Amazon Bedrock（Converse API＋Tool Use＋多模態）
- **為什麼要學**：系統大腦；「AWS 生成式 AI 黑客松」的架構圖不可能沒有它
- **本題怎麼用**：意圖分類、多輪追問、表單預填、案件摘要、報修照片理解
- **最小 PoC**：boto3 `converse()` 傳「我家馬桶不通」→ 回 JSON `{service_type, confidence}`；再加一輪 tool use；再傳一張照片
- **預估學習時間**：0.5 天
- **最容易踩雷**：① IAM 缺少 `bedrock:InvokeModel`；② Region 或指定模型不可用；
  ③ Anthropic 首次使用表單尚未完成；④ 忘了 client-side tool use 要由自己的程式
  執行工具並回填結果
- **Demo 呈現**：對話視窗即 Bedrock 輸出；可加「本次呼叫工具鏈」側欄可視化
- **簡報亮點講法**：「LLM 不直接寫資料庫——所有動作經過受控的 tool 白名單，Bedrock tool use 保證輸出結構化、可驗證」

### 2. IAM（最小限度）
- **為什麼要學**：不會 IAM 連 Bedrock 都打不通
- **本題怎麼用**：開發者使用暫時憑證；Runtime、Gateway、Lambda 使用各自的 IAM role
- **最小 PoC**：使用主辦方 session 或 IAM Identity Center 登入，先讓
  `sts get-caller-identity` 成功，再呼叫 Bedrock
- **預估學習時間**：2 小時
- **最容易踩雷**：AccessDenied 訊息看不懂。先檢查「誰在呼叫（user/role）」、
  「目前 Region」與「policy 允許了什麼 action」；不要使用 root，也不要把長期
  access key 寫進 `.env` 或 GitHub
- **Demo 呈現**：不呈現
- **簡報亮點講法**：資安 Q&A 備彈：「服務間權限走 IAM role 最小授權」

### 3. S3
- **為什麼要學**：照片上傳是修繕場景的靈魂；官方 feedback 範例的圖片答案就是 bucket 路徑格式
- **本題怎麼用**：報修照片上傳 → 存 key 進諮詢單 → 前端 presigned URL 顯示
- **最小 PoC**：boto3 上傳一張圖＋產 presigned URL 在瀏覽器打開
- **預估學習時間**：2 小時
- **最容易踩雷**：bucket 預設全私有（正確！），忘了用 presigned URL 而直接拼 URL 會 403；region 與 bucket 名稱寫死在程式裡要抽成環境變數
- **Demo 呈現**：上傳照片 → 廠商後台看到同一張照片
- **簡報亮點講法**：「使用者照片私有儲存，前端僅獲時效性簽名連結」

### 4.（自建但必要）PostgreSQL——不是 AWS 服務，但它是資料層的 P0
- 官方 3 個 SQL 檔直接匯入；架構圖標「PostgreSQL（production: Amazon RDS）」。學習時間 0.5 天（含 jsonb 查詢練習）。

---

## P1 建議學（讓架構完整、簡報更好看）

### 5. Amazon Bedrock AgentCore Runtime / Gateway
- **為什麼要學**：這是工作坊展示的 Agent 執行與 MCP 工具入口，也是自家 Agent
  和 Lumine one 共用工具的方式
- **本題怎麼用**：Runtime 託管自製 Agent 或 FastMCP Server；Gateway 讓 Agent 以
  `tools/list`、`tools/call` 發現並呼叫白名單工具
- **最小 PoC**：先把一個本機 FastMCP tool 部署到 Runtime，再由 Gateway 成功列出
  並呼叫；下一步才接完整 Service Layer
- **預估學習時間**：0.5–1 天
- **最容易踩雷**：把 AgentCore Gateway 和 API Gateway 混為一談；前者面向 MCP
  Agent 工具，後者面向一般 HTTP API
- **Demo 呈現**：在側欄顯示 Gateway 實際呼叫的 tool 名稱、輸入摘要與延遲

### 6. AWS Lambda（最多一支展示）
- **為什麼要學**：serverless 是雲端履歷關鍵字；讓架構圖不只一個後端方塊
- **本題怎麼用**：有餘裕時把一個無狀態工具做成 AgentCore Gateway 的 Lambda target
- **最小 PoC**：console 建 Python Lambda，測試事件回傳假廠商列表
- **預估學習時間**：0.5 天
- **最容易踩雷**：為展示而複製一套媒合邏輯。Lambda 和 FastMCP 必須呼叫同一個
  Service Layer；若部署依賴或資料庫網路尚未打通，就保留 FastMCP 版本
- **Demo 呈現**：「推薦服務商」瞬間背後是 Lambda——側欄顯示呼叫延遲
- **簡報亮點講法**：「媒合引擎 serverless 化，尖峰自動擴展、閒置零成本——符合社區服務晚間尖峰的流量形態」

### 7. API Gateway（有一般 REST API 需求才學）
- **為什麼要學**：讓一般網頁、手機或合作廠商以 HTTPS 呼叫 Lambda / REST API
- **本題怎麼用**：只有確定要公開 `POST /vendors/search` 等 REST endpoint 時才加
- **最小 PoC**：將一支 Lambda 掛到 HTTP API 並用測試 client 打通
- **預估學習時間**：2 小時
- **最容易踩雷**：把它誤當 AgentCore Gateway。Agent 呼叫 MCP Tools 已由
  AgentCore Gateway 負責，不需要再多繞一層 API Gateway

### 8. Amazon Transcribe（若做語音模組）
- **為什麼要學**：語音是「智慧管家可透過語音互動」的官方場景；AWS AI 服務展示點
- **本題怎麼用**：長者語音 → 文字進對話管線；demo 現場用預錄音檔
- **最小 PoC**：一段 10 秒中文 wav 上 S3 → batch transcription job → 取回文字
- **預估學習時間**：3 小時
- **最容易踩雷**：streaming 模式複雜度高十倍，**只用 batch**；中文要指定 `zh-TW`；現場收音品質不可控——demo 用預錄檔，live 用瀏覽器 Web Speech API 保底
- **Demo 呈現**：播放長者語音 → 文字出現 → AI 接手追問
- **簡報亮點講法**：「同一套對話引擎，文字與語音雙通道；語音層用 Transcribe/Polly，高齡使用者零打字完成留資」

### 9. CloudWatch（被動使用）
- 學習時間 30 分鐘：會看 Lambda log group 排錯即可。簡報講法：「全鏈路 log 可審計」。

---

## P2 有時間再學（加分但別優先）

| 服務 | 加分點 | 最小投入 | 何時值得做 |
|---|---|---|---|
| Amazon Polly | 高齡模式語音回覆 | 2 小時 | 語音模組完成且還有餘裕 |
| Amplify Hosting | 公開 demo 網址最快路徑 | 2 小時 | 7/18 後確認部署環境不含前端托管時 |
| DynamoDB | 對話 session 存放 | 3 小時 | Postgres 都穩了、想加 NoSQL 詞彙 |
| pgvector / Bedrock Embedding | 餐廳/商品語意檢索 | 3 小時 | 選了餐廳或購物場景 |
| GitHub Actions（CI） | 「我們有 CI」一句話 | 2 小時 | 最後一週收尾期 |

---

## 不建議現在學（CP 值陷阱）

| 服務 | 為什麼不學 | 簡報替代講法 |
|---|---|---|
| Bedrock Agents Classic / Knowledge Base | 本案已選自製 Agent＋AgentCore；不要再疊另一套編排框架 | 「目前以 AgentCore 託管自製 Agent，保留框架控制權」 |
| Step Functions | 學習成本高，本題狀態流用 DB 欄位即可表達 | 未來架構圖畫一個狀態機示意 |
| Cognito | 真登入對 demo 無增益，設定繁瑣 | 「production 採 Cognito＋UniOpen SSO」 |
| SageMaker | 本題零自訓模型需求 | 不提，提了反而被追問 |
| EKS/ECS 深度 | 容器編排超出需求 | Docker Compose 就是你們的編排 |
| VPC 網路 | 一天級黑洞 | 不提 |
| CloudFront | 規模無感 | 架構圖畫一格即可 |

---

## 7 天 AWS 速成路線（每天 2–3 小時，兩人可拆）

| 天 | 主題 | 具體任務 | 產出（驗收） |
|---|---|---|---|
| D1 | 帳號＋IAM＋Bedrock 可用性 | 使用主辦方暫時憑證或 IAM Identity Center、確認 Region / model ID / 額度；選 Anthropic 才填首次使用表單 | `aws sts get-caller-identity` 與一次 Converse 呼叫成功 |
| D2 | Bedrock 基礎 | boto3 converse 第一次對話；試 system prompt；量測延遲 | 「馬桶不通」→ 正確 JSON 分類 |
| D3 | Bedrock tool use | 定義 `classify_service_type`＋`search_vendor` 兩個 tool，寫執行迴圈 | 一句話觸發兩段 tool 呼叫並總結 |
| D4 | S3＋多模態 | 照片上傳、presigned URL；Claude 讀圖回結構化 JSON | 上傳馬桶照→判型正確→前端可顯示 |
| D5 | AgentCore Runtime | 部署最小 Agent 或 FastMCP Server | Runtime endpoint 可呼叫 |
| D6 | AgentCore Gateway＋CloudWatch | 將 Runtime MCP Server 加為 target；練習 `tools/list` / `tools/call` 並查看 log | Gateway 成功呼叫一個真實 tool |
| D7 | 整合＋架構圖 | 切換 Bedrock / Gateway adapters，跑完整閉環；Lambda 僅在有餘裕時追加 | 端到端跑通；架構圖與實作一致 |

**分工**：D1–D2 兩人一起（都要會打 Bedrock）；D3–D7 資工主開發、統計同步做 prompt 語料與假資料（見 data_plan），每天收工前互相 demo 十分鐘。

**履歷收割**：完成後可依實際成果寫「以 Amazon Bedrock tool use 建構多輪需求
理解 Agent；以 AgentCore Runtime / Gateway 部署並治理 MCP 工具；PII 以
AES-256-GCM 加密並以 hash 欄位支援等值查詢」。只寫真正完成並展示過的部分。
