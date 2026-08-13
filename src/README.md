# 核心源码

这里是本项目最主要的代码目录：

- `conference_paper/`：论文发现、筛选、alphaXiv 分析、Likes 采集、checkpoint 和报告生成 Block
- `conference_paper_bridge/`：AutoGPT 与影刀 RPA 之间的本地任务桥
- `json_blocks.py`：Graph 使用的 JSON 编解码 Block
- `test_json_blocks.py`：JSON Block 测试

这些文件由 `scripts/install.py` 安装到 AutoGPT Platform 对应位置。

