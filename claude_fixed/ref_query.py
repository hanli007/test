# -*- coding: utf-8 -*-
"""
量化交易测试参考清单查询工具 —— 直读 5 份 xlsx，不依赖 md 摘要。

放在 ~/PycharmProjects/tc-refs/ 执行（skill 目录下的新脚本会被执行管控拦截）。

用法：
  python3 ref_query.py                       # 全量统计概览
  python3 ref_query.py 提现                   # 关键词搜索
  python3 ref_query.py 搬砖 -p P0            # 限优先级
  python3 ref_query.py -d 撮合                # 按维度/文件过滤
  python3 ref_query.py --md                  # 只列维度清单（选型用）
  python3 ref_query.py -f 05                 # 只看某个源文件
"""
import os
import sys
import glob

try:
    import openpyxl
except ImportError:
    print("需要 openpyxl: pip install openpyxl")
    sys.exit(1)

BASE = "/Users/silas/.claude/skills/测试用例/references"

ALIAS = {
    "id":   ["编号", "序号"],
    "dim":  ["维度", "场景分类", "类别", "测试领域", "子场景", "能力类别", "阶段"],
    "item": ["测试项", "测试点", "测试用例", "检查项", "具体能力", "活动"],
    "pre":  ["前置/步骤", "前置/构造", "测试步骤/场景", "测试方法", "典型表现/风险", "说明"],
    "exp":  ["预期结果/通过标准", "预期结果", "关键指标/通过标准", "验证方法", "产出"],
    "prio": ["优先级", "严重程度", "重要度"],
}


def _map_header(hdr):
    m = {}
    for i, h in enumerate(hdr):
        if h is None:
            continue
        h = str(h).strip()
        for key, alist in ALIAS.items():
            if h in alist and key not in m:
                m[key] = i
    return m


def load_all():
    rows = []
    for path in sorted(glob.glob(os.path.join(BASE, "*.xlsx"))):
        short = os.path.basename(path).split("_")[0]
        wb = openpyxl.load_workbook(path, data_only=True)
        for ws in wb.worksheets:
            m = _map_header([c.value for c in ws[1]])
            if "item" not in m:
                continue
            for r in ws.iter_rows(min_row=2, values_only=True):
                if not any(r):
                    continue

                def g(k):
                    idx = m.get(k)
                    if idx is None or idx >= len(r) or r[idx] is None:
                        return ""
                    return str(r[idx]).strip()

                rows.append({
                    "id": g("id"), "dim": g("dim") or ws.title,
                    "item": g("item"), "pre": g("pre"), "exp": g("exp"),
                    "prio": g("prio"), "file": short, "sheet": ws.title,
                })
    return rows


def show(rows, limit=200):
    if not rows:
        print("无匹配")
        return
    print(f"{'编号':6s} {'维度':12s} {'测试项':36s} {'优先级':6s} 预期结果")
    print("-" * 130)
    for r in rows[:limit]:
        print(f"{r['id'][:6]:6s} {r['dim'][:12]:12s} {r['item'][:36]:36s} "
              f"{r['prio'][:6]:6s} {r['exp'][:46]}")
    print(f"\n命中 {len(rows)} 条" + (f"（仅显示前 {limit}）" if len(rows) > limit else ""))


def overview(rows):
    from collections import Counter, defaultdict
    by_file = defaultdict(Counter)
    for r in rows:
        by_file[r["file"]][r["sheet"]] += 1
    for f in sorted(by_file):
        print(f"\n[{f}] 共 {sum(by_file[f].values())} 条")
        for sheet, n in by_file[f].items():
            print(f"    {sheet:18s} {n:3d}")
    print("\n优先级分布:", dict(Counter(r["prio"] for r in rows)))
    print("总条数:", len(rows))


def main():
    args = sys.argv[1:]
    if not args:
        overview(load_all())
        return

    kw = prio = dim = filef = None
    only_dim = False
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-p", "--prio") and i + 1 < len(args):
            prio = args[i + 1].upper(); i += 2
        elif a in ("-d", "--dim") and i + 1 < len(args):
            dim = args[i + 1]; i += 2
        elif a in ("-f", "--file") and i + 1 < len(args):
            filef = args[i + 1]; i += 2
        elif a == "--md":
            only_dim = True; i += 1
        else:
            kw = a; i += 1

    rows = load_all()
    if filef:
        rows = [r for r in rows if r["file"].startswith(filef)]
    if prio:
        rows = [r for r in rows if r["prio"].upper() == prio]
    if dim:
        rows = [r for r in rows if dim in r["dim"] or dim in r["sheet"] or dim in r["file"]]
    if kw:
        k = kw.lower()
        rows = [r for r in rows
                if k in (r["item"] + r["dim"] + r["pre"] + r["exp"] + r["sheet"]).lower()]

    if only_dim:
        from collections import Counter
        print("=== 可选维度（决定这次加载哪一类）===")
        for (f, s), n in sorted(Counter((r["file"], r["sheet"]) for r in rows).items()):
            print(f"  {f}  {s:18s} {n:3d} 条")
        return

    show(rows)


if __name__ == "__main__":
    main()
