# technical_strategy.md — 技術架構方案（3 套）

> **2026-07-26 更新**：本文件保留早期三案比較供決策追溯。工作坊完整資料與
> AgentCore 路線確認後，現在採用的實作架構以
> [architecture.md](architecture.md) 為唯一準則；兩份內容衝突時，以該文件為準。
> Lambda 與 API Gateway 已降為選配，不是為了增加 AWS 方塊而必做。
>
> 選型原則（依你們指定的優先序）：
> 1. **實用性**：大廠在用、對 DS／AI Engineer／AI Infra 求職有幫助
> 2. **難易度**：兩人、無 AWS 經驗、中低時間內能完成
> 3. 其他：美觀、擴充性、炫技
>
> 共通前提：官方 schema 是 PostgreSQL；MCP Server 是命題必做項；部署環境（EDIMUS/Ademus）7/18 才公布 → **一切容器化是三套方案共同的保險**。

---

## 方案一：全 Python 單體 MVP（最低風險）

### 適用情境
時間最緊、或 7/18 後發現部署環境限制很多時的保底方案；也是任何情況下的第一階段骨架。

### 技術棧
| 層 | 選擇 |
|---|---|
| Frontend | Streamlit（消費者聊天頁＋廠商後台頁，同一 app 兩個 page） |
| Backend | FastAPI（單一服務：對話、諮詢單、媒合、狀態 API） |
| Database | PostgreSQL（Docker 容器，匯入官方 3 個 SQL 檔） |
| AI Model | Amazon Bedrock — Claude（Converse API＋tool use＋多模態） |
| MCP | Python MCP SDK（FastMCP），與 FastAPI 共用同一套 service 函式 |
| Deployment | Docker Compose（postgres＋api＋ui 三容器），部署到官方指定環境或任一台 VM |
| Auth | 寫死的 demo 帳號（消費者×1、廠商×2）＋簡單 session |

### 系統流程
```
User（文字/照片）
→ Streamlit Chat UI
→ FastAPI /chat
→ Bedrock Claude（tool use 迴圈）
   ├─ classify_service_type
   ├─ get_form_schema（讀 pms_form_topic）
   ├─ create_consultation_case（寫 pms_form_feedback，PII 加密）
   └─ search_vendor（規則計分排序）
→ PostgreSQL
→ Streamlit 廠商後台（案件列表＋AI 摘要＋狀態更新）

外部 Agent（Lumine one / Claude Desktop）
→ MCP Server（同一組 service 函式的另一個入口）
→ PostgreSQL
```

### 優點
- 兩人都能全棧參與（全 Python，統計系可直接改 Streamlit 與 prompt）
- 除錯半徑最小：一個 repo、一個 compose、本機全跑得起來
- 官方 SQL 直接匯入，資料層零翻譯成本
- MCP 與 Web 共用 service 層——「一份邏輯、兩個協定入口」本身就是好架構故事

### 缺點
- 架構圖上 AWS 元素少（只有 Bedrock＋S3），AWS 展示分偏弱
- Streamlit UI 上限明顯，觀賞性輸給 React 隊伍

### 風險
- Streamlit 的聊天互動客製化能力有限（打字動畫、氣泡樣式）——用「slot filling 進度面板」等資訊設計補觀賞性
- 單體掛掉全掛——demo 前準備好一鍵重啟腳本

### 適合我們嗎？
**完全適合**。這是兩人無 AWS 經驗、中低時間的量身方案，最壞情況下它就是決賽作品，而且已經滿足命題所有必做項。

### 推薦程度：★★★★★（5/5，作為第一階段骨架）

---

## 方案二：混合雲架構（中等完整度，推薦主方案）

### 適用情境
方案一骨架在 7 月中旬前打通後的升級型態；AWS 展示價值與完成度的最佳平衡點。**這是建議你們最終呈現的架構。**

### 技術棧
| 層 | 選擇 |
|---|---|
| Frontend | Streamlit（保底）；若 Kiro 生成順利，換成 React 聊天頁＋保留 Streamlit 當廠商後台 |
| Backend | FastAPI 容器（核心對話與 CRUD）＋ **2 支 Lambda**（`search_vendor` 媒合、`summarize_case` 摘要）掛 API Gateway |
| Database | PostgreSQL 容器（架構圖標註「production: RDS」）；照片存 **S3** |
| AI Model | Bedrock Claude（對話＋多模態＋摘要）；語音模組：瀏覽器 Web Speech API 保底＋ **Transcribe** 展示 |
| MCP | 同方案一，另加 HTTP transport（供外部 Agent 遠端調用） |
| Deployment | Docker Compose；前端若靜態化可上 Amplify 拿公開網址 |
| Auth | demo 帳號；簡報講 Cognito 為未來方案 |
| 監控 | CloudWatch（Lambda log）＝「AI 呼叫可審計」的故事 |

### 系統流程
```
User ──文字/語音/照片──▶ Web UI（React 或 Streamlit）
                            │
                            ▼
                    FastAPI（對話編排）
                            │
        ┌───────────────────┼─────────────────────┐
        ▼                   ▼                     ▼
  Bedrock Claude      S3（報修照片）      API Gateway
  （分類/追問/多模態）                        │
        │                                 ├─ Lambda: search_vendor
        ▼                                 └─ Lambda: summarize_case
  Tool Router（tool use 迴圈）                   │
        │                                       ▼
        ▼                                  CloudWatch Logs
  PostgreSQL（官方 schema＋PII AES-256-GCM）
        │
        ├──▶ 消費者端：案件狀態追蹤
        └──▶ 廠商後台：案件列表／AI 摘要／接案／狀態機

External Agent（Lumine one）──MCP protocol──▶ MCP Server ──▶ 同一組 service 層
```

### 優點
- 架構圖同時有 Bedrock、Lambda、API Gateway、S3、Transcribe、CloudWatch——足夠豐富且**每個都真的在用**（評審追問不心虛）
- Lambda 只包兩支無狀態純函式，是 serverless 最不容易踩雷的用法
- 求職素材完整：Bedrock＋Lambda＋MCP＋FastAPI＋Postgres 是 2026 AI 應用工程的標準組合
- 升級是增量的：任何一步失敗都能退回方案一

### 缺點
- 需要真的碰 AWS 帳號、IAM、部署——約多花 2–3 天學習
- 服務分散後，demo 現場的故障點變多

### 風險
- IAM 權限排錯可能吃掉半天 → 賽前 PoC 先打通一次（見 prototype_test_plan）
- Lambda 依賴打包（psycopg 等）有坑 → 媒合 Lambda 改為只查 API 不直連 DB，或用容器 image Lambda
- 現場網路不穩 → 所有雲端呼叫都留本機 fallback 開關

### 適合我們嗎？
**適合，但有前提**：方案一骨架必須在 7/22 前跑通，AWS 增量部分在 7 月下旬逐項疊加，疊不上去就砍。

### 推薦程度：★★★★☆（4.5/5，作為目標形態）

---

## 方案三：全託管 Serverless＋Bedrock Agents Classic（歷史方案，不採用）

### 適用情境
想在「AWS 原生程度」上壓過其他隊、且兩人中至少一人能全職投入時才考慮。

### 技術棧
| 層 | 選擇 |
|---|---|
| Frontend | React（Amplify Hosting＋CloudFront） |
| Backend | 全 Lambda（API Gateway 統一入口），無常駐服務 |
| Database | DynamoDB（案件、session）＋ S3；或 Aurora Serverless 對齊官方 schema |
| AI | **Bedrock Agents Classic**（託管 agent：action group 綁 Lambda、自動編排）＋ Knowledge Base |
| MCP | MCP Server 部署為容器（AgentCore／Fargate 類） |
| Auth | Cognito（真登入） |
| 編排 | Step Functions（案件狀態流轉） |

### 系統流程
```
User → CloudFront/Amplify（React）
→ API Gateway → Cognito 驗證
→ Bedrock Agent（託管編排）
   ├─ Action Group A：表單服務（Lambda 群）
   ├─ Action Group B：媒合服務（Lambda 群）
   └─ Knowledge Base（維修知識 RAG）
→ DynamoDB / Aurora
→ Step Functions（狀態流轉＋通知）
→ 廠商後台（另一個 React app）
```

### 優點
- AWS 展示分數天花板最高，架構圖最華麗
- Bedrock Agents Classic／Step Functions 的 AWS 原生整合程度高

### 缺點
- 每一個組件對你們都是新的：學習曲線×10
- Bedrock Agents Classic 的除錯體驗較黑盒，prompt 行為難控
- DynamoDB 偏離官方 PostgreSQL schema，資料故事變弱
- 本機幾乎無法完整重現，現場除錯全靠雲端 console

### 風險
- **做不完的機率超過五成**。任何一個 IAM／VPC／冷啟動問題都可能吃掉一整天
- Demo 依賴網路與多個雲服務同時正常

### 適合我們嗎？
**不適合且不採用**。目前改採自製 Agent＋AgentCore Runtime / Gateway；不要再把
Bedrock Agents Classic 畫進未來架構，以免和已選方案混淆。

### 推薦程度：★★☆☆☆（2/5，僅取素材）

---

## 最終推薦

**主架構＝方案二（混合雲），實作路徑＝先做方案一、增量升級。**

理由：
1. **對齊評分結構**：技術可行 25%＋完成度 15% 由方案一的穩定骨架保證；AWS 架構圖與技術亮點由方案二的 Bedrock／Lambda／S3／Transcribe 增量提供；商業 25% 靠官方 schema 對齊與生態系故事，與架構無關但被方案一的資料層直接支撐。
2. **對齊你們的求職優先序**：Bedrock、FastAPI、MCP、Postgres、Docker、Lambda 每一項都是大廠 AI 應用團隊的實際技術棧；LangChain 類框架與炫技組件全部剔除。
3. **對齊未知風險**：7/18 前你們不知道部署環境長怎樣。方案一/二的所有自建組件都在 Docker 裡，EDIMUS/Ademus 只要能跑容器或給一台 VM 就能落地；全託管的方案三反而被綁死在 AWS 帳號設定上。
4. **兩人分工自然**：資工＝FastAPI／MCP／AWS／Docker；統計＝Streamlit 後台／prompt 與 eval／合成資料／媒合計分與統計圖表。兩條線只在 API 介面交會，可平行開發。

**判斷點**：7/22 檢查——方案一閉環（對話→諮詢單→後台→狀態更新）是否 demo 得出來？是 → 開始疊方案二增量；否 → 鎖定方案一打磨到穩。
