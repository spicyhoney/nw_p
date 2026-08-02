# AgentCore Remote MCP Demo — Tasks

- [x] 驗證 exact base commit，建立獨立 stacked worktree／branch，確認未碰 PR #20。
- [x] 聚焦閱讀既有 AgentCore POC、MCP composition／protocol tests及兩份官方 Runtime 文件。
- [x] 完成 timeboxed Quick Spec，鎖定 P0、synthetic-only、SigV4、失敗 cleanup 與 P1 non-goal。
- [x] 新增最小 Runtime MCP entrypoint 與 synthetic-only ASGI guard。
- [x] 新增 authenticated remote MCP client，動態解析前序 ToolResult IDs。
- [x] 新增 purpose-scoped deploy／status／invoke／cleanup CLI、isolated requirements 與 synthetic fixture。
- [x] 新增 focused protocol／guard／deploy safety tests，不修改既有 Tool／Service contracts。
- [x] 執行 focused tests、完整 pytest、Ruff check/format、compileall、diff check、credential／PII scan。
- [x] 先驗證 cleanup command，再執行短效 AWS deploy 與 remote 四工具 P0；成功後依指示保留至 expiry。
- [x] 產生遮罩 evidence、ENGINEER_LOG、implementation index；ChatGPT Developer Mode 明確列為未驗證。
- [x] 建立本機 snapshot commit；依最新指示不 push、不開 PR、不 merge。
