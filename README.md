# DiggerKit

> GoldDigger SI Agent 的金铲子 —— **Python SDK + MCP server**，让你的 AI Agent 一行接入挖客。

**SI Agent** = Supper Intelligence Agent = 你（外贸供应商）自己的 AI Agent（Claude / Cline / Cursor / 自家 worker）。
**DiggerKit 助力赋能** = 我们给你工具，**不替你跑**。

| | |
|---|---|
| 服务端 | <https://golddigger.gold> |
| 商务合作 | factorihub@outlook.com |
| 备案号 | 浙ICP备2026078906号-1 |
| 许可证 | MIT |

---

## 安装

### 从源码（推荐，PyPI 未发布）

```bash
git clone https://github.com/SassumiX/diggerkit.git
cd diggerkit
pip install -e .
```

零第三方依赖 —— `DiggerKitClient` 只用 Python 标准库，`pip install -e .` 不会拖进任何包。

需要 v1.1 旧版 SDK（`GolddiggerClient` / `AgentTokenClient`）时：

```bash
pip install -e ".[legacy]"
```

### 国内网络不通 GitHub 时

用离线 bundle 走服务器侧更新通道（见下方「离线更新通道」），或直接取仓库 `releases/` 下的 zip。

---

## 30 秒接入

```python
from diggerkit import Client

c = Client(api_key="gds_你的KEY")     # 供应商 gds_ / 买家 gdb_
print(c.quota())                      # 配额
leads = c.search_leads(keywords=["silk scarf"], lang="es")
```

也可以直接用命令行：

```bash
python -m diggerkit.client --api-key gds_你的KEY --query "silk scarf" --country AE
```

**认证**：API Key 走 `X-API-KEY` header，来源 <https://golddigger.gold/ui/>。
Agent 授权走 `AgentTokenClient(agent_token="agt_...")`。

---

## MCP server（只读工具集）

`diggerkit/mcp/` 是零依赖的 Node 实现（Node ≥ 18）。

```bash
cd diggerkit/mcp
node node/index.js --api-key gds_你的KEY
```

客户端配置（把路径换成你的绝对路径）：

```json
{
  "mcpServers": {
    "golddigger": {
      "command": "node",
      "args": ["/absolute/path/to/diggerkit/mcp/node/index.js"],
      "env": {
        "GOLDDIGGER_API_KEY": "gds_xxxxxxxx",
        "GOLDDIGGER_BASE_URL": "https://golddigger.gold"
      }
    }
  }
}
```

工具集只读 —— 不提供写入、不提供外发、不提供裸数据导出。
每个结果带 `provenance`（来源 + 置信度），不给没来处的结论。
`check_readiness` 一次报全所有阻塞项；`check_answerable` 覆盖不足就明说。

> ⚠️ **npm 上的 `golddigger-mcp` 包从未发布**（404）。请用本仓库的源码跑，别用 `npx -y golddigger-mcp`。

---

## 离线更新通道

本仓库支持用 git bundle 做离线同步（服务器到 GitHub 直连不稳、或内网环境）：

```bash
# 首次
git clone git@github.com:SassumiX/diggerkit.git /opt/diggerkit

# 之后每次（拿到 diggerkit.bundle 后）
cd /opt/diggerkit
git pull /path/to/diggerkit.bundle main
git push origin main
```

`git bundle` 是单文件全量镜像，`git pull <bundle> main` 会把该 bundle 里的提交并进本地 `main`。

---

## 版本历史

| 版本 | 日期 | 内容 |
|---|---|---|
| v2.1.0 | 2026-11-11 | MCP server 重写：零依赖 Node、只读工具集、`check_readiness` / `check_answerable` |
| v2.0.0 | 2026-11-11 | Python SDK 重写：纯标准库、错误分层（Quota / InvalidKey / RateLimited / ServerError） |
| v1.1.0 | 2026-10-09 | Agent 授权机制（4 维度控制）+ `diggerkit_tools.py` 工具箱（服务端） |
| v1.0.0 | 2026-10-08 | 首个公开包 |

历史 zip 全档在仓库的 `releases/`（客户下载包里只放当前版本，不带历史坏包）。

---

## 边界

- 我们**不替你跑** Agent：Token、LLM、模型你自带。
- API 池与挖客行动池是**两套独立配额**，各自 UTC 00:00 重置。
- 蒸馏永久免费。
- 我们不持有你的买家数据。
