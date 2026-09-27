# ECCV 2026 → arXiv 映射

该工具是现有 CVPR 分析流水线之前的独立数据准备阶段。它获取 ECCV 官方名单，查询 arXiv 的真实元数据，保存匹配依据；不调用 LLM，不需要 API Key，也不启动 AutoGPT 分析。

## 运行

需要 Python 3.10+ 和可在 PATH 中执行的 `curl`，无需额外 Python 依赖。在本扩展仓库根目录执行：

```powershell
python scripts/map_eccv_arxiv.py --limit 3
python scripts/map_eccv_arxiv.py --limit 50
```

默认输出为 `data/eccv-2026-mapping/`。抽样按官方主题分组，在组内使用稳定 ID 哈希排序，再轮流取样；50 篇是确定性主题分层样本，不是简单取网页前 50 篇，也不代表全会议的随机统计样本。无论抽样多少篇，均保存完整官方目录。

确认小批量结果后，全量命令为：

```powershell
python scripts/map_eccv_arxiv.py --limit 0
```

同一输出目录再次运行，会跳过已有非错误结果。错误记录自动重试。重新查询尚未确认的记录：

```powershell
python scripts/map_eccv_arxiv.py --limit 50 --retry-unresolved --refresh-cache
```

官方 HTML 快照在同一输出目录内保持不变，便于复现。若要获取新版本名单，使用新的 `--output data/eccv-2026-mapping-YYYYMMDD`，不会覆盖原始快照。

## 如何判断同一篇论文

1. 如果名单偶尔附带直接 arXiv 链接，先通过 arXiv ID 查询元数据，仍需核对标题和作者。
2. 否则用完整标题查询 arXiv；没有确认结果时，使用最长的四个非停用标题词与第一作者姓氏检索候选。
3. 仅在规范化标题完全一致、两边作者列表各至少 80% 的完整姓名一致、至少两位完整姓名相符（单作者论文要求该作者全名相符）、且没有其他同标题或强相似候选时自动确认。
4. 大小写、Unicode 兼容形式、空白和标点可规范化。姓名缩写、姓名转写差异、数学标题、改题论文不放宽自动确认规则，保留人工复核。模糊分数只供复核，不会单独触发接受。

本版本不自动遍历任意作者项目站点，不用模型猜测 ID，不声称解决所有改题情况。召回率可能保守。`matched` 是按上述规则自动确认，不等于独立人工审查过，也不是统计意义上已测得的准确率。

## 输出与状态

| 文件 | 内容 |
|---|---|
| `accepted-papers.html`、`source.json` | 官方页面快照、来源、获取时间 |
| `catalog.jsonl` | 全部条目：官方 ID、标题、作者、主题、会场、项目链接 |
| `mapping-checkpoint.jsonl` | 逐篇追加的处理记录，含输入指纹、检索词、候选元数据、匹配依据和时间 |
| `mappings.jsonl` | 本轮所选论文的最新处理结果 |
| `matched-papers.jsonl` | 本轮所选论文中自动确认的记录 |
| `summary.json` | 全目录、样本、已处理、待处理、各状态数量及快照 SHA-256 |
| `arxiv-cache/` | 通过验证的 Atom 响应、请求 URL 和抓取时间 |

- `matched`：唯一候选满足自动确认规则。
- `needs_review`：检索到候选，但不能可靠自动确认。
- `not_found`：本次限定查询没有返回候选，**不表示证明 arXiv 上不存在论文**。
- `error`：网络、服务、解析或结果截断等错误，不能解释成未找到。
- `pending_count`：选中但尚未处理的条目。

标题和作者元数据变更，或匹配器版本升级，会改变断点指纹。异常中断导致 JSONL 末行不完整时，工具备份原文件后恢复完整前缀；中间行损坏则停止，不静默丢弃。

请求单连接串行执行，至少间隔 3.1 秒。可重试的网络失败最多尝试两次；429/403 立即停止本轮；连续三个记录出错也会停止。相同查询优先复用缓存。**不要同时运行多个输出目录的任务**，限流器不是跨进程全局限流器。

若进程被强制终止导致 `.mapping.lock` 残留，确认没有映射进程仍在运行后再移除该文件。正常退出和 Ctrl+C 会释放锁。

正常完成返回 0；存在错误或未处理条目返回 2；Ctrl+C 返回 130。`complete` 只表示所选映射任务处理完毕，不表示所有论文都有 arXiv 映射。

## 与 AutoGPT 的衔接边界

现有发布版的会议字段和 Graph 仍面向 CVPR。`matched-papers.jsonl` 提供后续接入所需的官方记录和已确认 arXiv ID，**目前不能直接作为旧 Graph 的输入**。完成映射验证后，再扩展会议模型、导入块和 Graph；这里不会修改或污染 CVPR 的历史 checkpoint。

## 离线验证

```powershell
python -m unittest discover -s tests -v
```

覆盖官方页面解析、作者缺失、重复官方 ID、同名不同作者、候选歧义、版本去重、API 错误、缓存、限速、断点损坏恢复、输入变更、输出生成和批量错误停止。

官方参考：[ECCV 名单](https://eccv.ecva.net/Conferences/2026/AcceptedPapers)、[arXiv API 查询说明](https://info.arxiv.org/help/api/user-manual.html)、[arXiv API 使用要求](https://info.arxiv.org/help/api/tou.html)。
