"""
Dead code inventory. Reachability, not grep.

Grep already failed us once: the GBP 100k taper guard existed, matched a
search for the threshold, and protected nothing, because the function
holding it had no callers. So this walks real graphs.

  Python  - AST import graph from main.py (the HTTP entry point), with
            tests/, tools/ and verify/ treated as their own roots rather
            than as dead weight.
  TS/TSX  - import graph from the Next.js route entries (app/**/page.tsx,
            app/layout.tsx) and separately from each *.test.ts.

Reports. Deletes nothing.
"""
from __future__ import annotations

import ast
import io
import os
import re
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SKIP_DIRS = {
    "node_modules", ".next", ".git", "__pycache__", ".pytest_cache",
    ".venv", "venv", "patched_pkg", ".tsbuild",
}


def walk(exts, roots=(".",)):
    for root in roots:
        for dirpath, dirnames, names in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in names:
                if name.endswith(exts):
                    rel = os.path.relpath(os.path.join(dirpath, name), ".")
                    yield rel.replace("\\", "/")


# ==========================================================================
# Python graph
# ==========================================================================
py_files = sorted(walk((".py",)))
py_defs = {}
py_names = {}
py_imports = {}


def used_names(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
    return out


for path in py_files:
    try:
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    except SyntaxError:
        continue
    py_defs[path] = [
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    py_names[path] = used_names(tree)
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
            mods.add(node.module)
    py_imports[path] = mods


def module_of(path):
    return path[:-3].replace("/", ".")


reachable_py = set()
queue = ["main.py"]
while queue:
    current = queue.pop()
    if current in reachable_py or current not in py_defs:
        continue
    reachable_py.add(current)
    for other in py_defs:
        if other in reachable_py:
            continue
        mod = module_of(other)
        leaf = mod.split(".")[-1]
        if mod in py_imports[current] or leaf in py_imports[current]:
            queue.append(other)


# ==========================================================================
# TypeScript graph
# ==========================================================================
ts_files = sorted(walk((".ts", ".tsx"), roots=("app", "lib", "components")))
IMPORT_RE = re.compile(r'(?:from|import)\s+[\'"]([^\'"]+)[\'"]')


def resolve(spec, importer):
    if spec.startswith("@/"):
        base = spec[2:]
    elif spec.startswith("."):
        base = os.path.normpath(
            os.path.join(os.path.dirname(importer), spec)
        ).replace("\\", "/")
    else:
        return None
    for candidate in (base, base + ".ts", base + ".tsx",
                      base + "/index.ts", base + "/index.tsx"):
        if os.path.isfile(candidate):
            return candidate.replace("\\", "/")
    return None


ts_imports = {}
for path in ts_files:
    source = open(path, encoding="utf-8").read()
    resolved = set()
    for spec in IMPORT_RE.findall(source):
        target = resolve(spec, path)
        if target:
            resolved.add(target)
    ts_imports[path] = resolved

TS_ROOTS = [p for p in ts_files
            if re.search(r"app/(.*/)?(page|layout|not-found|error)\.tsx$", p)]
TS_TESTS = [p for p in ts_files if ".test." in p]


def closure(roots):
    seen, queue = set(), list(roots)
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(ts_imports.get(current, ()))
    return seen


reachable_ts = closure(TS_ROOTS)
reachable_tests = closure(TS_TESTS)


# ==========================================================================
# Report
# ==========================================================================
def head(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


head("A. FILES NOT REACHABLE FROM ANY ENTRY POINT")
print("Python root: main.py\n")
for path in py_files:
    if path.startswith(("tests/", "verify/")) or path.endswith("__init__.py"):
        continue
    if path in reachable_py:
        continue
    importers = [o for o in py_defs
                 if o != path and module_of(path).split(".")[-1] in py_imports.get(o, set())]
    role = "standalone script" if path.startswith("tools/") else "UNREFERENCED"
    print(f"  {path:40} {role:18} importers: {importers or 'none'}")

print("\nTS roots: " + ", ".join(TS_ROOTS) + "\n")
for path in ts_files:
    if path in reachable_ts or path in TS_TESTS:
        continue
    importers = [o for o in ts_files if path in ts_imports.get(o, set())]
    where = "test-only" if path in reachable_tests else "UNREFERENCED"
    print(f"  {path:48} {where:14} importers: {importers or 'none'}")


head("B. TOP-LEVEL PYTHON DEFINITIONS NOTHING USES")
print("Counts uses ANYWHERE including the defining file - a helper called")
print("one line below its own def is not dead. Skips test functions (pytest")
print("collects them by name) and decorated route handlers (FastAPI calls")
print("them through the decorator, so the name is never referenced).\n")

decorated = set()
for path in py_files:
    try:
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    except SyntaxError:
        continue
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.decorator_list:
            decorated.add((path, node.name))

anything_flagged = False
for path in sorted(py_defs):
    if path.startswith(("verify/", "tests/")):
        continue
    dead = []
    for name in py_defs[path]:
        if name.startswith("__") or name.startswith("test_"):
            continue
        if (path, name) in decorated:
            continue
        if any(name in py_names[other] for other in py_names):
            continue
        dead.append(name)
    if dead:
        anything_flagged = True
        print(f"  {path}")
        for name in dead:
            print(f"      {name}")
if not anything_flagged:
    print("  none")


head("C. COMMENTED-OUT CODE (>= 10 consecutive comment lines that parse as code)")
for path in sorted(list(py_files) + list(ts_files)):
    if path.startswith("verify/"):
        continue
    lines = open(path, encoding="utf-8").read().splitlines()
    marker = "#" if path.endswith(".py") else "//"
    run, start, blocks = 0, 0, []
    for i, line in enumerate(lines, 1):
        if line.strip().startswith(marker):
            if run == 0:
                start = i
            run += 1
        else:
            if run >= 10:
                blocks.append((start, i - 1, run))
            run = 0
    if run >= 10:
        blocks.append((start, len(lines), run))

    # Prose beginning with "#" looks identical to code beginning with "#",
    # so decide by PARSING rather than by pattern. A block is commented-out
    # code only if stripping the marker yields something the language
    # actually accepts.
    code_blocks = []
    for begin, end, count in blocks:
        stripped = []
        for line in lines[begin - 1:end]:
            text = line.strip()
            stripped.append(text[len(marker):].rstrip() if text.startswith(marker) else "")
        body = "\n".join(stripped)
        if path.endswith(".py"):
            try:
                parsed = ast.parse(textwrap.dedent(body))
            except SyntaxError:
                continue
            # A parse of pure prose yields only bare expressions; real code
            # has definitions, assignments or control flow.
            if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                         ast.ClassDef, ast.Assign, ast.AnnAssign,
                                         ast.Return, ast.If, ast.For, ast.Raise))
                       for node in ast.walk(parsed)):
                continue
        else:
            code_like = sum(1 for line in stripped
                            if re.search(r"[;{}]\s*$|=>|\bconst |\bfunction |\breturn ", line))
            if code_like < max(3, count // 4):
                continue
        code_blocks.append((begin, end, count))
    if code_blocks:
        total = sum(c for _, _, c in code_blocks)
        print(f"  {path:36} {total:>5} lines across {len(code_blocks)} block(s)")
        for begin, end, count in code_blocks[:5]:
            print(f"        lines {begin}-{end}  ({count})")


head("D. SPECIFICALLY FLAGGED IN EARLIER REPORTS")
for target, note in (
    ("tools/try_analysis.py", "flagged dead in verify/REPORT.md"),
    ("components/prototype/usePrototypeMode.ts", "hook behind the basis:mode key"),
):
    if not os.path.exists(target):
        print(f"  {target:48} ALREADY GONE   ({note})")
        continue
    if target.endswith((".ts", ".tsx")):
        importers = [o for o in ts_files if target in ts_imports.get(o, set())]
    else:
        leaf = os.path.basename(target)[:-3]
        importers = [o for o in py_defs if leaf in py_imports.get(o, set())]
    print(f"  {target:48} EXISTS  importers: {importers or 'none'}   ({note})")

refs = [p for p in ts_files if "basis:mode" in open(p, encoding="utf-8").read()]
print(f"  localStorage key 'basis:mode' referenced in: {refs or 'nowhere'}")


head("E. .env.example COMPLETENESS (verify, do not delete)")
env_example = {}
for line in open(".env.example", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        env_example[line.split("=", 1)[0]] = True

read_by_code = set()
for path in list(py_files) + list(ts_files) + ["main.py"]:
    if path.startswith("verify/"):
        continue
    try:
        src = open(path, encoding="utf-8").read()
    except OSError:
        continue
    read_by_code |= set(re.findall(r'os\.environ\.get\(\s*["\']([A-Z_0-9]+)', src))
    read_by_code |= set(re.findall(r'os\.getenv\(\s*["\']([A-Z_0-9]+)', src))
    read_by_code |= set(re.findall(r'process\.env\.([A-Z_0-9]+)', src))
# Read by the SDKs rather than by our code, but still required.
sdk_read = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}

print("  variable                     in .env.example   read by")
for name in sorted(read_by_code | sdk_read | set(env_example)):
    listed = "yes" if name in env_example else "NO"
    if name in read_by_code:
        who = "our code"
    elif name in sdk_read:
        who = "provider SDK"
    else:
        who = "NOTHING - stale?"
    print(f"  {name:28} {listed:^15}   {who}")
