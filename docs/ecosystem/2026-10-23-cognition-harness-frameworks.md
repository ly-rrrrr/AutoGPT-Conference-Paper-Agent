# 认知 Harness 框架候选

日期：2026-10-23

## 结论

优先对 LangGraph 做适配器 PoC；LlamaIndex 用于后续全文数据与 Agentic RAG；暂不选择 CrewAI；不在新架构中采用已进入维护模式的 AutoGen。

## 候选比较

| 项目 | GitHub Stars（调查时） | 适合能力 | 决策 |
|---|---:|---|---|
| [LangGraph](https://github.com/langchain-ai/langgraph) | 43.7k | 持久化、分支、循环、流式事件、人工中断、子图 | Harness 优先 PoC |
| [LlamaIndex](https://github.com/run-llama/llama_index) | 52.6k | 文档处理、索引、Agentic RAG、工作流 | 全文与检索适配器候选 |
| [CrewAI](https://github.com/crewAIInc/crewAI) | 60k | 角色型多 Agent 编排 | 不作为核心控制面；容易把问题收窄为固定角色接力 |
| [AutoGen](https://github.com/microsoft/autogen) | 61.2k | 多 Agent 对话与工具协作 | 官方已进入维护模式，不用于新架构 |
| [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) | 14.3k | AutoGen 后继、多 Agent 与工作流 | 保留为后续候选，先观察 Python 生态和接入成本 |

## 边界

第三方框架只实现可替换的运行适配器。论文、证据、洞见、缓存键、覆盖率和版本历史继续使用工作台自己的领域模型，避免锁定在任一框架的私有对象中。
