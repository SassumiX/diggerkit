# golddigger-mcp — DiggerKit MCP server（Node.js · v2.2.0）

零依赖 Node 实现（Node 18+），工具集**只读**：不提供任何写入 / 外发能力。

> ⚠️ **npm registry 上没有发布**（`npm install golddigger-mcp` 和 `npx golddigger-mcp` 都会 404）。
> 官方分发只走下面 A / B / C 三条路，**三条指向同一份源码**（`node/index.js`）。

---

## v2.2（Node.js，推荐）

### 安装 —— 3 种方式，都不需要 npm 账号

**A · zip 直下（推荐 · 国内最稳）**

```bash
curl -LO https://golddigger.gold/static/diggerkit-mcp-v2.2.0.zip
unzip diggerkit-mcp-v2.2.0.zip
cd golddigger-mcp-v2.2.0
node node/index.js
```

官方站直下，不依赖 GitHub，国内速度最快。

**B · 从源码仓库跑（想改代码 / 要离线环境）**

```bash
git clone https://github.com/SassumiX/diggerkit.git
cd diggerkit/diggerkit/mcp
node node/index.js
```

> 国内网络 clone 慢或握手失败时，直接用 A 方式的 zip。

**C · 已经在用 DiggerKit SDK 包**

DiggerKit.zip 里就有 `diggerkit/mcp/node/index.js`，不用单独下载 MCP 包。

### 接入 MCP 客户端

```json
{
  "mcpServers": {
    "golddigger": {
      "command": "node",
      "args": ["/绝对路径/golddigger-mcp-v2.2.0/node/index.js"],
      "env": {
        "GOLDDIGGER_API_KEY": "gds_你的KEY"
      }
    }
  }
}
```

也可以用启动参数（命令行优先于环境变量）：

```bash
node node/index.js --api-key gds_你的KEY
node node/index.js --api-key gds_你的KEY --base-url https://golddigger.gold
```

### 传输分帧

- **标准 MCP 换行分帧**（JSON-RPC over newline）—— Claude Desktop / VS Code / MCP Inspector 等标准客户端走这个，本 server 原生支持
- **LSP `Content-Length` 分帧** —— 兼容早期自研 wrapper

出站格式**跟随入站格式**：客户端怎么发，server 就怎么回。

### 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `GOLDDIGGER_API_KEY` | 是 | 你的 API Key，注册后在看板 <https://golddigger.gold/dashboard.html> 查看 |
| `GOLDDIGGER_BASE_URL` | 否 | 默认 `https://golddigger.gold` |
| `GOLDDIGGER_TIMEOUT_MS` | 否 | 单次请求超时，默认 60000（毫秒） |

API Key 前缀决定角色：`gds_` = 供应商（挖客），`gdb_` = 买家。越权返回 `KEY_ROLE_MISMATCH`（403）。

### v2.2 工具集（5 个 · 只读）

| 工具 | 说明 | 数据流 |
|---|---|---|
| `check_readiness` | 一次报出所有阻塞项：key 有效性 + 后端连通 + 配额 | 外部调用（不消耗配额） |
| `check_quota` | 剩余配额、套餐、重置时间 | 外部调用（只读，不消耗配额） |
| `check_answerable` | 覆盖度预检：这次计划挖 N 条，够不够 | 本地 + `/api/quota` |
| `search_leads` | 按产品关键词 + 国家 + 行业检索潜在买家 | **API 池**，每次 1 次配额 |
| `mine_leads` | 挖客行动池检索，带 `score` 评分与来源 | **挖客行动池**，每次 100 Quota |

### 两个配额池

| 池 | 覆盖 | 单位 | 额度 |
|---|---|---|---|
| API 池 | `search_leads` | 次 | Starter 20 / Pro 100 / Premium 500 / Whitelabel 无限 |
| 挖客行动池 | `mine_leads` | Quota | 每天 1000 Quota = **10 次挖客行动** |

两池互不占用，各自 UTC 00:00 重置。Whitelabel 豁免挖客池。
`check_quota` 会直接给一句人话总结。

### 工作流

```
check_readiness  → 确认 key / 后端 / 配额都正常
      ↓
check_quota      → 看还剩多少次
      ↓
check_answerable → 这次计划挖 N 条，够不够
      ↓
search_leads / mine_leads → 逐次挖（挖到就转化，不要囤着等以后）
```

**配额不对称**：搜索花 1 次配额，外联（写邮件 / WhatsApp）花 0 次。
「挖 10 条只跟 3 条」是浪费额度 —— 挖 5 条全部跟完才是正常节奏。

---

## 数据主权

- **Token 客户自购** —— 模型开销走客户自己的账户，我们不代付
- **数据客户自抓** —— 线索返回给调用方即止，我们不留存
- **0 抽佣** —— 不抽流水
- **不代找客户** —— 只把你的关键词变成检索请求，结果来自公开 B2B 数据源
- **不保证认证** —— 检索到的只是线索，不是已验证的合规身份

---

## 为什么没发 npm registry

npm registry 需要 npm 账号 + 发布 token。没有可用凭证时，
硬把包装到别人账号下会造成「谁维护、谁收 telemetry、谁能下架」的归属混乱。

所以官方分发固定走这三条路，**三条指向同一份源码**（`node/index.js`），
不存在「npm 版和官网版不一样」的问题：

1. **官方站 `/static/diggerkit-mcp-v<版本>.zip`** —— 国内直连，走 Caddy 显式 MIME 路由
2. **GitHub 源码仓库** —— <https://github.com/SassumiX/diggerkit>（`diggerkit/mcp/`）
3. **DiggerKit SDK 包内** —— 已在包里时不用单独下载

---

## License

MIT
