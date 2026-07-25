# 賽前作戰文件包 — 2026 雲湧智生黑客松（統一資訊：AI 生活管家）

產出日期：2026-07-08｜團隊：2 人（電機＋統計）｜決賽：8/1–8/2（30h）

## 閱讀順序

| 檔案 | 內容 | 先讀 |
|---|---|---|
| [final_recommendation.md](final_recommendation.md) | 總結：Top 3 題目、唯一技術棧、3 天行動清單 | ⭐ 兩人都先讀 |
| [brainstorm.md](brainstorm.md) | 10 個候選方向＋SWOT＋評分＋排名 | ⭐ 拍板題目前必讀 |
| [gantt_plan.md](gantt_plan.md) | 7/8→8/2 甘特圖＋30 小時決賽衝刺表 | ⭐ |
| [technical_strategy.md](technical_strategy.md) | 3 套架構方案＋推薦（方案二混合雲） | 資工先讀 |
| [data_plan.md](data_plan.md) | **官方資料集實際分析結果**＋資料表設計＋合成資料策略 | 統計先讀 |
| [mcp_agent_plan.md](mcp_agent_plan.md) | 8 個 tool schema＋Agent 流程＋10 條 eval | 資工 |
| [aws_learning_plan.md](aws_learning_plan.md) | AWS P0–P3 學習計畫＋7 天速成路線 | 資工主、統計跟 |
| [tools_description.md](tools_description.md) | 54 個工具「學到什麼程度才夠」＋Top 10 優先序 | 查閱用 |
| [prototype_test_plan.md](prototype_test_plan.md) | 20 個賽前 PoC 測試（含必做 Top 5） | 開工前 |
| [presentation_strategy.md](presentation_strategy.md) | 10 頁簡報大綱＋demo 劇本＋18 題 Q&A | 7/28 起 |

## 三個關鍵事實（讀什麼都別忘）

1. **MCP Server 是命題必做項**（不是加分）：需自行設計 API 並包成標準 MCP Server 供 Lumine one 等外部 Agent 調用。
2. **官方 schema 是 PostgreSQL**，PII 欄位內建 AES-256-GCM 密文＋hash 設計——照做就是切合度證據。
3. **技術可行 25%＋商業 25%＋切合 20%＝70%**：穩、切題、講得出商業故事 > 炫技；創意只佔 15%，用場景與敘事補。

## 近期節點

- **7/18 上午**：工作坊（EDIMUS/Ademus 規格公布）——帶 gantt_plan 第 2 節的問題清單去
- **7/22**：疑似入選/重要節點——前一天要有可跑閉環＋粗 demo 影片
- **8/1–8/2**：決賽 30 小時——最終交付以現場公告為準
