"""飞书写入模块（P1 阶段实现）。

职责：把深度分析结果渲染成结构化报告，写入指定飞书文档（最新在最上方）。

实现要点（P1 再做）：
  - 用 FEISHU_APP_ID + FEISHU_APP_SECRET 换取 tenant_access_token
  - 调用飞书文档 block 写入接口，向 FEISHU_DOC_ID 文档头部插入内容
  - 需要应用权限 docx:document，并把应用加入文档协作者

P0 阶段我们只在终端打印报告（见 src/main.py 的 render_report），先不写飞书。
"""

from __future__ import annotations


def write_report(result: dict) -> None:
    raise NotImplementedError(
        "飞书写入是 P1 阶段的功能，等 P0 在本地跑通后再实现。"
    )
