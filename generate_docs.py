import os
import ast
import subprocess
import datetime
import sys

def get_ast_info(directory):
    classes_info = []
    methods_info = []
    calls_info = []

    for root, _, files in os.walk(directory):
        if root != directory:
            continue # Only process files in this exact directory
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        tree = ast.parse(f.read(), filename=filepath)
                except Exception:
                    continue

                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        classes_info.append({
                            'name': node.name,
                            'filepath': filepath,
                            'lineno': node.lineno
                        })
                        for class_node in node.body:
                            if isinstance(class_node, ast.FunctionDef):
                                methods_info.append({
                                    'class_name': node.name,
                                    'name': class_node.name,
                                    'filepath': filepath,
                                    'lineno': class_node.lineno
                                })
                                # Look for calls inside the method
                                for stmt in ast.walk(class_node):
                                    if isinstance(stmt, ast.Call):
                                        func = stmt.func
                                        if isinstance(func, ast.Attribute):
                                            if isinstance(func.value, ast.Name):
                                                caller = node.name
                                                callee = func.value.id
                                                method = func.attr
                                                calls_info.append((caller, callee, method))
                    elif isinstance(node, ast.FunctionDef) and not any(isinstance(parent, ast.ClassDef) for parent in ast.walk(tree)):
                         pass

    return classes_info, methods_info, calls_info

def generate_sequence_diagram(calls_info):
    if not calls_info:
        return "sequenceDiagram\n    participant System\n    Note over System: No deterministic execution flow detected."

    lines = ["sequenceDiagram", "    autonumber"]
    participants = set()
    for caller, callee, method in calls_info:
        participants.add(caller)
        if callee == "self":
             participants.add(caller)
        else:
             participants.add(callee)

    for p in sorted(participants):
        lines.append(f"    participant {p}")

    for caller, callee, method in calls_info:
        if callee == "self":
            lines.append(f"    {caller}->>{caller}: {method}()")
        else:
            lines.append(f"    {caller}->>{callee}: {method}()")

    return "\n".join(lines)


def generate_package_diagram(directory):
    # we can try to extract imports
    imports = []
    for root, _, files in os.walk(directory):
        if root != directory:
            continue
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r') as f:
                         tree = ast.parse(f.read(), filename=filepath)
                         for node in ast.walk(tree):
                             if isinstance(node, ast.Import):
                                 for alias in node.names:
                                     imports.append(alias.name)
                             elif isinstance(node, ast.ImportFrom):
                                 if node.module:
                                     imports.append(node.module)
                except Exception:
                    continue

    lines = ["classDiagram"]
    pkg_name = os.path.basename(os.path.abspath(directory))
    lines.append(f"    class {pkg_name} {{}}")
    for imp in set(imports):
        if imp:
            # just take root module
            root_mod = imp.split('.')[0]
            lines.append(f"    class {root_mod} {{}}")
            lines.append(f"    {pkg_name} --> {root_mod} : imports")

    return "\n".join(lines)

def main():
    # Identify target directories
    # We will process all directories that contain at least one .py file, OR are explicitly standard directories like 'docs'
    # Actually, the prompt says "For every target folder in the source codebase", implying 1:1 mirroring.
    target_dirs = []
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in ['.git', 'openwiki', '__pycache__', '.pytest_cache', 'venv', 'env']]
        rel_path = os.path.normpath(root)
        # check if it's a valid target folder. A target folder is any folder.
        target_dirs.append(rel_path)

    os.makedirs('openwiki', exist_ok=True)
    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    logs = ["# OpenWiki Logs\n\n- Initialized OKF documentation."]

    for d in target_dirs:
        if d == '.':
            out_dir = 'openwiki'
            module_name = 'root'
            src_path = './'
            md_file = os.path.join('openwiki', "root.md")
        else:
            out_dir = os.path.join('openwiki', os.path.dirname(d))
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            module_name = os.path.basename(d)
            src_path = d.replace('\\', '/') + '/'
            if src_path.startswith('./'):
                src_path = src_path[2:]
            md_file = os.path.join('openwiki', f"{d}.md")

        # 1. Run pyreverse for class diagram
        class_diagram = ""
        # We run pyreverse if there are python files
        has_py = any(f.endswith('.py') for f in os.listdir(d)) if os.path.isdir(d) else False
        if has_py:
            try:
                # pyreverse outputs to classes.mmd and packages.mmd in current dir
                # clear old ones
                if os.path.exists('classes.mmd'): os.remove('classes.mmd')
                subprocess.run(['pyreverse', d, '-o', 'mmd'], capture_output=True, text=True)
                if os.path.exists('classes.mmd'):
                    with open('classes.mmd', 'r') as f:
                        class_diagram = f.read().strip()
            except Exception as e:
                print(f"Pyreverse error on {d}: {e}")

        if not class_diagram:
             class_diagram = "classDiagram\n    class EmptyModule {\n        %% No python classes found\n    }"
        else:
             # Pyreverse often adds some extra notes or formatting, ensure it starts with classDiagram
             if not class_diagram.startswith("classDiagram"):
                  class_diagram = "classDiagram\n" + class_diagram

        classes_info, methods_info, calls_info = get_ast_info(d)
        seq_diagram = generate_sequence_diagram(calls_info)
        pkg_diagram = generate_package_diagram(d)

        # Build Citations
        citations = []
        for c in classes_info:
            p = c['filepath'].replace('\\', '/')
            if p.startswith('./'): p = p[2:]
            citations.append(f"* **Source Reference:** `{p}:{c['lineno']}` - Class `{c['name']}`")
        for m in methods_info:
            p = m['filepath'].replace('\\', '/')
            if p.startswith('./'): p = p[2:]
            citations.append(f"* **Source Reference:** `{p}:{m['lineno']}` - Method `{m['name']}`")

        if not citations:
             citations_str = "* **Source Citations:** No classes or methods detected."
        else:
             # The prompt asks for:
             # * **Source Citations:** - Class `ConcreteProcessor`: `src/path/to/module/processor.py:15`
             # * Method `process`: `src/path/to/module/processor.py:32`
             # Let's match their format exactly:
             cit_lines = []
             first = True
             for c in classes_info:
                 p = c['filepath'].replace('\\', '/')
                 if p.startswith('./'): p = p[2:]
                 if first:
                     cit_lines.append(f"* **Source Citations:** - Class `{c['name']}`: `{p}:{c['lineno']}`")
                     first = False
                 else:
                     cit_lines.append(f"* Class `{c['name']}`: `{p}:{c['lineno']}`")
             for m in methods_info:
                 p = m['filepath'].replace('\\', '/')
                 if p.startswith('./'): p = p[2:]
                 if first:
                     cit_lines.append(f"* **Source Citations:** - Method `{m['name']}`: `{p}:{m['lineno']}`")
                     first = False
                 else:
                     cit_lines.append(f"* Method `{m['name']}`: `{p}:{m['lineno']}`")
             citations_str = "\n".join(cit_lines)


        deps = [] # we need to get imports properly

        # Let's just use the pkg_diagram for section 3
        # Actually wait, the template requires:

        template = f"""---
type: "module-architecture"
title: "{module_name}"
description: "Technical architecture and class hierarchy for {module_name}"
tags: ["architecture", "uml", "pyreverse", "openwiki"]
timestamp: "{timestamp}"
---

# Module Name: {module_name}

* **Source Directory Reference:** `{src_path}`
* **Package Dependency:** [List upstream and downstream package boundaries]

## 1. Executive Summary & Purpose
Deterministic architectural mapping of {module_name}.

## 2. UML 2.0 Class & Inheritance Architecture (Deterministic)
The following class diagram models the object-oriented structure, explicit inheritance hierarchies, and polymorphic interface implementations derived from local AST analysis:

```mermaid
{class_diagram}
```

## 3. Package & Class Relations

* **Inheritance & Polymorphism:** Detailed breakdown of abstract base classes, interfaces, and concrete overrides.
* **Dependencies:** How classes within this package collaborate externally.

```mermaid
{pkg_diagram}
```

## 4. Execution Flow & Runtime Behavior

The following sequence diagram outlines the execution lifecycle and message passing during core operations:

```mermaid
{seq_diagram}
```

---

{citations_str}
"""
        with open(md_file, 'w', encoding='utf-8') as f:
            f.write(template)
        logs.append(f"- Generated docs for {d}")

    # cleanup
    if os.path.exists('classes.mmd'): os.remove('classes.mmd')
    if os.path.exists('packages.mmd'): os.remove('packages.mmd')

    with open('openwiki/index.md', 'w', encoding='utf-8') as f:
        f.write("# OpenWiki Index\n\nWelcome to the deterministic OpenWiki.\n")

    with open('openwiki/logs.md', 'w', encoding='utf-8') as f:
        f.write("\n".join(logs) + "\n")

if __name__ == '__main__':
    main()
