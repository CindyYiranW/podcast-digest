"""去重 / 合并逻辑（P1 阶段实现）。

目标：当多集 episode 标签高度重合、主题相近时，标记为同一主题簇，
深度分析时合并讨论，避免报告冗余。

P0 阶段还用不到，先留占位。"""

from __future__ import annotations


def merge_similar(episodes: list[dict]) -> list[dict]:
    # TODO(P1): 基于 tags / framework_ids 的重合度做主题聚类合并。
    return episodes
