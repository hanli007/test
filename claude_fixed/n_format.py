#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给验证结果 xlsx 的 N 列（待确认结论 / 参数自适应说明）做富文本标注。

不改列结构、不改文字内容，只做三件事：
  1. 长文按「；」「[上一轮依据]」「【复核】」断成多行，便于扫读
  2. 关键词着色：差异/缺陷/未实现 红；结论 绿；补充 蓝；数值 橙
  3. 类名:行号 依据 灰色小一档，视觉上退到背景

用法：python3 n_format.py <输入xlsx> <输出xlsx>
"""

import re
import sys

import openpyxl
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.styles import Alignment
from openpyxl.cell.text import InlineFont

# ── 颜色 ──────────────────────────────────────────────
RED = "C00000"      # 差异 / 缺陷 / 未实现
GREEN = "1E7145"    # 结论 / 通过
BLUE = "1F4E79"     # 补充 / 机制
ORANGE = "B45F06"   # 数值 / 参数
GRAY = "808080"     # 依据（类名:行号）
MUTED = "A6A6A6"    # 已推翻的旧结论
BLACK = "000000"

# 分句级别的前缀 → 颜色（按优先级从上到下匹配）
SEGMENT_RULES = [
    (r'^\[上一轮依据\]', RED, True),
    (r'^【[\d\s\-年月日]*复核】', BLUE, True),
    (r'^(差异|缺陷|风险提示|同类风险|不一致)', RED, True),
    (r'^(结论|判定|已覆盖|等效覆盖)', GREEN, True),
    (r'^(补充|补充内容|机制|代码事实)', BLUE, True),
    (r'^(数值|参数自适应)', ORANGE, True),
    (r'^(未实现|功能未实现|仍缺|缺失业务定义)', RED, True),
]

# 句内还需着色的片段
INLINE_RULES = [
    # 类名:行号  或  类名#方法
    (re.compile(r'[A-Z][A-Za-z0-9_]{2,}(?::\d+(?:-\d+)?(?:,\s*\d+(?:-\d+)?)*|#[A-Za-z0-9_]+)'), GRAY),
    (re.compile(r'(?<![A-Za-z0-9_])[:：]\d{1,4}(?:-\d{1,4})?'), GRAY),          # 裸 :386
    (re.compile(r'→'), ORANGE),                                                   # 用例口径→代码实际
    (re.compile(r'(未实现|无告警|不一致|缺陷|失败)'), RED),
]


def font(color=BLACK, bold=False, size=None, italic=False):
    return InlineFont(rFont="Calibri", sz=size, color=color, b=bold, i=italic)


def split_segments(text):
    """把整段拆成 (是否历史的标志, 小句)，保留 [上一轮依据] / 【复核】 分块。

    [上一轮依据] 之后的所有小句都属于"已被推翻的旧结论"，整体弱化，
    不能只把标记那一段变灰。
    """
    text = re.sub(r'(?=\[上一轮依据\])', '\n', text)
    text = re.sub(r'(?=【[\d\s\-年月日]*复核】)', '\n', text)
    out = []
    for block in text.split('\n'):
        block = block.strip()
        if not block:
            continue
        is_hist = block.startswith('[上一轮依据]')
        for p in re.split(r'(?<=[；。])(?!$)', block):
            p = p.strip()
            if p:
                out.append((is_hist, p))
    return out


def style_segment(seg, is_hist=False):
    """返回该句的 [TextBlock]，先按句级规则定基调，再按句内规则插色。"""
    # 历史块整体弱化：小号斜体灰字，不参与任何高亮
    if is_hist:
        return [TextBlock(font(MUTED, False, size=9, italic=True), seg)]

    base_color, base_bold = BLACK, False
    for pat, color, bold in SEGMENT_RULES:
        if re.match(pat, seg):
            base_color, base_bold = color, bold
            break

    # 找出所有需要内联着色的区间
    spans = []
    for pat, color in INLINE_RULES:
        for m in pat.finditer(seg):
            spans.append((m.start(), m.end(), color))
    spans.sort()

    def mk(color, bold, text):
        return TextBlock(font(color, bold), text)

    blocks = []
    pos = 0
    for start, end, color in spans:
        if start < pos:          # 与已着色区间重叠，跳过
            continue
        if start > pos:
            blocks.append(mk(base_color, base_bold, seg[pos:start]))
        blocks.append(mk(color, False, seg[start:end]))
        pos = end
    if pos < len(seg):
        blocks.append(mk(base_color, base_bold, seg[pos:]))
    if not blocks:
        blocks.append(mk(base_color, base_bold, seg))
    return blocks


def build_rich(text):
    blocks = []
    segs = split_segments(text)
    for i, (is_hist, seg) in enumerate(segs):
        blocks.extend(style_segment(seg, is_hist))
        if i != len(segs) - 1:
            blocks.append(TextBlock(font(), "\n"))
    return CellRichText(blocks)


def main():
    if len(sys.argv) < 3:
        print("用法: python3 n_format.py <输入.xlsx> <输出.xlsx>")
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]

    wb = openpyxl.load_workbook(src, rich_text=True)
    ws = wb["测试用例"]

    # 定位 N 列：优先按表头名找，找不到再退化为第 14 列
    n_col = None
    for c in ws[1]:
        if c.value and "待确认结论" in str(c.value):
            n_col = c.column
            break
    if n_col is None:
        n_col = 14
    print(f"N 列 = 第 {n_col} 列（{openpyxl.utils.get_column_letter(n_col)}）")

    done = 0
    for row in range(2, ws.max_row + 1):
        cell = ws.cell(row=row, column=n_col)
        val = cell.value
        if val is None:
            continue
        text = str(val)
        if not text.strip():
            continue
        rich = build_rich(text)
        n_lines = sum(1 for b in rich if isinstance(b, TextBlock) and "\n" in str(b.text))
        n_lines += 1
        cell.value = rich
        cell.alignment = Alignment(
            wrap_text=True, vertical="top",
            horizontal=cell.alignment.horizontal or "left",
        )
        ws.row_dimensions[row].height = max(30, min(230, 15 * n_lines))
        done += 1

    ws.column_dimensions[openpyxl.utils.get_column_letter(n_col)].width = 92
    wb.save(dst)
    print(f"已处理 {done} 行 → {dst}")


if __name__ == "__main__":
    main()
