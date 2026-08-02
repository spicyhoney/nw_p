# 專案文件入口

最後更新：2026-08-02

本目錄同時保留「目前可執行系統」與「早期發想」。兩者不能混用：要回答現在
做了什麼，請讀目前事實；歷史規劃只能用來理解決策背景。

## 目前事實

| 文件 | 用途 | 何時讀 |
|---|---|---|
| [專案白話指南](project-guide.md) | 系統怎麼運作、三條主要流程、重要模組 | 第一次加入時先讀 |
| [HANDOFF](../HANDOFF.md) | 目前 branch、最近驗證與不可破壞契約 | 每次接手先讀 |
| [TASKS](../TASKS.md) | 尚未完成工作、優先級、依賴與驗收 | 選下一項工作 |
| [實作索引](implementation-index.md) | 已完成程式、位置與驗證證據 | 確認是否真的做過 |
| [系統與 AWS 架構](architecture.md) | 本機元件、AWS 角色與未來 adapter | 理解部署邊界 |
| [派單／接單](provider-workflow.md) | 確認、遮罩、授權、冪等、audit 與狀態機 | 修改案件流程前 |
| [資料政策](data-policy.md) | official、curated、synthetic 與 quarantine 規則 | 修改資料前 |
| [資料字典](data-dictionary.md) | PostgreSQL schema、欄位與關聯 | 修改 repository 前 |
| [資料清洗手冊](data-cleaning-runbook.md) | B+ pipeline、重跑與載入 | 修改清洗流程前 |
| [AI 資料 Review 清單](ai-data-review-checklist.md) | 給隊友 AI 的資料檢查方式 | Review 資料改動 |
| [作品集整理紀錄](portfolio-release.md) | 賽後收斂範圍、驗證與刻意保留的限制 | 理解公開版如何形成 |

程式模組的詳細介面、執行與測試方式放在各自 README：

- [Web](../src/home_repair_agent/web/README.md)
- [Agent](../src/home_repair_agent/agent/README.md)
- [MCP Server](../src/home_repair_agent/mcp_server/README.md)
- [SQL](../sql/README.md)
- [Tests](../tests/README.md)

## 歷史規劃

下列文件是 2026-07-08 起的探索、學習與提案草稿。它們可能包含已放棄方案、
估算數字或尚未實作功能，不能作為目前程式契約或簡報成果宣稱。

| 文件 | 歷史用途 |
|---|---|
| [最初建議](final_recommendation.md) | 題目、技術棧與早期三天行動清單 |
| [Brainstorm](brainstorm.md) | 十個候選方向、SWOT 與排名 |
| [早期資料策略](data_plan.md) | 初步資料檢查與後續 synthetic／分析構想；事實以品質報告為準 |
| [Gantt](gantt_plan.md) | 早期日期與決賽時間分配 |
| [技術策略](technical_strategy.md) | 三套候選架構方案 |
| [MCP／Agent 規劃](mcp_agent_plan.md) | 早期八個候選 Tool 與 eval 構想 |
| [AWS 學習計畫](aws_learning_plan.md) | 賽前學習順序 |
| [工具說明](tools_description.md) | 工具盤點與早期優先級 |
| [Prototype 測試計畫](prototype_test_plan.md) | 早期 PoC 風險清單 |
| [簡報策略](presentation_strategy.md) | 簡報骨架與 Demo 構想，不等於已完成成果 |

規劃文件若與程式、測試、HANDOFF 或實作索引衝突，以後四者為準。

## 文件維護規則

- 現在能執行的行為改變：更新 HANDOFF、實作索引與相關模組 README。
- 未來任務的狀態、優先級或範圍改變：更新 `TASKS.md`。
- 新功能必須說明做了什麼、刻意沒做什麼、資料流、安全邊界、測試與風險。
- 不得把 planned、synthetic 或只在簡報構想中的項目寫成 verified。
- 數字必須能指向品質報告、測試結果或明確資料來源。
- 文件結構與完成標準見 [AGENTS.md](../AGENTS.md)。
