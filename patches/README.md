# AutoGPT 适配补丁

`autogpt-platform.patch` 包含本项目对 AutoGPT Platform 的必要适配，包括：

- Graph 输入数组 Schema 修复
- OpenAI-compatible Base URL 传递
- 全量任务消息大小与执行器稳定性适配
- MCP OAuth Credential 恢复与前端交互修复
- 运行数据卷与 Block 成本配置

通常无需手动应用，`scripts/install.py` 会完成兼容性检查和安装。

