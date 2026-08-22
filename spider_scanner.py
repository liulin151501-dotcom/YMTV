#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地爬虫源扫描解析工具
========================

读取本地目录中的 .py / .js / .json 三种格式的爬虫文件并解析出元信息：

  .js    -> TVbox JS 爬虫（var rule = {...}），优先用 Node 提取完整 rule 对象
  .json  -> TVbox 站点配置（sites / spider 字段）或单个爬虫配置
  .py    -> TVbox Python 爬虫（from base.spider import Spider）

用法示例：
  python3 spider_scanner.py                          # 扫描当前目录
  python3 spider_scanner.py --dir 本地包              # 扫描指定目录
  python3 spider_scanner.py --type json              # 只看 json
  python3 spider_scanner.py --keyword 影视            # 按名称过滤
  python3 spider_scanner.py --out 爬虫清单.json       # 报告保存到文件
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

NODE_HELPER = r"""
const vm = require('vm');
let input = '';
process.stdin.on('data', d => input += d);
process.stdin.on('end', () => {
  try {
    const items = JSON.parse(input);
    const out = items.map(it => {
      try {
        // 沙箱桩: 屏蔽 rule 对象求值时依赖的 TVbox 运行时
        const sandbox = {
          log: () => {}, JSON: JSON, Math: Math, console: console,
          base64Decode: () => '', unescape: s => s,
          decodeURIComponent: decodeURIComponent, encodeURIComponent: encodeURIComponent,
          request: () => '', fetch: () => {}, $js: { toString: () => '' },
          muban: {}, Object: Object, Array: Array, String: String,
          parseInt: parseInt, parseFloat: parseFloat, RegExp: RegExp,
        };
        sandbox.globalThis = sandbox;
        const code = (it.pre || '') + '\n(' + it.code + ')';
        const val = vm.runInNewContext(code, sandbox);
        // JSON 往返: 丢弃函数等不可序列化字段
        const data = JSON.parse(JSON.stringify(val));
        return { f: it.f, ok: true, data: data };
      } catch (e) {
        return { f: it.f, ok: false, err: String(e) };
      }
    });
    console.log(JSON.stringify(out));
  } catch (e) {
    console.log(JSON.stringify({ fatal: String(e) }));
  }
});
"""

# 常见编码顺序: UTF-8 (含 BOM) -> GBK
ENCODINGS = ("utf-8-sig", "utf-8", "gbk", "latin-1")

RULE_RE = re.compile(r"\b(?:var|let|const)\s+rule\s*=\s*\{")

# TVbox 爬虫特征字段（用于区分真实爬虫与库文件）
SPIDER_FEAT_RE = re.compile(
    r"\b(?:host|url|class_parse|一级|二级|搜索|searchUrl|detailUrl|play_parse)\s*:"
)

# ---------------- 基础工具 ----------------


def read_text(path):
    """容错读取文本文件"""
    raw = open(path, "rb").read()
    for enc in ENCODINGS:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def bracket_match(text, start, open_ch="{", close_ch="}"):
    """从 text[start] == open_ch 开始做括号配对，返回匹配的 close_ch 下标"""
    depth = 0
    in_str = None  # None / "'" / '"'
    i = start
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        else:
            if ch in ("'", '"'):
                in_str = ch
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


VAR_ARR_RE = re.compile(r"\bvar\s+(\w+)\s*=\s*\[")


def extract_var_arrays(text, limit_pos):
    """提取 rule 之前出现的 'var xxx = [...]' 数组声明，用于解析混淆的 rule"""
    parts = []
    for m in VAR_ARR_RE.finditer(text, 0, limit_pos):
        start = text.find("[", m.start(), limit_pos)
        if start < 0:
            continue
        end = bracket_match(text, start, "[", "]")
        if end < 0:
            continue
        parts.append(text[m.start() : end + 1])
    return ";".join(parts) + ";" if parts else ""


def extract_rule(text):
    """提取 'var rule = {...}' 中的 JS 对象文本，返回 (前缀数组声明, 对象文本)"""
    m = RULE_RE.search(text)
    if not m:
        return None
    start = text.find("{", m.start())
    end = bracket_match(text, start)
    if end < 0:
        return None
    return extract_var_arrays(text, m.start()), text[start : end + 1]


# ---------------- JS 爬虫解析 ----------------


def parse_js_with_node(code_list):
    """用 Node 批量把 JS 对象文本转成 Python dict"""
    if not code_list:
        return {}
    helper = os.path.join(tempfile.gettempdir(), "rule_extract.js")
    with open(helper, "w", encoding="utf-8") as f:
        f.write(NODE_HELPER)
    proc = subprocess.run(
        ["node", helper],
        input=json.dumps(code_list, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        return {}
    try:
        out = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return {}
    if isinstance(out, dict) and "fatal" in out:
        return {}
    result = {}
    for item in out:
        if item.get("ok"):
            result[item["f"]] = item.get("data") or {}
    return result


def parse_js_fallback(text):
    """Node 不可用时的正则回退，提取常用字段"""
    fields = {}
    for key in ("title", "host", "url", "searchUrl", "detailUrl", "class_parse"):
        m = re.search(
            r"\b%s\s*:\s*['\"]([^'\"]*)['\"]" % re.escape(key), text
        )
        if m:
            fields[key] = m.group(1)
    # hostJs 动态 host: 尝试解码 base64Decode('...') 中的 HOST
    if not fields.get("host"):
        m = re.search(
            r"\bHOST\s*=\s*base64Decode\(\s*['\"]([^'\"]+)['\"]", text
        )
        if m:
            try:
                import base64 as _b64
                fields["host"] = _b64.b64decode(m.group(1)).decode(
                    "utf-8", errors="replace"
                )
            except Exception:
                fields["host"] = m.group(1)
    return fields


def parse_js_spider(path, rel, rule_data):
    """组装 JS 爬虫的解析结果"""
    info = {
        "file": rel,
        "kind": "js",
        "name": None,
        "host": None,
        "url": None,
        "searchUrl": None,
        "detailUrl": None,
        "type": None,
        "filterable": None,
        "ok": True,
        "note": "",
    }
    if rule_data:
        for k in ("title", "name"):
            if rule_data.get(k):
                info["name"] = str(rule_data[k]).strip()
                break
        info["host"] = rule_data.get("host")
        info["url"] = rule_data.get("url")
        info["searchUrl"] = rule_data.get("searchUrl")
        info["detailUrl"] = rule_data.get("detailUrl")
        info["type"] = rule_data.get("type")
        info["filterable"] = rule_data.get("filterable")
    else:
        text = read_text(path)
        fallback = parse_js_fallback(text)
        if fallback:
            info["name"] = (fallback.get("title") or os.path.basename(path)).strip()
            info["host"] = fallback.get("host")
            info["url"] = fallback.get("url")
            info["searchUrl"] = fallback.get("searchUrl")
            info["detailUrl"] = fallback.get("detailUrl")
            info["ok"] = True
            info["note"] = "仅正则提取"
        elif SPIDER_FEAT_RE.search(text) and re.search(r"\btitle\s*:", text):
            info["ok"] = False
            info["note"] = "rule 提取失败（混淆/复杂语法）"
        else:
            info["ok"] = True
            info["note"] = "库文件（无爬虫特征）"
    if not info["name"]:
        info["name"] = os.path.basename(path)
    return info


# ---------------- JSON 配置解析 ----------------


def strip_json_comments(text):
    """字符串感知地去除 JSON 中的 // 与 /* */ 注释、清理尾逗号、转义字符串内的裸控制字符。

    返回 (清洗后的文本, 是否发生了修改)。不会误删字符串内部的 http:// 等。
    """
    out = []
    i, n = 0, len(text)
    in_str = False
    changed = False
    while i < n:
        ch = text[i]
        if in_str:
            if ch == "\\":
                out.append(ch)
                if i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                    continue
            elif ch == '"':
                out.append(ch)
                in_str = False
            elif ord(ch) < 0x20:
                esc = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}.get(
                    ch, "\\u%04x" % ord(ch))
                out.append(esc)
                changed = True
            else:
                out.append(ch)
            i += 1
        else:
            if ch == '"':
                in_str = True
                out.append(ch)
                i += 1
            elif ch == "/" and i + 1 < n and text[i + 1] == "/":
                changed = True
                while i < n and text[i] not in "\r\n":
                    i += 1
            elif ch == "/" and i + 1 < n and text[i + 1] == "*":
                changed = True
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2
            else:
                out.append(ch)
                i += 1
    text2 = "".join(out)
    text2 = re.sub(r",(\s*[}\]])", r"\1", text2)
    return text2, changed


def looks_encrypted(text):
    """识别 TVbox 密文配置：#密文配置 标记开头，或纯 base64 字符组成的无结构内容"""
    head = text[:200]
    if "#密文" in head or "密文配置" in head:
        return True
    compact = re.sub(r"\s+", "", head)
    if len(compact) < 60:
        return False
    if any(ch in compact for ch in "{}[]\":<"):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9+/=_-]+", compact))


def parse_json_file(path, rel):
    text = read_text(path).lstrip("\ufeff")
    tolerant = False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        clean, changed = strip_json_comments(text)
        tolerant = changed
        try:
            data = json.loads(clean)
        except json.JSONDecodeError:
            data = None
    if data is None:
        head = text[:512].lower()
        if looks_encrypted(text):
            note = "密文配置（加密，需解密后解析）"
        elif "<!doctype" in head or "<html" in head:
            note = "非 JSON 内容（HTML 页面）"
        else:
            try:
                json.loads(text)
            except json.JSONDecodeError as e:
                note = "JSON 解析失败: %s" % e.msg
            else:
                note = "JSON 解析失败"
        return {"file": rel, "kind": "json", "ok": False,
                "note": note,
                "site_count": 0, "sites": [], "spider": None}

    info = {
        "file": rel,
        "kind": "json",
        "ok": True,
        "note": "",
        "site_count": 0,
        "spider": None,
        "sites": [],
    }

    if isinstance(data, dict):
        sites = data.get("sites")
        if isinstance(sites, list):
            info["note"] = "TVbox 配置(sites)"
            info["site_count"] = len(sites)
            for s in sites:
                if not isinstance(s, dict):
                    continue
                info["sites"].append({
                    "key": s.get("key"),
                    "name": s.get("name"),
                    "type": s.get("type"),
                    "api": s.get("api"),
                })
        spider = data.get("spider")
        if spider:
            info["spider"] = spider
            info["note"] = (info["note"] + " + jar" if info["note"] else "含 spider(jar) 配置")
        if not info["note"]:
            # 单个爬虫配置对象
            if any(k in data for k in ("key", "api", "url", "name")):
                info["note"] = "单爬虫配置"
                info["site_count"] = 1
                info["sites"].append({
                    "key": data.get("key"),
                    "name": data.get("name") or data.get("title"),
                    "type": data.get("type"),
                    "api": data.get("api"),
                })
            else:
                info["note"] = "其他 JSON"
    elif isinstance(data, list):
        info["note"] = "JSON 数组(元素 %d 个)" % len(data)
    else:
        info["note"] = "标量 JSON"
    if tolerant and info["note"]:
        info["note"] += "（容错解析）"
    return info


# ---------------- Python 爬虫解析 ----------------


PY_CLASS_RE = re.compile(
    r"^\s*class\s+([A-Za-z_]\w*)\s*\(([^)]*Spider[^)]*)\)", re.M
)
PY_METHOD_RE = re.compile(r"^\s+def\s+(\w+)\s*\(", re.M)
PY_HOST_RE = re.compile(
    r"^\s*(?:xurl|host|baseUrl|base_url|mainUrl)\s*=\s*['\"]([^'\"]+)['\"]",
    re.M,
)


def parse_py_spider(path, rel):
    text = read_text(path)
    info = {
        "file": rel,
        "kind": "py",
        "ok": True,
        "name": None,
        "class": None,
        "methods": [],
        "host": None,
        "note": "",
    }
    m = PY_CLASS_RE.search(text)
    if m:
        info["class"] = m.group(1)
        info["name"] = m.group(1)
        # 只收集该类名下的方法（避免收集到辅助类的方法）
        cls_start = m.start()
        next_cls = PY_CLASS_RE.search(text, m.end())
        seg_end = next_cls.start() if next_cls else len(text)
        seg = text[cls_start:seg_end]
        info["methods"] = [x for x in PY_METHOD_RE.findall(seg)]
    hm = PY_HOST_RE.search(text)
    if hm:
        info["host"] = hm.group(1)
    if not info["name"]:
        # 无 Spider 类，按普通 py 处理
        info["name"] = os.path.basename(path)
        info["note"] = "未发现 Spider 类"
    else:
        info["note"] = "TVbox Python 爬虫"
    return info


# ---------------- 扫描主流程 ----------------


def scan(root, exclude_files=()):
    js_candidates = []  # [{f, code}] 传给 node 批量解析
    py_results = []
    json_results = []
    exclude_abs = {os.path.abspath(p) for p in exclude_files}

    for dirpath, _dirs, files in os.walk(root):
        # 跳过常见无关目录
        if any(part in ("node_modules", ".git", "venv", "__pycache__")
               for part in dirpath.split(os.sep)):
            continue
        for fn in files:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            # 排除工具自身与输出报告
            if os.path.abspath(full) in exclude_abs:
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext == ".js":
                text = read_text(full)
                if RULE_RE.search(text):
                    extracted = extract_rule(text)
                    if extracted:
                        pre, code = extracted
                        js_candidates.append({"f": rel, "pre": pre, "code": code})
            elif ext == ".json":
                json_results.append(parse_json_file(full, rel))
            elif ext == ".py":
                py_results.append(parse_py_spider(full, rel))

    # Node 批量提取所有 JS rule
    rule_map = parse_js_with_node(js_candidates)
    js_results = []
    for cand in js_candidates:
        js_results.append(
            parse_js_spider(
                os.path.join(root, cand["f"]), cand["f"], rule_map.get(cand["f"])
            )
        )

    return {"js": js_results, "py": py_results, "json": json_results}


def summarize(results):
    js, py, jsons = results["js"], results["py"], results["json"]
    js_lib = sum(1 for x in js if "库文件" in x.get("note", ""))
    return {
        "js_total": len(js) - js_lib,
        "js_lib": js_lib,
        "js_ok": sum(1 for x in js if x.get("ok") and "库文件" not in x.get("note", "")),
        "py_total": len(py),
        "json_total": len(jsons),
        "json_ok": sum(1 for x in jsons if x.get("ok")),
        "tvbox_site_count": sum(x.get("site_count", 0) for x in jsons),
        "jar_spider_count": sum(1 for x in jsons if x.get("spider")),
        "py_spider_count": sum(1 for x in py if x.get("class")),
    }


def dedup_sites(results):
    """跨全部 JSON 配置按 key 去重站点，返回 {key: {...}} 索引"""
    from collections import defaultdict
    site_map = defaultdict(list)
    for r in results["json"]:
        for s in r.get("sites") or []:
            k = s.get("key")
            if not k:
                continue
            site_map[k].append({
                "file": r["file"], "name": s.get("name"),
                "type": s.get("type"), "api": s.get("api"),
            })
    index = {}
    for k, refs in site_map.items():
        first = refs[0]
        index[k] = {
            "key": k,
            "name": first["name"],
            "type": first["type"],
            "api": first["api"],
            "ref_count": len(refs),
            "files": sorted({x["file"] for x in refs}),
        }
    return index


def fmt_table(headers, rows):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    line = "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    sep = "  ".join("-" * widths[i] for i in range(len(headers)))
    body = [
        "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row))
        for row in rows
    ]
    return "\n".join([line, sep] + body)


def main():
    ap = argparse.ArgumentParser(description="读取本地 py/js/json 爬虫文件")
    ap.add_argument("--dir", default=".", help="要扫描的目录（默认当前目录）")
    ap.add_argument("--type", choices=["js", "py", "json"], default=None,
                    help="只显示指定类型")
    ap.add_argument("--keyword", default=None, help="按爬虫名称/文件名关键词过滤")
    ap.add_argument("--limit", type=int, default=50,
                    help="每类最多显示条数（0 表示全部）")
    ap.add_argument("--out", default=None, help="把完整报告保存为 JSON 文件")
    ap.add_argument("--sites-out", default=None,
                    help="把跨配置去重后的站点索引保存为 JSON 文件")
    args = ap.parse_args()

    root = args.dir
    if not os.path.isdir(root):
        print("目录不存在: %s" % root)
        sys.exit(1)

    print("正在扫描: %s" % os.path.abspath(root))
    excludes = [os.path.abspath(__file__)]
    if args.out:
        excludes.append(args.out)
    results = scan(root, excludes)
    summary = summarize(results)

    def matches(info):
        if args.type and info["kind"] != args.type:
            return False
        if args.keyword:
            name = str(info.get("name") or "")
            fname = os.path.basename(info.get("file") or "")
            if args.keyword not in name and args.keyword not in fname:
                return False
        return True

    sections = []

    # ---- 汇总 ----
    print("\n==== 扫描汇总 ====")
    print("JS 爬虫源 : %d 个（成功解析 %d，库文件 %d）" % (
        summary["js_total"], summary["js_ok"], summary["js_lib"]))
    print("Python 爬虫: %d 个（含 Spider 类 %d）" % (
        summary["py_total"], summary["py_spider_count"]))
    print("JSON 配置 : %d 个（有效 %d，含站点 %d 个，含 jar %d 个）" % (
        summary["json_total"], summary["json_ok"],
        summary["tvbox_site_count"], summary["jar_spider_count"]))

    # ---- JS ----
    if args.type in (None, "js"):
        rows = [
            (r["file"], r["name"] or "", r["host"] or "",
             r["url"] or "", r["searchUrl"] or "")
            for r in results["js"]
            if matches(r) and "库文件" not in r.get("note", "")
        ]
        if rows:
            sections.append(("JS 爬虫明细", ["文件", "名称", "host", "url", "搜索接口"], rows))

    # ---- PY ----
    if args.type in (None, "py"):
        rows = [
            (r["file"], r["name"] or "", r["class"] or "",
             ",".join(r["methods"][:6]), r["host"] or "")
            for r in results["py"] if matches(r)
        ]
        if rows:
            sections.append(("Python 爬虫明细", ["文件", "类名", "继承类", "方法", "host"], rows))

    # ---- JSON ----
    if args.type in (None, "json"):
        rows = []
        for r in results["json"]:
            if not matches(r):
                continue
            if r.get("sites"):
                for s in r["sites"][:5]:
                    rows.append((r["file"], s.get("name") or "", s.get("type"),
                                 s.get("api") or ""))
                if r["site_count"] > 5:
                    rows.append((r["file"], "... 还有 %d 个站点" % (r["site_count"] - 5), "", ""))
            else:
                rows.append((r["file"], "-", "-", r.get("note") or ""))
        if rows:
            sections.append(("JSON 站点/配置明细", ["文件", "站点名", "类型", "api"], rows))

    for title, headers, rows in sections:
        print("\n==== %s（%d 条）====" % (title, len(rows)))
        limit = args.limit if args.limit > 0 else len(rows)
        print(fmt_table(headers, rows[:limit]))
        if len(rows) > limit:
            print("... 共 %d 条，仅显示前 %d 条（可用 --limit 0 显示全部）"
                  % (len(rows), limit))

    # ---- 保存报告 ----
    if args.out:
        report = {"summary": summary, "results": results}
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print("\n完整报告已保存: %s" % os.path.abspath(args.out))

    # ---- 保存去重站点索引 ----
    if args.sites_out:
        index = dedup_sites(results)
        ref_total = sum(v["ref_count"] for v in index.values())
        with open(args.sites_out, "w", encoding="utf-8") as f:
            json.dump({"unique_count": len(index),
                       "ref_total": ref_total,
                       "sites": index}, f, ensure_ascii=False, indent=2)
        print("去重站点索引已保存: %s（唯一 %d 个，引用 %d 次）"
              % (os.path.abspath(args.sites_out), len(index), ref_total))


if __name__ == "__main__":
    main()
