# Web Demo viewport 與 HF 多輪驗證收尾

最後更新：2026-08-01

主要模組：`src/home_repair_agent/web/`、`scripts/huggingface_web_eval.py`

## 目標

修正消費者與廠商工作台在 100%／高縮放時的不可達操作，將廠商案件答案改成受控中文顯示，並建立不會把 Mock 冒充 live HF 的可重跑多輪驗證入口。

## Root cause

消費者頁原本同時讓 conversation pane、message list 與 consultation form 捲動，composer 又位於多個自然高度 grid row 的最後方；media、表單與摘要同時出現時，composer 會被推出 pane 的可視範圍。廠商頁則以 viewport 高度與較晚的雙欄 breakpoint 壓縮內容，狀態頁籤還依賴水平捲動。

HF 情境重播另揭露兩個 Web 狀態問題：branch 確認前的純地點訊息被誤設為 safety stop，且 form ready 後的明確地點更正被 `FORM_ALREADY_READY` 擋住。

## 實作

- 消費者 conversation 改成「標題／單一內容捲動區／composer」三列；message、routing、media、form 與 summary 共用內容捲動區，composer 保持獨立可操作。
- 新訊息只調整內容捲動區，不捲動整頁，並交由 CSS `scroll-behavior` 尊重 reduced-motion。
- 廠商頁使用自然頁面垂直捲動，1100px 以下單欄 reflow；狀態頁籤改為可重排 grid，核心控制項至少 44px。
- 廠商答案使用 closed-world label/value mapping；`preferred_time` 不在 generic answers 重複，未知 key 不顯示、未知 enum 顯示受控提示，所有未知文字仍只經 `textContent`。
- branch 確認前可累積純地點與模糊需求，仍不驗證 service／location、不呼叫 matching；明確 non-target service 與真正 hazard 的 fail-closed 行為不變。
- matching 前允許明確地點更正：清除舊 location/form provenance、重置 Agent conversation，以已確認 branch 重新執行三個唯讀 discovery tools；舊 summary identity 失效，answers/time 保留但必須重新提交確認。
- 新增 opt-in HF 七案 harness。沒有 `--live` 不會建立 HF client；輸出只含去識別訊息標記、受控 tool arguments、stop reason 與 session snapshot。

## 安全邊界

- 沒有修改 AgentRunner、MCPToolClient、MCP schema、matching 權重、CaseWorkflowService 或 AWS AgentCore 工作線。
- Mock 仍不能上傳／分析圖片，HF provider 失敗不 fallback Mock。
- 多輪與地點更正不會提前 matching、dispatch 或建立案件；hazard、PII、summary version 與 case/audit 鎖仍由既有 service boundary 驗證。
- Provider unknown values 不以 `innerHTML` 輸出；harness 不保存 raw messages、token、完整 provider payload 或本機路徑。

## 驗證範圍

- consumer：1280×720、1366×768、1440×900、1920×1080、390×844，以及 125%／200% 等效 CSS viewport；composer 可見、單一內容捲動、無水平 overflow。
- provider：相同桌面／手機與等效縮放；可捲到案件詳情、聯絡資料、audit 與接受／拒絕按鈕。
- Python 完整 suite、focused Web/HF regressions、Node syntax、compileall 與 `git diff --check`。
- 本分支 Python 檔通過 Ruff check/format；repository-wide Ruff 仍會重現 baseline data-cleaning lint／format debt，未在本工作線掃改。

## 尚待 live 驗收

必須由人類建立新的 HF token，只放在目前 shell，再執行 `python scripts/huggingface_web_eval.py --live`。文字七案與 VLM 圖片閉環是兩項不同驗證；在新 token 與合規 synthetic/public 圖片可用前，不得把 offline contract 或歷史結果描述成這一輪 live 通過。
