# Data

本目錄保存資料使用規則、固定版本的公共參考資料，以及通過隱私檢查的清洗產出。

- `raw/`：主辦方原始資料，本機保存且不提交 Git。
- `reference/`：有來源與授權資訊的公共參考資料快照。
- `processed/`：清洗流程產生的資料；只有 `.gitignore` 白名單中的安全輸出可提交。
- `quarantine/`：無法確認或未通過驗證的資料，不供 Agent 使用。

所有產出都必須能由 `src/home_repair_agent/data_cleaning/` 的程式重新建立。
