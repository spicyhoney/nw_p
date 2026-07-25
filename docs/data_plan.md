# data_plan.md — 資料策略（含官方資料集實際分析結果）

> 狀態更新：官方資料集已到手並完成初步分析（2026-07-08）。本文件第 1 節是**實際分析結果**而非假設，後續節次據此設計。

---

## 1. 官方資料集分析結果與檢查清單

### 1.1 檔案清單（8 檔）

| 檔案 | 內容 | 狀態 |
|---|---|---|
| `諮詢單相關table.sql` | PostgreSQL DDL×7 表（動態表單引擎） | ✅ 已分析 |
| `mms_order_record.sql` | 訂單/訂位統一紀錄表 DDL＋完整狀態機註解 | ✅ 已分析 |
| `縣市區域檔.sql` | `sys_county`＋`sys_district` DDL | ✅ 已分析 |
| `相關主檔設定.json` | 6 服務商＋服務主檔（含 type 代碼表） | ✅ 已分析 |
| `諮詢單相關範例資料.json` | 各表 1–7 筆樣本（含一筆完整 feedback） | ✅ 已分析 |
| `order_record範例資料.json/.csv` | 99 筆（JSON）／221 筆（CSV）訂單 | ✅ 已分析 |
| `縣市區域範例資料.json` | 22 縣市＋約 200 行政區 | ✅ 已分析 |

### 1.2 核心結構：動態表單七表（諮詢單引擎）

```
pms_form（表單主檔，掛在 service_vendor_id 下）
 └─ pms_form_group（題組）
     └─ pms_form_topic（題目，10 種題型）
         ├─ pms_topic_option（選項：單價/數量/另行報價/feature 內含雙層子選項）
         ├─ pms_topic_media（題目輔助圖）
         └─ pms_topic_county_district_relation（地區題可選範圍 → sys_county/sys_district）
pms_form_feedback（諮詢單提交＝我們的核心寫入目標）
 ├─ feedback_content jsonb：{data:[{topicId, type, answerList:[{answer, answerId, countyCode, ...}]}], formId, calculations:{totalAmount}}
 ├─ PII 欄位成對出現：contact_name(bytea 密文)＋contact_name_hash（mobile/landline/email/address_detail 同構）
 └─ status、is_read（廠商後台的狀態欄位）
```

**10 種題型代碼**（`pms_form_topic.type`）：1 簡答、2 詳答、3 單選、4 複選、5 地區選單、6 上傳照片、7 備註說明、8 聯絡資料、9 日期、10 聯絡資料(不含地址)。
題目可帶 `feature` JSON：regex 驗證（範例有身分證格式）、`columnMapping`（答案直寫 feedback 主欄位，如 preferredContactTime）、雙層子選項（範例：馬桶→馬桶不通/馬桶無法沖水，附維修說明文字——**這就是修繕場景的官方實據**）。

### 1.3 訂單表 `mms_order_record` 重點

- `order_type`：01 服務訂單、02 訂位、03 預約、04 其他、05 商品訂單、06 訂餐
- **狀態機**（註解明定）：
  - 服務訂單（01）：11 待訂金 → 12 已付訂金待報價 → 13 已報價待同意 → 14 客戶同意 → 15 已驗收待尾款 → 80 完成／90 取消／98 部分退款／99 退款
  - 訂位（02）：01 待付款 → 02 待確認 → 03 已確認 → 04 進行中 → 70/80 完成
- OpenPoint 生態欄位：`order_points/used_points/earn_points/point_status`——**商業故事素材：完成服務發點數回流零售**
- `order_items` jsonb：範例為「現場勘驗費 $286，場勘時間 2026/06/25 09:00」
- PII 同樣密文＋hash 成對

### 1.4 範例資料分佈（99 筆 JSON 訂單）

| 維度 | 分佈 |
|---|---|
| order_type | **07×64（未定義！）**、01 服務訂單×21、02 訂位×12、06 訂餐×2 |
| order_status | 80 完成×54、99 退款×26、12 待報價×9、70×3、98×3、03×2、11×1、90×1 |
| service_id | 18×64（未在主檔）、17 水電修繕×15、9 餐廳訂位×12、1×5、16 美食外送×2、2×1 |

### 1.5 ⚠️ 發現的官方資料缺口（簡報與 Q&A 的彈藥）

1. **order_type=07、service_id=18、vendor_id=15 未在任何 schema 註解與主檔中定義**（64/99 筆！）——需自行擴充主檔補上定義（合理推測是寄件/包裹類，從 service_vendor 2「寄件」延伸；以你們的假設為準並在 README 註明）。
2. **沒有廠商明細表**：`service_vendor_id` 只有 ID 與名稱（清潔/寄件/餐廳訂位/商城購物/修繕服務/美食外送 6 家），無地區、評分、容量——**媒合引擎需要的 vendors 表要全部自建**（合成資料主戰場）。
3. **沒有使用者主檔**：只有 `inbr_account_id` uuid 散在單據中。
4. **縣市代碼是官方自定義**（01=台北市…非政府標準碼），地區題選項受 `pms_topic_county_district_relation` 限縮——媒合引擎必須用同一套代碼。
5. 範例 feedback 只有 1 筆完整案例（修繕）——對話→feedback_content 的組裝邏輯要靠自己大量生成測試。
6. 兩份訂單範例（JSON 99 筆 vs CSV 221 筆）筆數不同，以 CSV 為超集做統計、JSON 為結構參考。

### 1.6 剩餘檢查清單（拿到更多官方資料或工作坊後）
- [ ] 官方是否補發 ERD 圖檔與 YAML/README（說明會口頭承諾過）
- [ ] `pms_form_feedback.status` 的合法值域（目前只見 "1"）——需要自定義狀態字典
- [ ] order_type=07 官方定義
- [ ] AES-256-GCM 的金鑰管理慣例（自管即可，但確認是否有指定格式：範例 hash 是 base64、密文是 bytea）
- [ ] Lumine one 調用 MCP 的 transport 要求（stdio or HTTP）

---

## 2. 資料表設計建議

### 2.1 原則
**官方表照單全收（7＋1＋2 表直接匯入），缺的補自建表**。demo 資料庫 = 官方 schema ＋ 自建擴充，這句話本身就是簡報亮點。

### 2.2 自建擴充表

| 表 | 用途 | 重要欄位 | 加密/hash | Demo 需要真做？ |
|---|---|---|---|---|
| `vendors` | 廠商主檔（媒合對象） | vendor_id(對齊官方 service_vendor_id 值域)、name、service_types[]、rating、intro、capacity_per_day | 否（虛構商號） | ✅ 必做 |
| `vendor_service_areas` | 廠商可服務區域 | vendor_id、county_code、district_code（FK→sys_district） | 否 | ✅ 必做 |
| `vendor_reviews` | 評分明細 | vendor_id、rating、comment、cre_time | 否 | ⭕ 20 筆假資料即可 |
| `case_status_logs` | 案件狀態軌跡 | feedback_no、old_status、new_status、actor、note、ts | 否 | ✅ 必做（後台時間軸） |
| `notifications` | 使用者通知 | user_id、feedback_no、message、is_read、ts | 否 | ✅ 必做（閉環展示） |
| `users`（極簡） | demo 帳號 | user_id(uuid 對齊 inbr_account_id)、display_name、role(consumer/vendor)、elder_mode(bool) | 名字可加密示範 | ⭕ 3 個帳號寫死 |
| `chat_sessions` | 對話狀態 | session_id、user_id、state、collected_answers jsonb | 否 | ✅ 必做 |
| `eval_cases` | 測試語料 | utterance、expected_type、expected_slots | 否 | ⭕ JSON 檔亦可 |

官方表的使用姿勢：
- `pms_form_feedback`：**核心寫入目標**，PII 四組欄位照官方做加密＋hash（見第 5 節）
- `pms_form/topic/option`：為 demo 的 2 個場景各手工設計一張高品質表單（修繕表單直接擴充官方範例 form_id=9 的馬桶結構）
- `mms_order_record`：訂位/勘驗訂單寫入用；221 筆範例匯入供後台統計圖表
- `sys_county/sys_district`：媒合與地區題的唯一地理來源，不要自創代碼

## 3. Synthetic Data Generation 策略

| 資料 | 生成方式 | 量 | 注意 |
|---|---|---|---|
| 廠商（清潔/修繕各 10–15 家） | **LLM 批量生成**＋人工過目 | 25 家 | 虛構名（「安心水電坊」），禁真實品牌；地區覆蓋 demo 城市 2–3 區；評分常態分佈 3.5–4.9 |
| 餐廳（若做食場景） | LLM 生成（菜系/區域/價位/包廂/評分） | 50 家 | 名稱全虛構；區域用官方代碼 |
| 商品目錄（若做購物） | LLM 生成 | 100 品 | 品牌虛構 |
| 使用者對話語料 | **LLM 生成→人工挑選改寫**（persona×需求×口語程度矩陣） | 50–80 句 | 這是 prompt 調校與 eval 的原料，品質重於量 |
| 諮詢單歷史 | 程式組裝（隨機廠商×表單×答案）＋LLM 填自由文字欄 | 100 筆 | feedback_content 結構必須嚴格對齊官方範例 JSON |
| 訂單歷史 | **官方 221 筆為底**，補生成 200 筆拉長時間軸 | 400+ | 保持官方狀態機值域；金額分佈合理（勘驗費 ~300、清潔 2000–5000） |
| 案件狀態軌跡 | 程式依狀態機隨機推演 | 隨案件 | 時間間隔要像真的（接案 <2hr、勘驗隔天） |
| 對話紀錄（demo 重播用） | 人工精修 3 段黃金劇本 | 3 段 | demo 保命符，一字一句打磨 |
| 修繕知識片段（RAG 選配） | 從官方子選項 remark 擴寫（LLM） | 30 條 | 官方範例已有「通管機疏通…」文案風格可仿 |

分工：**統計系主導**（生成腳本、分佈合理性、資料字典），資工提供入庫管道。人工設計 vs LLM 生成的判斷線：**結構與分佈人工定，血肉 LLM 填**。公開資料（如政府區域資料）不需要——官方已給縣市檔。

## 4. 資料如何成為簡報亮點

1. **需求理解**：「20 條真實口語測試，意圖分類準確率 95%、slot 抽取 F1 0.9」＋混淆矩陣圖——用數字證明 AI 有效（統計系署名的一頁）
2. **服務媒合**：媒合計分公式攤開講（地區/專長/評分/時段加權），附一筆案例的計分明細表——透明可解釋，反而比黑盒 ML 加分
3. **商業洞察**：用官方 221 筆訂單畫圖——狀態漏斗（54% 完成、26% 退款→「退款率偏高，AI 追問把需求釐清在前端，預期降低錯配退款」）——**把官方資料的統計變成你們的價值主張**
4. **管理後台**：案件量/區域分佈/回應時長儀表板（Streamlit 三張圖）
5. **AI 摘要**：後台「10 秒讀懂一張單」對比原始 JSON——效率語言
6. **服務品質**：狀態軌跡表 → 平均接案時長、完成率 per 廠商 → 回饋媒合排序（飛輪故事）
7. **統一生態系**：訂單表的 points 欄位是現成鉤子——「服務完成發 OpenPoint，點數回 7-ELEVEN 消費，生活服務與零售互相導流」；並主動指出我們發現並補齊了 order_type=07 缺口（讀資料讀得深的證據）

## 5. 隱私與資安

- **個資欄位盤點**（官方 schema 既定）：姓名、手機、市話、Email、詳細地址（諮詢單＋訂單兩表、密文＋hash 成對）；demo 一律用假人名假電話
- **AES-256-GCM 講法**：「採官方 schema 規範的 AES-256-GCM——認證加密，密文不可讀且防竄改；每筆隨機 nonce」；實作：Python `cryptography` AESGCM，金鑰走環境變數，簡報註明「production 交由 AWS KMS 託管輪替」
- **hash 欄位用途**：密文無法 `WHERE` 查詢 → 以 SHA-256 hash 做等值查詢（「用手機號找客戶案件」查 hash 欄位）；demo 實際演示這條查詢路徑更加分
- **權限管理**：三角色（消費者/廠商/系統）；廠商只見自家案件；**LLM 永不接觸 PII 明文——摘要 tool 輸出遮罩（王○明、0912***678）**；MCP tool 白名單＝說明會特別點名的「MCP 權限管理」答案
- **Demo 要真做嗎**：**要，因為便宜**——兩個工具函式（encrypt/hash）約 2 小時，換來 DB 畫面秀密文＋hash 反查的 30 秒高光時刻
- **誠實呈現未做的部分**：簡報資安頁分兩欄「已實作：欄位級 AES-256-GCM、hash 查詢、角色隔離、LLM 遮罩」vs「Production 規劃：KMS 金鑰輪替、Cognito/UniOpen SSO、傳輸層 mTLS、審計告警」——誠實的邊界感是加分項，被追問時絕不謊稱已做
