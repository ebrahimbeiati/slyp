"""
Stranded-guard audit: every refusal in the engine, and whether the
function holding it is reachable from the request path.

The FR-04 defect was not a missing check - it was a check on a function
with no callers. This finds any other guard in the same position.

Reachability is computed as a real call graph from the two request-path
entry points (extract_payslip, analyse_payslip), by walking the AST for
Name/Attribute calls, not by grepping.
"""
from __future__ import annotations
import ast, os, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "slyp")

# Every function defined in the package, plus the calls it makes.
defs: dict[str, ast.FunctionDef] = {}
calls: dict[str, set[str]] = collections.defaultdict(set)
module_of: dict[str, str] = {}

def _called_names(node):
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = sub.func
            if isinstance(fn, ast.Name):
                out.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                out.add(fn.attr)
    return out

for fname in sorted(os.listdir(PKG)):
    if not fname.endswith(".py"):
        continue
    path = os.path.join(PKG, fname)
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs[node.name] = node
            module_of[node.name] = fname
            calls[node.name] |= _called_names(node)

# main.py is the HTTP entry point.
main_tree = ast.parse(open(os.path.join(ROOT, "main.py"), encoding="utf-8").read())
ENTRY = set()
for node in ast.walk(main_tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        ENTRY |= _called_names(node)

reachable, queue = set(), [n for n in ENTRY if n in defs]
while queue:
    fn = queue.pop()
    if fn in reachable:
        continue
    reachable.add(fn)
    queue.extend(c for c in calls[fn] if c in defs and c not in reachable)

# Every function that raises a refusal.
REFUSALS = ("UnsupportedPayslip", "RedactionFailure", "NotAPayslip",
            "UnreadableDocument", "ValueError")

guards = []
for name, node in defs.items():
    raised = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Raise) and sub.exc is not None:
            exc = sub.exc
            target = exc.func if isinstance(exc, ast.Call) else exc
            if isinstance(target, ast.Name) and target.id in REFUSALS:
                raised.add(target.id)
            elif isinstance(target, ast.Attribute) and target.attr in REFUSALS:
                raised.add(target.attr)
    if raised:
        guards.append((name, module_of[name], sorted(raised), name in reachable))

print("=" * 92)
print("EVERY REFUSAL IN slyp/, AND WHETHER IT IS ON THE REQUEST PATH")
print("=" * 92)
print(f"{'REACHABLE':10} {'FUNCTION':36} {'MODULE':16} RAISES")
print("-" * 92)
for name, mod, raised, ok in sorted(guards, key=lambda g: (g[3], g[1], g[0])):
    print(f"{'yes' if ok else '** NO **':10} {name:36} {mod:16} {', '.join(raised)}")

stranded = [g for g in guards if not g[3]]
print("-" * 92)
print(f"{len(guards)} guard-bearing functions, {len(stranded)} STRANDED")
if stranded:
    print("\nSTRANDED (a refusal nothing on the request path can reach):")
    for name, mod, raised, _ in stranded:
        print(f"  {mod}:{name}() raises {', '.join(raised)}")

# Also: functions with no callers at all, guard or not.
called_by_anyone = set()
for fn, cs in calls.items():
    called_by_anyone |= cs
called_by_anyone |= ENTRY
orphans = sorted(
    n for n in defs
    if n not in called_by_anyone and not n.startswith("__")
)
print("\n" + "=" * 92)
print("FUNCTIONS WITH NO CALLER ANYWHERE IN slyp/ OR main.py")
print("=" * 92)
for n in orphans:
    has_guard = any(g[0] == n for g in guards)
    print(f"  {module_of[n]:16} {n:40} {'<-- HOLDS A REFUSAL' if has_guard else ''}")
