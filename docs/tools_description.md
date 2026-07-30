# tools_description.md — 工具學習與使用說明

> **歷史學習文件**：本頁是早期工具盤點，不代表所有工具已採用或仍具相同優先級。
> 目前技術棧看 [README](../README.md)，未完成工作看 [TASKS](../TASKS.md)。

> 目的：回答「這次黑客松需要會到什麼程度才夠」，不是教到精通。
> 求職價值標記：**DS**=資料科學家、**AIE**=AI Engineer、**Infra**=AI Infra、**BE**=Backend、**Cloud**=Cloud Engineer；◎=高價值、○=中等、△=低。
> 優先級：P0=這次很可能必須會｜P1=非常建議會｜P2=有時間再學｜P3=可以先跳過。

---

# A. AWS 相關

## Amazon Bedrock

### 這是什麼？
AWS 上的「模型即服務」：用一支 API 呼叫 Claude、Llama、Titan 等模型，不用自己架 GPU。

### 和本次黑客松的關係
整個 AI 管家的大腦：意圖分類、多輪追問、表單預填、案件摘要、多模態看照片，全部經 Bedrock 的 Converse API（含 tool use）完成。AWS 架構圖的核心方塊。

### 是否必要？ **必學（P0）**

### 需要學到什麼程度？
- 30 分鐘：懂 console 開通模型存取、什麼是 model id、on-demand 計費
- 2 小時：用 boto3 `converse()` 完成一次對話＋一次 tool use 回圈
- 1 天：多模態（傳圖）、system prompt 設計、錯誤重試
- 不建議深入：fine-tuning、Bedrock Agents Classic 編排、Knowledge Base 調參

### 最小實作任務
用 boto3 呼叫 Claude：傳入「我家馬桶不通」，要求回傳 JSON `{service_type, missing_fields}`。

### 求職價值：DS ○｜AIE ◎｜Infra ◎｜BE ○｜Cloud ◎

---

## AWS Lambda

### 這是什麼？
不用管伺服器的函式運行服務：上傳一段程式，有請求才執行、按次計費。

### 和本次黑客松的關係
把媒合 API（如 `search_vendor`）包成 Lambda，是架構圖上「serverless」的展示點；但 MVP 用 FastAPI 單體也能活。

### 是否必要？ **建議學（P1）**

### 需要學到什麼程度？
- 30 分鐘：懂觸發模型（API Gateway → Lambda → 回應）
- 2 小時：console 建一個 Python Lambda、測試事件、看 log
- 1 天：連 DB、打 Bedrock、部署依賴（layer 或容器）
- 不建議深入：VPC 內網、冷啟動優化、SAM/CDK 全套 IaC

### 最小實作任務
建一個 Lambda：輸入 `{county, service_type}`，回傳假的廠商排序 JSON。

### 求職價值：DS △｜AIE ○｜Infra ◎｜BE ◎｜Cloud ◎

---

## API Gateway

### 這是什麼？
把 Lambda（或其他後端）掛上一個公開 HTTPS 網址的服務，管路由、金鑰、流量。

### 和本次黑客松的關係
Lambda 的搭檔：讓前端與 MCP Server 能透過 URL 呼叫媒合 API。

### 是否必要？ **建議學（P1）**（跟 Lambda 綁定學）

### 需要學到什麼程度？
- 30 分鐘：懂 REST API vs HTTP API、stage 概念
- 2 小時：把 Lambda 掛上 HTTP API 並用 curl 打通
- 不建議深入：custom authorizer、usage plan、WAF

### 最小實作任務
把上面的 `search_vendor` Lambda 掛成 `POST /vendors/search` 公開端點。

### 求職價值：DS △｜AIE ○｜Infra ○｜BE ◎｜Cloud ◎

---

## DynamoDB

### 這是什麼？
AWS 的 serverless NoSQL key-value 資料庫，免管機器、毫秒級讀寫。

### 和本次黑客松的關係
可存對話 session 與案件；但官方 schema 是 PostgreSQL（jsonb/uuid），用 Postgres 對齊官方資料更省事。DynamoDB 當備選或存 session state。

### 是否必要？ **加分學（P2）**

### 需要學到什麼程度？
- 30 分鐘：懂 partition key / sort key、和 RDB 的差異
- 2 小時：boto3 put_item / get_item / query 一輪
- 不建議深入：GSI 設計、single-table design

### 最小實作任務
存一筆諮詢單 `{case_id, user_id, status, content}` 並用 case_id 查回。

### 求職價值：DS △｜AIE ○｜Infra ○｜BE ◎｜Cloud ◎

---

## RDS / PostgreSQL

### 這是什麼？
AWS 代管的關聯式資料庫服務；PostgreSQL 是業界最主流的開源 RDB。

### 和本次黑客松的關係
**官方 3 個 SQL 檔就是 PostgreSQL 語法（serial4、jsonb、timestamptz、bytea）**，直接 `psql -f` 匯入就有官方表結構。demo 用本機/容器 Postgres，架構圖上畫 RDS。

### 是否必要？ **必學（P0，PostgreSQL 本體）／RDS 本身 P2**

### 需要學到什麼程度？
- 30 分鐘：能啟一個 Postgres（Docker 一行）、匯入官方 SQL
- 2 小時：SELECT/INSERT/JOIN、查 jsonb 欄位（`->>`）
- 1 天：用 Python（SQLAlchemy 或 psycopg）做 CRUD
- 不建議深入：RDS 高可用、效能調參、備份策略

### 最小實作任務
`docker run postgres` → 匯入官方 3 個 SQL 檔 → 插入一筆 `pms_form_feedback` 並 JOIN `sys_district` 查出區域名稱。

### 求職價值：DS ◎｜AIE ◎｜Infra ◎｜BE ◎｜Cloud ○

---

## S3

### 這是什麼？
物件儲存：丟檔案給你一個 URL，近乎無限容量。

### 和本次黑客松的關係
存使用者上傳的報修照片（官方 feedback 範例中的圖片就是存 bucket 路徑 `/pic-inbr-test-bucket-1/form-feedbacks/upload-imgs/...`），也可托管靜態前端。

### 是否必要？ **必學（P0）**

### 需要學到什麼程度？
- 30 分鐘：bucket / key / presigned URL 概念
- 2 小時：boto3 上傳照片、產 presigned URL 給前端顯示
- 不建議深入：生命週期、跨區複製、事件觸發

### 最小實作任務
上傳一張馬桶照片到 bucket，把路徑寫進諮詢單、前端能顯示。

### 求職價值：DS ○｜AIE ○｜Infra ◎｜BE ◎｜Cloud ◎

---

## Amplify

### 這是什麼？
AWS 的前端托管＋CI/CD 服務：連 GitHub repo 自動 build 部署，給你 HTTPS 網址。

### 和本次黑客松的關係
若前端是靜態網站（React build 產物），Amplify 是最快拿到「Live Demo 部署網址」的方法之一。但部署環境以 7/18 公布的 EDIMUS/Ademus 為準，先不押注。

### 是否必要？ **加分學（P2）**
### 需要學到什麼程度？
- 30 分鐘：懂「連 repo → 自動部署」流程即可
- 不建議深入：Amplify Studio、DataStore 全家桶

### 最小實作任務
把一個 hello-world 靜態頁部署出公開網址。

### 求職價值：DS △｜AIE △｜Infra △｜BE ○｜Cloud ○

---

## CloudFront

### 這是什麼？
CDN：把內容快取到全球邊緣節點加速。

### 和本次黑客松的關係
架構圖上放在前端前面顯專業；黑客松規模下實質效益為零。

### 是否必要？ **可忽略（P3）**——架構圖畫出來、口頭講得出「靜態資源快取」即可。

---

## Cognito

### 這是什麼？
AWS 的使用者註冊／登入／JWT 發放服務。

### 和本次黑客松的關係
消費者端與廠商後台的登入。demo 用寫死的兩個測試帳號＋簡單 session 即可，Cognito 講在「未來架構」。

### 是否必要？ **可忽略（P3）**（簡報提到即可）

---

## CloudWatch

### 這是什麼？
AWS 的 log 與監控中心，Lambda/Bedrock 呼叫紀錄都自動進來。

### 和本次黑客松的關係
除錯 Lambda 必用；簡報可講「所有 AI 呼叫留有審計軌跡」。

### 是否必要？ **建議學（P1，被動會用到）**
### 需要學到什麼程度？
- 30 分鐘：會找到 Lambda 的 log group 看錯誤訊息——夠了。

### 最小實作任務
故意讓 Lambda 拋錯，在 CloudWatch Logs 找到 traceback。

### 求職價值：DS △｜AIE ○｜Infra ◎｜BE ○｜Cloud ◎

---

## IAM

### 這是什麼？
AWS 的權限系統：誰（user/role）能對什麼資源做什麼操作。

### 和本次黑客松的關係
繞不開：Lambda 要讀 S3、打 Bedrock 都需要 role。學到「會排錯 AccessDenied」即可。

### 是否必要？ **必學（P0，最小限度）**
### 需要學到什麼程度？
- 30 分鐘：principal / role / policy 三概念、不要用 root、優先使用暫時憑證
- 2 小時：給 Lambda 掛上 Bedrock＋S3 權限的 managed policy
- 不建議深入：SCP、跨帳號；但正式部署應逐步從 managed policy 收斂為最小權限

### 最小實作任務
使用主辦方提供的 session 或 IAM Identity Center 登入，確認
`aws sts get-caller-identity` 後成功呼叫一次 Bedrock。長期 access key 不得放入
`.env`、原始碼或 GitHub。

### 求職價值：DS △｜AIE ○｜Infra ◎｜BE ○｜Cloud ◎

---

## Amazon Transcribe

### 這是什麼？
語音轉文字（STT）服務，支援中文。

### 和本次黑客松的關係
銀髮語音模組的核心 AWS 展示點。瀏覽器 Web Speech API 當保底、Transcribe 上架構圖。

### 是否必要？ **加分學（P2，若選語音模組則 P1）**
### 需要學到什麼程度？
- 2 小時：上傳一段 wav 到 S3 → 開 transcription job → 取回文字（batch 模式就好，streaming 不要碰）

### 最小實作任務
錄一句「我想找人打掃」，Transcribe 轉出正確中文。

### 求職價值：DS △｜AIE ○｜Infra △｜BE △｜Cloud ○

---

## Amazon Polly

### 這是什麼？
文字轉語音（TTS），有中文聲音。

### 和本次黑客松的關係
高齡模式「唸出回覆」。錦上添花。

### 是否必要？ **加分學（P2）**——2 小時內可完成一次合成，demo 播放一句即可。

---

## Amazon Textract

### 這是什麼？
文件 OCR 服務（表格、表單抽取），中文支援有限。

### 和本次黑客松的關係
處方籤場景才用；Claude 多模態直接讀圖通常更簡單且中文更好。

### 是否必要？ **可忽略（P3）**——需要 OCR 時優先用 Bedrock 多模態。

---

## Amazon Rekognition

### 這是什麼？
影像辨識服務（物件、人臉、標籤）。

### 和本次黑客松的關係
判斷報修照片理論上可用，但 Claude 多模態一次搞定且能輸出結構化 JSON。

### 是否必要？ **可忽略（P3）**

---

## SageMaker

### 這是什麼？
自建／訓練／部署 ML 模型的全家桶平台。

### 和本次黑客松的關係
無：本題不需要訓練模型。簡報別亂放，會被追問。

### 是否必要？ **可忽略（P3）**（求職上 DS/Infra ◎，但那是賽後的事）

---

## Step Functions

### 這是什麼？
用狀態機圖形編排多個 Lambda／服務的工作流服務。

### 和本次黑客松的關係
「未來架構」素材：媒合→通知→逾時重派 的編排可以畫給評審看，不要真做。

### 是否必要？ **可忽略（P3，簡報詞彙）**

---

# B. Agent / Tool / MCP 相關

## MCP Server

### 這是什麼？
Model Context Protocol：Anthropic 開源的「AI 工具接口標準」，讓任何 Agent 用統一協定呼叫你的工具（類似 AI 界的 USB 規格）。

### 和本次黑客松的關係
**命題明定任務：自行設計 API 並包成標準 MCP Server，供 Lumine one 等外部 Agent 調用。這是必做項。** 官方指定參考 github.com/modelcontextprotocol/servers。

### 是否必要？ **必學（P0）**

### 需要學到什麼程度？
- 30 分鐘：懂 tools/resources 概念、stdio vs HTTP transport
- 2 小時：用 Python SDK（FastMCP）寫一個帶 2 個 tool 的 server，用 MCP Inspector 測通
- 1 天：早期估計可包 6–8 個候選 tools；目前實際完成四個唯讀 tools
- 不建議深入：sampling、roots、多 server 編排

### 最小實作任務
`pip install mcp` → 寫 `search_vendor(county, service_type)` tool → 用 `npx @modelcontextprotocol/inspector` 呼叫成功。

### 求職價值：DS ○｜AIE ◎｜Infra ◎｜BE ◎｜Cloud ○（2025 起大廠 Agent 基建標配）

---

## Function Calling / Tool Calling

### 這是什麼？
讓 LLM 輸出「我要呼叫某函式＋參數」的結構化回應，由你的程式執行後把結果餵回去。

### 和本次黑客松的關係
Agent 迴圈的心臟：判型、取表單、填單、媒合全靠它。MCP 只是 tool calling 的標準化外皮。

### 是否必要？ **必學（P0）**
### 需要學到什麼程度？
- 2 小時：用 Bedrock Converse API 定義一個 tool、跑通「模型要求呼叫→執行→回填→模型總結」迴圈
- 1 天：多工具、多輪、錯誤處理

### 最小實作任務
定義 `classify_service_type` tool，讓 Claude 對「冷氣不冷了」正確呼叫並回傳分類。

### 求職價值：DS ○｜AIE ◎｜Infra ◎｜BE ◎｜Cloud ○

---

## REST API

### 這是什麼？
用 HTTP 動詞（GET/POST/...）操作資源的 API 設計慣例。

### 和本次黑客松的關係
前端↔後端、MCP tool↔內部服務全是 REST。命題也說服務用 HTTP/REST 封裝皆可。

### 是否必要？ **必學（P0，基本功）**——2 小時能用 FastAPI 開出並用 curl 測 CRUD 即可。

### 求職價值：全職缺 ◎

---

## n8n

### 這是什麼？
開源的可視化工作流自動化工具（Zapier 類）。

### 和本次黑客松的關係
可拉「新諮詢單→通知廠商」的流程，但引入新工具的學習與部署成本高於自己寫 20 行 Python。

### 是否必要？ **可忽略（P3）**——除非工作坊宣布指定使用。

---

## Lumine AI（Lumine one）

### 這是什麼？
命題方提到的外部 Agent 平台（統一資訊生態），會來調用你們的 MCP Server。公開資料少。

### 和本次黑客松的關係
你們 MCP Server 的「假想客戶」。現階段無從自學，7/18 工作坊必問。

### 是否必要？ **等工作坊（暫 P2）**——先把 MCP Server 做標準，任何客戶端都能接。

---

## Kiro

### 這是什麼？
AWS 推出的 AI IDE（spec-driven development：先寫規格再由 AI 生成程式），類似 Cursor。

### 和本次黑客松的關係
**明定加分項 +5%**，且會查 log 與 GitHub 紀錄，不能只口頭聲稱。用它開發部分模組並留下 `.kiro/` spec 檔與 commit 紀錄。

### 是否必要？ **必學（P0，加分導向）**
### 需要學到什麼程度？
- 2 小時：安裝、登入、用 spec 模式生成一個小模組（如廠商後台頁面）、觀察它留下什麼檔案
- 不建議深入：拿它寫核心 agent 邏輯（除錯成本可能高於自寫）

### 最小實作任務
用 Kiro 生成「案件列表頁」，把 spec 檔與程式 commit 進 GitHub。

### 求職價值：DS △｜AIE ○｜Infra △｜BE ○｜Cloud △（會用 AI IDE 是通用加分）

---

## EDIMUS / Ademus

### 這是什麼？
主辦指定的部署環境，規格 7/18 工作坊公布，目前公開資訊近乎零。

### 和本次黑客松的關係
最終成果需部署其上——**這是最大的未知風險**。對策：一切服務容器化（Docker），任何環境都能跑。

### 是否必要？ **等工作坊（P0 級關注、暫無法學）**

---

## LangChain

### 這是什麼？
LLM 應用開發框架（鏈、工具、記憶、RAG 組件）。

### 和本次黑客松的關係
本題工具數少、流程可控，直接用 boto3＋自寫迴圈更透明好除錯。框架抽象層在黑客松除錯時是負債。

### 是否必要？ **可忽略（P3）**——履歷上想寫，賽後再補。

---

## LangGraph

### 這是什麼？
LangChain 家的狀態圖 agent 編排框架（節點＝步驟、邊＝轉移）。

### 和本次黑客松的關係
對話狀態機（分類→追問→確認→送單）理論上適用，但兩人時間內自寫 while 迴圈＋state dict 更快。

### 是否必要？ **可忽略（P3）**（求職 AIE ◎，賽後值得學）

---

## LlamaIndex

### 這是什麼？
以「資料接入＋檢索」見長的 LLM 框架。

### 和本次黑客松的關係
本題 RAG 需求輕（廠商庫用 SQL 查即可），不需要。

### 是否必要？ **可忽略（P3）**

---

# C. 前後端與資料工程

## FastAPI

### 這是什麼？
Python 最主流的現代 Web API 框架，async、自動文件、Pydantic 驗證。

### 和本次黑客松的關係
你們的後端本體：對話 endpoint、諮詢單 CRUD、媒合 API、廠商後台 API 全部用它。**Python 團隊的最重要工具**。

### 是否必要？ **必學（P0）**
### 需要學到什麼程度？
- 2 小時：GET/POST、Pydantic model、自動 /docs 測試
- 1 天：連 Postgres、掛 Bedrock 呼叫、CORS、檔案上傳

### 最小實作任務
做 `POST /create_case`：收 JSON、驗證、寫 DB、回 case_id。

### 求職價值：DS ○｜AIE ◎｜Infra ◎｜BE ◎｜Cloud ○

---

## Next.js / React

### 這是什麼？
業界最主流的前端框架（React）與其全端框架（Next.js）。

### 和本次黑客松的關係
你們沒有前端經驗，**不建議手學**；但可以讓 Kiro/Claude 生成 React 前端（同時賺 Kiro 加分），你們只改文案與串 API。

### 是否必要？ **加分學（P2，AI 代寫模式）**
### 需要學到什麼程度？
- 30 分鐘：懂 component/props/fetch 概念，能看懂 AI 生成的程式碼並改壞掉的地方
- 不建議：從零學 hooks、狀態管理、SSR

### 最小實作任務
讓 Kiro 生成一個聊天 UI 頁面，成功打到你的 FastAPI `/chat`。

### 求職價值：DS △｜AIE ○｜Infra △｜BE ○｜Cloud △

---

## Node.js / Express

### 這是什麼？
JavaScript 後端運行環境與極簡 Web 框架。

### 和本次黑客松的關係
你們是 Python 隊，後端無理由用 Node。唯一例外：官方 MCP 範例庫部分是 TypeScript——看得懂即可，寫用 Python SDK。

### 是否必要？ **可忽略（P3）**

---

## Streamlit

### 這是什麼？
用純 Python 快速做資料應用 UI 的框架（`st.chat_message` 幾行就有聊天介面）。

### 和本次黑客松的關係
**你們的保底前端**：消費者聊天頁＋廠商後台（表格、狀態按鈕、圖表）都能純 Python 完成，統計系隊友也能上手改。DS 圈（含大廠資料團隊）真實在用，履歷不丟人。

### 是否必要？ **必學（P0）**
### 需要學到什麼程度？
- 2 小時：chat UI、dataframe 表格、button/selectbox、session_state
- 1 天：多頁 app（消費者頁＋廠商頁）、串 FastAPI、上傳圖片

### 最小實作任務
`st.chat_input` 收訊息 → 呼叫 Bedrock → `st.chat_message` 顯示回覆。

### 求職價值：DS ◎｜AIE ○｜Infra △｜BE △｜Cloud △

---

## Gradio

### 這是什麼？
與 Streamlit 類似的 ML demo UI 框架，強在模型 I/O 展示。

### 和本次黑客松的關係
與 Streamlit 二選一即可；Streamlit 的多頁與表格更適合「後台」需求。

### 是否必要？ **可忽略（P3，選了 Streamlit 就不用）**

---

## PostgreSQL（見 A 節 RDS/PostgreSQL）
**必學（P0）**——官方 schema 原生格式，理由同前。

## SQLite

### 這是什麼？
單檔案嵌入式資料庫，Python 內建。

### 和本次黑客松的關係
Postgres 掛掉時的逃生門（把 jsonb 當 TEXT 存）。先用 Postgres，不行再降級。

### 是否必要？ **加分學（P2，備援）**——你們大概已經會了。

---

## Docker

### 這是什麼？
把程式＋依賴打包成可在任何機器一致運行的容器。

### 和本次黑客松的關係
三個用途：一行啟動本機 Postgres；把 FastAPI 打包成 image 應對未知的 EDIMUS/Ademus 環境；隊內環境一致。**面對未知部署環境的最大保險**。

### 是否必要？ **必學（P0）**
### 需要學到什麼程度？
- 30 分鐘：image/container/port mapping 概念
- 2 小時：`docker run postgres`、為 FastAPI 寫 10 行 Dockerfile、`docker compose up` 起全套
- 不建議深入：多階段構建優化、k8s

### 最小實作任務
`docker compose up` 同時起 Postgres＋FastAPI，curl 打通。

### 求職價值：DS ○｜AIE ◎｜Infra ◎｜BE ◎｜Cloud ◎

---

## GitHub

### 這是什麼？
程式碼托管與協作平台。

### 和本次黑客松的關係
**交付項目**：評審會看 repo；Kiro 加分也要在 repo 留痕。兩人協作 branch→PR→merge 基本流即可。

### 是否必要？ **必學（P0，你們應已會）**——補：README 寫法（架構圖、安裝步驟、demo 連結）。

### 最小實作任務
建 repo、雙人各發一個 PR 互相 merge、寫出含架構圖的 README 骨架。

---

## GitHub Actions

### 這是什麼？
GitHub 內建 CI/CD：push 時自動跑測試／部署。

### 和本次黑客松的關係
錦上添花（自動跑 pytest 或 build image）。時間緊就跳過。

### 是否必要？ **有時間再學（P2）**——一個 20 行的 pytest workflow 即可講「我們有 CI」。

---

## Prisma / SQLAlchemy

### 這是什麼？
ORM：用程式物件操作資料庫。Prisma 是 TS 生態、SQLAlchemy 是 Python 生態。

### 和本次黑客松的關係
SQLAlchemy（或更輕的 `psycopg` 裸 SQL）連 Postgres。官方表已存在，用 SQLAlchemy Core／裸 SQL 比 ORM 映射省事。

### 是否必要？ **建議學（P1，SQLAlchemy 淺用）**——2 小時會 engine、execute、參數化查詢即可。Prisma 忽略。

### 求職價值：DS ○｜AIE ○｜Infra ○｜BE ◎｜Cloud △

---

## Tailwind CSS

### 這是什麼？
utility-class 風格的 CSS 框架。

### 和本次黑客松的關係
只在 AI 生成 React 前端時間接出現；你們不需要手寫。

### 是否必要？ **可忽略（P3）**

---

# D. AI / 資料科學

## RAG

### 這是什麼？
檢索增強生成：回答前先從知識庫撈相關內容塞進 prompt。

### 和本次黑客松的關係
輕量用法：維修知識庫（馬桶不通的處理方式與注意事項）讓追問更專業。本題非 RAG 主戰場，媒合用 SQL 就好。

### 是否必要？ **加分學（P2）**——會「查表→塞 prompt」的樸素 RAG 即可，不必上向量庫。

### 求職價值：DS ◎｜AIE ◎｜Infra ○｜BE ○

---

## Embedding

### 這是什麼？
把文字轉成語意向量，相似內容向量相近。

### 和本次黑客松的關係
餐廳／商品語意檢索可用（Bedrock Titan embedding）；規模小時 LLM 直接選品也行。

### 是否必要？ **加分學（P2）**——2 小時會算向量＋cosine 相似度排序即可。

---

## Vector Database

### 這是什麼？
專存向量、做近鄰搜尋的資料庫（pgvector、Pinecone…）。

### 和本次黑客松的關係
資料量 <1000 筆，numpy 算 cosine 就夠；想加分用 pgvector（還在 Postgres 生態內）。

### 是否必要？ **可忽略（P3）**，pgvector 選配。

---

## Intent Classification

### 這是什麼？
判斷使用者輸入屬於哪類意圖（本題：六大服務類型＋閒聊/其他）。

### 和本次黑客松的關係
對話入口第一步，用 Claude＋few-shot prompt 完成（不訓模型），輸出必須是受控 enum。

### 是否必要？ **必學（P0，prompt 技能）**
### 最小實作任務
寫一個 prompt，對 20 句測試語料分類正確率 ≥ 18/20（統計系可做混淆矩陣——簡報素材）。

### 求職價值：DS ◎｜AIE ◎

---

## Slot Filling

### 這是什麼？
從對話中抽取結構化欄位（地區、時段、預算），缺的欄位觸發追問。

### 和本次黑客松的關係
**本題 AI 核心**：把對話對映到 `pms_form_topic` 題目、判斷缺漏、生成追問。做得好壞直接決定作品高度。

### 是否必要？ **必學（P0）**
### 最小實作任務
給定清潔表單 5 個必填題，對話兩輪後輸出 `{filled: {...}, missing: [...], next_question: "..."}`。

### 求職價值：DS ◎｜AIE ◎

---

## Recommendation System

### 這是什麼？
依條件／行為排序推薦項目。

### 和本次黑客松的關係
媒合引擎＝規則計分排序（地區符合 +3、子類型專長 +2、評分 ×1、可服務時段 +1）。**不要上協同過濾**——資料是假的，講規則反而誠實可信。統計系負責設計計分公式與展示。

### 是否必要？ **必學（P0，規則版）**
### 最小實作任務
對 20 家假廠商依（地區、類型、評分）排序並輸出「推薦理由」欄位。

---

## Synthetic Data Generation

### 這是什麼？
用 LLM／程式生成擬真假資料。

### 和本次黑客松的關係
命題明說「可自行生成數據資料」：廠商庫、餐廳庫、歷史訂單、對話語料全靠它。品質＝demo 質感。

### 是否必要？ **必學（P0）**
### 最小實作任務
用 Claude 批量生成 20 家清潔／水電廠商 JSON（名稱、服務區、專長、評分、簡介），入庫。

### 求職價值：DS ◎｜AIE ○（LLM 生資料是實務常用技能）

---

## OCR
見 Textract／多模態。**可忽略（P3）**——需要讀圖時用 Claude 多模態。

## Speech-to-Text
見 Transcribe。**加分學（P2）**；Web Speech API 為保底方案（免費、即時、瀏覽器原生）。

## Text-to-Speech
見 Polly。**加分學（P2）**。

## Image Understanding

### 這是什麼？
讓多模態 LLM 直接理解照片內容。

### 和本次黑客松的關係
報修照片判斷（「這是馬桶堵塞還是漏水？」）＝demo 記憶點。Claude 一個 API 呼叫完成。

### 是否必要？ **建議學（P1，選修繕場景則 P0）**
### 最小實作任務
傳一張水管照片給 Bedrock Claude，回傳 `{problem_type, severity, suggested_service}` JSON。

---

## PII Encryption / Hashing ＋ AES-256-GCM

### 這是什麼？
AES-256-GCM＝帶完整性驗證的對稱加密；hash＝單向摘要，加密後仍可等值查詢用。

### 和本次黑客松的關係
**官方 schema 直接內建**：`contact_name bytea`（密文）＋`contact_name_hash`（查詢用）。照做＝證明你們讀懂了官方資料設計。Python `cryptography` 套件 15 行搞定。

### 是否必要？ **必學（P0，小時級投資、高報酬）**
### 需要學到什麼程度？
- 2 小時：AESGCM 加解密一個姓名欄位＋SHA-256 hash 查詢，寫成 `encrypt_pii()/hash_pii()` 兩個函式全專案共用
- 不建議深入：KMS 金鑰輪替（口頭講未來用 KMS 管金鑰即可）

### 最小實作任務
姓名「王小明」加密入庫 → 用 hash 反查該筆 → 解密顯示；後台未授權視角顯示「王○明」遮罩。

### 求職價值：BE ◎｜Infra ◎｜Cloud ○（資安意識是面試加分題）

---

## Evaluation / Test Cases

### 這是什麼？
系統化驗證 AI 行為：固定測試語料＋預期輸出＋通過率。

### 和本次黑客松的關係
固定分類案例、實際通過率與錯誤分析會是很有價值的技術證據；目前尚未完成
固定 HF eval，不能預先寫成 95%。

### 是否必要？ **必學（P0）**
### 最小實作任務
建 `eval_cases.json`（20 條輸入＋預期分類），寫 30 行腳本跑通過率、輸出表格。

### 求職價值：DS ◎｜AIE ◎（LLM eval 是 2025-26 最熱門技能之一）

---

# 總結：你們的工具學習優先順序（10 個以內）

按「實用性 > 難易度 > 其他」排序，資工＝A、統計＝B：

| # | 工具 | 級別 | 建議負責 | 一句話理由 |
|---|---|---|---|---|
| 1 | Amazon Bedrock（含 tool use） | P0 | A 主、B 跟 | 全系統大腦＋AWS 架構圖核心，AIE 求職硬通貨 |
| 2 | FastAPI | P0 | A | Python 後端業界標準，所有 API 的家 |
| 3 | MCP Server（Python SDK） | P0 | A | 命題必做項，2026 求職新標配 |
| 4 | PostgreSQL（Docker 起） | P0 | B 主、A 跟 | 官方 schema 原生格式，DS/BE 通用技能 |
| 5 | Streamlit | P0 | B | 無前端經驗的最短路徑，DS 實務常用 |
| 6 | Prompt 工程三件套（分類/slot filling/摘要） | P0 | B 主、A 跟 | 本題 AI 品質的決定因素 |
| 7 | Docker（compose） | P0 | A | 對抗未知部署環境的保險 |
| 8 | Kiro | P0 | 兩人 | +5% 白給分，須留 log 與 repo 痕跡 |
| 9 | AES-256-GCM＋hash（cryptography 套件） | P1 | A | 官方 schema 內建要求，2 小時完成 |
| 10 | Lambda＋API Gateway | P1 | A | 架構圖 serverless 展示點，各包一支即可 |

> S3、IAM 不單獨列——學 Bedrock 與照片上傳時自然會碰到，屬於「順路學」。
> LangChain/LangGraph/SageMaker/n8n/Textract：**這次全部跳過**，賽後有興趣再補。
