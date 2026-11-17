#!/usr/bin/env python3
"""给 diggerkit 仓库补 v2.2.0 版本行 + 打 tag

版本历史表是客户和后续维护者判断"这个包到底是什么"的唯一地方，
发 v2.2.0 必须补一行。

用法：python3 add_v220_version_row.py [--apply]
"""
import argparse
import subprocess
import sys

REPO = "/opt/diggerkit"
README = REPO + "/README.md"

OLD = "| v2.1.0 | 2026-11-11 | MCP server 重写：零依赖 Node、只读工具集、`check_readiness` / `check_answerable` |"
NEW = ("| v2.2.0 | 2026-11-17 | MCP 支持标准换行分帧（原来只吃 LSP 分帧 → 标准 MCP 客户端连不上）；`--api-key` 真正生效；"
       "客户包换真 SDK（含租户自己的关键词）；包内不再带历史坏 zip |\n"
       "| v2.1.0 | 2026-11-11 | MCP server 重写：零依赖 Node、只读工具集、`check_readiness` / `check_answerable` |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    print("════ v2.2.0 版本行 ════")
    with open(README, encoding="utf-8") as f:
        c = f.read()

    if "| v2.2.0 |" in c:
        print("  · 版本行已存在，跳过")
        return 0
    n = c.count(OLD)
    if n != 1:
        print(f"  ✗ 版本表锚点期望 1 处，实际 {n} 处 → 拒写")
        return 1
    c = c.replace(OLD, NEW)
    print("  ✓ 版本表锚点命中 1 处")

    if not args.apply:
        print("\n  (dry-run)")
        return 0

    with open(README, "w", encoding="utf-8") as f:
        f.write(c)
    print("  ✓ README 已更新")

    subprocess.run(["git", "add", "README.md"], cwd=REPO)
    subprocess.run(["git", "commit", "-q", "-m", "docs(diggerkit): 补 v2.2.0 版本行"], cwd=REPO)
    r = subprocess.run(["git", "log", "--oneline", "-1"], cwd=REPO, capture_output=True, text=True)
    print("  ✓ 提交:", r.stdout.strip())

    # tag
    r = subprocess.run(["git", "tag", "-a", "v2.2.0", "-m", "v2.2.0: 标准 MCP 换行分帧 + 客户包换真 SDK"],
                       cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        print("  ✗ tag 失败:", (r.stderr or r.stdout).strip()[:160])
        return 1
    print("  ✓ tag v2.2.0 已建")

    for i in (1, 2, 3):
        ok = subprocess.run(
            ["git", "-c", "http.version=HTTP/1.1", "push", "origin", "main", "--tags"],
            cwd=REPO, capture_output=True, text=True)
        out = (ok.stdout or "") + (ok.stderr or "")
        if "main -> main" in out or "-> main" in out:
            print(f"  ✓ push 成功（第 {i} 次）")
            break
        print(f"  · 重试 {i}")
        import time
        time.sleep(4)

    r = subprocess.run(["git", "log", "--oneline", "-1", "origin/main"], cwd=REPO,
                       capture_output=True, text=True)
    print("  远端:", r.stdout.strip())
    r = subprocess.run(["git", "ls-remote", "--tags", "origin"], cwd=REPO,
                       capture_output=True, text=True)
    print("  远端 tag:", [l.split("/")[-1].replace("^{}", "") for l in r.stdout.strip().split("\n") if l])
    return 0


if __name__ == "__main__":
    sys.exit(main())
