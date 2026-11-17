#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diggerkit_client.py — DiggerKit Python SDK v2.0 (2026-11-11)

⚠️ v1.1 与本文的差别 (重要):
   v1.1 的 SDK 调用 /api/leads/search, /api/leads/score, /api/outreach/draft,
   /api/report/generate —— 这 4 个端点在生产后端**从来不存在** (实测 404)。
   客户装完 v1.1 第一行调用就崩。v2.0 全部对齐真实端点。

对标 NVIDIA/auto-ontology 的方法论:
   - 每个方法对应一个**真实存在**的端点, 不承诺不存在的接口
   - 响应契约显式化 (返回结构固定, 不让调用方猜)
   - 只读方法与写方法分离, 写方法显式标注
   - 错误分层: 配额 / 鉴权 / 限流 / 业务, 与后端 error code 对齐

数据主权 (不变):
   - Token 客户自购, 不经过我们
   - 抓到的买家信息存客户自己的服务器
   - 0 留存 0 抽佣
   - 我们不持有买家数据
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

__version__ = "2.0.0"

BASE_URL = os.getenv("GOLDDIGGER_BASE_URL", "https://golddigger.gold")


# ══════════════════════════════════════════════════════════════
# 异常分层 (与后端 error code 一一对应)
# ══════════════════════════════════════════════════════════════

class DiggerKitError(Exception):
    """所有 DiggerKit 异常的基类"""

    def __init__(self, message: str, *, code: str = "",
                 status: int = 0, payload: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.payload = payload or {}


class QuotaExceeded(DiggerKitError):
    """配额用完 —— 等周期重置或升级"""

    def __init__(self, message="配额用完", *, quota=0, used=0,
                 period="", payload=None):
        super().__init__(message, code="quota_exceeded",
                         status=402, payload=payload)
        self.quota = quota
        self.used = used
        self.period = period


class InvalidKey(DiggerKitError):
    """API Key 无效 —— 换 key 或重新生成"""


class RateLimited(DiggerKitError):
    """被限流 —— 退避后重试"""

    def __init__(self, message="请求过于频繁", *, retry_after=0, payload=None):
        super().__init__(message, code="RATE_LIMITED", status=429,
                         payload=payload)
        self.retry_after = retry_after


class ServerError(DiggerKitError):
    """后端 5xx"""


# ══════════════════════════════════════════════════════════════
# 客户端
# ══════════════════════════════════════════════════════════════

class DiggerKitClient:
    """
    DiggerKit 客户端 —— 客户本地跑的"金铲子"

    认证: 完整 API Key (gds_xxx 供应商 / gdb_xxx 买家)
          环境变量 GOLDDIGGER_API_KEY 或构造参数 api_key
    """

    def __init__(self, api_key: Optional[str] = None,
                 base_url: Optional[str] = None, timeout: int = 60):
        self.api_key = api_key or os.getenv("GOLDDIGGER_API_KEY", "")
        self.base_url = (base_url or BASE_URL).rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise InvalidKey(
                "缺 API Key — 用 DiggerKitClient(api_key='gds_xxx') "
                "或设环境变量 GOLDDIGGER_API_KEY")

    # ── 内部 ──
    def _req(self, method: str, path: str, body: Optional[dict] = None,
             query: Optional[dict] = None) -> Any:
        url = f"{self.base_url}{path}"
        if query:
            from urllib.parse import urlencode
            url = f"{url}?{urlencode(query)}"

        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-API-KEY", self.api_key)
        req.add_header("Accept", "application/json")
        if data:
            req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read().decode("utf-8", "replace")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"error": raw[:200]}
            self._raise_for(e.code, payload)
        except urllib.error.URLError as e:
            raise DiggerKitError(f"网络不可达: {e.reason}",
                                 code="network_error") from e
        except json.JSONDecodeError as e:
            raise DiggerKitError(f"响应不是合法 JSON: {e}",
                                 code="bad_response") from e

    def _raise_for(self, status: int, payload: dict):
        err = str(payload.get("error") or payload.get("message") or "")
        code = str(payload.get("code") or "")
        if status == 402 or code == "quota_exceeded":
            raise QuotaExceeded(
                err or "配额用完", quota=payload.get("quota", 0),
                used=payload.get("used", 0),
                period=payload.get("period", ""), payload=payload)
        if status == 403 and "Invalid API key" in err:
            raise InvalidKey(err or "API Key 无效", status=status,
                             payload=payload)
        if status == 429 or code == "RATE_LIMITED":
            raise RateLimited(err or "请求过于频繁",
                              retry_after=payload.get("retry_after", 0),
                              payload=payload)
        if status >= 500:
            raise ServerError(err or f"服务端错误 {status}",
                              code=code, status=status, payload=payload)
        raise DiggerKitError(err or f"HTTP {status}", code=code,
                             status=status, payload=payload)

    # ── 只读能力 ──

    def check_quota(self) -> Dict[str, Any]:
        """
        查配额 (不消耗)

        返回 (2026-11-11 配额二次校对后新增 3 个字段, 旧字段全部保留向后兼容):
          allowed           是否还有额度
          remaining         剩余次数
          quota             当日额度上限
          used              今日已用
          plan              套餐档位
          plan_expires      套餐到期时间
          resets_at         重置时刻 (UTC 00:00)
          unlimited         ★ Whitelabel 档为 true (真正无限, 不受数值上限约束)
          cost              ★ 各接口本次调用的扣分 {api_search:1, kb_ask:1,
                            diggerkit_c:100, diggerkit_c_plus:100}
          resets_in_seconds 距离下次重置的秒数 (可做倒计时 UI)
          pools             ★ 双池明细 (2026-11-11 独立池):
                            pools.api = API 池 (search_leads / kb_ask, 单位「次」)
                            pools.dig = 挖客行动池 (DiggerKit C/C+, 单位「Quota」,
                                              每天 10 次, 不占 API 池)
        """
        return self._req("GET", "/api/quota")

    def search_leads(self, query: str, country: str = "", industry: str = "",
                     limit: int = 10) -> List[Dict[str, Any]]:
        """
        挖客 —— 真实端点 POST /api/search

        query   必填, 产品关键词 (如 "全棉府绸 133x72 GOTS")
        country 可选, 目标国家 (如 "DE")
        industry 可选, 行业 (如 "textile")
        limit   可选, 1-10 (后端硬上限 10)

        返回: leads 列表。⚠️ 消耗配额 (每次 1 次)

        真实 lead 字段 (2026-11-11 实测, 41 个):
          id / tenant_id / company / country / industry / product_match
          contact_name / contact_title / email / phone / website / linkedin
          source / source_url
          gd_score        — GoldDigger 6 维评分 (0-100)
          gd_tier         — hot / warm / cold
          gd_reason       — 评分构成明细 (可读)
          heat_score      — 热度分 (新鲜度/完整度)
          composite_score — 综合分 (用于排序)
          pool_status     — BUFFER / SENT 等
          tier / status / is_preview / paid
          keyword_match / country_match / contact_score / website_score
          source_score / rag_score
          created_at / updated_at / sent_count / reply_count

        ⚠️ 评分字段名是 gd_score / composite_score, **不是** score。
           v1.1 文档写 score —— 那是错的, 照着写会拿不到值。
           本 SDK 补了 score 兼容别名 (= composite_score), 让旧代码不崩。
        """
        if not query or not query.strip():
            raise DiggerKitError("query 必填", code="bad_request")
        limit = max(1, min(int(limit), 10))
        body: Dict[str, Any] = {"query": query.strip(), "limit": limit}
        if country:
            body["country"] = country.strip()
        if industry:
            body["industry"] = industry.strip()
        r = self._req("POST", "/api/search", body)
        if isinstance(r, dict):
            leads = r.get("leads") or r.get("results") or []
        else:
            leads = r if isinstance(r, list) else []
        for lead in leads:
            if isinstance(lead, dict) and "score" not in lead:
                # 兼容别名: 老文档写 score, 实际字段是 gd_score / composite_score
                lead["score"] = lead.get("composite_score",
                                         lead.get("gd_score", 0))
        return leads

    def mine(self, query: str, country: str = "", industry: str = "",
             limit: int = 10, tier: str = "C+") -> List[Dict[str, Any]]:
        """
        挖客行动池 —— 真实端点 POST /api/diggerkit/mine

        与 search_leads 的区别（配额池不同，勿混用）:
          search_leads -> POST /api/search        -> API 池（4 档订阅次数/天）
          mine         -> POST /api/diggerkit/mine -> 挖客行动池（1000 Quota/天 = 10 次/天）
        两池互不占用，各 UTC 00:00 重置。

        tier  "C"  = 基础版（不深度抓取）
              "C+" = 增强版（深度抓取，消耗更多算力配额）

        body: {key, query, country, industry, limit, tier}
        返回: leads 列表，每条含 score（0-100）/ company / website / email / phone ...
        端点还返回 saved / with_email / hot 等统计，挖客池余额用 check_quota() 查。
        """
        tier = str(tier).upper()
        if tier not in ("C", "C+"):
            tier = "C+"
        body = {
            "key": self.api_key,
            "query": query,
            "country": country,
            "industry": industry,
            "limit": int(limit),
            "tier": tier,
        }
        r = self._req("POST", "/api/diggerkit/mine", body=body)
        # 与 search_leads 保持一致: 返回 leads 列表
        # (端点原始响应是 dict: {ok,tier,found,saved,with_email,hot,leads,...})
        if isinstance(r, dict):
            leads = r.get("leads") or []
        else:
            leads = r if isinstance(r, list) else []
        for lead in leads:
            if isinstance(lead, dict) and "score" not in lead:
                lead["score"] = lead.get("composite_score",
                                         lead.get("gd_score", 0))
        return leads

    def list_leads(self) -> Dict[str, Any]:
        """
        列出本租户已存的线索 (只读, 不消耗配额)

        返回: {total, leads}
        """
        return self._req("GET", "/api/leads")

    def health(self) -> Dict[str, Any]:
        """健康检查 (不需要 key)"""
        return self._req("GET", "/api/health")

    # ── 便捷方法 ──

    def multi_query_loop(self, queries: List[str], country: str = "",
                         industry: str = "", limit: int = 10,
                         stop_on_quota: bool = True) -> List[Dict[str, Any]]:
        """
        多 query 批量挖客 —— 配额用完自动停

        返回: 合并去重后的 leads
        """
        seen: set = set()
        out: List[Dict[str, Any]] = []
        for q in queries:
            try:
                for lead in self.search_leads(q, country=country,
                                              industry=industry, limit=limit):
                    key = str(lead.get("website") or lead.get("company") or "")
                    if key and key in seen:
                        continue
                    if key:
                        seen.add(key)
                    out.append(lead)
            except QuotaExceeded:
                if stop_on_quota:
                    break
                raise
        return out


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

def main() -> int:
    import argparse
    import sys

    p = argparse.ArgumentParser(
        prog="diggerkit",
        description="GoldDigger DiggerKit · SI Agent 挖客工具")
    p.add_argument("--query", "-q", help="产品关键词")
    p.add_argument("--country", "-c", default="", help="目标国家 (如 DE)")
    p.add_argument("--industry", "-i", default="", help="行业 (如 textile)")
    p.add_argument("--limit", "-l", type=int, default=10, help="1-10")
    p.add_argument("--quota", action="store_true", help="只查配额")
    p.add_argument("--leads", action="store_true", help="列出已存线索")
    p.add_argument("--mine", action="store_true",
                   help="走挖客行动池 (POST /api/diggerkit/mine)")
    p.add_argument("--tier", default="C+", choices=["C", "C+"],
                   help="挖客档位: C=基础 / C+=增强 (默认 C+)")
    p.add_argument("--api-key", default="", help="API Key (默认读环境变量)")
    p.add_argument("--base-url", default="", help="后端地址")
    args = p.parse_args()

    try:
        client = DiggerKitClient(api_key=args.api_key or None,
                                 base_url=args.base_url or None)
    except DiggerKitError as e:
        print(f"❌ {e.message}", file=sys.stderr)
        return 2

    try:
        if args.quota:
            q = client.check_quota()
            print(json.dumps(q, ensure_ascii=False, indent=2))
            return 0

        if args.leads:
            print(json.dumps(client.list_leads(), ensure_ascii=False, indent=2))
            return 0

        if not args.query:
            p.print_help()
            return 1

        if args.mine:
            leads = client.mine(args.query, country=args.country,
                                industry=args.industry, limit=args.limit,
                                tier=args.tier)
        else:
            leads = client.search_leads(args.query, country=args.country,
                                        industry=args.industry, limit=args.limit)
        print(f"🔍 {len(leads)} 条线索 (query={args.query})\n")
        for lead in leads:
            print(f"  · {lead.get('company') or lead.get('name') or '?'} "
                  f"({lead.get('country') or '?'}) "
                  f"score={lead.get('score', '?')}")
            if lead.get("website"):
                print(f"    {lead['website']}")
        return 0

    except QuotaExceeded as e:
        print(f"❌ 配额用完 ({e.used}/{e.quota}) — 等周期重置或升级",
              file=sys.stderr)
        return 3
    except RateLimited as e:
        print(f"❌ 限流 — {e.retry_after}s 后重试", file=sys.stderr)
        return 4
    except DiggerKitError as e:
        print(f"❌ {e.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
