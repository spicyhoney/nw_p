---
inclusion: always
---
# 產品脈絡

## 判讀原則

- 本專案是既有、可執行的 baseline，不是空白專案。
- 完成狀態以實際程式、測試與 `docs/implementation-index.md` 為準；規劃文件不得覆蓋程式事實。
- 競賽要求與來源優先順序以 `competition-constraints.md` 為準。
- 本文件描述跨功能且相對穩定的產品脈絡；單一功能的 requirements、design 與 tasks 應另建 Spec。
- `competition-constraints.md` 尚未經人工確認前，不得產生 Feature Spec、implementation tasks 或開始產品實作。

## 產品目的與暫定主題

本專案參加 2026 雲湧智生黑客松「AI 生活管家：智慧社區服務需求理解與媒合平台」命題。MVP 聚焦居家水電修繕，以自然語言協助使用者理解服務、確認行政區、取得彈性諮詢表單、媒合服務商，並經雙方確認形成 Demo 案件與訂單。

目前產品主題暫定為：

> 台語友善、會主動補問、可隨時轉真人的高齡生活管家

「台語友善」、「主動補問」與「隨時轉真人」目前是下一階段方向，不得在 Demo、簡報或 Spec 中誤稱為已完成能力。

## 目標使用者

- **主要使用者方向**：高齡者、偏好台語或不熟悉多個 App 的使用者，以及需要低認知負擔引導的人。
- **次要使用者方向**：協助長輩處理生活服務的家人／照顧者；忙碌、需要一次安排多項家務的家庭。
- **服務供給端**：接收需求、查看案件並接受或拒絕指派的服務商／師傅。
- **外部整合端**：可透過標準 MCP 調用本平台有限能力的智慧管家或其他 Agent。

照顧者代理權、真人客服角色、正式服務商資格與不同使用者間的資料授權都尚未定案。

## 已由程式與測試確認的 baseline

截至 2026-08-01，本機完整測試實跑結果為 `134 passed, 18 skipped, 52 subtests passed`；skip 代表環境條件未具備，不可視為通過。

| 能力 | 現況與邊界 |
|---|---|
| 資料清洗 | 有可重複執行的清洗、來源標籤、隔離區、PostgreSQL migration／loader；未知代碼與斷裂關聯不猜測。 |
| 唯讀服務 | `ReadServiceLayer` 支援服務搜尋、行政區解析、最新唯一諮詢表單與可解釋的 synthetic 師傅媒合。 |
| MCP | 四個標準唯讀 Tools：`search_services`、`resolve_location`、`get_consultation_form`、`match_service_providers`；不建案、不保留時段、不建單。 |
| Agent | `AgentRunner` 可使用 deterministic Mock 或 Hugging Face hosted text model，經 MCP 進行多輪工具呼叫；有步數、白名單與錯誤遮罩。 |
| 消費者 Web | 可建立 process-local session、自然語言查詢、人工 Checklist、動態表單、時區化希望時段、synthetic 候選與明確確認派單。 |
| 服務商 Web | 兩個 synthetic Demo 身分可查看被指派案件、接受或拒絕；pending 僅見遮罩聯絡資料，accepted 才揭露 synthetic contact 並建立 `SYN-ORDER-*`。 |
| 寫入 workflow | `CaseWorkflowService` 有確認、冪等、稽核、授權投影與原子狀態轉換；案件 repository 可用 memory 或 PostgreSQL。寫入不經 MCP／LLM。 |
| 照片 | HF 模式可處理一張 JPEG／PNG／WebP（上限 8 MiB）；先正規化並移除 metadata，取得外部處理同意後送 VLM，結果須人工修正／確認並由服務目錄重驗。 |
| 無障礙 | 有鍵盤操作、live region、清楚 focus、約 44px 觸控目標、reduced-motion 與桌機／手機響應式基線。 |

## baseline 刻意未完成

- 台語／國語 Speech-to-Text、繁體中文轉寫確認與台語 Text-to-Speech。
- 可泛化的主動 slot filling；目前 Web 仍以 Agent 查詢加人工表單為主。
- 同一使用者的多項任務分流、各自狀態與跨次持久化。
- 真人轉接、客服工作台、轉接 SLA 或回呼機制。
- 服務商語言能力欄位及語言偏好媒合。
- 正式登入、RBAC、多租戶隔離、真實服務商、真實個資與正式時段保留。
- 點數制度、付款、通知、取消／退款與完整服務進度追蹤。
- Bedrock、AgentCore、RDS、S3 或任何公開 AWS 部署。
- Web 唯讀路徑的 PostgreSQL 切換；目前 Web 服務／地點／表單／媒合固定使用 synthetic `DemoReadRepository`。

## 產品價值

1. **降低表達與數位操作門檻**：讓使用者先說需求，再由系統以可核對資訊逐步補問。
2. **避免錯配與捏造**：行政區、服務、表單與候選必須來自受控資料與工具；不完整就追問。
3. **保留人的控制權**：外部處理、照片分析、派單及服務商決策都需要明確確認；未來加入真人出口。
4. **建立可信任閉環**：需求、媒合理由、遮罩／揭露、冪等與稽核可被解釋及重現。
5. **可擴充但不重寫規則**：模型、MCP transport、repository、媒體儲存與未來語音／AWS 都以 adapter 替換，商業規則留在 Service Layer。

## 後續 Spec 的產品規則

- 每個 Feature Spec 必須明列「目前已有」、「本次新增」、「刻意不做」與可驗證完成條件。
- 高齡友善不能只等同大字；需涵蓋清楚語言、低步驟、回顯確認、錯誤復原、真人出口與隱私理解。
- 不得以聊天次數、訊息數或延長使用時間作為點數來源。
- 不得把 synthetic 資料、Mock、單次 hosted-model smoke 或候選推薦宣稱為真實營運成效。
- 任何不可逆或有副作用的行為不得僅由模型文字觸發。
