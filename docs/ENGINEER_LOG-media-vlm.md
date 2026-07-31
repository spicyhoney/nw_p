# MEDIA-001A：Hugging Face 視覺模型 adapter

日期：2026-07-31

## 已完成範圍

新增 `home_repair_agent.agent.huggingface_vision.HuggingFaceVisionClient`。它接收已由媒體
上傳層驗證的圖片 bytes 與 MIME，將 JPEG、PNG、WebP 轉為 Hugging Face chat-completion
的 `data:<mime>;base64,...` `image_url` content part，並要求 JSON Schema 結果。

`analyze()` 的唯一輸出是嚴格驗證的 `VisionAnalysisResult`：

- `service_query`
- `problem_summary`
- `safety_warnings`
- `confidence`
- `uncertain`

結果模型拒絕未知欄位（包括 `service_id`）、遺漏欄位與錯誤型別。它沒有呼叫
`ReadServiceLayer`、沒有建立案件，也沒有任何派單能力；整合端必須先以
`ReadServiceLayer` 驗證 service query，並由使用者確認後才可把建議帶進後續流程。

## 設定與失敗語義

使用 `HF_TOKEN`、`HF_VL_MODEL_ID`、`HF_VL_PROVIDER`、`HF_VL_MAX_TOKENS` 與
`HF_VL_TIMEOUT_SECONDS`。預設模型為 `Qwen/Qwen3-VL-30B-A3B-Instruct`，但 provider 對特定
模型／response schema 的支援仍由部署設定決定。缺 token、空模型、空 provider 與不合法
數值在發送前失敗；不支援 MIME、provider error、timeout 與非結構化回應也各自明確失敗。
所有 provider exception 都遮罩原始內容，不記錄 token、圖片 bytes 或 provider payload，且
沒有 Mock fallback。

Hugging Face 官方 Chat Completion／Image-Text-to-Text VLM contract 使用 user `content`
陣列中的 `text` 與 `image_url` item，並支援 data URL；`InferenceClient.chat_completion`
支援 `response_format`。截至 2026-07-31，預設的 Qwen 模型頁列出 Featherless AI 與
`image-text-to-text`；其可用性與特性仍會隨 provider 改變，部署前應用測試 token 對選定的
model/provider 作一次受控 smoke test：
[Image-Text-to-Text 文件](https://huggingface.co/docs/inference-providers/tasks/image-text-to-text)、
[Chat Completion 文件](https://huggingface.co/docs/inference-providers/tasks/chat-completion)、
[Qwen/Qwen3-VL-30B-A3B-Instruct 模型頁](https://huggingface.co/Qwen/Qwen3-VL-30B-A3B-Instruct)。

2026-07-31 以無個資、無 EXIF 的 synthetic 水漬圖片和既有 `HF_TOKEN` 完成 live smoke。
原先的 `Qwen/Qwen2.5-VL-7B-Instruct` 被官方 router 以 `model_not_supported` 拒絕；改用
`Qwen/Qwen3-VL-30B-A3B-Instruct` 後，`HF_VL_PROVIDER=novita` 與 `auto` 都成功回傳符合
schema 的繁中建議、安全提醒、confidence 與 uncertain。紀錄不包含 token、圖片 payload
或 provider request ID。

## 驗證

`tests/test_huggingface_vision.py` 全程注入 recording/failing hosted client，未發送 live
network request。測試涵蓋 multimodal payload、正常和低信心結果、缺 token、空模型、不支援
MIME、schema/JSON 格式錯誤、provider error 與 timeout。

## 整合注意事項

此 adapter 尚未掛入 Web upload 流程或 AgentRunner。媒體層必須先驗證真實影像內容、大小與
使用者對外傳模型的同意；呼叫端再以 `await client.analyze(...)` 取得「待確認」建議，不能把
其直接視為案件、媒合或派單指令。
