# 方法认知 AI 工作流生态候选

日期：2026-10-23

## 调查目标

目标不是寻找一个“自动生成知识图谱”的仓库，而是组合经过广泛验证的能力，使工作台能够围绕会议年度或研究问题主动探索论文语料、形成候选洞察、搜集支持与反例、修正解释，并发布可追溯的交互式认知制品。

成熟生态负责文献检索、证据收集、Agent 运行、语义程序优化和语料级综合；本项目只自研方法认知语义、研究制品协议、跨领域迁移表达和产品交互。

## 候选比较

Stars 为 2026-10-23 调查时的近似值，只作为社区验证信号之一。

| 能力 | 候选 | Stars | 许可证 | 适配度与结论 |
|---|---|---:|---|---|
| 科学文献研究 Agent | [PaperQA2](https://github.com/Future-House/paper-qa) | 9.2k | Apache-2.0 | 面向科学论文，已经实现搜索、证据收集、重排、带引文回答和矛盾检查。确定为首选证据研究适配器，不复制其 RAG 实现。 |
| 语义程序与优化 | [DSPy](https://github.com/stanfordnlp/dspy) | 38.6k | MIT | 用声明式签名和可优化程序代替大量脆弱提示词，适合方法认知抽取、洞察提议与证据批判模块。确定进入 PoC。 |
| 持久化 Agent 编排 | [LangGraph](https://github.com/langchain-ai/langgraph) | 41.5k | MIT | 持久状态、流式输出、调试和人工介入成熟，但与现有 AutoGPT 执行层重叠。暂不作为首个运行时；只有 AutoGPT 无法承载研究循环时再做对照 PoC。 |
| 语料级图与社区综合 | [Microsoft GraphRAG](https://github.com/microsoft/graphrag) | 36.4k | MIT | 适合知识图谱、社区层级和全局查询。保留为语料级综合适配器候选，不采用其通用实体关系作为本项目方法语义真相。 |
| 向量检索 | [Milvus](https://github.com/milvus-io/milvus) | 40k+ | Apache-2.0 | 用户确定采用独立 Milvus 服务，承担论文、段落和未来图片向量的候选召回；PostgreSQL 继续保存业务事实与索引来源。相似度只用于发现候选。 |
| 语义编码与重排 | [Sentence Transformers](https://github.com/huggingface/sentence-transformers) | 19k+ | Apache-2.0 | 支持语义相似、检索、聚类和 reranker。作为可替换本地模型适配器，不把特定模型写入领域数据结构。 |
| 学术元数据 | [OpenAlex](https://help.openalex.org/api/) / [Semantic Scholar Academic Graph](https://api.semanticscholar.org/api-docs/) | API | 各自条款 | 用于身份、引用和主题事实补全，不负责判断思想继承或方法迁移。 |

## 架构决定

### 保留 AutoGPT，但改变使用方式

AutoGPT 继续承担外层任务提交、模型凭证、并发、断点和长任务执行。现有固定论文问答不是最终认知工作流；新的研究任务向 Agent 提供目标、范围、工具和产物协议，允许其根据中间证据调整检索与分析路径。

### PaperQA2 作为科学证据工具

通过独立适配器接入 PaperQA2 的论文索引、证据收集、带引文回答和矛盾搜索。工作台不读取其内部存储作为领域数据库，只保存规范化的证据引用、工具版本和调用结果。

### DSPy 作为认知程序层

方法解剖、候选洞察、批判与综合使用声明式输入输出签名。优化目标来自少量人工认可的研究制品和字段级证据一致性，而不是不断手工叠加提示词。

### GraphRAG 只做语料级候选综合

GraphRAG 的社区和全局摘要可帮助发现会议年度的潜在结构，但输出只能成为 `InsightProposal`。只有经过原文证据、反例搜索与来源范围说明后，才能发布为 `PublishedInsight`。

### Milvus 作为独立向量服务

Milvus 通过可替换适配器接入，按论文、文本片段和图片等语义粒度分 collection。PostgreSQL 保存稳定 ID、来源哈希、嵌入模型和索引版本，Milvus 只保存可重建向量与最小过滤字段。原先的 pgvector 候选不再作为当前实施方案。

### 暂不引入第二套编排运行时

LangGraph 能力成熟，但直接引入会与 AutoGPT、FastAPI 任务记录和现有 checkpoint 形成三套状态源。V1 先定义框架无关的 `ResearchWorkflowAdapter`；若 AutoGPT 无法实现动态工具循环、恢复或流式观察，再用同一协议对比 LangGraph，而不是提前重构。

### 凭据与兼容模型接入

- 供应商调用采用 OpenAI-compatible Responses API 边界，模型配置不与 AIHubMix、OpenAI 或其他兼容供应商的数据结构绑定。
- 本机密钥交给 Python `keyring` 与 Windows Credential Manager 托管；PostgreSQL 只保存凭据引用，前端和 API 不具备读取明文密钥的接口。
- 第一条可运行纵向链路直接使用 Responses 工具调用验证产品闭环。PaperQA2 与 DSPy 仍保留在适配器边界之后，分别增强证据研究和可优化语义程序，而不是阻塞基础闭环。

## 自研边界

必须自研：

- `ResearchBrief`：用户目标、会议范围、希望获得的认知与预算；
- `ResearchArtifact`：AI 工作流之间唯一可持久交换的制品协议；
- `InsightProposal`：带支持、反例、不确定性和展示建议的候选洞察；
- 方法思想的来源、改造、组合、迁移和适用边界表达；
- 论文、方法家族、年度全景之间的交互式下钻体验；
- 版本、来源、用户修订和重新生成规则。

不自研：

- 通用 PDF RAG、向量索引、reranker、学术元数据图；
- 通用 Agent 调度框架；
- 通用社区检测与图布局算法。

## PoC 顺序

1. 用 PaperQA2 对本地 VLA-R1 PDF 执行一个“思想来源与方法改造”研究任务，确认返回证据引用能够映射到工作台页码或文本片段。
2. 用 DSPy 声明同一研究任务的结构化研究制品，比较现有自由问答与声明式程序的字段完整性和证据绑定。
3. 将二者接入框架无关适配器，由工作台创建、观察和保存一次研究会话。
4. 当单篇与小语料研究制品稳定后，再对 GraphRAG 做会议语料社区综合 PoC。

PoC 不是缩减最终目标，而是确认成熟组件能否承担通用能力；失败时记录接口缺口，再决定替换或自研。
