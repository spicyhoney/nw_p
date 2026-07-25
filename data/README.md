# Data

本目錄只保存資料使用規則與可公開的去識別化小型範例。

- `raw/`：主辦方原始資料，本機保存且不提交 Git。
- `processed/`：清洗流程產生的資料；預設不提交，通過審查的樣本除外。
- `quarantine/`：無法確認或未通過驗證的資料，不供 Agent 使用。

所有產出都必須能由 `src/home_repair_agent/data_cleaning/` 的程式重新建立。

