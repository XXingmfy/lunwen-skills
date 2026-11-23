#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_project.py —— 项目源码证据扫描（阶段一）

产出：
  <out>.json  结构化证据（技术栈/模块/路由/数据表/页面/角色/配置文件）
  <out>.md    人读摘要（含证据文件路径，便于回到源码核对）

用法：
  python scan_project.py D:/code/my-project --out paper-context/project-evidence

注意：脚本只做“线索提取”，不替代逐文件精读；论文中的每个事实仍须能指回源码位置。
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

SKIP_DIRS = {".git", ".svn", ".idea", ".vscode", "node_modules", "target", "build", "dist",
             "out", "bin", "obj", "venv", ".venv", "env", "__pycache__", ".next", ".nuxt",
             "coverage", "logs", "log", "tmp", "temp", "uploads", "static", "assets"}
CODE_EXT = {".java", ".kt", ".py", ".js", ".ts", ".vue", ".jsx", ".tsx", ".php", ".cs",
            ".go", ".rb", ".sql", ".xml", ".yml", ".yaml", ".json", ".properties"}
TEXT_EXT = CODE_EXT | {".md", ".txt", ".html", ".css", ".scss", ".sh", ".bat"}
MAX_FILE_BYTES = 1_500_000


def read_text(path):
    for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                return f.read()
        except (UnicodeDecodeError, LookupError):
            continue
        except Exception:
            break
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""


def walk(root):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(p) > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            files.append(p)
    return files


def rel(root, p):
    return os.path.relpath(p, root).replace("\\", "/")


def detect_stack(root, files):
    stack = []
    evidence = defaultdict(list)
    names = [os.path.basename(f).lower() for f in files]

    def add(name, why, path):
        if name not in stack:
            stack.append(name)
        evidence[name].append(f"{why}：{rel(root, path)}")

    for f in files:
        low = os.path.basename(f).lower()
        if low in ("pom.xml", "build.gradle", "build.gradle.kts"):
            txt = read_text(f)
            add("Java", "构建文件", f)
            if "spring-boot" in txt.lower():
                add("Spring Boot", "构建依赖", f)
            if "mybatis" in txt.lower():
                add("MyBatis / MyBatis-Plus", "构建依赖", f)
            if "mysql" in txt.lower():
                add("MySQL", "构建依赖", f)
            if "jwt" in txt.lower() or "jjwt" in txt.lower():
                add("JWT", "构建依赖", f)
        elif low == "package.json":
            try:
                data = json.loads(read_text(f))
            except Exception:
                data = {}
            deps = {}
            for k in ("dependencies", "devDependencies"):
                deps.update(data.get(k, {}) or {})
            add("Node.js / 前端工程", "package.json", f)
            mapping = {
                "vue": "Vue", "react": "React", "element-ui": "Element UI",
                "element-plus": "Element Plus", "ant-design-vue": "Ant Design Vue",
                "vant": "Vant", "uni-app": "@dcloudio/uni-app", "@dcloudio/uni-app": "uni-app",
                "axios": "Axios", "echarts": "ECharts", "vue-router": "Vue Router",
                "pinia": "Pinia", "vuex": "Vuex", "typescript": "TypeScript",
                "express": "Express", "koa": "Koa", "webpack": "Webpack", "vite": "Vite",
            }
            for dep, label in mapping.items():
                if dep in deps:
                    add(label, f"依赖 {dep}@{deps[dep]}", f)
        elif low == "app.json":
            txt = read_text(f)
            if '"pages"' in txt:
                add("微信小程序", "app.json pages", f)
        elif low in ("project.config.json", "project.private.config.json"):
            add("微信开发者工具工程", "项目配置", f)
        elif low in ("requirements.txt", "pyproject.toml", "pipfile"):
            txt = read_text(f).lower()
            add("Python", "依赖文件", f)
            for kw, label in (("flask", "Flask"), ("django", "Django"), ("fastapi", "FastAPI"),
                              ("sqlalchemy", "SQLAlchemy"), ("pymysql", "PyMySQL")):
                if kw in txt:
                    add(label, "依赖声明", f)
        elif low == "composer.json":
            add("PHP", "composer.json", f)
            if "laravel" in read_text(f).lower():
                add("Laravel", "依赖声明", f)
        elif low.endswith(".csproj"):
            add(".NET", "项目文件", f)
        elif low.endswith(".sql"):
            add("SQL 脚本", "数据库脚本", f)
        elif low in ("application.yml", "application.yaml", "application.properties"):
            add("Spring Boot 配置", "配置文件", f)
        elif low in ("dockerfile", "docker-compose.yml", "docker-compose.yaml"):
            add("Docker", "容器配置", f)
    return stack, {k: v[:10] for k, v in evidence.items()}


def detect_routes(root, files):
    routes = []
    java_cls = re.compile(r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']')
    java_m = re.compile(r'@(Get|Post|Put|Delete|Patch)Mapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']*)["\']')
    expr = re.compile(r'(?:router|app)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', re.I)
    flask = re.compile(r'@\w+\.(route|get|post|put|delete)\s*\(\s*["\']([^"\']+)["\']', re.I)
    laravel = re.compile(r'Route::(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', re.I)
    aspnet = re.compile(r'\[Http(Get|Post|Put|Delete|Patch)(?:\s*\(\s*["\']([^"\']*)["\']\s*\))?\]', re.I)
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        if ext not in (".java", ".kt", ".js", ".ts", ".py", ".php", ".cs"):
            continue
        txt = read_text(f)
        if not txt:
            continue
        base = ""
        if ext in (".java", ".kt"):
            m = java_cls.search(txt)
            if m:
                base = m.group(1).rstrip("/")
            for mm in java_m.finditer(txt):
                method = mm.group(1).upper()
                path = mm.group(2)
                full = (base + "/" + path.lstrip("/")).replace("//", "/") if base else path
                routes.append({"method": method, "path": full, "file": rel(root, f)})
        elif ext in (".js", ".ts"):
            for mm in expr.finditer(txt):
                routes.append({"method": mm.group(1).upper(), "path": mm.group(2), "file": rel(root, f)})
        elif ext == ".py":
            for mm in flask.finditer(txt):
                routes.append({"method": mm.group(1).upper(), "path": mm.group(2), "file": rel(root, f)})
        elif ext == ".php":
            for mm in laravel.finditer(txt):
                routes.append({"method": mm.group(1).upper(), "path": mm.group(2), "file": rel(root, f)})
        elif ext == ".cs":
            for mm in aspnet.finditer(txt):
                routes.append({"method": mm.group(1).upper(), "path": mm.group(2) or "", "file": rel(root, f)})
    # 去重
    seen, out = set(), []
    for r in routes:
        key = (r["method"], r["path"], r["file"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out[:300]


def detect_tables(root, files):
    tables = []
    create_re = re.compile(r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+[`\"\[]?([\w.]+)[`\"\]]?", re.I)
    table_name_re = re.compile(r'@TableName\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']')
    entity_re = re.compile(r'@Table\s*\(\s*name\s*=\s*["\']([^"\']+)["\']')
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        txt = read_text(f)
        if not txt:
            continue
        if ext == ".sql":
            for m in create_re.finditer(txt):
                name = m.group(1)
                start = m.end()
                end = txt.find(";", start)
                body = txt[start:end if end > 0 else start + 4000]
                cols = []
                for line in body.splitlines():
                    line = line.strip().strip(",")
                    if not line or line.startswith(("PRIMARY", "KEY", "UNIQUE", "INDEX",
                                                   "CONSTRAINT", "FOREIGN", "CHECK", ")", "--")):
                        continue
                    cm = re.match(r"[`\"\[]?([\w]+)[`\"\]]?\s+([\w()]+)", line)
                    if cm:
                        comment = ""
                        mc = re.search(r"COMMENT\s+['\"]([^'\"]*)['\"]", line, re.I)
                        if mc:
                            comment = mc.group(1)
                        cols.append({"name": cm.group(1), "type": cm.group(2), "comment": comment})
                tables.append({"name": name, "columns": cols, "file": rel(root, f), "source": "CREATE TABLE"})
        elif ext in (".java", ".kt"):
            for m in table_name_re.finditer(txt):
                tables.append({"name": m.group(1), "columns": [], "file": rel(root, f), "source": "@TableName"})
            for m in entity_re.finditer(txt):
                tables.append({"name": m.group(1), "columns": [], "file": rel(root, f), "source": "@Table"})
    # 去重合并
    merged = {}
    for t in tables:
        key = t["name"].lower()
        if key not in merged:
            merged[key] = t
        elif t["columns"] and not merged[key]["columns"]:
            merged[key] = t
    return list(merged.values())[:120]


def detect_pages(root, files):
    pages = []
    for f in files:
        low = rel(root, f).lower()
        if low.endswith(".vue"):
            pages.append({"type": "Vue 页面/组件", "path": rel(root, f)})
        elif re.search(r"(^|/)pages/.+\.(wxml|js|json)$", low):
            pages.append({"type": "小程序页面", "path": rel(root, f)})
    # app.json / pages.json 中的页面清单
    page_lists = []
    for f in files:
        if os.path.basename(f).lower() in ("app.json", "pages.json"):
            txt = read_text(f)
            m = re.search(r'"pages"\s*:\s*\[(.*?)\]', txt, re.S)
            if m:
                for item in re.findall(r'"([^"]+)"', m.group(1)):
                    page_lists.append({"type": "注册页面", "path": item, "from": rel(root, f)})
    return pages[:200] + page_lists[:100]


def detect_roles(root, files):
    roles = Counter()
    witnesses = defaultdict(list)
    for f in files:
        if os.path.splitext(f)[1].lower() not in CODE_EXT:
            continue
        txt = read_text(f).lower()
        for kw in ("admin", "administrator", "role", "permission", "authority", "管理员", "角色", "权限"):
            c = txt.count(kw)
            if c:
                roles[kw] += c
                if len(witnesses[kw]) < 3:
                    witnesses[kw].append(rel(root, f))
    return {"keywords": dict(roles.most_common(12)),
            "witnesses": {k: v for k, v in witnesses.items()}}


def detect_config(root, files):
    out = []
    for f in files:
        low = os.path.basename(f).lower()
        if low in ("application.yml", "application.yaml", "application.properties", ".env",
                   "application-dev.yml", "application-prod.yml", "config.js", "config.ts"):
            txt = read_text(f)
            keys = []
            for line in txt.splitlines():
                if re.match(r"\s*[\w.-]+\s*[:=]", line):
                    k = re.split(r"[:=]", line, 1)[0].strip()
                    if any(s in k.lower() for s in ("password", "secret", "token", "key")):
                        keys.append(k + "（值已省略）")
                    elif k:
                        keys.append(k)
            out.append({"file": rel(root, f), "keys": keys[:60]})
    return out[:30]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--out", default="paper-context/project-evidence")
    args = ap.parse_args()
    root = os.path.abspath(args.project)
    if not os.path.isdir(root):
        print(f"目录不存在：{root}")
        sys.exit(1)
    files = walk(root)
    ext_count = Counter(os.path.splitext(f)[1].lower() or "(无扩展名)" for f in files)
    stack, evidence = detect_stack(root, files)
    routes = detect_routes(root, files)
    tables = detect_tables(root, files)
    pages = detect_pages(root, files)
    roles = detect_roles(root, files)
    configs = detect_config(root, files)

    readme = ""
    for f in files:
        if os.path.basename(f).lower().startswith("readme"):
            readme = "\n".join(read_text(f).splitlines()[:30])
            break

    data = {
        "project_root": root,
        "file_count": len(files),
        "extensions": dict(ext_count.most_common(20)),
        "tech_stack": stack,
        "tech_evidence": evidence,
        "routes": routes,
        "tables": tables,
        "pages": pages,
        "roles": roles,
        "configs": configs,
        "readme_excerpt": readme,
        "notes": [
            "本文件是线索清单，不是论文正文；论文中的每个功能/字段/接口都应对应源码位置。",
            "未扫描到的模块不等于不存在，请人工补读 Controller/Service/Mapper 与前端 pages。",
        ],
    }

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out + ".json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    lines = [f"# 项目证据扫描：{os.path.basename(root)}", ""]
    lines.append(f"- 文件总数：{len(files)}")
    lines.append(f"- 技术栈线索：{'、'.join(stack) if stack else '未识别'}")
    lines.append("")
    lines.append("## 技术栈证据")
    for k, vs in evidence.items():
        lines.append(f"- **{k}**")
        for v in vs[:6]:
            lines.append(f"  - {v}")
    lines.append("")
    lines.append(f"## 数据表（{len(tables)}）")
    for t in tables:
        cols = "、".join(c["name"] for c in t["columns"][:12])
        lines.append(f"- **{t['name']}**（{t['source']}，{t['file']}）" + (f"：{cols}" if cols else ""))
    lines.append("")
    lines.append(f"## 路由 / 接口（{len(routes)}，最多列 60 条）")
    for r in routes[:60]:
        lines.append(f"- `{r['method']} {r['path']}` — {r['file']}")
    lines.append("")
    lines.append(f"## 页面/模块（{len(pages)}，最多列 60 条）")
    for p in pages[:60]:
        lines.append(f"- {p['type']}：`{p['path']}`" + (f"（{p.get('from')}）" if p.get("from") else ""))
    lines.append("")
    lines.append("## 角色/权限关键词")
    for k, c in roles["keywords"].items():
        lines.append(f"- {k}：{c} 次，如 {', '.join(roles['witnesses'].get(k, []))}")
    lines.append("")
    lines.append("## 配置文件")
    for c in configs:
        lines.append(f"- `{c['file']}`：{'、'.join(c['keys'][:20])}")
    if readme:
        lines.append("")
        lines.append("## README 摘录")
        lines.append("```")
        lines.append(readme)
        lines.append("```")
    with open(out + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[scan_project] 扫描 {len(files)} 个文件")
    print(f"[scan_project] 技术栈：{'、'.join(stack) if stack else '未识别'}")
    print(f"[scan_project] 数据表 {len(tables)}，路由 {len(routes)}，页面 {len(pages)}")
    print(f"[scan_project] 输出：{out}.json / {out}.md")


if __name__ == "__main__":
    main()
