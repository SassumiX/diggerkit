#!/usr/bin/env python3
"""修 diggerkit 仓库里「照着装必然连不通」的 5 处（Verifier 独立核验发现）

1. README 的「30 秒接入」示例调用了不存在的方法：
   `c.quota()` → 真实方法名 `check_quota()`
   `c.search_leads(keywords=[...], lang="es")` → 真实签名 `search_leads(query, country, industry, limit)`
   客户照抄 → AttributeError / TypeError，第一步就崩。
   另：API Key 来源写的是 /ui/ → 实际在看板 /dashboard.html。

2. client.py 里 `__version__ = "2.0.0"`，而 __init__.py / pyproject 都是 2.2.0（版本自述不一致）。

3. mcp.json（根与 node/ 两份）args 写 `/absolute/path/to/golddigger-mcp/index.js`，
   实际文件在 `node/index.js` → 照抄即路径错，服务起不来。

4. server.v2.json 是陈旧/错误元数据：
   version 2.1.0（实为 2.2.0）、写「4 个只读工具」（实为 5）、
   宣称 npm 包 `github:SassumiX/golddigger-mcp`（该仓不存在 + npm 从未发布）、
   宣称 remote streamable-http `https://golddigger.gold/mcp`（该 URL 实测回首页 HTML，无 MCP HTTP 端点）。

5. LSP 分帧只吃 `\\r\\n\\r\\n`，喂 `Content-Length: N\\n\\n` 时静默零输出 → 兼容 `\\n\\n`。

用法：python3 fix_repo_false_statements.py [--apply]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

REPO = "/opt/diggerkit"
BACKUP = REPO + "/backup"

# ── 1. README ──
README = REPO + "/README.md"
R_README = [
    ('print(c.quota())                      # 配额',
     'print(c.check_quota())                 # 配额', 1),
    ('leads = c.search_leads(keywords=["silk scarf"], lang="es")',
     'leads = c.search_leads(query="silk scarf", country="AE", limit=10)', 1),
    ('**认证**：API Key 走 `X-API-KEY` header，来源 <https://golddigger.gold/ui/>。',
     '**认证**：API Key 走 `X-API-KEY` header，注册后在看板 <https://golddigger.gold/dashboard.html> 查看。', 1),
]

# ── 2. client.py 版本号 ──
CLIENT = REPO + "/diggerkit/client.py"
R_CLIENT = [
    ('__version__ = "2.0.0"', '__version__ = "2.2.0"', 1),
]

# ── 3. mcp.json ×2 ──
MCP_JSONS = [REPO + "/diggerkit/mcp/mcp.json", REPO + "/diggerkit/mcp/node/mcp.json"]
R_MCPJSON = [
    ('"args": ["/absolute/path/to/golddigger-mcp/index.js"]',
     '"args": ["/absolute/path/to/golddigger-mcp-v2.2.0/node/index.js"]', 1),
]

# ── 5. index.js 分帧兼容 ──
INDEX = REPO + "/diggerkit/mcp/node/index.js"
R_INDEX = [
    ("""    // ② LSP: Content-Length 分帧
    const headerEnd = buffer.indexOf('\\r\\n\\r\\n');
    if (headerEnd === -1) break;""",
     """    // ② LSP: Content-Length 分帧（\\r\\n\\r\\n 与 \\n\\n 都吃）
    let headerEnd = buffer.indexOf('\\r\\n\\r\\n');
    let sepLen = 4;
    if (headerEnd === -1) {
      headerEnd = buffer.indexOf('\\n\\n');
      sepLen = 2;
      if (headerEnd === -1) break;
    }""", 1),
    ("""      // 无法解析头, 丢弃这段
      buffer = buffer.slice(headerEnd + 4);""",
     """      // 无法解析头, 丢弃这段
      buffer = buffer.slice(headerEnd + sepLen);""", 1),
    ("""    const bodyStart = headerEnd + 4;""",
     """    const bodyStart = headerEnd + sepLen;""", 1),
]

# ── 4. server.v2.json 整体重写 ──
SERVER_V2 = REPO + "/diggerkit/mcp/node/server.v2.json"
NEW_SERVER_V2 = {
    "$schema": "https://static.modelcontextprotocol.io/schemas/2025-09-29/server.schema.json",
    "name": "io.github.sassumix/diggerkit",
    "description": (
        "GoldDigger DiggerKit MCP server — 工厂 Agent 一击接入挖客。零依赖 Node.js, 5 个只读工具 "
        "(check_readiness / check_quota / check_answerable / search_leads / mine_leads)。"
        "双配额池: API 池 (按档位次数) + 挖客行动池 (每天 1000 Quota = 10 次, DiggerKit C/C+)。"
        "数据客户自抓, Token 客户自购, 0 留存 0 抽佣。"
        "分发: 官方站 zip https://golddigger.gold/static/diggerkit-mcp-v2.2.0.zip ; "
        "源码 https://github.com/SassumiX/diggerkit ; 未发布 npm, 无 HTTP 端点, 仅 stdio。"
    ),
    "version": "2.2.0",
    "websiteUrl": "https://golddigger.gold",
    "repository": {
        "url": "https://github.com/SassumiX/diggerkit",
        "source": "github"
    },
}


def apply_rules(path, rules):
    with open(path, encoding="utf-8", errors="surrogateescape") as f:
        c = f.read()
    for old, new, expect in rules:
        n = c.count(old)
        if n != expect:
            print(f"  ✗ {os.path.basename(path)}: 锚点 {old[:40]!r} 期望 {expect} 处，实际 {n} 处 → 拒写")
            return None
        c = c.replace(old, new)
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    print("════ 仓库侧不实声明修复 ════")
    plan = []

    c = apply_rules(README, R_README)
    if c is None:
        return 1
    plan.append((README, c))
    print(f"  ✓ README: {len(R_README)} 处")

    c = apply_rules(CLIENT, R_CLIENT)
    if c is None:
        return 1
    plan.append((CLIENT, c))
    print(f"  ✓ client.py: {len(R_CLIENT)} 处")

    for p in MCP_JSONS:
        c = apply_rules(p, R_MCPJSON)
        if c is None:
            return 1
        plan.append((p, c))
    print(f"  ✓ mcp.json ×2: {len(R_MCPJSON)} 处")

    c = apply_rules(INDEX, R_INDEX)
    if c is None:
        return 1
    plan.append((INDEX, c))
    print(f"  ✓ index.js: {len(R_INDEX)} 处（\\n\\n 兼容）")

    # server.v2.json 重写
    with open(SERVER_V2, encoding="utf-8") as f:
        old_sv = json.load(f)
    if old_sv.get("version") == "2.2.0" and "packages" not in old_sv:
        print("  · server.v2.json 已是新版，跳过")
    else:
        plan.append((SERVER_V2, json.dumps(NEW_SERVER_V2, ensure_ascii=False, indent=2) + "\n"))
        print("  ✓ server.v2.json: 整体重写（去 npm 宣称 + 去假 remote + 5 工具 + 2.2.0）")

    # ── 校验 ──
    tmp_js = "/tmp/_mcp_check.js"
    for path, content in plan:
        if path.endswith(".js"):
            with open(tmp_js, "w", encoding="utf-8", errors="surrogateescape") as f:
                f.write(content)
            r = subprocess.run(["node", "--check", tmp_js], capture_output=True, text=True)
            if r.returncode != 0:
                print("  ✗ node --check 失败:", r.stderr.strip()[:300])
                return 1
    if os.path.exists(tmp_js):
        os.unlink(tmp_js)
    print("  ✓ node --check 通过")

    for path, content in plan:
        if path.endswith(".json"):
            try:
                json.loads(content)
            except Exception as e:
                print(f"  ✗ {path} JSON 非法:", e)
                return 1
    print("  ✓ JSON 校验通过")

    # Python 语法
    tmp_py = "/tmp/_cli_check.py"
    for path, content in plan:
        if path.endswith(".py"):
            with open(tmp_py, "w", encoding="utf-8", errors="surrogateescape") as f:
                f.write(content)
            r = subprocess.run(["python3", "-m", "py_compile", tmp_py], capture_output=True, text=True)
            if r.returncode != 0:
                print("  ✗ py_compile 失败:", r.stderr.strip()[:300])
                return 1
    if os.path.exists(tmp_py):
        os.unlink(tmp_py)
    print("  ✓ py_compile 通过")

    if not args.apply:
        print("\n  (dry-run)")
        return 0

    ts = time.strftime("%Y%m%d_%H%M%S")
    bdir = os.path.join(BACKUP, f"false_statements_{ts}")
    for path, _ in plan:
        dst = os.path.join(bdir, os.path.relpath(path, REPO))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(path, dst)
    print(f"\n  ✓ 已备份 {len(plan)} 个文件 → {bdir}")

    for path, content in plan:
        with open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
            f.write(content)
    print(f"  ✓ 已写入 {len(plan)} 个文件")

    # 写后复核
    bad = []
    for path, _ in plan:
        with open(path, encoding="utf-8", errors="surrogateescape") as f:
            t = f.read()
        if path == README:
            if "c.quota()" in t or "keywords=[\"silk scarf\"]" in t:
                bad.append("README 仍有旧示例")
        if path == CLIENT and '__version__ = "2.0.0"' in t:
            bad.append("client.py 版本号未改")
        if path in MCP_JSONS and "golddigger-mcp/index.js" in t:
            bad.append(f"{path} 路径未改")
        if path == SERVER_V2:
            d = json.loads(t)
            if d.get("version") != "2.2.0" or "packages" in d or "remotes" in d:
                bad.append("server.v2.json 未改干净")
        if path == INDEX and "sepLen" not in t:
            bad.append("index.js 分帧兼容未加")
    if bad:
        for b in bad:
            print("  ✗", b)
        return 1
    print("  ✓ 写后复核全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
