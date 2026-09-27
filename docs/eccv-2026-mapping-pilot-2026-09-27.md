# ECCV 2026 映射试跑：2026-09-27

本次验证只处理论文目录和 arXiv 元数据，没有调用付费 LLM 或运行论文问答。

## 官方目录

- 来源：https://eccv.ecva.net/Conferences/2026/AcceptedPapers
- 原始文件 SHA-256：`4d0d866526e4f5bf699a33bd6a34c7fae01603994255fc4c57f8582e36b43b3c`
- 2,851 行论文记录，17 行重复，按官方 ID 去重得到 **2,834 篇**。
- 另有一行 Cookie 提示表格，不属于论文。此前粗略表格行计数得到的 2,852 不能作为论文总数。
- 2,834 篇均有作者信息；共有 34 种非空主题标签组合。

## 50 篇分层样本

| 状态 | 篇数 | 含义 |
|---|---:|---|
| matched | 28 | 唯一候选通过标题和完整作者名规则 |
| needs_review | 8 | 有候选，但作者或标题变化未通过自动规则 |
| not_found | 14 | 本次两级查询未找到候选，不代表没有 arXiv 版本 |
| error / pending | 0 | 没有遗留网络错误或未处理样本 |

自动确认覆盖率为本样本的 56%，检索到候选的覆盖率为 72%。这不是准确率，也不直接外推全会议。28 条自动确认记录对应 28 个不同 arXiv ID。

对28条确认记录逐项检查了候选标题和作者匹配依据，未发现标题冲突。作者差异包括 PointSplat / SyncCache 的姓名顺序、Revisiting Scene Graph Generation 的中间名、CL-Anomaly 的连字符。MixGRPO 的预印本额外列有一位作者，其他十位均匹配；该差异保留在候选元数据中。此检查不等同于由外部人员建立金标准并测量准确率。

## 待复核案例

| 官方论文 | arXiv 候选 | 未自动接受的原因 |
|---|---|---|
| FixAnything | 2608.23549 | `Srinivasa G. Narasimhan` / `Srinivasa Narasimhan`，全名交集仅 2/3 |
| LaMP | 2603.25399 | 官方 `Policies` 与预印本 `Policy` 不同；另有不相关检索候选 |
| From Gaze to Meaning | 2609.06208 | 官方 `Unified Zero-Shot` 与预印本 `Training-Free ... Unified` 标题变化 |
| Guardrail-Agnostic Societal Bias Evaluation | 2608.29590 | 两位作者在预印本中增加中间名 |
| CoMaTrack | 2603.22846 | 作者数变化、`Lyu` / `Lv` 转写差异 |
| IRG-MotionLLM | 2512.10730 | `Yuanming` / `Yuan-Ming`、`Weishi` / `Wei-Shi` |
| DiTailed | 2607.12539 | 两位作者在预印本中使用更完整的姓名 |
| CountEx | 2602.19432 | `Minh Hoai Nguyen` / `Minh Hoai` |

这些候选保持 `needs_review`，本次没有修改规则来强行提高确认率。后续可以针对明确的姓名书写差异增加独立测试与有证据的复核流程；改题和作者变更仍需更强证据。

## 复现与边界

```powershell
python scripts/map_eccv_arxiv.py --limit 50
python -m unittest discover -s tests -v
```

原始网页、全目录、API 原始响应、50篇完整映射与断点保存在本地 `data/eccv-2026-mapping/`，该目录由 Git 忽略。重新执行使用同一快照和断点，不重复请求已完成记录。下一阶段是复核这8篇、补查14篇，再决定是否全量运行和接入 AutoGPT Graph。
