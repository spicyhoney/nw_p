# B+ 資料品質報告

產生時間：`2026-07-25T08:22:23.736970+00:00`

## 結論

- 原始檔保持不變。
- 訂單 JSON 與 CSV 經語意比較後只選 JSON 作為權威來源。
- 無法確認的服務、供應商與訂單類型保留原值並隔離。
- 官方 `service_id=17` 為水電修繕 MVP 的可信主軸。
- 水電表單標記為 `curated_config`；師傅、時段、案件與訂單標記為 `synthetic`。
- 歷史訂單已去除會員識別與密文，不提供給 Agent。

## 原始檔

| 檔案 | SHA-256 |
|---|---|
| `相關主檔設定.json` | `124d1b6b8eb38eb4fa0636cd47d1a5f5991db3af8f357367c0bb4a8bdf11cc9a` |
| `縣市區域範例資料.json` | `f13399aef45c8cc2a00f74003e34df7e273573fe24583a84def240e79e0cd085` |
| `諮詢單相關範例資料.json` | `d2aceeec230a5323bbb65408a07738899829959299349f1243838aa567f445e9` |
| `order_record範例資料.json` | `5c49c89fe8195a28dca447e739ee0b379a4e4fd762502db448ce255d823a67bc` |
| `order_record範例資料.csv` | `e1f3758468685e3d09ed7a414b0e0fd278564aa7890de2f1eb946de5873c7e82` |

## 資料表筆數

| 資料表 | 筆數 |
|---|---:|
| `cms_homepage_service` | 8 |
| `cms_homepage_service_vendor` | 6 |
| `mms_order_record` | 99 |
| `pms_form` | 1 |
| `pms_form_feedback` | 1 |
| `pms_form_topic` | 7 |
| `pms_topic_county_district_relation` | 1 |
| `pms_topic_media` | 1 |
| `pms_topic_option` | 6 |
| `sys_county` | 22 |
| `sys_district` | 200 |

## 訂單雙來源驗證

- JSON：99 筆
- CSV：99 筆
- Record IDs 相同：True
- 欄位語意一致：True

## 行政區整合

- `organizer_counties`：22
- `organizer_districts`：200
- `external_counties`：22
- `external_districts`：368
- `matched_organizer_districts`：200
- `external_only_districts`：168
- `canonical_locations`：368

外部參考來源：[內政部國土測繪中心行政區 API](https://data.gov.tw/dataset/102011)，資料標記為 `external_reference`。

## 歷史訂單處理

- `rows`：99
- `verified`：1
- `review`：28
- `quarantined`：70
- `agent_eligible`：0
- `shape_list`：82
- `shape_object_goods`：2
- `shape_object_orderItems`：15

## 品質問題

- Error：211
- Warning：69

| 問題代碼 | 筆數 |
|---|---:|
| `CANCELLED_WITHOUT_CANCEL_TIME` | 1 |
| `COMPLETED_WITHOUT_COMPLETE_TIME` | 5 |
| `CORRUPTED_ENCRYPTED_PII` | 33 |
| `DUPLICATE_TOPIC_SORT` | 2 |
| `FORM_DISABLED_OR_DELETED` | 1 |
| `FRAGMENTED_JSON_DOCUMENT` | 1 |
| `MISSING_FEEDBACK_OPTIONS` | 1 |
| `MISSING_FEEDBACK_TOPICS` | 1 |
| `MISSING_SERVICE_DESCRIPTION` | 3 |
| `ORPHAN_FEEDBACK_SERVICE` | 1 |
| `ORPHAN_MEDIA_TOPIC` | 1 |
| `ORPHAN_ORDER_SERVICE` | 64 |
| `ORPHAN_ORDER_VENDOR` | 64 |
| `ORPHAN_TOPIC_GROUP` | 7 |
| `PLAINTEXT_PII_IN_FEEDBACK_JSON` | 1 |
| `REFUND_STATUS_WITH_ZERO_AMOUNT` | 22 |
| `REUSED_PLACEHOLDER_IMAGE` | 8 |
| `UNDEFINED_ORDER_TYPE` | 64 |

## 無法確認的代碼

| 類型 | 來源 ID | 候選 ID | 狀態 | 處理 |
|---|---|---|---|---|
| service | `7` | `17` | unresolved | 保留原值、隔離、不供 Agent 使用 |
| service | `18` | `` | unresolved | 保留原值、隔離、不供 Agent 使用 |
| service_vendor | `15` | `` | unresolved | 保留原值、隔離、不供 Agent 使用 |
| order_type | `07` | `` | unresolved | 保留原值、隔離、不供 Agent 使用 |

## Agent 資料閘門

只有 `quality_status=verified` 且 `agent_eligible=true` 的資料可進入 `agent` schema views。`quarantine`、歷史個資與 unresolved mapping 不會被暴露。
