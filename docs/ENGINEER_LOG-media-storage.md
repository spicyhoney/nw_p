# MEDIA-001：本機媒體儲存

日期：2026-07-31

## 範圍

新增獨立的 `backend/media_storage.py`，不改動 FastAPI、Web session、案件模型或兩種
案件 repository。整合層可保存 `StoredMedia.relative_path`（相對於 `MEDIA_ROOT`）；圖片
二進位內容不應寫入 PostgreSQL、audit、log 或例外訊息。

## 安全契約

- `LocalMediaStorage` 預設寫入 repo 的 `var/media/`，可用 `MEDIA_ROOT` 或建構子參數覆寫；
  `var/media/` 已忽略於 Git。
- 只接受實際可完整解碼的 JPEG、PNG 與 WebP，輸入上限為 8 MiB。client 宣告的 MIME 和
  檔名不參與格式判斷。
- 每次寫入以伺服器產生的 UUID media id 命名，並由解碼格式決定 `.jpg`、`.png` 或
  `.webp`。session 路徑為 `sessions/{session_id}/{media_id}.{ext}`，關聯後為
  `cases/{case_id}/{media_id}.{ext}`。
- 內容會經 Pillow 解碼後以新影像重新編碼，移除 EXIF 與其他容器 metadata。讀、寫、移動和
  刪除均拒絕 traversal、任意 key、符號連結與非一般檔案；安全錯誤不回傳絕對路徑或二進位。
- `associate_with_case`／`rollback_association` 支援案件 transaction 的移動與補償；
  `stage_delete`、`rollback_delete`、`commit_delete` 支援先暫存刪除、再依資料庫 transaction
  成功或失敗收斂。沒有 rollback 需求時可呼叫永久的 `delete`。

## 依賴

`Pillow>=10,<13` 加入 `app` extra。專案最低 Python 為 3.11，Pillow 10 起支援該版本；
上限避免未驗證的下一個大版行為改變。Pillow 提供真正解碼與乾淨重新編碼，不能用檔名或
MIME sniffing 取代。

## 整合提醒

Web adapter 應在 multipart upload 後呼叫 `store_session_image`，只將回傳的相對 path 帶到
後續 case command。case 寫入成功後呼叫 `associate_with_case`；若 DB transaction 失敗，呼叫
`rollback_association`。受授權的 provider image endpoint 應以 `read_image` 取資料和由模組
提供的 content type 回應，並自行設定 `Content-Disposition` 與 `Cache-Control: no-store`。

## 驗證

focused tests 覆蓋 JPEG/PNG/WebP、偽 MIME、超過上限、損壞影像、traversal、符號連結、EXIF
清除、session/case 移動及 staged deletion rollback/cleanup。執行結果記錄於本次工程交付。
