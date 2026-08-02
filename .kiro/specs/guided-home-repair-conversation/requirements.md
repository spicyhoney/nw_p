# Requirements Document

## Introduction

本文件定義 `guided-home-repair-conversation` 的 Requirements-First P0 範圍。P0 僅支援既有 `service_id=17` 水電修繕與既有 `repair_form_v1`。`repair_form_v1` 的五個受控 `issue_category`：`faucet_leak`、`toilet_issue`、`pipe_issue`、`electrical_issue`、`other`，全部都是 P0 支援的 Validated_Repair_Branch。完整 E2E／Demo 固定以 `faucet_leak` 與 `electrical_issue` 作為代表性分支，不限制其餘三個分支的 P0 支援。

- **目前已有**：`search_services`、`resolve_location`、`get_consultation_form`、既有媒合、`CaseWorkflowService`、dispatch、Idempotency、Audit、PII／Authorization 邊界、Existing Photo Flow 及 `repair_form_v1`。
- **本次新增**：單一 Active Consultation Task、五個受控 Repair Branch 的路由與可恢復 Slot State、Branch 切換隔離、全部五個分支的 focused／HTTP 契約驗證，以及兩個固定代表分支的完整端到端驗收。
- **刻意不做**：第二個 Canonical Service、跨服務或多任務、語音、真人轉接、語言偏好媒合、點數、AWS、Production Auth／RBAC、新照片管線及 MCP Schema 變更。

## Glossary

- **引導式居家修繕對話系統**：本功能的受控對話與 Session 協調能力；負責路由、補問、狀態、摘要及既有 Service Layer／案件流程的串接。
- **P0_實作**：本文件核准範圍內的後續程式、設定、UI 與自動化測試變更。
- **Session**：一次消費者互動範圍。
- **Active_Consultation_Task**：Session 中唯一可接收回答、修正、照片、摘要確認及後續動作的修繕諮詢任務。
- **Canonical_Service_ID**：由目前請求的 `search_services` 或等價 Service Layer 規則驗證的正式服務識別碼；P0 唯一允許值為 `17`。
- **Repair_Branch**：`service_id=17` 的受控 `issue_category` 值；Repair Branch 不是 Service ID，Runtime 也不能從自由文字建立新值。
- **`repair_form_v1`**：本功能執行前已存在、隸屬 `service_id=17` 且具有版本識別的 Versioned Form；其受控 `issue_category` 為 `faucet_leak`、`toilet_issue`、`pipe_issue`、`electrical_issue` 與 `other`。
- **Validated_Repair_Branch**：已由 Service Layer 驗證存在於目前有效 `repair_form_v1` 且明確隸屬 `service_id=17` 的 Repair Branch；P0 的 Validated_Repair_Branch 恰為五個受控 `issue_category`。
- **Field_Applicability_Config**：本功能執行前已存在、經人工 review 且隨 `repair_form_v1` 版本化的欄位適用性設定；定義每個 Validated_Repair_Branch 可詢問、驗證、保存、摘要及提交的 Form Field。
- **`issue_description`**：`repair_form_v1` 中既有的問題詳述欄位；`other` 分支的內容保留為表單答案，不形成新的 Repair Branch。
- **`water_shutoff`**：`repair_form_v1` 中既有的水源關閉欄位；只有 Field_Applicability_Config 標記該欄位適用的目前分支才可處理該欄位。
- **Versioned_Form**：事先存在、經受控審查、具有版本識別且與 `service_id=17` 及適用 Repair Branch 相符的諮詢表單；P0 使用 `repair_form_v1`。
- **Routing_Contract**：服務與 Repair Branch 路由的結構化結果，包含 `confidence`、`alternatives`、`unsupported`、`clarification_question`、`canonical_service_id` 與 `repair_branch`。
- **Confidence**：Routing Contract 的字串列舉，唯一允許值為 `high`、`medium`、`low`。
- **Alternatives**：由 Service Layer 與受控 Versioned Form 驗證的候選 Repair Branch 集合。
- **Clarification_Question**：用於解決單一缺漏、歧義或矛盾的聚焦補問。
- **Unsupported**：非水電需求、P0 範圍外需求，或沒有任何有效 `service_id=17` Repair Branch 候選時的結構化結果。
- **Temporarily_Unavailable**：`service_id=17` 缺少有效 Versioned Form、適用 Repair Branch 或有效 Matching Data，因而無法安全繼續的結構化結果。
- **Slot_State**：Active Consultation Task 內各 Slot 的值、驗證狀態及回答狀態。
- **`skipped`**：使用者未提供答案或表示不知道時的 Slot 回答狀態；`skipped` 不包含推測值。
- **`declined_to_answer`**：使用者明確拒絕回答時的 Slot 回答狀態。
- **必要_Slot**：進入副作用前必須有效的資料，包括已確認服務與 Repair Branch、唯一縣市／行政區、排程、表單必填答案、Synthetic Contact 及目前摘要的明確確認。
- **排程**：有效日期與時段的組合，或使用者明確選擇的「時間彈性」。
- **Synthetic_Contact**：明確標示為展示／測試用途且不代表真實個人的聯絡資料。
- **摘要**：提交前回顯目前服務、Repair Branch、地點、排程、表單答案、選填欄位、Synthetic Contact、表單版本及資料狀態的結構化內容。
- **完整性規則**：判定必要 Slot 是否足以進入目前摘要確認、媒合、建案與派單的受控規則。
- **Service_Layer**：持有服務、地點、表單、媒合及案件商業規則的既有受控服務層。
- **`search_services`**：驗證服務候選及 Canonical Service ID 的既有唯讀能力。
- **`resolve_location`**：驗證縣市與行政區唯一結果的既有唯讀能力。
- **`get_consultation_form`**：讀取既有 Versioned Form 的唯讀能力。
- **Matching_Data**：由既有受控資料提供、可供既有媒合使用的服務商、availability 與媒合輸入。
- **`matching_v1`**：既有媒合政策版本；P0 不因 `urgent` 改變權重。
- **Runtime**：執行期間的 Agent、LLM 與對話協調程式；Runtime 輸出在通過結構驗證、Service Layer 驗證及必要使用者確認前不是業務事實。
- **受控_UI_API**：具輸入驗證、確認證據及 Service Layer 串接的 UI 或 HTTP API 入口。
- **明確摘要確認**：使用者透過受控 UI／API 對目前摘要版本作出的獨立肯定動作。
- **CaseWorkflowService**：既有案件建立、狀態轉換、冪等與稽核服務。
- **Dispatch**：透過既有案件 Workflow 將已確認案件交給候選服務商的受控副作用。
- **Idempotency**：相同已確認意圖重複提交時，維持一致結果且不重複建案或派單的既有保護。
- **Audit**：既有 Workflow 對確認、副作用、授權與冪等結果保存的可追溯紀錄。
- **Authorization_Projection**：依案件狀態與服務商身分限制可見資料的既有授權投影。
- **Existing_Photo_Flow**：既有照片上傳、私有儲存、外部處理同意、VLM 建議、使用者確認及服務目錄重驗流程。
- **安全停止**：停止一般媒合、建案與派單，並顯示受控原因及下一步的狀態。
- **人工核准安全內容**：由指定人員審查、版本化並核准後，才可由安全停止顯示的危險情境內容與官方聯絡資訊。
- **E2E_驗收套件**：透過受控 UI／API 與既有 Service Layer、案件 Workflow 驗證完整流程的自動化端到端測試集合。
- **Focused_HTTP_測試**：針對單一 Repair Branch 契約的 focused 自動化測試，以及透過受控_UI_API 執行的 HTTP 整合測試。

## Requirements

### Requirement 1: P0 單一服務與單一 Active Task

**User Story:** 身為需要水電修繕的使用者，我希望每個 Session 專注處理一項修繕任務，使補問、照片、摘要及派單不會混入其他服務或第二個任務。

#### Acceptance Criteria

1. THE P0_實作 SHALL 將 `service_id=17` 設為唯一支援的 Canonical_Service_ID。
2. THE P0_實作 SHALL 將 `service_id=4`、專業清潔、第二個 Canonical Service 及跨服務流程排除於支援範圍。
3. WHILE Session 存在 Active_Consultation_Task，THE 引導式居家修繕對話系統 SHALL 維持最多一個 Active_Consultation_Task。
4. WHEN 沒有 Active_Consultation_Task 的 Session 開始水電修繕諮詢，THE 引導式居家修繕對話系統 SHALL 建立一個 Active_Consultation_Task。
5. IF 使用者要求建立第二個任務或處理跨服務需求，THEN THE 引導式居家修繕對話系統 SHALL 保持現有 Active_Consultation_Task 數量不變並回傳 Unsupported。
6. IF 使用者需求不是水電修繕，THEN THE 引導式居家修繕對話系統 SHALL 回傳 Unsupported 並進入安全停止。

### Requirement 2: 受控服務與 Repair Branch 路由

**User Story:** 身為使用者，我希望服務與修繕問題分支只來自既有受控資料，使 LLM 無法捏造服務或分支。

#### Acceptance Criteria

1. WHEN 使用者描述修繕需求，THE 引導式居家修繕對話系統 SHALL 先透過 `search_services` 或等價 Service Layer 規則驗證 Canonical_Service_ID。
2. THE Routing_Contract SHALL 包含 `confidence`、`alternatives`、`unsupported`、`clarification_question`、`canonical_service_id` 與 `repair_branch` 欄位。
3. WHEN Routing_Contract 的 `canonical_service_id` 有值，THE 引導式居家修繕對話系統 SHALL 確保該值為目前請求驗證所得的 `17`。
4. WHEN Routing_Contract 的 `repair_branch` 有值，THE 引導式居家修繕對話系統 SHALL 確保該值為目前有效資料中的 Validated_Repair_Branch。
5. THE P0_實作 SHALL 將 `repair_form_v1` 的 `faucet_leak`、`toilet_issue`、`pipe_issue`、`electrical_issue` 與 `other` 全部支援為 Validated_Repair_Branch。
6. WHEN Runtime 提出不存在或未通過驗證的 Repair_Branch，THE 引導式居家修繕對話系統 SHALL 排除該 Repair_Branch 進入 Routing_Contract、Slot_State 與業務流程。
7. WHEN 使用者確認已驗證的 Canonical_Service_ID 與 Validated_Repair_Branch，THE 引導式居家修繕對話系統 SHALL 將確認結果保存於同一 Active_Consultation_Task。
8. WHEN 使用者確認 `other`，THE 引導式居家修繕對話系統 SHALL 要求使用者提供移除前後空白後非空白且不等於 `other` 選項值或標籤的 `issue_description`，並在該答案通過 `repair_form_v1` 驗證前保持表單不完整。
9. WHEN 已確認 `other` 的使用者提供通過 `repair_form_v1` 驗證的 `issue_description`，THE 引導式居家修繕對話系統 SHALL 將該描述保存為 `other` 分支的表單答案並保持 Repair_Branch 為 `other`。

### Requirement 3: Confidence、Alternatives 與歧義處理

**User Story:** 身為使用者，我希望系統清楚處理路由信心與候選，使高信心不會取代我的確認，低信心也不會變成猜測。

#### Acceptance Criteria

1. THE Routing_Contract SHALL 將 `confidence` 限制為字串 `high`、`medium` 或 `low`。
2. WHEN `confidence` 為 `high` 且服務與 Repair_Branch 均已驗證，THE 引導式居家修繕對話系統 SHALL 顯示建議並要求使用者確認後才設定已確認路由。
3. WHEN `confidence` 為 `medium` 或 `low` 且存在有效候選，THE 引導式居家修繕對話系統 SHALL 回傳 Validated_Repair_Branch Alternatives 或 Clarification_Question，且保持 Repair_Branch 未確認。
4. IF `confidence` 為 `medium` 或 `low` 且不存在有效候選，THEN THE 引導式居家修繕對話系統 SHALL 回傳 Unsupported 並進入安全停止。
5. IF 使用者需求僅能對應非 `service_id=17` 服務，THEN THE 引導式居家修繕對話系統 SHALL 回傳 Unsupported 並進入安全停止。
6. WHEN Clarification_Question 取得可唯一驗證的回答，THE 引導式居家修繕對話系統 SHALL 重新產生 Routing_Contract 並再次要求使用者確認路由。

### Requirement 4: Slot 收集、略過與拒答

**User Story:** 身為使用者，我希望系統記住有效回答，並在我不知道、未回答或拒絕時繼續其他問題，使對話不會猜測或反覆追問。

#### Acceptance Criteria

1. THE Slot_State SHALL 追蹤已確認服務、Validated_Repair_Branch、唯一縣市／行政區、排程、Versioned_Form 必填答案、Synthetic_Contact、預算、緊急程度及摘要確認。
2. THE 完整性規則 SHALL 將已確認服務與 Validated_Repair_Branch、唯一縣市／行政區、排程、Versioned_Form 必填答案、Synthetic_Contact 及目前摘要確認列為必要 Slot。
3. WHEN 使用者提供通過驗證的 Slot 值，THE 引導式居家修繕對話系統 SHALL 在同一 Active_Consultation_Task 的後續輪次保留該值。
4. WHEN 使用者未提供 Slot 答案或表示不知道，THE 引導式居家修繕對話系統 SHALL 將該 Slot 標記為 `skipped`。
5. WHEN 使用者明確拒絕回答 Slot，THE 引導式居家修繕對話系統 SHALL 將該 Slot 標記為 `declined_to_answer`。
6. WHILE Slot 標記為 `skipped` 或 `declined_to_answer`，THE 引導式居家修繕對話系統 SHALL 保持 Slot 值為空且不以預設值、模型常識或其他 Session 資料補值。
7. WHEN Slot 被標記為 `skipped` 或 `declined_to_answer`，THE 引導式居家修繕對話系統 SHALL 移至下一個適用且尚未回答的 Slot，且不自動重問同一 Slot。
8. WHILE 任一必要 Slot 缺少有效值，THE 引導式居家修繕對話系統 SHALL 保持媒合、建案與 Dispatch 不可執行。
9. WHEN 使用者主動補充或修正 Slot，THE 引導式居家修繕對話系統 SHALL 更新該 Slot 並重新計算完整性。

### Requirement 5: 地點、排程與選填欄位

**User Story:** 身為使用者，我希望地點與時間被明確驗證，並可選擇略過預算或緊急程度，使必要資訊完整而選填資訊不阻擋流程。

#### Acceptance Criteria

1. WHEN 使用者提供縣市或行政區，THE 引導式居家修繕對話系統 SHALL 透過 `resolve_location` 或等價 Service Layer 規則取得唯一縣市／行政區結果。
2. IF 縣市與行政區缺少、矛盾、不存在或結果不唯一，THEN THE 引導式居家修繕對話系統 SHALL 提出地點 Clarification_Question 並保持地點 Slot 未驗證。
3. IF 敘述同時包含目前位置與不同的服務地點，THEN THE 引導式居家修繕對話系統 SHALL 要求使用者確認服務地點。
4. WHEN 使用者提供有效日期與時段，THE 引導式居家修繕對話系統 SHALL 將日期與時段共同保存為排程。
5. WHEN 使用者明確選擇「時間彈性」，THE 引導式居家修繕對話系統 SHALL 將「時間彈性」保存為有效排程。
6. THE 完整性規則 SHALL 將預算設為選填 Slot。
7. THE 完整性規則 SHALL 將緊急程度設為選填 Slot，且只接受 `normal` 或 `urgent`。
8. IF 使用者提供 `normal` 或 `urgent` 以外的緊急程度，THEN THE 引導式居家修繕對話系統 SHALL 提出 Clarification_Question 並保持緊急程度未驗證。
9. WHEN 使用者提供聯絡資料，THE 引導式居家修繕對話系統 SHALL 只接受通過既有 PII 邊界驗證的 Synthetic_Contact。
10. IF 使用者提供真實姓名、電話、Email 或精確住家地址，THEN THE 引導式居家修繕對話系統 SHALL 排除該資料進入 Slot_State、模型輸入、Log、Audit、案件與 Dispatch。

### Requirement 6: Repair Branch 切換與狀態隔離

**User Story:** 身為使用者，我希望更換修繕問題分支前先確認，並只保留不矛盾的共用資訊，使舊分支答案與照片分析不會污染新分支。

#### Acceptance Criteria

1. WHEN 使用者要求改用另一個 Validated_Repair_Branch，THE 引導式居家修繕對話系統 SHALL 在變更前要求明確確認。
2. WHILE Repair_Branch 變更尚未確認，THE 引導式居家修繕對話系統 SHALL 保持原 Repair_Branch 與原 Slot_State 不變。
3. IF 使用者拒絕 Repair_Branch 變更，THEN THE 引導式居家修繕對話系統 SHALL 繼續原 Active_Consultation_Task。
4. WHEN 使用者確認 Repair_Branch 變更，THE 引導式居家修繕對話系統 SHALL 在同一 Active_Consultation_Task 以新 Validated_Repair_Branch 取代舊 Repair_Branch。
5. WHEN 使用者確認 Repair_Branch 變更，THE 引導式居家修繕對話系統 SHALL 清除舊 Repair_Branch 專屬表單答案。
6. WHEN 使用者確認 Repair_Branch 變更，THE 引導式居家修繕對話系統 SHALL 清除不適用於新 Repair_Branch 的照片分析與媒體參照。
7. WHEN 使用者確認 Repair_Branch 變更，THE 引導式居家修繕對話系統 SHALL 保留與新 Repair_Branch 不矛盾的服務、地點、排程、預算、緊急程度及 Synthetic_Contact。
8. WHEN 使用者確認 Repair_Branch 變更，THE 引導式居家修繕對話系統 SHALL 使先前摘要確認失效並依新分支重新計算完整性。
9. WHEN Repair_Branch 完成變更，THE 引導式居家修繕對話系統 SHALL 保持 Session 只有原本的一個 Active_Consultation_Task。

### Requirement 7: Versioned Form、欄位適用性與 Runtime 業務事實邊界

**User Story:** 身為使用者，我希望表單、分支、欄位適用性、服務商及媒合結果只來自受控資料，使 Runtime 無法補造缺少的業務事實。

#### Acceptance Criteria

1. WHEN Canonical_Service_ID 與 Repair_Branch 尚未由使用者確認，THE 引導式居家修繕對話系統 SHALL 保持動態 Versioned_Form 不可載入。
2. WHEN 使用者確認 `service_id=17` 與 Validated_Repair_Branch，THE 引導式居家修繕對話系統 SHALL 只透過 `get_consultation_form` 或等價 Service Layer 規則載入事先存在且版本化的 `repair_form_v1`。
3. WHEN Versioned_Form 載入成功，THE 引導式居家修繕對話系統 SHALL 保存表單版本、Canonical_Service_ID 與 Validated_Repair_Branch 供摘要、案件及 Audit 追溯。
4. IF `service_id=17` 缺少有效 Versioned_Form 或適用 Validated_Repair_Branch，THEN THE 引導式居家修繕對話系統 SHALL 回傳 Temporarily_Unavailable 並進入安全停止。
5. IF `service_id=17` 缺少有效 Matching_Data，THEN THE 引導式居家修繕對話系統 SHALL 回傳 Temporarily_Unavailable 並保持媒合、建案與 Dispatch 不可執行。
6. THE Runtime SHALL 將 Service ID、Repair Branch、Form Schema、Form Field、Field_Applicability_Config、Provider、Availability 與 Matching Result 限制為只能由事先存在的受控資料及 Service Layer 提供的業務事實。
7. WHEN LLM 輸出 Service ID、Repair Branch、Form Schema、Form Field、欄位適用性規則、Provider、Availability 或 Matching Result，THE 引導式居家修繕對話系統 SHALL 將輸出視為待驗證提案，且不直接寫入業務狀態。
8. WHEN 使用者或 LLM 提供不存在於有效 `repair_form_v1` 的 Repair Branch、Form Field 或欄位適用性規則，THE 引導式居家修繕對話系統 SHALL 保持 Form Schema 與 Field_Applicability_Config 不變並排除該提案。
9. THE Versioned_Form SHALL 以本功能執行前已存在、經人工 review 且隨 `repair_form_v1` 版本化的 Field_Applicability_Config 定義五個 Validated_Repair_Branch 的欄位適用性。
10. THE Field_Applicability_Config SHALL 將 `water_shutoff` 標記為 `electrical_issue` 的不適用欄位。
11. WHEN Validated_Repair_Branch 已確認，THE 引導式居家修繕對話系統 SHALL 只詢問、驗證、保存、摘要及提交 Field_Applicability_Config 標記為該分支適用的 Form Field。
12. WHERE Field_Applicability_Config 將 `water_shutoff` 標記為目前 Validated_Repair_Branch 的適用欄位，THE 引導式居家修繕對話系統 SHALL 依 `repair_form_v1` 的欄位規則詢問、驗證、保存、摘要及提交 `water_shutoff`。
13. WHILE 已確認的 Repair_Branch 為 `electrical_issue`，THE 引導式居家修繕對話系統 SHALL 從補問、Slot_State、表單答案、摘要及媒合／建案／Dispatch 提交資料排除 `water_shutoff`。

### Requirement 8: 摘要確認、媒合與受控副作用

**User Story:** 身為使用者，我希望在任何建案或派單前核對完整摘要，使既有媒合與案件流程只處理我明確確認的資料。

#### Acceptance Criteria

1. WHEN 除摘要確認外的必要 Slot 均有效，THE 引導式居家修繕對話系統 SHALL 顯示目前摘要。
2. THE 摘要 SHALL 顯示 Canonical_Service_ID、Validated_Repair_Branch、唯一縣市／行政區、排程、Versioned_Form 版本與答案、預算、緊急程度、Synthetic_Contact 及 `skipped`／`declined_to_answer` 狀態。
3. WHEN 使用者透過受控_UI_API 對目前摘要作出明確摘要確認，THE 引導式居家修繕對話系統 SHALL 將該摘要版本標記為可提交版本。
4. WHEN 可提交摘要進入媒合，THE 引導式居家修繕對話系統 SHALL 呼叫既有 Service Layer 媒合能力及有效 Matching_Data。
5. WHEN 可提交摘要進入建案與 Dispatch，THE 引導式居家修繕對話系統 SHALL 呼叫既有 CaseWorkflowService 與既有 Dispatch 路徑。
6. IF 建案或 Dispatch 僅由 LLM 文字、模型 Tool Request 或未受控前端狀態觸發，THEN THE 引導式居家修繕對話系統 SHALL 拒絕副作用。
7. WHEN 摘要確認後任何影響案件或媒合的 Slot 發生變更，THE 引導式居家修繕對話系統 SHALL 使原摘要確認失效並要求確認更新後摘要。
8. WHEN 相同可提交摘要被重複提交，THE 引導式居家修繕對話系統 SHALL 使用既有 Idempotency 回傳一致結果，且只保留一個案件與一次 Dispatch 效果。
9. WHEN 建案、Dispatch 或重複提交被處理，THE 引導式居家修繕對話系統 SHALL 使用既有 Audit 記錄確認版本、結果與冪等判定。
10. WHEN 服務商讀取案件，THE 引導式居家修繕對話系統 SHALL 使用既有 Authorization_Projection 與 PII 邊界限制可見資料。

### Requirement 9: Urgent 保存與危險情境安全停止

**User Story:** 身為使用者，我希望緊急程度被如實保存，而危險情境使用經人工核准的安全停止，使系統不會把一般媒合誤稱為緊急救援。

#### Acceptance Criteria

1. WHEN 使用者提供 `urgent`，THE 引導式居家修繕對話系統 SHALL 將 `urgent` 保存於 Slot_State 並回顯於摘要。
2. WHILE 緊急程度為 `urgent`，THE 引導式居家修繕對話系統 SHALL 維持 `matching_v1` 的既有權重不變。
3. WHILE 緊急程度為 `urgent`，THE 引導式居家修繕對話系統 SHALL 將媒合呈現為一般服務流程且不承諾到場或回應速度。
4. IF 使用者描述漏電、火災、瓦斯或人身危險，THEN THE 引導式居家修繕對話系統 SHALL 進入安全停止並保持一般媒合、建案與 Dispatch 不可執行。
5. WHEN 引導式居家修繕對話系統因危險情境進入安全停止，THE 引導式居家修繕對話系統 SHALL 只顯示人工核准安全內容。

### Requirement 10: Active Repair Task 照片整合

**User Story:** 身為水電修繕使用者，我希望照片只屬於目前適用的修繕分支並沿用既有安全流程，使照片不會建立平行管線或污染其他狀態。

#### Acceptance Criteria

1. WHERE Validated_Repair_Branch 允許照片，THE 引導式居家修繕對話系統 SHALL 只透過 Existing_Photo_Flow 接受照片。
2. WHEN Existing_Photo_Flow 接受照片，THE 引導式居家修繕對話系統 SHALL 將媒體與分析綁定目前 Active_Consultation_Task 及 Validated_Repair_Branch。
3. IF Validated_Repair_Branch 不允許照片，THEN THE 引導式居家修繕對話系統 SHALL 排除照片與照片分析進入 Slot_State、摘要、媒合及案件。
4. WHEN Existing_Photo_Flow 產生 VLM 建議，THE 引導式居家修繕對話系統 SHALL 在使用者確認及受控 Repair Branch 驗證前保持建議不是業務事實。
5. THE P0_實作 SHALL 重用 Existing_Photo_Flow，且不建立第二套上傳、儲存、VLM 或服務判斷管線。

### Requirement 11: P0 端到端與分支契約驗收

**User Story:** 身為產品驗收者，我希望兩個固定代表分支具有完整 E2E／Demo 證據，且全部五個支援分支具有聚焦與 HTTP 證據，使代表性覆蓋不會被誤解為支援上限。

#### Acceptance Criteria

1. THE E2E_驗收套件 SHALL 將 `faucet_leak` 與 `electrical_issue` 固定為完整 E2E／Demo 代表分支，並對兩者各自驗證多輪補問、Field_Applicability_Config 標記的適用欄位、摘要、明確摘要確認、媒合、建案與 Dispatch 的完整順序。
2. THE Focused_HTTP_測試 SHALL 對 `faucet_leak`、`toilet_issue`、`pipe_issue`、`electrical_issue` 與 `other` 每一分支各自包含 focused 自動化測試與 HTTP 整合測試，並驗證 Routing_Contract 路由、Service_Layer 分支驗證、`repair_form_v1` 與 Field_Applicability_Config 驗證，以及使用者確認路由。
3. WHEN `electrical_issue` 的完整 E2E 情境執行，THE E2E_驗收套件 SHALL 驗證補問、Slot_State、表單答案、摘要及媒合／建案／Dispatch 提交資料均排除 `water_shutoff`。
4. WHEN `other` 的 focused 與 HTTP 情境執行，THE Focused_HTTP_測試 SHALL 驗證系統要求並保存有效 `issue_description`、保持 Repair_Branch 為 `other`，且不將描述建立為新 Repair_Branch。
5. WHEN E2E 情境提供不足以唯一解析的縣市／行政區，THE E2E_驗收套件 SHALL 驗證系統提出地點 Clarification_Question 且不執行媒合、建案或 Dispatch。
6. WHEN E2E 情境提供可對應多個 Repair_Branch 的模糊描述，THE E2E_驗收套件 SHALL 驗證系統回傳 Alternatives 或 Clarification_Question 且不設定已確認 Repair_Branch。
7. WHEN E2E 情境確認 Repair_Branch 切換，THE E2E_驗收套件 SHALL 驗證舊分支答案與不適用照片分析被清除、不矛盾共用欄位被保留且未建立第二個任務。
8. WHEN E2E 情境提出非水電需求，THE E2E_驗收套件 SHALL 驗證系統回傳 Unsupported 且不載入表單、不媒合、不建案及不 Dispatch。
9. WHEN E2E 情境重複提交同一可提交摘要，THE E2E_驗收套件 SHALL 驗證回傳結果一致且案件數與 Dispatch 效果各不超過一次。

### Requirement 12: 非目標與能力聲明邊界

**User Story:** 身為產品審查者，我希望 P0 非目標可被明確驗證，使文件、Demo 與測試不會把未完成能力宣稱為成果。

#### Acceptance Criteria

1. THE P0_實作 SHALL 將專業清潔、`service_id=4`、第二個 Canonical Service、跨服務流程及多 Active Consultation Tasks 保持為未提供能力。
2. THE P0_實作 SHALL 維持文字互動，並將語音輸入、語音輸出及語音轉寫排除於本功能。
3. THE P0_實作 SHALL 將真人轉接、客服工作台、回呼與 SLA 保持為未提供能力。
4. THE P0_實作 SHALL 維持既有 `matching_v1` 輸入，並將服務商語言偏好媒合排除於本功能。
5. THE P0_實作 SHALL 將點數、獎勵規則及點數 Ledger 排除於本功能。
6. THE P0_實作 SHALL 維持既有 MCP Tool Schema 不變，並將外部 MCP E2E 排除於本功能驗收。
7. THE P0_實作 SHALL 將 Bedrock、AgentCore、S3、RDS 及其他 AWS 實作或部署排除於本功能。
8. THE P0_實作 SHALL 重用既有 Synthetic Demo 授權邊界，並將 Production Authentication 與 RBAC 排除於本功能。
9. THE P0_實作 SHALL 重用 Existing_Photo_Flow，並將新照片管線排除於本功能。

## 待 Requirements Review

1. Confidence 分類與校準方法。
2. Active_Consultation_Task 的明確結束點。
3. 五個已決定 Validated_Repair_Branch 各自的完整必填欄位清單。
4. 聯絡偏好。
5. Synthetic 地址粒度。
6. Versioned_Form 選版政策。
7. 緊急安全內容治理。
8. Session 與媒體保存政策。
