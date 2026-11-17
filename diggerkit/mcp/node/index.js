#!/usr/bin/env node
/**
 * golddigger-mcp — DiggerKit MCP server v2.2 (2026-11-17)
 *
 * ⚠️ v1.0 是空壳: package.json + mcp.json 两个文件, 没有 index.js,
 *    并且 mcp.json 指向的 npm 包 golddigger-mcp 从未发布 (404)。
 *    客户照文档 npx -y golddigger-mcp 直接失败。v2.0 是可运行的实现。
 *
 * 对标 NVIDIA/auto-ontology 的 MCP 设计:
 *   - 工具集只读, 不提供任何写入 / 外发能力
 *     (Auto Ontology: "deliberately no tool for browsing raw schemas"
 *      我们同理: 不提供"批量导出全部线索"这类会带走客户数据的工具)
 *   - check_readiness: 部署能不能干活, 一次报全所有阻塞项
 *   - check_answerable: 这道题能不能答, 覆盖不足就明说
 *   - 每个结果带 provenance (来源 + 置信度), 不给无出处的结论
 *   - 不做裸数据浏览: 只暴露"能做什么"和"配额多少", 客户自己的数据自己存
 *
 * 认证: GOLDDIGGER_API_KEY (gds_xxx 供应商 / gdb_xxx 买家)
 *       或启动参数 --api-key（命令行优先）
 */

'use strict';

// ── 启动参数（命令行优先于环境变量）──
//   node index.js --api-key gds_xxx [--base-url https://golddigger.gold]
const argv = process.argv.slice(2);
function argVal(flag) {
  const i = argv.indexOf(flag);
  if (i !== -1 && argv[i + 1] && !argv[i + 1].startsWith('--')) return argv[i + 1];
  const hit = argv.find((a) => a.startsWith(flag + '='));
  return hit ? hit.slice(flag.length + 1) : '';
}

const BASE_URL = (argVal('--base-url') || process.env.GOLDDIGGER_BASE_URL || 'https://golddigger.gold').replace(/\/$/, '');
const API_KEY = argVal('--api-key') || process.env.GOLDDIGGER_API_KEY || '';
const TIMEOUT_MS = Number(process.env.GOLDDIGGER_TIMEOUT_MS || 60000);

// ── 错误分层 (与 SDK / 后端 error code 对齐) ──
class DiggerKitError extends Error {
  constructor(message, code = '', status = 0, payload = null) {
    super(message);
    this.code = code;
    this.status = status;
    this.payload = payload;
  }
}

async function apiRequest(method, path, body, query) {
  let url = `${BASE_URL}${path}`;
  if (query && Object.keys(query).length) {
    const qs = new URLSearchParams(
      Object.entries(query).filter(([, v]) => v !== undefined && v !== '')
    ).toString();
    if (qs) url += `?${qs}`;
  }

  const headers = { Accept: 'application/json' };
  if (API_KEY) headers['X-API-KEY'] = API_KEY;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  let res;
  try {
    res = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctrl.signal,
    });
  } catch (e) {
    clearTimeout(timer);
    if (e.name === 'AbortError') {
      throw new DiggerKitError(`请求超时 (${TIMEOUT_MS}ms)`, 'timeout');
    }
    throw new DiggerKitError(`网络不可达: ${e.message}`, 'network_error');
  }
  clearTimeout(timer);

  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { error: text.slice(0, 200) };
  }

  if (!res.ok) {
    const err = String(data.error || data.message || '');
    const code = String(data.code || '');
    if (res.status === 402 || code === 'quota_exceeded') {
      throw new DiggerKitError(err || '配额用完', 'quota_exceeded', 402, data);
    }
    if (res.status === 429 || code === 'RATE_LIMITED') {
      throw new DiggerKitError(err || '请求过于频繁', 'RATE_LIMITED', 429, data);
    }
    if (res.status === 403) {
      throw new DiggerKitError(err || 'API Key 无效', 'invalid_key', 403, data);
    }
    throw new DiggerKitError(err || `HTTP ${res.status}`, code, res.status, data);
  }
  return data;
}

// ══════════════════════════════════════════════════════════════
// 工具定义
// ══════════════════════════════════════════════════════════════

const TOOLS = [
  {
    name: 'check_readiness',
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    description:
      '检查部署是否可用: API Key 有效性 + 配额状态 + 后端连通性。' +
      '一次报出所有阻塞项。接入后先调这个。',
    inputSchema: { type: 'object', properties: {}, required: [] },
  },
  {
    name: 'check_quota',
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    description:
      '查剩余配额与套餐周期 (只读, 不消耗配额)。' +
      '挖客前先查, 避免白跑。',
    inputSchema: { type: 'object', properties: {}, required: [] },
  },
  {
    name: 'search_leads',
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    description:
      '挖客: 按产品关键词 + 国家 + 行业检索潜在买家, 返回带评分的线索列表。' +
      '⚠️ 消耗配额 (每次 1 次)。limit 1-10。' +
      '数据只返回给调用方, 我们不持有。',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: '产品关键词 (必填), 如 "全棉府绸 133x72 GOTS"' },
        country: { type: 'string', description: '目标国家代码, 如 DE / NL / AE' },
        industry: { type: 'string', description: '行业, 如 textile / building' },
        limit: { type: 'integer', description: '返回条数 1-10', default: 10, minimum: 1, maximum: 10 },
      },
      required: ['query'],
    },
  },
  {
    name: 'mine_leads',
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    description:
      '挖客行动 (DiggerKit C / C+ 档): 按产品关键词 + 国家 + 行业挖潜在买家, ' +
      '结果自动存进你自己的线索库, 并返回公司 / 网站 / 邮箱; ' +
      'C+ 额外给电话 / 联系人 / 意向评分 (深度抓官网)。' +
      '⚠️ 走【挖客行动池】(1000 Quota/天, 每次行动扣 100 → 每天 10 次), ' +
      '与 search_leads 的 API 池互不占用。' +
      'tier: C = 基础 (最多 8 条) / C+ = 增强 (最多 15 条)。' +
      '数据只返回给调用方, 我们不持有。',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: '产品关键词 (必填), 如 "全棉府绸 133x72 GOTS"' },
        country: { type: 'string', description: '目标国家, 如 Germany / DE' },
        industry: { type: 'string', description: '行业, 如 textile / building' },
        tier: { type: 'string', description: 'C = 基础 / C+ = 增强', default: 'C+', enum: ['C', 'C+'] },
        limit: { type: 'integer', description: '返回条数 (C 上限 8 / C+ 上限 15)', minimum: 3, maximum: 20 },
      },
      required: ['query'],
    },
  },
  {
    name: 'check_answerable',
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    description:
      '判断当前配额与配置能否支撑这次挖客需求。' +
      '覆盖不足就明说, 不做无意义的调用。',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: '想挖的客源关键词' },
        limit: { type: 'integer', description: '计划条数', default: 10 },
      },
      required: ['query'],
    },
  },
];

// ══════════════════════════════════════════════════════════════
// 工具实现
// ══════════════════════════════════════════════════════════════

async function t_check_readiness() {
  const blockers = [];
  const report = { ready: false, checks: {}, blockers };

  // ① Key 是否配置
  if (!API_KEY) {
    blockers.push('未设置 GOLDDIGGER_API_KEY — 客户自己的 API Key, 不是我们出 Token');
    report.checks.api_key = { ok: false, reason: 'missing' };
  } else {
    report.checks.api_key = { ok: true, prefix: API_KEY.slice(0, 4) + '…' };
  }

  // ② 后端连通
  try {
    const h = await apiRequest('GET', '/api/health');
    report.checks.backend = { ok: true, service: h.service, version: h.version };
  } catch (e) {
    report.checks.backend = { ok: false, reason: e.message };
    blockers.push(`后端不可达: ${e.message}`);
  }

  // ③ 配额
  if (report.checks.api_key && report.checks.api_key.ok) {
    try {
      const q = await apiRequest('GET', '/api/quota');
      report.checks.quota = {
        ok: !!q.allowed,
        allowed: q.allowed,
        remaining: q.remaining,
        quota: q.quota,
        plan: q.plan,
        resets_at: q.resets_at,
      };
      if (!q.allowed) blockers.push('API 配额已用完, 等 UTC 00:00 重置或升级');
      // 挖客行动池 (DiggerKit C/C+) — 独立于 API 池 (2026-11-11)
      const dig = q.pools && q.pools.dig;
      if (dig) {
        report.checks.dig_quota = {
          ok: !!dig.allowed,
          allowed: dig.allowed,
          actions_left: dig.actions_left,
          quota: dig.quota,
          used: dig.used,
          cost_per_action: dig.cost_per_action,
          resets_at: dig.resets_at,
        };
        if (!dig.allowed) blockers.push('今日挖客行动次数已用完 (次日 UTC 00:00 自动重置)');
      }
    } catch (e) {
      report.checks.quota = { ok: false, reason: e.message };
      if (e.code !== 'invalid_key') blockers.push(`配额查询失败: ${e.message}`);
    }
  }

  report.ready = blockers.length === 0;
  const _api = report.checks.quota || {};
  const _dig = report.checks.dig_quota || {};
  report.summary = report.ready
    ? `✅ 可以开工 — API 池剩 ${_api.remaining ?? '?'} 次, 挖客行动剩 ${_dig.actions_left ?? '?'} 次`
    : `🚫 有 ${blockers.length} 项阻塞, 见 blockers`;
  return report;
}

async function t_check_quota() {
  const q = await apiRequest('GET', '/api/quota');
  // 人话总结: 两个独立池子, 别把「次」和「挖客行动」搞混 (2026-11-11)
  const dig = q.pools && q.pools.dig;
  const apiLine = q.unlimited
    ? `API 池: 无限 (${q.plan} 档)`
    : `API 池: ${q.remaining}/${q.quota} 次 (search_leads / kb_ask 各扣 1 次)`;
  const digLine = !dig
    ? '挖客池: (后端未返回)'
    : dig.unlimited
      ? '挖客池: 无限 (Whitelabel 档豁免)'
      : `挖客池: ${dig.actions_left} 次挖客行动 (DiggerKit C/C+, 每次扣 ${dig.cost_per_action} Quota, 不占 API 池)`;
  return {
    ...q,
    summary: `${apiLine} · ${digLine} · 次日 UTC 00:00 各自重置`,
    _provenance: {
      source: 'GET /api/quota',
      note: '只读, 不消耗配额',
    },
  };
}

async function t_search_leads(args) {
  const query = String(args.query || '').trim();
  if (!query) throw new DiggerKitError('query 必填', 'bad_request');
  const limit = Math.max(1, Math.min(Number(args.limit) || 10, 10));

  const body = { query, limit };
  if (args.country) body.country = String(args.country).trim();
  if (args.industry) body.industry = String(args.industry).trim();

  const r = await apiRequest('POST', '/api/search', body);
  const leads = Array.isArray(r) ? r : (r.leads || r.results || []);

  // 兼容别名: 老文档写 score, 实际字段是 gd_score / composite_score
  for (const lead of leads) {
    if (lead && typeof lead === 'object' && lead.score === undefined) {
      lead.score = lead.composite_score !== undefined
        ? lead.composite_score
        : (lead.gd_score || 0);
    }
  }

  return {
    count: leads.length,
    query,
    leads,
    _field_contract: {
      note: '评分字段是 gd_score / composite_score / heat_score, 不是 score (score 为兼容别名)',
      company: '公司名',
      country: '国家',
      website: '官网',
      contact_name: '联系人',
      email: '邮箱',
      gd_score: 'GoldDigger 6 维评分 0-100',
      gd_tier: 'hot / warm / cold',
      gd_reason: '评分构成明细',
      composite_score: '综合分',
    },
    _provenance: {
      source: 'POST /api/search',
      consumed_quota: 1,
      note: '数据只返回给调用方, 客户自己存; 我们不持有买家数据',
    },
  };
}

async function t_mine_leads(args) {
  const query = String(args.query || '').trim();
  if (!query) throw new DiggerKitError('query 必填', 'bad_request');
  const tier = String(args.tier || 'C+').toUpperCase() === 'C' ? 'C' : 'C+';
  const maxResults = tier === 'C' ? 8 : 15;
  const limit = Math.max(3, Math.min(Number(args.limit) || maxResults, 20));

  // 后端 /api/diggerkit/mine 从 body 取凭据 (body.key / body.key4)，
  // X-API-KEY header 只过鉴权中间件 —— 两个都要给，否则 400 "请先登录"
  const body = { key: API_KEY, query, limit, tier };
  if (args.country) body.country = String(args.country).trim();
  if (args.industry) body.industry = String(args.industry).trim();

  const r = await apiRequest('POST', '/api/diggerkit/mine', body);
  const leads = Array.isArray(r) ? r : (r.leads || []);

  return {
    count: leads.length,
    tier: r.tier || tier,
    tier_label: r.tier_label || '',
    query: r.query || query,
    saved: r.saved !== undefined ? r.saved : leads.length,
    with_email: r.with_email !== undefined ? r.with_email : 0,
    hot: r.hot !== undefined ? r.hot : 0,
    leads,
    _field_contract: {
      note: '本端点的评分字段是 score (DiggerKit C+ 意向评分 0-100), 不是 gd_score',
      company: '公司名',
      website: '官网',
      email: '邮箱',
      phone: '电话 (C+ 才有)',
      contact_name: '联系人 (C+ 才有)',
      country: '国家',
      industry: '行业',
      score: 'DiggerKit C+ 意向评分 0-100',
    },
    _provenance: {
      source: 'POST /api/diggerkit/mine',
      consumed_pool: '挖客行动池 (1000 Quota/天, 每次行动扣 100)',
      actions_left: r.dig_actions_left,
      note: '结果已存进你自己的线索库, 平台不持有买家数据',
    },
  };
}

async function t_check_answerable(args) {
  const query = String(args.query || '').trim();
  const want = Math.max(1, Number(args.limit) || 10);

  const checks = {};
  const blockers = [];

  try {
    const q = await apiRequest('GET', '/api/quota');
    checks.quota = { ok: !!q.allowed, remaining: q.remaining, quota: q.quota, plan: q.plan };
    if (!q.allowed) blockers.push('配额已用完');
    else if (q.remaining < 1) blockers.push('剩余配额不足以发起一次搜索');
  } catch (e) {
    checks.quota = { ok: false, reason: e.message };
    blockers.push(`配额不可查: ${e.message}`);
  }

  const answerable = blockers.length === 0;
  return {
    answerable,
    confidence: answerable ? 1.0 : 0.0,
    requested: want,
    query,
    checks,
    blockers,
    advice: answerable
      ? `可以跑, 最多 ${want} 条 (每次消耗 1 配额)`
      : '先解决 blockers, 否则调用只会浪费配额',
    _provenance: { source: 'GET /api/quota', note: '预检不消耗配额' },
  };
}

const HANDLERS = {
  check_readiness: t_check_readiness,
  check_quota: t_check_quota,
  search_leads: t_search_leads,
  mine_leads: t_mine_leads,
  check_answerable: t_check_answerable,
};

// ══════════════════════════════════════════════════════════════
// MCP stdio 协议
// ══════════════════════════════════════════════════════════════

// 出站分帧：跟随入站格式（标准 MCP 客户端只认换行分帧）
let outFraming = 'newline';
function send(msg) {
  const body = JSON.stringify(msg);
  if (outFraming === 'lsp') {
    process.stdout.write(`Content-Length: ${Buffer.byteLength(body, 'utf8')}\r\n\r\n${body}`);
  } else {
    process.stdout.write(body + '\n');
  }
}

function errPayload(e) {
  return {
    code: e.code || 'error',
    message: e.message || String(e),
    status: e.status || 0,
    data: e.payload || null,
  };
}

async function handle(msg) {
  const { id, method, params } = msg;

  switch (method) {
    case 'initialize':
      return {
        protocolVersion: '2024-11-05',
        capabilities: { tools: {} },
        serverInfo: { name: 'golddigger-mcp', version: '2.2.0' },
      };

    case 'notifications/initialized':
      return null;

    case 'tools/list':
      return { tools: TOOLS };

    case 'tools/call': {
      const name = params && params.name;
      const args = (params && params.arguments) || {};
      const fn = HANDLERS[name];
      if (!fn) {
        return {
          content: [{ type: 'text', text: `未知工具: ${name}` }],
          isError: true,
        };
      }
      try {
        const result = await fn(args);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          isError: false,
        };
      } catch (e) {
        return {
          content: [
            { type: 'text', text: JSON.stringify({ error: errPayload(e) }, null, 2) },
          ],
          isError: true,
        };
      }
    }

    case 'ping':
      return {};

    default:
      if (id === undefined) return null;
      return null;
  }
}

// ── 主循环: 同时支持两种 stdin 分帧 ──
//   ① 标准 MCP 换行分帧 (JSON-RPC over newline) —— Claude Desktop / VS Code / MCP Inspector 走这个
//   ② LSP Content-Length 分帧 —— 兼容早期自研 wrapper
let buffer = Buffer.alloc(0);
const pending = new Set();   // 在途请求 (2026-11-11: stdin 关闭时等它们跑完)

function dispatch(msg) {
  const task = Promise.resolve(handle(msg))
    .then((result) => {
      if (result === null || msg.id === undefined) return; // notification
      send({ jsonrpc: '2.0', id: msg.id, result });
    })
    .catch((e) => {
      if (msg.id === undefined) return;
      send({
        jsonrpc: '2.0',
        id: msg.id,
        error: { code: -32603, message: e.message || String(e) },
      });
    });
  pending.add(task);
  task.finally(() => pending.delete(task));
}

process.stdin.on('data', (chunk) => {
  buffer = Buffer.concat([buffer, chunk]);

  while (true) {
    // ① 标准 MCP: 一行一条 JSON-RPC
    const nl = buffer.indexOf(0x0a);
    if (nl !== -1) {
      const line = buffer.slice(0, nl).toString('utf8').trim();
      if (line.startsWith('{')) {
        buffer = buffer.slice(nl + 1);
        let msg = null;
        try { msg = JSON.parse(line); } catch { msg = null; }
        if (msg) dispatch(msg);
        continue;   // 坏行丢弃，防死循环
      }
    }

    // ② LSP: Content-Length 分帧
    const headerEnd = buffer.indexOf('\r\n\r\n');
    if (headerEnd === -1) break;

    const header = buffer.slice(0, headerEnd).toString('ascii');
    const m = /Content-Length:\s*(\d+)/i.exec(header);
    if (!m) {
      // 无法解析头, 丢弃这段
      buffer = buffer.slice(headerEnd + 4);
      continue;
    }
    outFraming = 'lsp';
    const len = parseInt(m[1], 10);
    const bodyStart = headerEnd + 4;
    if (buffer.length < bodyStart + len) break; // 还没收全

    const body = buffer.slice(bodyStart, bodyStart + len).toString('utf8');
    buffer = buffer.slice(bodyStart + len);

    let msg;
    try {
      msg = JSON.parse(body);
    } catch {
      continue;
    }

    dispatch(msg);
  }
});

// stdin 关闭时不要立刻 exit —— 否则在途的异步请求 (真实 API 调用) 会被丢掉,
// 客户端收到的就是一个"没有响应"的空结果。改为等在途请求跑完再退。
process.stdin.on('end', () => {
  Promise.allSettled([...pending]).then(() => process.exit(0));
});

// stderr 用于日志 (stdout 是协议通道, 不能污染)
process.stderr.write(
  `[golddigger-mcp] v2.2.0 ready · base=${BASE_URL} · key=${API_KEY ? API_KEY.slice(0, 4) + '…' : '(未设置)'}\n`
);
