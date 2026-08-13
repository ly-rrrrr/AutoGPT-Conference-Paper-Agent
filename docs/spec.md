# Conference Paper Research Agent 设计规格

## 文档状态

- 状态：Approved for Implementation
- 版本：0.3.0
- 日期：2026-08-12
- 项目目录：`projects/conference-paper-research-agent/`
- V1 数据源：CVPR 2025/2026 CVF Open Access（默认 2026）
- V1 自动化模式：AutoGPT Platform 编排 + alphaXiv API Likes 主路径 + 影刀可切换兜底

## 1. 背景与问题

AI 顶会公开论文数量很大。用户逐篇打开会议页面、判断是否存在 arXiv 版本、记录
alphaXiv Likes、向论文助手提交固定问题并保存回答，过程重复、耗时且容易发生论文与
结果错位。

CVF Open Access 的 CVPR 页面按会议日列出论文，并对部分论文直接提供 `[arXiv]`
链接。V1 只处理页面明确提供该链接的论文，不再通过搜索引擎或 LLM 推断论文是否被
arXiv 收录。系统从链接确定性解析 `arxiv_id`，默认从 alphaXiv metadata API 读取 Likes；
需要 UI 复核或接口不可用时才切换影刀。AutoGPT Platform 并行执行论文分析、Likes 获取、
结果汇合和报告生成。

## 2. 项目目标

### 2.1 V1 目标

- 从配置年份对应的 CVF Open Access 首页发现会议日页面，默认 CVPR 2026。
- 受控并行获取分日页面，提取论文标题、作者、详情页、PDF 和页面自带 arXiv 链接。
- 合并分日结果并以详情页 URL 去重，显式报告空页面、失败页面和重复记录。
- 只选择带 CVF `[arXiv]` 链接且符合主题关键词的论文。
- 从 arXiv URL 确定性解析 `arxiv_id`，不执行标题搜索或模糊身份推断。
- 默认从 alphaXiv metadata API 并发读取 Likes；保留影刀单浏览器 Worker 作为可切换兜底。
- 默认通过 alphaXiv MCP `answer_pdf_queries` 为每篇论文一次性提交全部问题，并原样保存完整回答；可选使用外部 LLM 生成细粒度结构化分析。
- 按 `paper_key` 汇合 Likes 与论文分析，防止跨论文错配。
- 每篇论文完成后立即持久化，重跑时跳过已经完成的任务。
- 生成单篇 Markdown 报告、会议汇总报告和机器可读结果。
- 让论文发现、分析、Likes 采集、结果保存的状态、数量和错误均可观察。

### 2.2 后续目标

- 增加 ICCV、ICLR 和 ECCV 数据源适配器。
- 增加定时运行和增量发现。
- 在验证稳定性后评估无人值守影刀 Worker。
- 支持按研究方向、方法、数据集和代码可用性进行趋势分析。

## 3. 非目标

- V1 不处理 CVF 页面没有 `[arXiv]` 链接的论文。
- V1 不用标题搜索 arXiv，不调用搜索引擎判断是否收录。
- V1 不让影刀抓取会议论文列表或解析论文正文。
- V1 不使用 OCR 获取 Likes；只读取网页元素文本。
- V1 不点击 Like、Bookmark、AI Chat 或其他会改变外部状态的控件。
- V1 不并行运行多个影刀浏览器实例。
- 支持 CVPR 全量处理：`topics=[]` 表示不做标题过滤，`max_papers=0` 表示不设论文数量上限。
- 全量执行按论文写入 Likes 与分析检查点；同一 `run_id` 重跑时跳过已成功且分析模式、问题列表一致的结果。
- V1 不修改 AutoGPT Platform 的 Block 加载机制。
- V1 不要求修改 `schema.prisma` 或新增 Platform 数据库表。
- 不把 Likes 解释为论文质量或学术影响力。
- 不保存 alphaXiv、arXiv 或其他站点的账号、Cookie 和 Token。

## 4. 用户与主要用例

主要用户是希望跟踪 AI 顶会研究进展，同时学习 AutoGPT 自定义 Block、Graph、MCP、
RPA 集成和并行任务编排的开发者。

典型用例：

1. 用户选择 `CVPR`、`2025`，输入研究主题关键词和固定论文问题。
2. AutoGPT 获取 CVF 首页并发现 Day 1、Day 2、Day 3 页面。
3. 系统并行读取分日页面，形成唯一论文列表。
4. 系统保留带 `[arXiv]` 链接且命中可选主题关键词的论文；`max_papers=0` 时不截断。
5. 每篇论文同时进入内容分析分支和 Likes 采集分支。
6. alphaXiv MCP 或 LLM Provider 返回结构化论文分析。
7. Likes 分支默认并发请求 alphaXiv metadata API；需要时可切换为影刀逐篇读取。
8. AutoGPT 按 `paper_key` 汇合两个分支并保存单篇报告。
9. 全部任务达到终态后生成会议汇总报告和失败清单。

## 5. 系统架构

```text
CVF Conference Index
        |
        v
DiscoverCVFPapersBlock
  - 发现会议日
  - 并行获取分日页面
  - 解析、合并、去重、校验
        |
        v
SelectArxivPapersBlock
  - 只接受页面自带 arXiv 链接
  - 主题过滤与数量限制
  - 解析 arxiv_id / paper_key
        |
        +-------------------------------+
        |                               |
        v                               v
Paper Analysis Branch             Likes Branch
alphaXiv MCP / LLM                strategy=alphaxiv_api（默认）
并发 2..3                          并发读取 metadata API
                                          |
                                          +-- strategy=shadowbot（兜底）
                                              RPA Task Bridge
                                                    |
                                              ShadowBot Worker
        |                               |
        +---------------+---------------+
                        |
                        v
                 JoinPaperResultsBlock
                  - 按 paper_key 汇合
                  - 校验终态和必填结果
                        |
                        v
                  PersistPaperResultBlock
                        |
                        v
                 Conference Report Block
```

### 5.1 职责边界

AutoGPT Platform 负责工作流编排、HTTP/MCP 调用、结构化模型、受控并发、状态转换、
重试、结果汇合和报告生成。

确定性 Python 代码负责 HTML 解析、URL 校验、`arxiv_id` 解析、去重、关键词过滤、
Likes 文本校验和状态机；这些逻辑不交给 LLM。

Likes 默认从 alphaXiv metadata API 的
`data.paper_group.metrics.public_total_votes` 确定性读取。影刀只作为可配置兜底：接收
准确 arXiv URL、等待 alphaXiv 扩展注入 Likes 控件、读取元素文本并回传结果。影刀不分析
论文语义。

alphaXiv MCP 或可选 LLM Provider 只负责论文内容问答和结构化总结，不负责论文身份关联、
Likes 读取或运行状态判断。

## 6. 输入与配置

```yaml
ConferenceRunInput:
  conference: CVPR
  year: 2025
  topics: list[string]
  max_papers: integer = 20
  paper_questions: list[string]
  analysis_concurrency: integer = 3
  likes_strategy: alphaxiv_api | shadowbot = alphaxiv_api
```

约束：

- V1 `conference` 只能为 `CVPR`，`year` 只能为 `2025`。
- `topics` 可以为空；非空时每项去空白后不得为空字符串。
- `max_papers` 范围为 1 至 20。
- `paper_questions` 为 1 至 10 个非空问题。
- `analysis_concurrency` 范围为 1 至 3。
- `alphaxiv_api` 最多并发 5 个 metadata 请求；`shadowbot` Worker 并发固定为 1。

## 7. 核心数据契约

### 7.1 `PaperSeed`

```yaml
conference: string
year: integer
title: string
authors: list[string]
detail_url: string
pdf_url: string
arxiv_url: string | null
conference_day: string
```

`PaperSeed` 表示从 CVF 页面获得的事实，不包含推断或 LLM 结果。

### 7.2 `PaperTask`

```yaml
paper_key: string
conference: string
year: integer
title: string
authors: list[string]
detail_url: string
pdf_url: string
arxiv_url: string
arxiv_id: string
questions: list[string]
conference_day: string
```

`paper_key` 固定为 `arxiv:<canonical_arxiv_id>`。版本后缀从用于唯一标识的 ID 中移除，
原始 arXiv URL 保留。无法解析规范 arXiv ID 的论文不得创建 `PaperTask`。

### 7.3 `LikesTask`

```yaml
paper_key: string
title: string
arxiv_url: string
arxiv_id: string
```

### 7.4 `LikesResult`

```yaml
paper_key: string
arxiv_id: string
likes: integer | null
raw_text: string | null
status: SUCCESS | FAILED
error_code: string | null
```

规则：

- 成功结果的 `likes` 必须为非负整数。
- 成功结果的 `raw_text` 必须匹配 `^\s*[\d,]+\s+Likes?\s*$`。
- `paper_key` 和 `arxiv_id` 必须与输入任务完全一致。
- 失败结果的 `likes` 必须为 `null`，并包含稳定错误码。
- 单篇 Likes 结果不包含 `observed_at`；运行时间只记录在批次运行清单中。

### 7.5 `PaperAnalysis`

```yaml
paper_key: string
research_problem: string
main_contributions: list[string]
method_summary: string
datasets: list[string]
key_results: list[string]
limitations: list[string]
code_urls: list[string]
answer_by_question: map[string, string]
source_references: list[string]
warnings: list[string]
```

### 7.6 `PaperResult`

```yaml
paper: PaperTask
likes: LikesResult
analysis: PaperAnalysis | null
status: COMPLETED | PARTIAL | FAILED
warnings: list[string]
```

只有 Likes 和 Analysis 都成功时，论文状态才是 `COMPLETED`。只有一个分支成功时状态为
`PARTIAL`，并把失败分支加入可重试清单；两个分支都失败时状态为 `FAILED`。分析失败时
`analysis` 为 `null`，不得用无来源内容构造占位分析。

## 8. 论文发现流程

### 8.1 数据源

V1 入口：

```text
https://openaccess.thecvf.com/CVPR2025
```

系统先解析首页中的会议日链接，而不是直接假设日期或只依赖 `?day=all`。当前页面的
Day 1、Day 2、Day 3 页面并行度上限为 3。

### 8.2 页面解析

每个分日页面提取：

- 论文标题；
- 作者列表；
- CVF 详情页 URL；
- PDF URL；
- 页面自带 `[arXiv]` URL，可空；
- 会议日。

定位使用稳定的内容结构和相对链接关系，不依赖列表顺序或完整绝对 XPath。

### 8.3 合并与完整性

- 以规范化后的 `detail_url` 去重。
- 同一详情页在多个会议日出现时只保留一条并记录重复计数。
- 首页没有会议日、成功页面没有论文、论文缺标题或详情页时明确失败。
- 单个会议日请求失败时整批状态为 `PARTIAL`，不得报告为当天无论文。
- 每次运行输出 raw count、unique count、duplicate count、failed page count。

### 8.4 选择规则

1. 丢弃没有页面自带 `[arXiv]` 链接的论文，并计入 `skipped_no_arxiv_link`。
2. V1 使用大小写不敏感的确定性关键词匹配标题；摘要过滤留到后续版本，避免在选择前
   隐式增加逐篇详情请求。
3. 按规范化标题升序、`detail_url` 升序保证稳定顺序。
4. 截取前 `max_papers` 篇。
5. 从每条 arXiv URL 解析规范 `arxiv_id`，解析失败进入拒绝清单。

V1 不使用 Likes 决定哪些论文进入分析；Likes 是每个已选论文的必填结果字段。

## 9. Likes 双策略

### 9.1 默认策略：alphaXiv API

固定请求 `GET https://api.alphaxiv.org/v2/papers/{arxiv_id}/metadata`，读取
`data.paper_group.metrics.public_total_votes`。请求地址不允许由运行输入覆盖，避免将通用
HTTP 能力引入此领域 Block。各论文请求受 Semaphore 限制并发，单篇接口失败返回明确的
`FAILED` 结果，不中断其他论文。

该接口来自 alphaXiv 官方浏览器扩展当前使用的 metadata 路径，但不是 MCP 中公开的 Likes
工具，因此保留 `shadowbot` 作为协议变化时的可切换兜底。

### 9.2 影刀兜底前置条件

- 使用本机影刀客户端 6.2.23。
- 使用已启用 alphaXiv 扩展的受控浏览器环境。
- Likes 在未登录状态下可见；流程不登录任何站点。
- 影刀可访问本地 RPA Task Bridge。

### 9.3 影刀单任务步骤

```text
获取下一条 LikesTask
  -> 验证 paper_key / arxiv_id / arxiv_url
  -> 打开准确 arxiv_url
  -> 等待论文标题或 arXiv ID 出现
  -> 等待 alphaXiv Likes 元素出现
  -> 读取包含 "N Likes" 的元素文本
  -> 正则解析整数
  -> 回传 LikesResult
  -> 关闭当前标签页并领取下一条任务
```

不得使用标题搜索替代已提供的 arXiv URL。不得点击 Like 按钮。元素缺失或文本不合法时
最多重试一次；第二次失败后返回 `FAILED`，继续下一篇。

### 9.4 影刀元素定位

- 优先使用 `Likes` 可见文本和其所在控件的相对结构。
- 不使用屏幕固定坐标和从 `html/body` 开始的完整绝对 XPath。
- 读取整个 Likes 控件的文本，再以正则解析数值。
- 不以“页面第一个数字”作为 Likes。

## 10. RPA Task Bridge

V1 使用仅绑定本机的轻量 HTTP 服务解耦 Platform 和影刀：

```http
POST /runs/{run_id}/tasks
GET  /runs/{run_id}/tasks/next
POST /runs/{run_id}/results
GET  /runs/{run_id}/status
```

任务状态为：

```text
PENDING -> CLAIMED -> SUCCESS
                   -> FAILED
```

- 以 `(run_id, paper_key)` 保证任务幂等。
- 同一任务只能接受一次 SUCCESS；重复 SUCCESS 返回冲突但不得覆盖原结果。
- Bridge 地址通过配置提供，不在代码中硬编码。Platform 原生运行时默认绑定
  `127.0.0.1`；Platform 在容器中运行时绑定显式配置的宿主机私有接口，只允许容器
  网络与本机影刀访问。
- Bridge 不暴露到公网。容器模式使用每批次随机 Bearer Token，并通过 Windows 防火墙
  限制来源；Token 只存在于进程环境或本地忽略文件中，不写入运行产物。
- 影刀由用户手动启动一次并连续消费该批次任务；V1 不要求远程启动影刀应用。

## 11. AutoGPT Graph 与并行策略

```text
Discover -> Select -> Fan Out PaperTask
                         |            |
                         v            v
                  Analyze Paper    Collect Likes
                    concurrency=3  API concurrency=5
                                   或 RPA worker=1
                         |            |
                         +----- Join -+
                                |
                              Persist
                                |
                             Aggregate
```

- 会议日请求最多并发 3。
- 论文分析最多并发 3，并使用有界 Semaphore 和 Provider 速率限制。
- Likes 默认以最多 5 个并发请求读取 alphaXiv metadata；切换为影刀时只由一个 Worker 串行处理。
- 内容分析和 Likes 采集互不阻塞，按 `paper_key` 在 Join 阶段汇合。
- Writer 单实例持久化，避免并发覆盖。
- 聚合阶段只读取已持久化的单篇结果，不依赖内存中间状态。

AutoGPT 复用现有 HTTP、列表迭代、MCP Tool 和 AI Text Generator Block；论文发现、
选择、任务桥、结果汇合和持久化使用领域自定义 Block。

## 12. 持久化与运行产物

```text
projects/conference-paper-research-agent/data/runs/<run_id>/
├── manifest.json
├── papers.jsonl
├── likes-results.jsonl
├── paper-results.jsonl
├── reports/
│   └── <arxiv-id>.md  # 每个已选论文一份
└── conference-summary.md
```

`data/runs/` 是本地运行产物，不提交 Git。Fixture、契约和脱敏的验收样例可以提交。

批次 Manifest 至少记录：输入、开始与结束时间、发现页数、发现论文数、跳过数、选择数、
Likes 成功/失败数、分析成功/失败数、最终完成/部分/失败数。时间属于批次运行元数据，
不复制到每条 Likes 结果。

## 13. 错误模型

| 错误码 | 阶段 | 处理 |
|---|---|---|
| `CONFERENCE_INDEX_UNAVAILABLE` | Discover | 整批失败 |
| `NO_CONFERENCE_DAYS` | Discover | 整批失败 |
| `DAY_PAGE_UNAVAILABLE` | Discover | 批次 Partial，重试该页 |
| `EMPTY_PAPER_LIST` | Discover | 批次 Partial，不解释为空日 |
| `INVALID_PAPER_RECORD` | Discover | 隔离该记录 |
| `INVALID_ARXIV_URL` | Select | 拒绝该论文 |
| `ALPHAXIV_LIKES_NOT_FOUND` | Likes | 单篇失败，可切换影刀复核 |
| `ALPHAXIV_LIKES_UNAVAILABLE` | Likes | 有限重试后单篇失败，可切换影刀 |
| `RPA_BRIDGE_UNAVAILABLE` | Likes | 暂停派发，有限重试 |
| `LIKES_ELEMENT_NOT_FOUND` | Likes | 重试一次后单篇失败 |
| `INVALID_LIKES_TEXT` | Likes | 重试一次后单篇失败 |
| `LIKES_RESULT_MISMATCH` | Join | 拒绝错配结果 |
| `PAPER_ANALYSIS_FAILED` | Analysis | 单篇失败，不中断其他论文 |
| `RESULT_PERSIST_FAILED` | Persist | 停止聚合，不报告虚假完成 |

## 14. 正确性与安全约束

- 所有外部 URL 必须使用 HTTPS，并限制为批准的 CVF、arXiv 和 alphaXiv 主机。
- HTML 中的链接必须规范化并校验，禁止任意 URL 进入影刀和 MCP。
- `paper_key` 只由规范 arXiv ID 生成，不由 LLM 生成。
- Likes 必须由 `N Likes` 元素文本解析，不从截图、页面位置或其他裸数字推断。
- LLM 输出必须通过 Pydantic Schema 校验；无来源支持的字段进入 warnings。
- 提示词、账号信息、Cookie、OAuth Token 和浏览器数据不得写入运行产物。
- 外部服务限流或失败时采用有界重试，不无限循环。
- 单篇失败不得中断其他独立论文，持久化失败除外。

## 15. 测试策略

### 15.1 离线自动化测试

- CVF 首页 Fixture：发现三个会议日。
- 分日页面 Fixture：解析标题、作者、详情、PDF 和可选 arXiv 链接。
- 重复论文 Fixture：以详情 URL 去重并报告计数。
- 空页面和请求失败 Fixture：不得报告为成功空结果。
- arXiv URL 测试：解析新式 ID、版本后缀和拒绝非法主机。
- Likes 文本测试：接受 `0 Likes`、`1 Like`、`1,080 Likes`，拒绝裸数字和其他字段。
- Join 测试：拒绝 paper key 或 arXiv ID 不一致的 Likes 结果。
- 幂等测试：重复运行跳过 COMPLETED 论文。
- 并发测试：分析并发不超过配置值，Writer 不并发写。

自动化测试不启动真实浏览器、影刀、CVF、arXiv、alphaXiv 或外部 LLM。

### 15.2 影刀人工验收

- 用 5 篇带 CVF `[arXiv]` 链接的论文运行 Likes Worker。
- 人工逐页核对 5 个 Likes 数字，必须全部一致。
- 构造一个无 Likes 元素的本地测试页，确认重试一次后返回稳定错误码。
- 重复投递同一任务，确认不会覆盖已有 SUCCESS。
- 确认流程没有点击 Like 和 Bookmark。

### 15.3 端到端验收

- 输入 CVPR 2025、至少一个主题、`max_papers=5`。
- 三个会议日成功发现，论文列表非空且无重复详情 URL。
- 只选择页面自带 `[arXiv]` 链接的论文。
- 5 篇论文的 Likes 和分析分支可同时推进。
- 每篇结果按正确 `paper_key` 汇合。
- 失败任务出现在报告和可重试清单中。
- 重跑不重复分析或覆盖已完成论文。
- 生成 5 份单篇报告和 1 份会议汇总报告。

## 16. 功能验收条件

| ID | 条件 |
|---|---|
| `AC-001` | 首页发现全部会议日并并行读取分日页面 |
| `AC-002` | 论文列表以详情 URL 去重且计数可解释 |
| `AC-003` | 没有 CVF `[arXiv]` 链接的论文明确跳过 |
| `AC-004` | arXiv ID 仅由批准主机 URL 确定性解析 |
| `AC-005` | 默认 API 从 `public_total_votes` 读取非负整数；影刀兜底不点击 Like |
| `AC-006` | 抽查 5 篇 API、Bridge 与页面数字完全一致 |
| `AC-007` | 内容分析最多并发 3；Likes API 最多并发 5，影刀兜底并发 1 |
| `AC-008` | 两分支按 paper key 正确汇合，错配结果被拒绝 |
| `AC-009` | 单篇失败不影响其他论文，持久化失败不误报完成 |
| `AC-010` | 重跑跳过 COMPLETED 论文且不覆盖已有 SUCCESS |
| `AC-011` | 最终报告包含选择数、完成数、部分数、失败数和 Likes |

## 17. 项目边界与迁移

本项目使用独立目录，不删除或改写 `projects/job-market-agent/`。Job Market Agent 保留为
此前的数据契约和 AutoGPT Block 学习原型。Conference Paper Research Agent 可以复用
其 TDD、JSONL、运行清单和 Block 设计经验，但不复用招聘领域模型。

## 18. 参考数据源与能力

- CVPR 2025 CVF Open Access：`https://openaccess.thecvf.com/CVPR2025`
- CVPR 2025 All Papers：`https://openaccess.thecvf.com/CVPR2025?day=all`
- arXiv API：`https://info.arxiv.org/help/api/`
- alphaXiv MCP：`https://www.alphaxiv.org/docs/mcp`
- 影刀网页自动化能力：`https://rpa.lsepc.com/yddoc/language/zh-cn/产品介绍/影刀能做什么.html`
