# final_recommendation.md — 總結建議

> **歷史規劃文件**：這是 2026-07-08 的題目與技術棧建議，不代表目前程式狀態。
> 請以[專案白話指南](project-guide.md)、[實作索引](implementation-index.md)、
> [HANDOFF](../HANDOFF.md)與[TASKS](../TASKS.md)為準。

## 1. 最推薦的 Top 3 題目

| 排名 | 題目 | 為什麼 |
|---|---|---|
| 🥇 | **修繕小隊長**（拍照報修×動態諮詢單×報價媒合） | 官方資料重合度最高（馬桶子選項、勘驗費訂單、報價狀態機都是現成實據）；閉環完整、兩人可完成；照片判斷是低成本高記憶點的 demo 亮點 |
| 🥈 | **LifeHub 媒合中樞**（彈性諮詢單平台直球） | 零審題風險、切合度滿分；動態表單引擎是技術主打；缺記憶點需疊模組 |
| 🥉 | **銀髮語音模組**（疊加在前兩者之上） | 不獨立成題；作為第二幕彩蛋，用最小成本補創意分與觀賞性，且是命題明文鼓勵的方向 |

**建議形態**：LifeHub 骨架 ＋ 修繕作為深度示範場景（第二場景放清潔）＋ 銀髮語音當可砍彩蛋。工程量一份、故事三層。最終拍板與 persona 選擇留給你們（見第 6 節）。

## 2. 最推薦的技術棧（明確唯一解）

```
Frontend   : Streamlit（消費者聊天頁＋廠商後台）；Kiro 生成 React 聊天頁為選配升級
Backend    : FastAPI（Python）＋ service 層共用
AI         : Amazon Bedrock（Converse API：對話/tool use/多模態/摘要）
Agent      : 自製 Python Agent；AWS 目標為 AgentCore Runtime
MCP        : Python MCP SDK（FastMCP）＋ AgentCore Gateway，與 FastAPI 共用 service 層
Database   : 本機 PostgreSQL；正式環境目標為 RDS for PostgreSQL
AWS        : AgentCore Runtime / Gateway＋IAM＋CloudWatch；照片選配 S3
AWS 選配   : Lambda target×1；確有一般 REST API 需求才加 API Gateway
安全       : Python cryptography 做 AES-256-GCM＋SHA-256 hash（照官方欄位規格）
部署       : 本機可用原生 PostgreSQL 或 Docker；雲端依主辦方環境部署
協作       : GitHub（PR flow）＋ Kiro（留痕拿 +5%）
```
不用：LangChain/LangGraph、Bedrock Agents Classic、DynamoDB（主庫）、Cognito、
Step Functions、n8n。AgentCore Runtime / Gateway 是目前主架構，不要和
Bedrock Agents Classic 混為一談。

## 3. 最推薦優先學的工具（10 個）

1. Amazon Bedrock（Converse＋tool use）
2. FastAPI
3. MCP Python SDK
4. PostgreSQL（含 jsonb）
5. Streamlit
6. Prompt 三件套（意圖分類／slot filling／摘要）
7. Docker Compose
8. Kiro
9. AES-256-GCM＋hash（cryptography 套件）
10. AgentCore Runtime＋Gateway

## 4. 最推薦先做的 5 個 PoC（依序）

1. **T01 Bedrock 首呼**（取得憑證後確認 Region、model ID 與 IAM；選 Anthropic
   才需完成首次使用表單）
2. **T04 官方 SQL 匯入＋寫一筆諮詢單**（資料層地基＋讀懂官方結構）
3. **T02 Tool use 迴圈**（Agent 架構成立前提）
4. **T05 MCP Server 最小版**（命題必做項，早通早安心）
5. **T03 意圖分類 eval 20 句**（決定 demo 敢不敢開放輸入；統計系主場）

## 5. 本週行動清單（7/8–7/10，3 天）

**Day 1（今天）**
- [ ] 兩人各花 40 分鐘讀完 brainstorm.md＋final_recommendation.md，約定明晚拍板題目
- [ ] 取得/確認 AWS 帳號或主辦方暫時憑證，確認 Bedrock 指定 Region、model ID、
  額度與 AgentCore 權限
- [ ] 建 GitHub repo（含 docs/ 放本文件包）；依電腦環境選原生 PostgreSQL 或 Docker

**Day 2**
- [ ] 拍板：主體題目＋demo 的 2 個服務場景＋persona（人類決策，見第 6 節）
- [ ] A：PostgreSQL 起庫＋匯入官方 3 個 SQL 檔（T04 前半）
- [ ] B：手寫 20 句 eval 語料（六類服務＋3 個陷阱題）

**Day 3**
- [ ] A：boto3 第一次 converse 呼叫成功（T01）
- [ ] B：用分類 prompt 跑 20 句、記下準確率基線（T03 前半）
- [ ] 兩人同步 30 分鐘：對照 gantt_plan 第 0 週表，確認下週任務認領

## 6. 人類需要決定的事情（AI 不代決）

1. **最終題目與形態**：修繕主打 or 平台主打？語音模組做不做？
2. **Persona 與世界觀**：主角是誰（租屋青年/雙薪家庭/獨居長輩）、作品名稱、開場那句台詞——這是評審記住你們的地方
3. **Demo 的 2 個服務場景**選哪兩個（建議修繕＋清潔，但訂位也合理）
4. **砍功能的取捨時刻**：7/20、7/27、決賽 18h 三個凍結點，砍什麼由你們現場判斷（原則已寫在 gantt_plan）
5. **商業故事的口味**：主打「轉換率」還是「生態系點數飛輪」還是「高齡社會」——選你們講得最有熱情的那個
6. **分工邊界**：文件建議 A/B 分工是預設值，按實際興趣調整（誰想多碰 AWS、誰想主講簡報）

## 7. AI（我）接下來可以協助的事情

隨時開新對話丟給我：
- 寫 prompt：分類/slot filling/摘要/照片判斷的完整 system prompt＋few-shot
- 產假資料：25 家廠商、50 句語料、100 筆諮詢單的生成腳本與批量產出
- 設計 schema：自建表 DDL、feedback_content 組裝函式、加密工具函式
- 寫早期候選 API spec；目前實際契約是四個唯讀 MCP Tool
- 寫 code 骨架：FastAPI 專案結構、MCP server、Streamlit 雙頁 app、docker-compose.yml
- 寫 README、demo script 逐字稿、簡報每頁講稿
- 產測試案例：eval 擴充到 50 句＋自動跑分腳本
- 7/18 工作坊後：根據官方公布的環境規格即時調整部署方案
- 模擬評審：拿你們的簡報稿讓我提刁鑽問題

---
**一句話總結**：地基（Bedrock＋官方 schema＋閉環）在 7/20 前打穩，AWS 與亮點在 7/21–7/27 增量疊加，7/28 起只收斂不擴張——這個節奏下，你們兩人可以帶著一個「能跑、切題、講得出商業故事」的作品上台，同時把 Bedrock/FastAPI/MCP/Postgres/Docker 五個求職硬通貨寫進履歷。
