# aws_learning_plan.md — AWS 學習計畫（零經驗、只學必要的）

> 原則：每學一個服務，都必須同時回答「Demo 用在哪」與「簡報架構圖講什麼」。學了但上不了架構圖＝浪費時間。
> 前置一次性設定（兩人共做，約 2 小時）：註冊帳號（或等主辦提供）→ 開 IAM user（絕不用 root 寫程式）→ 本機 `aws configure` → 設定 billing alert（$10、$50 兩道）→ 在 Bedrock console 申請模型存取（Claude 系列，審核可能要等，**第一天就做**）。

---

## P0 必學（不會就無法交付）

### 1. Amazon Bedrock（Converse API＋Tool Use＋多模態）
- **為什麼要學**：系統大腦；「AWS 生成式 AI 黑客松」的架構圖不可能沒有它
- **本題怎麼用**：意圖分類、多輪追問、表單預填、案件摘要、報修照片理解
- **最小 PoC**：boto3 `converse()` 傳「我家馬桶不通」→ 回 JSON `{service_type, confidence}`；再加一輪 tool use；再傳一張照片
- **預估學習時間**：0.5 天（含等模型存取審核的空檔看文件）
- **最容易踩雷**：① 模型存取沒先申請，寫好程式才發現 403；② region 選錯（模型不是每區都有，建議 us-west-2 或工作坊指定區）；③ 忘了 tool use 要自己寫「執行→回填」迴圈
- **Demo 呈現**：對話視窗即 Bedrock 輸出；可加「本次呼叫工具鏈」側欄可視化
- **簡報亮點講法**：「LLM 不直接寫資料庫——所有動作經過受控的 tool 白名單，Bedrock tool use 保證輸出結構化、可驗證」

### 2. IAM（最小限度）
- **為什麼要學**：不會 IAM 連 Bedrock 都打不通
- **本題怎麼用**：程式用 IAM user；Lambda 執行 role 掛 Bedrock/S3 權限
- **最小 PoC**：建 user＋access key，本機成功呼叫 Bedrock
- **預估學習時間**：2 小時
- **最容易踩雷**：AccessDenied 訊息看不懂——先檢查「誰在呼叫（user/role）」再檢查「policy 允許了什麼 action」；黑客松用 AWS managed policy 就好，不要自寫 JSON
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

### 5. AWS Lambda（包 1–2 支純函式）
- **為什麼要學**：serverless 是雲端履歷關鍵字；讓架構圖不只一個後端方塊
- **本題怎麼用**：`search_vendor`（媒合計分）、`summarize_case`（案件摘要，內呼 Bedrock）
- **最小 PoC**：console 建 Python Lambda，測試事件回傳假廠商列表
- **預估學習時間**：0.5 天
- **最容易踩雷**：① 第三方依賴要打包（layer/容器），**對策：媒合 Lambda 只用標準庫＋boto3，不連 DB，資料由呼叫端帶入或內嵌 JSON**；② timeout 預設 3 秒，呼叫 Bedrock 要調到 30–60 秒；③ log 在 CloudWatch 不在 console
- **Demo 呈現**：「推薦服務商」瞬間背後是 Lambda——側欄顯示呼叫延遲
- **簡報亮點講法**：「媒合引擎 serverless 化，尖峰自動擴展、閒置零成本——符合社區服務晚間尖峰的流量形態」

### 6. API Gateway
- **為什麼要學**：Lambda 沒有它就沒有公開 URL
- **本題怎麼用**：`POST /vendors/search` → Lambda
- **最小 PoC**：HTTP API（不是 REST API，較簡單便宜）掛通、curl 成功
- **預估學習時間**：2 小時（與 Lambda 同天）
- **最容易踩雷**：CORS——前端跨域呼叫要在 API Gateway 開 CORS；deploy stage 忘了發布改動
- **簡報亮點講法**：「對外 API 統一入口，未來加金鑰與流量控管即可開放給合作廠商」——直接呼應命題「若合作廠商提供 API」的想像

### 7. Amazon Transcribe（若做語音模組）
- **為什麼要學**：語音是「智慧管家可透過語音互動」的官方場景；AWS AI 服務展示點
- **本題怎麼用**：長者語音 → 文字進對話管線；demo 現場用預錄音檔
- **最小 PoC**：一段 10 秒中文 wav 上 S3 → batch transcription job → 取回文字
- **預估學習時間**：3 小時
- **最容易踩雷**：streaming 模式複雜度高十倍，**只用 batch**；中文要指定 `zh-TW`；現場收音品質不可控——demo 用預錄檔，live 用瀏覽器 Web Speech API 保底
- **Demo 呈現**：播放長者語音 → 文字出現 → AI 接手追問
- **簡報亮點講法**：「同一套對話引擎，文字與語音雙通道；語音層用 Transcribe/Polly，高齡使用者零打字完成留資」

### 8. CloudWatch（被動使用）
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
| Bedrock Agents / Knowledge Base | 託管黑盒難除錯，行為不可控，賽場翻車率高 | 「未來規模化後遷移至 Bedrock Agents 託管編排」 |
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
| D1 | 帳號＋IAM＋Bedrock 申請 | 開帳號、billing alert、IAM user、`aws configure`、**申請 Claude 模型存取**、讀 Converse API 文件 | `aws sts get-caller-identity` 成功；模型申請送出 |
| D2 | Bedrock 基礎 | boto3 converse 第一次對話；試 system prompt；量測延遲 | 「馬桶不通」→ 正確 JSON 分類 |
| D3 | Bedrock tool use | 定義 `classify_service_type`＋`search_vendor` 兩個 tool，寫執行迴圈 | 一句話觸發兩段 tool 呼叫並總結 |
| D4 | S3＋多模態 | 照片上傳、presigned URL；Claude 讀圖回結構化 JSON | 上傳馬桶照→判型正確→前端可顯示 |
| D5 | Lambda | console 建 `search_vendor` Lambda（純 boto3＋內嵌假資料） | 測試事件回傳排序結果 |
| D6 | API Gateway＋CloudWatch | 掛 HTTP API、開 CORS、故意報錯練習查 log | curl 公網 URL 成功；找得到錯誤 log |
| D7 | 整合＋架構圖 | FastAPI 改呼叫 Lambda 版媒合；畫第一版 AWS 架構圖（draw.io） | 端到端跑通；架構圖 v1 存 repo |

**分工**：D1–D2 兩人一起（都要會打 Bedrock）；D3–D7 資工主開發、統計同步做 prompt 語料與假資料（見 data_plan），每天收工前互相 demo 十分鐘。

**履歷收割**：完賽後你們可以寫——「以 Bedrock Claude tool-use 建構多輪需求理解 Agent；Lambda＋API Gateway 部署 serverless 媒合服務；PII 以 AES-256-GCM 加密並以 hash 欄位支援等值查詢；MCP Server 對外提供標準化工具接口」。每個字都對應真的做過的東西。
