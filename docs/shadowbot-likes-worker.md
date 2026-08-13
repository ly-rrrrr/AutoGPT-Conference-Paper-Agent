# 影刀 Likes Worker 操作说明

该 Worker 现在是 `likes_strategy=shadowbot` 的可切换兜底。默认
`likes_strategy=alphaxiv_api` 时不启动本流程，AutoGPT 直接并发读取 alphaXiv metadata。

本文说明如何在影刀 UI 中手动建立最小 Likes Worker。仓库只提供流程契约、诊断页和操作说明；Codex 不能操作本机影刀 UI，也不能仅凭本文声称流程已经建立或验收通过。

## 前置条件

- 影刀客户端位于 `D:\RPA-yingdao\ShadowBot.exe`，版本为 6.2.23。
- 受控浏览器已经启用 alphaXiv 扩展。
- alphaXiv Likes 在未登录时可见；本流程不登录任何站点。
- Bridge 与影刀运行在用户控制的本机环境中。

## 启动 Bridge

在 PowerShell 中进入后端目录，为当前终端会话设置环境变量，再启动服务：

```powershell
cd autogpt_platform/backend
$bridgeTokenSecure = Read-Host -AsSecureString "输入本批次 Bridge Token"
$bridgeToken = [Net.NetworkCredential]::new("", $bridgeTokenSecure).Password
$env:CONFERENCE_PAPER_BRIDGE_TOKEN = $bridgeToken
$env:CONFERENCE_PAPER_BRIDGE_HOST = "127.0.0.1"
$env:CONFERENCE_PAPER_BRIDGE_PORT = "8765"
poetry run python -m backend.conference_paper_bridge
```

Token 只保存在当前进程环境和影刀本次运行的密码框结果中。不要把 Token 写进流程参数默认值、全局变量、请求日志、截图、仓库文件或运行产物。Bridge 应仅绑定 `127.0.0.1`，不得暴露到公网。

## 在影刀中配置 Bearer Token

影刀 6.2.23 的流程参数没有“密码”类型，因此不要创建明文 `BRIDGE_TOKEN` 流程参数。

1. 把“对话框 > 自定义对话框”作为流程的第一个节点。
2. 在对话框设计器中加入“密码框”，字段命名为 `bridge_token`，不要设置默认值。
3. 将对话框结果保存到 `dialog_result`，再通过影刀的变量选择器选取该密码框结果，保存为本次运行的局部变量 `BRIDGE_TOKEN`。
4. 启动流程时输入与 PowerShell 中相同的批次 Token。密码只在当次运行内使用，不保存到流程参数或全局变量。
5. HTTP 节点统一添加请求头 `Authorization`，值由表达式拼接 `Bearer ` 与 `BRIDGE_TOKEN`。
6. 关闭 HTTP 节点的请求头详细日志；禁止打印 `dialog_result`、请求头或 `BRIDGE_TOKEN`。

## 最小节点流程

为流程创建字符串输入变量 `BRIDGE_BASE_URL` 和 `RUN_ID`。`BRIDGE_BASE_URL` 使用 `http://127.0.0.1:8765`，`RUN_ID` 使用实际批次提供的值，不要在模板中伪造或固定批次 ID。`BRIDGE_TOKEN` 不属于流程参数，由前述运行时密码框产生。

1. 创建“循环”节点。
2. 在循环内创建 HTTP GET 节点，请求 `BRIDGE_BASE_URL + /runs/ + RUN_ID + /tasks/next`，附带 Bearer 请求头。
3. 解析响应。若 `task` 为 `null`，正常退出循环。
4. 校验 `task.paper_key`、`task.arxiv_id`、`task.arxiv_url` 均非空，并且 `arxiv_url` 的协议为 HTTPS、主机严格等于 `arxiv.org`。
5. 新标签页打开响应中的准确 `arxiv_url`。不得使用标题搜索替代该 URL。
6. 等待页面出现当前 `arxiv_id` 或完整论文标题，再等待 alphaXiv 动作区域出现包含可见文本 `Likes` 的控件。元素容器出现不代表扩展已经完成文本注入。
7. 初始化 `raw_text=""` 和 `likes_wait_attempts=0`。每秒读取一次父控件完整文本；删除 `Like`、`Likes` 和逗号后，只有剩余内容为纯数字时才结束等待。最多读取 15 次。
8. 轮询成功时将纯数字文本转为整数 `likes`；轮询超时则不得执行整数转换，也不得把空文本记为 `0`，应回传 `FAILED / INVALID_LIKES_TEXT`。
9. 按下方 JSON 契约 POST 到 `BRIDGE_BASE_URL + /runs/ + RUN_ID + /results`，附带 Bearer 请求头。
10. 关闭当前标签页，回到循环领取下一条任务。

## 定位器规则

- 锚点必须是 alphaXiv 动作区域中的可见文本 `Likes`，目标必须是包含该文本的父控件。
- 读取整个父控件文本，不读取页面第一个数字，不从论文标题、年份、引用数或坐标推断 Likes。
- 不使用屏幕固定坐标，也不使用从 `html/body` 开始的绝对 XPath。
- 只有完整文本通过 `^\s*([\d,]+)\s+Likes?\s*$` 才能回传成功。

## 有界轮询与错误处理

alphaXiv 扩展异步注入 Likes 文本。Worker 使用以下表达式判断当前文本是否已经可解析：

```python
raw_text.replace("Likes", "").replace("Like", "").replace(",", "").strip().isdigit()
```

每秒读取一次，最多读取 15 次。15 次后仍没有得到合法数字时回传 `FAILED`，错误码 `INVALID_LIKES_TEXT`。等待元素节点本身超时则回传 `LIKES_ELEMENT_NOT_FOUND`。失败后关闭标签页并继续下一条，不得无限重试。

## 回传 JSON

成功时，`likes` 是解析后的整数，`raw_text` 是完整 Likes 控件文本：

```json
{
  "paper_key": "<来自任务的 paper_key>",
  "arxiv_id": "<来自任务的 arxiv_id>",
  "likes": "<解析后的整数>",
  "raw_text": "<完整 Likes 控件文本>",
  "status": "SUCCESS",
  "error_code": null
}
```

影刀发送请求前应把 `likes` 转成 JSON 数字，而不是保留为字符串。失败时不得保留猜测值：

```json
{
  "paper_key": "<来自任务的 paper_key>",
  "arxiv_id": "<来自任务的 arxiv_id>",
  "likes": null,
  "raw_text": null,
  "status": "FAILED",
  "error_code": "<稳定错误码>"
}
```

## 安全禁用动作

流程禁止点击 Like、Bookmark 或 AI Chat，禁止登录，禁止按标题搜索。流程只允许打开 Bridge 提供且已校验的 `https://arxiv.org/` URL、读取 Likes 文本并回传结果。

## 本地定位器诊断

可先在受控浏览器中打开 `shadowbot/test-pages/likes.html`，确认定位器跳过标题中的 2025 等干扰数字并读取 `83 Likes`。随后打开 `shadowbot/test-pages/missing-likes.html`，确认只有 Bookmark 时走元素缺失分支。

这两个 HTML 页面只用于定位器诊断，不是真实 alphaXiv 数据，不能替代真实 alphaXiv 页面、真实影刀流程或 5 篇论文人工验收，也不能据此填写 PASS。

## 真实双任务批量验证

2026-07-23 使用真实批次 `shadowbot-batch-20260723-172649` 验证异步轮询和统一 POST：

| paper_key | arxiv_id | Worker 值 | Bridge 状态 |
|---|---|---:|---|
| `arxiv:1706.03762` | `1706.03762` | 1086 Likes | SUCCESS |
| `arxiv:1512.03385` | `1512.03385` | 225 Likes | SUCCESS |

Bridge 终态计数为 `pending=0`、`claimed=0`、`success=2`、`failed=0`。本次结果证明双任务批量读取没有再触发空字符串整数转换错误，但不替代下方真实 5 篇人工验收。

## 真实 5 篇人工验收

当前状态：`NOT_RUN`。以下表格必须由用户在影刀 UI 中建立并导出流程后，使用 5 篇真实论文逐页核对并据实填写。不要预填 Likes、结果、`run_id` 或虚假 PASS。

| paper_key | url | 页面值 | worker值 | result |
|---|---|---|---|---|
|  |  |  |  | NOT_RUN |
|  |  |  |  | NOT_RUN |
|  |  |  |  | NOT_RUN |
|  |  |  |  | NOT_RUN |
|  |  |  |  | NOT_RUN |

用户需要在影刀 UI 中手动建立、保存并导出流程；在流程导出文件和真实 5 篇核对记录存在之前，Task 5 的影刀人工部分保持 `NOT_RUN`。
