# 相关工作谱系生态候选调查

调查日期：2026-10-22

## 能力拆解

相关工作谱系不是一个“画图功能”，而是五个可以独立判断的能力单元：

1. 学术 PDF 获取与资产追踪；
2. 章节、参考文献和文内引用的结构化解析；
3. 引用目标的身份消歧；
4. 从引用语境识别 `extends`、`improves`、`compares_with`、`differs_from`、`addresses_gap_of` 等科研关系，并保存原文证据；
5. 可过滤、可回溯证据的谱系图与列表视图。

前两项和第五项是成熟通用能力，应优先复用。第四项是本项目的核心差异，必须围绕科研语义自行建设。第三项采用外部元数据适配器与本地匹配共同完成。

## 候选比较

Stars 为调查时 GitHub 页面显示的近似值，只用于候选准入和生态成熟度判断，不作为唯一决策依据。

| 能力 | 候选 | Stars | 许可证 | 适配判断 |
|---|---:|---:|---|---|
| 通用文档解析 | [Docling](https://github.com/docling-project/docling) | 69.1k | MIT | 文档模型、JSON/Markdown、OCR 和多格式支持成熟；适合作为非标准 PDF 与未来知识库的通用适配器，但不是引用语境抽取的首选。 |
| 通用 PDF/OCR | [MinerU](https://github.com/opendatalab/MinerU) | 80.4k | MinerU Open Source License | 复杂版面、公式和 OCR 能力强，但许可证带附加条件，模型与运行时较重；保留为复杂 PDF 候选，不作为首个默认依赖。 |
| 学术 PDF 解析 | [GROBID](https://github.com/grobidOrg/grobid) | 4.9k | Apache-2.0 | 与目标重叠度最高：直接输出 TEI XML、章节、参考文献、文内引用目标和坐标；官方 Docker 服务边界清晰，确定为 V1 主解析器。 |
| 关系图分析与展示 | [Cytoscape.js](https://github.com/cytoscape/cytoscape.js) | 11k | MIT | 同时提供图模型、选择、过滤、布局和交互；更适合科研关系类型与证据面板，确定为 V1 展示引擎。 |
| 大图 WebGL 展示 | [Sigma.js](https://github.com/jacomyal/sigma.js) | 12.2k | MIT | 数千节点渲染优秀，但需要 Graphology，针对单篇谱系的关系交互成本高于 Cytoscape.js；作为大规模全局图候选。 |
| 2D 力导向图 | [force-graph](https://github.com/vasturiano/force-graph) | 2.1k | MIT | 上手快，但图分析、类型筛选和复杂交互弱于 Cytoscape.js；不采用。 |
| 3D 图展示 | [3d-force-graph](https://github.com/vasturiano/3d-force-graph) | 6.4k | MIT | 可作为未来三维科研空间的可替换展示层；当前阶段不让 3D 先于可靠关系数据。 |

## 决策

- 学术结构解析：GROBID 0.9.1 Docker 服务，通过 `ScholarlyDocumentParser` 适配器接入。
- 通用文档解析：保留 Docling 适配器边界，遇到 GROBID 无法处理的非标准文档时再启用。
- 引用目标消歧：先使用 DOI、arXiv ID、规范化标题与年份；OpenAlex 作为可选远程元数据适配器，不让核心模型绑定外部 API。
- 关系分类：保存原始引用和上下文；规则分类器只作为无模型费用的基线，并显式记录分类器及版本。后续模型分类器必须复用同一接口，不覆盖原始证据。
- 展示：Vue 3 中封装 Cytoscape.js，页面只消费后端统一的 `nodes + edges + evidence` 契约。

## 运行与安全边界

- GROBID 只监听本机端口，不向公网暴露；完整论文处理预计至少需要 4GB Docker 内存。
- 默认关闭 Crossref consolidation，避免一次论文解析触发大量外部请求；元数据补全由独立、可观测的消歧步骤执行。
- PDF、TEI、抽取结果与关系断言分层保存；任何重算都以来源哈希和抽取器版本区分。
- 自动关系属于机器断言，不冒充事实。低置信度关系继续显示为“仅引用”，用户以后可以确认或否决。

## 首个 PoC 验收标准

1. 对一篇已有 arXiv 映射的论文，能够下载或复用本地 PDF，并通过 GROBID 得到 TEI。
2. 能解析参考文献和正文中的文内引用，将引用标记关联到参考文献条目。
3. 每条关系至少保存目标论文、关系类型、上下文、章节、页码或定位信息、分类器版本和置信度。
4. 工作台能够以图和证据列表两种方式浏览谱系，并按关系类型筛选。
5. GROBID 不可用、PDF 缺失或解析失败时明确说明原因，不伪造空谱系。
