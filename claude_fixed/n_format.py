#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给验收结果 xlsx 做富文本标注。

不改列结构、不改文字内容，只做五件事：
  1. 「待确认结论 / 参数自适应说明」列长文按「；」「。」「[上一轮依据]」「【复核】」断成多行，便于扫读
  2. 该列关键词着色：差异/缺陷/未实现 红；结论 绿；补充 蓝；数值/证据 橙
  3. 该列中 类名:行号 / 文件:行号 / 仓库/类名:行号 依据 灰色，视觉上退到背景
  4. 「验证判定」列按判定档加底纹（执行用例 8 档 + 规格节点 4 档 + 文档缺口 2 档）
  5. 若存在「代码反向覆盖」sheet：其「说明」列同样做 1~3；「覆盖程度」「风险等级」列按取值加底纹；
     「需求依据」为「需求外行为」的格子标红底（该 sheet 表头可不在第 1 行，自动查找）

写回前逐格比对「去掉空白后的文字」（两个 sheet 都比对），有任何一格不一致即报错退出、不保存，保证零丢失。

用法：python3 n_format.py <输入xlsx> <输出xlsx> [主sheet名]
  不给主 sheet 名时，自动选表头含「待确认结论」的 sheet。
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


# 「代码反向覆盖」sheet（第 6.8 步）
REVERSE_SHEET = "代码反向覆盖"
REVERSE_NOTE_HEADER = "说明"
COVERAGE_HEADER = "覆盖程度"
RISK_HEADER = "风险等级"
BASIS_HEADER = "需求依据"
OUT_OF_SCOPE = "需求外行为"
OUT_OF_SCOPE_FILL = "FFC7CE"
COVERAGE_FILLS = {
    "已覆盖": "C6EFCE",
    "用例有但未验证": "FFEB9C",
    "未覆盖": "FFC7CE",
}
RISK_FILLS = {
    "高": "FFC7CE",
    "中": "FCE4D6",
    "低": "EDEDED",
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


def find_header_col(ws, keyword, header_row=1):
    for c in ws[header_row]:
        if c.value is not None and keyword in plain_text(c.value):
            return c.column
    return None


def find_header_row(ws, keywords, max_scan=30):
    """表头不一定在第 1 行（反向覆盖 sheet 表头上方写有清点范围），找同时含全部关键词的那一行。"""
    for r in range(1, min(ws.max_row, max_scan) + 1):
        texts = [plain_text(c.value) for c in ws[r]]
        if all(any(k in t for t in texts) for k in keywords):
            return r
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


def format_note_column(ws, col, first_row):
    """把一列长文改成富文本；返回 (处理行数, 文字不一致的行号列表)。不一致的格子不写回。"""
    done, mismatches = 0, []
    for row in range(first_row, ws.max_row + 1):
        cell = ws.cell(row=row, column=col)
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
        height = max(30, min(230, 15 * n_lines))
        current = ws.row_dimensions[row].height
        ws.row_dimensions[row].height = max(height, current or 0)
        done += 1
    ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 92
    return done, mismatches


def fill_by_value(ws, col, first_row, fills):
    """按单元格取值加底纹；返回 (加底纹格数, 不认识的取值集合)。"""
    filled, unknown = 0, set()
    for row in range(first_row, ws.max_row + 1):
        cell = ws.cell(row=row, column=col)
        value = plain_text(cell.value).strip()
        if not value:
            continue
        color = fills.get(value)
        if color is None:
            unknown.add(value)
            continue
        cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
        filled += 1
    return filled, unknown


def format_reverse_sheet(wb):
    """处理「代码反向覆盖」sheet；不存在则跳过。返回 (报告行列表, 不一致行列表, 未知取值字典)。"""
    if REVERSE_SHEET not in wb.sheetnames:
        return [f"未找到「{REVERSE_SHEET}」sheet，跳过"], [], {}
    ws = wb[REVERSE_SHEET]
    header_row = find_header_row(ws, ["代码位置", REVERSE_NOTE_HEADER])
    if header_row is None:
        return [f"「{REVERSE_SHEET}」中找不到同时含「代码位置」「{REVERSE_NOTE_HEADER}」的表头行，跳过"], [], {}
    first = header_row + 1
    report, unknown = [], {}

    note_col = find_header_col(ws, REVERSE_NOTE_HEADER, header_row)
    done, mismatches = format_note_column(ws, note_col, first)
    report.append(f"「{REVERSE_SHEET}」表头在第 {header_row} 行；说明列处理 {done} 行")

    for header, fills in ((COVERAGE_HEADER, COVERAGE_FILLS), (RISK_HEADER, RISK_FILLS)):
        col = find_header_col(ws, header, header_row)
        if col is None:
            report.append(f"未找到「{header}」列，跳过底纹")
            continue
        filled, bad = fill_by_value(ws, col, first, fills)
        report.append(f"「{header}」列加底纹 {filled} 格")
        if bad:
            unknown[header] = sorted(bad)

    basis_col = find_header_col(ws, BASIS_HEADER, header_row)
    if basis_col:
        marked = 0
        for row in range(first, ws.max_row + 1):
            cell = ws.cell(row=row, column=basis_col)
            if plain_text(cell.value).strip() == OUT_OF_SCOPE:
                cell.fill = PatternFill(start_color=OUT_OF_SCOPE_FILL, end_color=OUT_OF_SCOPE_FILL,
                                        fill_type="solid")
                marked += 1
        report.append(f"「{BASIS_HEADER}」列标出「{OUT_OF_SCOPE}」{marked} 格")
    return report, [(REVERSE_SHEET, r) for r in mismatches], unknown


def main():
    if len(sys.argv) < 3:
        print("用法: python3 n_format.py <输入.xlsx> <输出.xlsx> [主sheet名]")
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

    done, main_bad = format_note_column(ws, n_col, 2)
    rev_report, rev_bad, rev_unknown = format_reverse_sheet(wb)

    mismatches = [(ws.title, r) for r in main_bad] + rev_bad
    if mismatches:
        print(f"文字比对不一致，未保存。出问题的位置（sheet, 行）：{mismatches}")
        sys.exit(2)

    filled, unknown = fill_by_value(ws, v_col, 2, VERDICT_FILLS) if v_col else (0, set())

    wb.save(dst)
    print(f"说明列已处理 {done} 行，文字比对零丢失；判定列加底纹 {filled} 格")
    for line in rev_report:
        print(line)
    print(f"→ {dst}")
    if unknown:
        print(f"注意：以下判定值不在固定档位中，未加底纹，请核对是否填错：{sorted(unknown)}")
    for header, values in rev_unknown.items():
        print(f"注意：「{REVERSE_SHEET}」的「{header}」列有不在固定档位中的取值，未加底纹，请核对：{values}")


if __name__ == "__main__":
    main()
