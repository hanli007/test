#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给验收结果 xlsx 做富文本标注。

不改列结构、不改文字内容，只做四件事：
  1. 「待确认结论 / 参数自适应说明」列长文按「；」「。」「[上一轮依据]」「【复核】」断成多行，便于扫读
  2. 该列关键词着色：差异/缺陷/未实现 红；结论 绿；补充 蓝；数值/证据 橙
  3. 该列中 类名:行号 / 文件:行号 / 仓库/类名:行号 依据 灰色，视觉上退到背景
  4. 「验证判定」列按判定档加底纹（执行用例 8 档 + 规格节点 4 档 + 文档缺口 2 档）

写回前逐格比对「去掉空白后的文字」，有任何一格不一致即报错退出、不保存，保证零丢失。

用法：python3 n_format.py <输入xlsx> <输出xlsx> [sheet名]
  不给 sheet 名时，自动选表头含「待确认结论」的 sheet。
"""

import re
import sys

import openpyxl
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Alignment, PatternFill

# ── 颜色 ──────────────────────────────────────────────
RED = "C00000"      # 差异 / 缺陷 / 未实现
GREEN = "1E7145"    # 结论 / 通过
BLUE = "1F4E79"     # 补充 / 机制
ORANGE = "B45F06"   # 数值 / 参数 / 证据
GRAY = "808080"     # 依据（类名:行号）
MUTED = "A6A6A6"    # 已推翻的旧结论
BLACK = "000000"

NOTE_HEADER = "待确认结论"
VERDICT_HEADER = "验证判定"

# 分句级别的前缀 → 颜色（按优先级从上到下匹配）
SEGMENT_RULES = [
    (r'^\[上一轮依据\]', RED, True),
    (r'^【[\d\s\-年月日]*复核】', BLUE, True),
    (r'^(差异|缺陷|用例缺陷|风险提示|同类风险|不一致)', RED, True),
    (r'^(结论|判定|已覆盖|等效覆盖)', GREEN, True),
    (r'^(补充|补充内容|机制|代码事实)', BLUE, True),
    (r'^(数值|参数自适应|证据)', ORANGE, True),
    (r'^(未实现|功能未实现|仍缺|缺失业务定义)', RED, True),
]

# 依据：可选「仓库/」前缀 + 类名或文件名（可带扩展名）+ :行号[-行号][,行号] 或 #方法
_REF = (
    r'(?:[A-Za-z][A-Za-z0-9_\-]*/)?'
    r'[A-Za-z][A-Za-z0-9_]{2,}'
    r'(?:\.(?:java|xml|sql|yml|yaml|properties|json|kt))?'
    r'(?::\d+(?:-\d+)?(?:,\s*\d+(?:-\d+)?)*|#[A-Za-z0-9_×]+)'
)

# 句内还需着色的片段
INLINE_RULES = [
    (re.compile(_REF), GRAY),
    (re.compile(r'(?<![A-Za-z0-9_])[:：]\d{1,4}(?:-\d{1,4})?'), GRAY),          # 裸 :386
    (re.compile(r'→'), ORANGE),                                                   # 用例口径→代码实际
    (re.compile(r'(未实现|无告警|不一致|缺陷|失败)'), RED),
]

# 「验证判定」列底纹（浅色，保证黑字可读）
VERDICT_FILLS = {
    # 执行用例
    "已覆盖": "C6EFCE",
    "部分覆盖": "FFEB9C",
    "等效覆盖": "D9EAD3",
    "未纳入本轮": "EDEDED",
    "功能未实现": "FFC7CE",
    "不可离线验证": "DDEBF7",
    "待产品确认": "FCE4D6",
    "范围外": "D9D9D9",
    # 规格节点
    "规格一致": "C6EFCE",
    "规格偏差": "FFC7CE",
    "代码缺失": "FFC7CE",
    "部分可核对": "FFEB9C",
    # 文档缺口
    "已有代码口径": "DDEBF7",
    "代码未涉及": "EDEDED",
}


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
    in_hist = False
    for block in text.split('\n'):
        block = block.strip()
        if not block:
            continue
        if block.startswith('[上一轮依据]'):
            in_hist = True
        elif re.match(r'^【[\d\s\-年月日]*复核】', block):
            in_hist = False
        for p in re.split(r'(?<=[；。])(?!$)', block):
            p = p.strip()
            if p:
                out.append((in_hist, p))
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


def plain_text(value):
    """单元格的纯文字（富文本则拼接各段）。"""
    if isinstance(value, CellRichText):
        return "".join(b.text if isinstance(b, TextBlock) else str(b) for b in value)
    return "" if value is None else str(value)


def squash(text):
    """去掉全部空白，用于比对：断行只增删换行与首尾空格，不应改动任何可见字符。"""
    return re.sub(r'\s+', '', text)


def find_header_col(ws, keyword):
    for c in ws[1]:
        if c.value is not None and keyword in plain_text(c.value):
            return c.column
    return None


def pick_sheet(wb, name=None):
    if name:
        return wb[name]
    for ws in wb.worksheets:
        if find_header_col(ws, NOTE_HEADER):
            return ws
    names = "、".join(wb.sheetnames)
    print(f"未找到表头含「{NOTE_HEADER}」的 sheet（现有：{names}），请用第 3 个参数指定 sheet 名")
    sys.exit(1)


def main():
    if len(sys.argv) < 3:
        print("用法: python3 n_format.py <输入.xlsx> <输出.xlsx> [sheet名]")
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    sheet_name = sys.argv[3] if len(sys.argv) > 3 else None
    if src == dst:
        print("输出文件不能与输入文件相同，避免覆盖原文件")
        sys.exit(1)

    wb = openpyxl.load_workbook(src, rich_text=True)
    ws = pick_sheet(wb, sheet_name)

    n_col = find_header_col(ws, NOTE_HEADER)
    if n_col is None:
        print(f"sheet「{ws.title}」表头中没有「{NOTE_HEADER}」列")
        sys.exit(1)
    v_col = find_header_col(ws, VERDICT_HEADER)
    n_letter = openpyxl.utils.get_column_letter(n_col)
    print(f"sheet = {ws.title}；说明列 = 第 {n_col} 列（{n_letter}）；"
          f"判定列 = {'第 %d 列' % v_col if v_col else '未找到，跳过底纹'}")

    done, mismatches = 0, []
    for row in range(2, ws.max_row + 1):
        cell = ws.cell(row=row, column=n_col)
        text = plain_text(cell.value)
        if not text.strip():
            continue
        rich = build_rich(text)
        if squash(plain_text(rich)) != squash(text):
            mismatches.append(row)
            continue
        n_lines = 1 + sum(str(b.text).count("\n") for b in rich if isinstance(b, TextBlock))
        cell.value = rich
        cell.alignment = Alignment(
            wrap_text=True, vertical="top",
            horizontal=cell.alignment.horizontal or "left",
        )
        ws.row_dimensions[row].height = max(30, min(230, 15 * n_lines))
        done += 1

    if mismatches:
        print(f"文字比对不一致，未保存。出问题的行：{mismatches}")
        sys.exit(2)

    filled, unknown = 0, set()
    if v_col:
        for row in range(2, ws.max_row + 1):
            cell = ws.cell(row=row, column=v_col)
            verdict = plain_text(cell.value).strip()
            if not verdict:
                continue
            color = VERDICT_FILLS.get(verdict)
            if color is None:
                unknown.add(verdict)
                continue
            cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
            filled += 1

    ws.column_dimensions[n_letter].width = 92
    wb.save(dst)
    print(f"说明列已处理 {done} 行，文字比对零丢失；判定列加底纹 {filled} 格 → {dst}")
    if unknown:
        print(f"注意：以下判定值不在固定档位中，未加底纹，请核对是否填错：{sorted(unknown)}")


if __name__ == "__main__":
    main()
