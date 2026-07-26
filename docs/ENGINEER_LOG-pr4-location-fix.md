# PR #4 行政區更正問題修正紀錄

- 日期：2026-07-26
- 分支：`feature/agent-prototype`
- 範圍：Mock Agent 多輪地點解析

## 問題與重現

第一輪輸入不存在的行政區，例如「臺北市不存在區水龍頭漏水」後，
第二輪即使改成「新北市板橋區」，Agent 仍會再次解析第一輪的臺北市資料，
導致 `resolve_location` 持續失敗，無法進入 `get_consultation_form`。

## 根因

地點解析固定合併所有歷史使用者訊息，再依縣市清單順序找第一個符合項目。
因此舊的錯誤地點會遮蔽新一輪的更正內容。

## 修正

保留原本「缺少地點時可跨輪補充」的行為；但若最近一次
`resolve_location` 已失敗，而且之後收到新的使用者訊息，地點解析只採用
最新一輪文字。

複查時另發現，最新一輪可能同時包含舊、新地點，例如「不是臺北市不存在區，
是新北市板橋區」。Mock 不具備可靠的語意消歧能力，因此不猜測其中一個地點；
它會要求使用者只輸入更正後的完整縣市與行政區，再繼續查詢。修正未變更
MCP Tool schema、資料庫或 AWS 整合。

## 回歸測試

新增兩個回歸測試：

1. 第一次查詢不存在的臺北市行政區，確認 Tool 回傳失敗。
2. 下一輪改成新北市板橋區。
3. 確認 Agent 使用新的縣市與行政區呼叫 `resolve_location`。
4. 確認流程繼續呼叫 `get_consultation_form`。
5. 若更正句同時含新、舊地點，確認 Agent 不呼叫 Tool，先要求單一地點。
6. 再提供單一新地點後，確認流程可繼續。

驗證結果：

- `python -m pytest tests/test_agent_loop.py -q`：12 passed。
- 本工作區有主辦方資料集、未設定 `TEST_DATABASE_URL`：
  `python -m pytest -q` 為 38 passed、8 skipped、25 subtests passed。
- 乾淨 checkout 若沒有主辦方資料集，資料清洗整合測試會再多 1 個 skipped；
  pass/skip 總數不應脫離環境條件單獨解讀。
- `python -m ruff check src/home_repair_agent/agent tests/test_agent_loop.py`：通過。
