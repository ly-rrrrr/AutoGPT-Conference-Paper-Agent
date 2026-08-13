# Conference Paper Research Agent 运行手册

本手册用于运行 CVPR 2026 全量论文研究 Graph。自动化测试验证 Graph、Block 契约、保存和恢复逻辑；外部服务仍以真实运行结果为准。

## 1. 准备后端

在仓库根目录执行：

```powershell
cd autogpt_platform/backend
poetry install
poetry run prisma generate
```

`poetry install` 按锁文件创建或更新 Python 虚拟环境并安装依赖。`poetry run prisma generate` 根据 `schema.prisma` 生成当前后端使用的 Prisma Python Client；它不迁移数据库，也不采集论文。

首次运行 Platform 时，再按 AutoGPT Platform 的本地开发文档启动数据库、Redis、RabbitMQ 和后端。不要为本项目单独修改 Prisma Schema。

## 2. 选择 Likes 策略

默认使用 `config.likes_strategy=alphaxiv_api`。该策略直接读取 alphaXiv metadata API，
不需要启动 Bridge、影刀或填写 Bridge Token，并以最多 5 个并发请求处理当前小样本。

只有需要验证 UI 兜底链路或 alphaXiv metadata 接口不可用时，才把配置改为
`config.likes_strategy=shadowbot`，再执行下面的 Token 和 Worker 步骤。

### 2.1 ShadowBot 策略：创建 Bridge Token

在新的 PowerShell 会话中生成随机 Token，并只放入本次会话环境变量：

```powershell
$bridgeToken = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$env:CONFERENCE_PAPER_BRIDGE_TOKEN = $bridgeToken
$env:CONFERENCE_PAPER_BRIDGE_HOST = "127.0.0.1"
$env:CONFERENCE_PAPER_BRIDGE_PORT = "8765"
$env:CONFERENCE_PAPER_BRIDGE_DB = "conference-paper-bridge.db"
```

不要把 Token 写入 Graph JSON、影刀流程参数默认值、全局变量、命令历史、日志、截图或项目文件。Graph 导入后，在 `CollectPaperLikesBlock` 的密码输入控件中填入同一 Token；影刀 6.2.23 则通过流程开始处的“自定义对话框 > 密码框”临时输入同一 Token。该值只应存在于平台的 Secret 输入、Bridge 进程环境和影刀本次运行内存中。

## 3. ShadowBot 策略：启动 Bridge 与 Worker

`alphaxiv_api` 策略跳过本节。`shadowbot` 策略保持上一步 PowerShell 会话，启动本地 Bridge：

```powershell
poetry run python -m backend.conference_paper_bridge
```

Bridge 必须绑定 `127.0.0.1:8765`，不要暴露到局域网或公网。随后手动启动 `D:\RPA-yingdao\ShadowBot.exe`，按照 [shadowbot-likes-worker.md](shadowbot-likes-worker.md) 创建或打开 Likes Worker，并设置：

- `BRIDGE_BASE_URL=http://127.0.0.1:8765`
- `RUN_ID` 与 Graph 本次 `config.run_id` 完全一致
- 运行流程后，在自定义对话框的密码框中输入与 Bridge 进程完全一致的 Token；不要创建明文 `BRIDGE_TOKEN` 流程参数

此时只打开并配置 Worker，不要点击运行。先按第 4、5 节启动 Graph；确认 `CollectPaperLikesBlock` 已进入运行/等待状态、任务已被投递到 Bridge 后，再运行 Worker。这样第一次领取不会因为队列尚未建立而收到 `task=null` 并提前退出。Worker 只能打开任务提供的 arXiv URL、读取 Likes 并回传；禁止登录、点击 Like、Bookmark 或 AI Chat。

## 4. 导入并配置 AutoGPT Graph

在 Platform 的 Builder 中导入：

```text
autogpt_platform/backend/agents/conference-paper-research-agent.json
```

导入后逐项检查：

1. `config` 默认是 `conference=CVPR`、`year=2026`、`topics=[]`、`max_papers=0`、`likes_strategy=alphaxiv_api`。空主题表示不过滤，`0` 表示处理所有带 CVF `[arXiv]` 链接的论文。
2. 默认策略无需填写 Bridge Token；切换为 `shadowbot` 后才填写 Token，并保留 `bridge_url=http://host.docker.internal:8765`。
3. alphaXiv MCP 是分析分支的内容源：默认调用 `get_paper_content` 获取通用报告，再通过 AIHubMix 的 `gpt-5.6-luna` 一次回答该论文的全部问题。最终完整 Markdown 问答原样写入 `qa-results.jsonl` 和单篇报告；不解析论文 XML，也不要求研究问题、数据集等结构化字段。
4. 全量运行保持 `config.topics=[]`；`config.paper_questions` 至少保留一项。
5. 给 `config.run_id` 设置本次真实、可复用且只包含字母、数字、点、下划线或连字符的批次 ID。切换 Likes 策略重新运行时建议使用新的 `run_id`，避免已有 COMPLETED 结果被恢复规则跳过。

## 5. 运行 CVPR 2026 全量任务

保持 `year=2026`、`topics=[]`、`max_papers=0`、`analysis_mode=structured_llm` 和
`likes_strategy=alphaxiv_api`，启动 Graph。Likes 分支最多并发 20 个 metadata 请求，不需要启动 Bridge 或影刀；分析分支最多并发 3 篇，每篇只调用一次 alphaXiv MCP 并提交全部问题。

全量任务耗时主要取决于 alphaXiv MCP。不要修改运行中的 `run_id`。若进程、容器或外部接口中断，使用同一 `run_id` 重新运行；系统会读取 `analysis-checkpoint.jsonl` 和 `likes-checkpoint.jsonl`，跳过已成功且问题配置未变化的论文。

超过 100 篇时，分析按 50 篇、Likes 按 100 篇分批调度。每篇分析完成后立即追加到
`analysis-checkpoint.jsonl` 和 `qa-results.jsonl`，每篇 Likes 完成后立即追加到
`likes-checkpoint.jsonl`。分支完成后仅通过 Graph 传递轻量信号，持久化节点从本地
checkpoint 汇合数据，避免全量答案超过 RabbitMQ 的单消息限制。

需要复核兜底时，新建一个 `run_id`，将 `likes_strategy` 改为 `shadowbot`，启动 Bridge 和
影刀后再次运行。两个策略输出完全相同的 `LikesResult`，下游无需改线。

观察并记录真实执行时间，确认分析与 Likes 分支存在时间重叠。不要用本地诊断 HTML、手写 Likes 或固定 LLM 响应替代该步骤。

## 6. 检查运行产物

产物目录为：

```text
projects/conference-paper-research-agent/data/runs/<run_id>/
```

真实五篇运行后逐项检查：

- `manifest.json`
- `papers.jsonl`
- `likes-results.jsonl`
- `paper-results.jsonl`
- `qa-results.jsonl`（标题、问题列表、完整回答）
- `analysis-checkpoint.jsonl`（分析断点）
- `likes-checkpoint.jsonl`（Likes 断点）
- `reports/` 下五份单篇 Markdown
- `conference-summary.md`

逐篇将 `likes-results.jsonl` 中的 `paper_key`、`arxiv_id` 和 Likes 与浏览器页面核对。失败项必须保留真实错误码，不能补猜测值。

## 7. 使用同一 run_id 恢复

若运行中断，修复外部服务或 Credential 后，保持相同的 `config.run_id` 再次运行。重跑前记录已完成论文的 `paper-results.jsonl` 内容；重跑后确认这些 `COMPLETED` 记录没有被覆盖，未完成项才继续处理。不要删除 Bridge SQLite 或运行目录来伪造“恢复成功”。

## 8. 验收状态

当前真实外部验收状态：`PARTIAL`。影刀到 Bridge、alphaXiv API、alphaXiv MCP 与 LLM 单篇端到端链路已经通过；全量运行、并行时间重叠和同 `run_id` 恢复仍需最终验收。

| 验收项 | 状态 | 真实证据 |
|---|---|---|
| ShadowBot UI Worker 双任务批量采集 | PASS | 真实批次 `shadowbot-batch-20260723-172649`：`1706.03762 → 1086`、`1512.03385 → 225`；Bridge 终态 `success=2`、`failed=0` |
| ShadowBot UI Worker 流程导出 | NOT_RUN | UI 流程已创建，但尚未把可导入流程文件保存到仓库 |
| alphaXiv MCP OAuth 调用 | PASS | 真实批次 `cvpr-2026-luna-smoke-01` 已取得论文内容并完成单篇报告 |
| LLM 完整问答 | PASS | `cvpr-2026-luna-smoke-01` 的 `analysis_success=1`，完整回答已写入 `qa-results.jsonl` 与单篇 Markdown |
| CVPR 2025 五篇 Likes 数字核对 | PASS | `2503.06960→25`、`2412.00556→14`、`2410.07599→1`、`2410.05346→14`、`2505.23766→34`；Bridge 与 alphaXiv `public_total_votes` 全部一致 |
| alphaXiv API 的 executor 容器采集 | PASS | 重建后的真实 executor 以并发 5 请求上述五篇，结果逐项一致，且无需 Bridge、影刀或浏览器 |
| alphaXiv API 默认策略的 AutoGPT 端到端运行 | PASS | `cvpr-2026-luna-smoke-01` 终态 `COMPLETED`，Likes 与分析均成功 |
| 两分支时间重叠 | NOT_RUN | 待 Platform 执行记录 |
| 同 run_id 恢复且不覆盖 COMPLETED | NOT_RUN | 待真实重跑记录 |

只有取得上述真实证据后，才能把对应状态改为 `PASS`。

## 9. 2026-07-19 自动化检查记录

以下结果只证明本地代码、Graph 契约和文件持久化，不替代第 8 节的真实外部验收：

| 检查 | 状态 | 证据 |
|---|---|---|
| 项目目标测试 | PASS | `130 passed, 2 warnings`；warnings 来自 Uvicorn/WebSockets 上游弃用提示 |
| Ruff | PASS | `All checks passed!` |
| isort | PASS | 目标目录无 import diff |
| Black | PASS | 沙箱外 `--check`：`23 files would be left unchanged` |
| Python 编译 | PASS | `COMPILE_OK` |
| AutoGPT 动态 Block 发现 | PASS | `get_blocks()` 找到并实例化全部 6 个领域 Block |
| Pyright | PASS | 沙箱外目标目录检查：`0 errors, 0 warnings, 0 informations` |

`spec.md` 继续保持 `Approved for Implementation`。只有 alphaXiv MCP 分析、默认 Likes API、
持久化产物、并行时间重叠和同 `run_id` 恢复均取得真实证据后，才可改为 `V1 Accepted`。

## 10. 2026-07-23 联调进度

已完成：

1. 影刀从 Bridge 连续领取两条真实 arXiv 任务。
2. 对 alphaXiv 异步注入的 Likes 文本执行有界轮询，避免将空字符串转成整数。
3. 两条结果通过同一个 POST 节点回传，Bridge 最终记录两条 `SUCCESS`。
4. 后端定向验证通过：`workflow_test.py`、`bridge_client_test.py`、`app_test.py` 合计 `29 passed`。
5. AutoGPT Platform 的数据库、Redis、RabbitMQ、FalkorDB、后端和前端已在本机启动，Builder 可通过 `http://127.0.0.1:3000` 访问。

## 11. 2026-08-07 联调进度

已完成：

1. 影刀与 Bridge 完成五篇真实论文，终态为 `success=5`、`failed=0`。
2. 五个结果与 alphaXiv metadata 的 `public_total_votes` 逐项一致。
3. 确认 Likes 不在 arXiv 原始 HTML 中，而由 alphaXiv 扩展读取 metadata 后插入 Shadow DOM。
4. `CollectPaperLikesBlock` 改为双策略，默认 `alphaxiv_api`，保留 `shadowbot` 兜底。
5. `rest_server` 与 `executor` 已重建；executor 内五篇 alphaXiv API 真实采集通过。

接下来的真实检查点：

1. 重新导入更新后的 Agent JSON，让已导入的旧 Graph 获得 `likes_strategy` 配置与新连线。
2. 使用新的 `run_id` 和默认 `likes_strategy=alphaxiv_api` 运行五篇样本。
3. 确认 Likes Block 不再等待影刀，并检查 `likes-results.jsonl`、单篇报告与会议汇总。
4. 验证 alphaXiv MCP 分析分支，使最终五篇达到 `COMPLETED`。
