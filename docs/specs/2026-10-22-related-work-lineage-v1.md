# 相关工作谱系 V1 规格

## 目标体验

用户打开一篇论文后，可以回答：它引用了哪些工作、在什么语境下引用、与前置工作是继承、改进、比较、差异还是问题缺口关系，以及这项判断对应论文中的哪段原文。

V1 不以节点数量或视觉复杂度衡量成功。成功标准是关系可追溯、失败原因可观察、解析器可替换，并完成“论文 PDF → 学术结构 → 引用关系 → 证据页面”的闭环。

## 能力单元

### 1. 文档资产获取

- 输入：论文 ID；论文已有本地 PDF 或受信任的 `pdf_url`。
- 输出：受管理的 PDF 文件、SHA-256、下载来源、状态。
- 状态：`MISSING → DOWNLOADING → AVAILABLE`，失败进入 `FAILED` 并记录错误。
- 约束：仅允许 HTTPS 且限制到受信任学术域名；下载大小受限；重复请求按哈希复用。

### 2. 学术结构解析

- 输入：本地 PDF。
- 输出：原始 GROBID TEI、参考文献条目、正文引用语境。
- 状态：`AVAILABLE → PARSING → PARSED`，失败进入 `FAILED`。
- 适配器：核心服务只依赖 `ScholarlyDocumentParser`，GROBID 是首个实现。

### 3. 引用身份消歧

- 优先级：DOI → arXiv ID → 已有论文规范化标题与年份 → 外部工作记录。
- 未能解析为现有 `Paper` 的引用仍保存为 `ReferenceWork`，不因不完整而丢失证据。
- 外部 API 补全与基础解析解耦，失败不阻塞本地谱系生成。

### 4. 科研关系断言

- 关系类型：`cites`、`extends`、`improves`、`uses`、`compares_with`、`differs_from`、`addresses_gap_of`。
- 每条断言保存上下文、章节、页码/坐标、置信度、分类器、版本和来源哈希。
- V1 基线分类器采用高精度触发词；没有充分证据时回退为 `cites`，不强行推断。
- 模型分类器通过相同接口接入，并保留规则结果和原始证据，不覆盖历史记录。

### 5. 谱系浏览

- 全局页面显示已有谱系统计、可选论文、关系筛选、图谱和证据面板。
- 论文详情提供“查看相关工作谱系”入口。
- 点击节点显示论文身份；点击边显示关系判断、置信度、章节和原文证据。
- 图谱展示由 Cytoscape.js 完成；后端响应不包含任何 Cytoscape 专属字段。

## 数据边界

- `ReferenceWork`：参考文献中的学术工作，可选择关联现有 `Paper`。
- `PaperReference`：某论文参考文献表中的一个条目，保留原始文本和解析身份。
- `RelatedWorkEvidence`：正文某次引用产生的关系断言与证据。
- `DocumentAsset`：继续记录 PDF 状态；TEI 作为独立 `kind=grobid_tei` 资产保存。

这三层避免把“参考文献存在”“正文提及”和“存在某种科研关系”混为一谈。

## API 契约

- `GET /api/lineage/overview`：返回论文、参考工作、关系和状态统计。
- `GET /api/lineage/papers`：返回已经生成谱系或可以生成谱系的论文。
- `GET /api/lineage/papers/{paper_id}`：返回中心论文的节点、边和证据。
- `POST /api/lineage/papers/{paper_id}/extract`：明确触发 PDF 获取与解析；属于可能产生网络流量和较高 CPU/内存消耗的本机动作。

## 错误与可观察性

- PDF 无可信地址：`PDF_SOURCE_MISSING`。
- 下载失败或超限：`PDF_DOWNLOAD_FAILED` / `PDF_TOO_LARGE`。
- GROBID 未启动：`PARSER_UNAVAILABLE`。
- GROBID 无内容：`PARSER_EMPTY_RESULT`。
- TEI 结构不完整：保留成功解析部分，并在结果中返回 warnings。

页面显示具体错误和恢复动作，不用空图伪装成功。

## 性能边界

- V1 单次只解析一篇论文，Web 请求设置明确超时，不做全量 2,915 篇批处理。
- 单篇图默认一跳、最多 300 个参考节点；超出部分按引用出现次数和关系强度截断，并返回截断信息。
- GROBID 是独立 Docker 服务，数据库和 Web 服务不与其进程生命周期耦合。

## 验收

- 使用固定 TEI fixture 验证引文解析、关系类型和幂等写入。
- 使用 API 测试验证空谱系、已有谱系和解析器不可用三条关键路径。
- 使用前端测试验证筛选、节点/边选择与证据展示。
- 仅做一篇公开 arXiv 论文的真实 PoC，不为了验证而批量下载或调用付费模型。
