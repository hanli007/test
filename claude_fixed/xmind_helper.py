"""
XMind 通用生成工具 (XMind 8 / content.xml 格式)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【已锁定配置 - 请勿修改以下风格参数】
  画布：逻辑图向右   structure-class = org.xmind.ui.logic.right
  主题：彩虹七色     模块级依次循环（红橙黄绿蓝靛紫）
  第一级文字：黑色   #000000（彩虹背景不变）
  子层级：前置条件/用例/步骤/预期/额外前置 各自独立配色
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
所有通过此 helper 生成的 .xmind 文件均自动应用以上配置。

使用方式：
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from xmind_helper import module_node, tc_node, build_xmind
"""
import zipfile, uuid

TS = "1733000000000"
SC = "org.xmind.ui.logic.right"   # 逻辑图向右

# ── 彩虹七色（模块级循环）────────────────────────────────────
RAINBOW = [
    {"id": "r0", "bg": "#F44336", "br": "#B71C1C", "fg": "#000000"},  # 红
    {"id": "r1", "bg": "#FF9800", "br": "#E65100", "fg": "#000000"},  # 橙
    {"id": "r2", "bg": "#FDD835", "br": "#F9A825", "fg": "#000000"},  # 黄
    {"id": "r3", "bg": "#66BB6A", "br": "#2E7D32", "fg": "#000000"},  # 绿
    {"id": "r4", "bg": "#29B6F6", "br": "#01579B", "fg": "#000000"},  # 蓝
    {"id": "r5", "bg": "#5C6BC0", "br": "#1A237E", "fg": "#000000"},  # 靛
    {"id": "r6", "bg": "#AB47BC", "br": "#4A148C", "fg": "#000000"},  # 紫
]
S_ROOT  = "s_root"
S_PRE   = "s_pre"
S_TC    = "s_tc"
S_STEP  = "s_step"
S_EXP   = "s_exp"
S_EXTRA = "s_extra"
S_TODO  = "s_todo"   # 文档信息不全时的待确认/待补充节点：红色加粗字体，不设背景（跟随父节点颜色）

def gen_id(): return uuid.uuid4().hex[:20]
def _e(s):   return s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

# ── XML 节点构建 ──────────────────────────────────────────────
def _topic(tid, title, children="", sid=None, sc=True):
    attr = f'id="{tid}" timestamp="{TS}"'
    if sid: attr += f' style-id="{sid}"'
    if sc:  attr += f' structure-class="{SC}"'
    body = f'<children><topics type="attached">{children}</topics></children>' if children else ''
    return f'<topic {attr}><title>{_e(title)}</title>{body}</topic>'

def tc_node(tc_id, title, steps, expected, extra_pre=None):
    exp  = _topic(gen_id(), f"预期结果：{expected}", sid=S_EXP,  sc=False)
    step = _topic(gen_id(), f"测试步骤：{steps}",    exp, sid=S_STEP)
    ch   = (_topic(gen_id(), f"额外前置：{extra_pre}", sid=S_EXTRA, sc=False) if extra_pre else "") + step
    return _topic(gen_id(), f"{tc_id} {title}", ch, sid=S_TC)

def module_node(title, common_pre, cases_xml, color_idx):
    sid   = RAINBOW[color_idx % 7]["id"]
    inner = _topic(gen_id(), f"前置条件：{common_pre}", sid=S_PRE, sc=False) + cases_xml
    return _topic(gen_id(), title, inner, sid=sid)

def todo_node(text):
    """待确认/待补充节点：文档信息不全时使用，红色加粗字体，不设背景"""
    return _topic(gen_id(), text, "", sid=S_TODO, sc=False)

# ── styles.xml 生成 ───────────────────────────────────────────
def _styles():
    rows = [
        f'<style id="{S_ROOT}" type="topic"><topic-properties '
        f'fill-color="#263238" border-line-color="#37474F" line-color="#546E7A" '
        f'fo:color="#FFFFFF" fo:font-weight="bold"/></style>',
    ]
    for r in RAINBOW:
        rows.append(
            f'<style id="{r["id"]}" type="topic"><topic-properties '
            f'fill-color="{r["bg"]}" border-line-color="{r["br"]}" line-color="{r["bg"]}" '
            f'fo:color="{r["fg"]}" fo:font-weight="bold"/></style>'
        )
    for sid, bg, br, fg in [
        (S_PRE,   "#FFF8E1", "#FFB300", "#5D4037"),
        (S_TC,    "#FAFAFA", "#BDBDBD", "#212121"),
        (S_STEP,  "#E3F2FD", "#90CAF9", "#1565C0"),
        (S_EXP,   "#E8F5E9", "#A5D6A7", "#2E7D32"),
        (S_EXTRA, "#FFF3E0", "#FFCC02", "#E65100"),
    ]:
        bold = ' fo:font-weight="bold"' if sid == S_TC else ''
        rows.append(
            f'<style id="{sid}" type="topic"><topic-properties '
            f'fill-color="{bg}" border-line-color="{br}" '
            f'fo:color="{fg}"{bold}/></style>'
        )
    rows.append(
        f'<style id="{S_TODO}" type="topic"><topic-properties '
        f'fo:color="#D32F2F" fo:font-weight="bold"/></style>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<xmap-styles xmlns="urn:xmind:xmap:xmlns:style:2.0" '
        'xmlns:fo="http://www.w3.org/1999/XSL/Format" version="2.0">\n'
        '  <styles>\n    ' + '\n    '.join(rows) + '\n  </styles>\n</xmap-styles>'
    )

# ── 生成 .xmind 文件 ──────────────────────────────────────────
def build_xmind(output_path, root_title, modules_xml):
    root     = _topic(gen_id(), root_title, modules_xml, sid=S_ROOT)
    sheet_id = gen_id()

    content = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<xmap-content xmlns="urn:xmind:xmap:xmlns:content:2.0" '
        'xmlns:fo="http://www.w3.org/1999/XSL/Format" '
        'xmlns:svg="http://www.w3.org/2000/svg" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'timestamp="{TS}" version="2.0">\n'
        f'<sheet id="{sheet_id}" timestamp="{TS}">\n{root}\n'
        '<title>Sheet 1</title>\n</sheet>\n</xmap-content>'
    )
    manifest = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<manifest xmlns="urn:xmind:xmap:xmlns:manifest:1.0">\n'
        '  <file-entry full-path="content.xml" media-type="text/xml"/>\n'
        '  <file-entry full-path="styles.xml"  media-type="text/xml"/>\n'
        '  <file-entry full-path="META-INF/"   media-type=""/>\n'
        '  <file-entry full-path="META-INF/manifest.xml" media-type="text/xml"/>\n'
        '</manifest>'
    )
    meta = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>'
        f'<meta xmlns="urn:xmind:xmap:xmlns:meta:2.0" timestamp="{TS}" version="2.0"/>'
    )
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("content.xml",           content.encode('utf-8'))
        zf.writestr("styles.xml",            _styles().encode('utf-8'))
        zf.writestr("meta.xml",              meta.encode('utf-8'))
        zf.writestr("META-INF/manifest.xml", manifest.encode('utf-8'))
    print(f"[xmind_helper] 生成成功：{output_path}")
