"""
Golddigger DiggerKit SDK v1.1.0 — 完全开源免费 (MIT License)
=============================================================

v1.1 新增 (2026-10-08):
  - AgentTokenClient: 租客授权 AI Agent 用的轻量客户端
  - 自带 quota 预检, 避免 429 错误
  - 错误用 QuotaExhausted / CountryBlocked / Revoked 等具体异常
  - 重试 + 退避内置

快速开始 (传统 API key 模式):
    pip install requests
    from diggerkit_sdk import GolddiggerClient
    c = GolddiggerClient(api_key="gd_xxx")
    leads, total = c.search("modular steel buildings", country="UAE")

AI Agent 模式 (DiggerKit v1.1):
    # 1. 租客在控制台授权你的 Agent 拿一个 agent_token
    # 2. 用 AgentTokenClient 调用, 配额独立管理
    from diggerkit_sdk import AgentTokenClient
    a = AgentTokenClient(agent_token="agt_xxx")
    if a.check_quota(country="AE")["allowed"]:
        leads = a.search("smart lock", country="AE")
"""

import os
import csv
import json
import time
import argparse
import requests
from typing import List, Dict, Optional, Tuple

__version__ = "1.1.0"
DEFAULT_BASE = "https://golddigger.gold"


# ══════════════════════════════════════════════════════════════
# Exceptions
# ══════════════════════════════════════════════════════════════
class GolddiggerError(Exception):
    """Base error"""
    pass

class QuotaExhausted(GolddiggerError):
    """配额用完, 等待重置或升级"""
    def __init__(self, used, limit, period):
        self.used = used
        self.limit = limit
        self.period = period
        super().__init__(f"quota exhausted: {used}/{limit} ({period})")

class CountryBlocked(GolddiggerError):
    """国家不在授权白名单 / 在黑名单"""
    def __init__(self, country, reason):
        self.country = country
        self.reason = reason
        super().__init__(f"country {country} blocked: {reason}")

class IndustryBlocked(GolddiggerError):
    """行业不在授权范围"""
    def __init__(self, industry):
        self.industry = industry
        super().__init__(f"industry {industry} not in allowed list")

class TokenRevoked(GolddiggerError):
    """Agent token 已被撤销"""
    def __init__(self, msg="agent token revoked"):
        super().__init__(msg)

class InvalidToken(GolddiggerError):
    """Agent token 无效"""
    def __init__(self, msg="invalid agent token"):
        super().__init__(msg)


# ══════════════════════════════════════════════════════════════
# GolddiggerClient (传统 API key 模式)
# ══════════════════════════════════════════════════════════════
class GolddiggerClient:
    """传统 API key 模式客户端 (租客本人用)"""

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE):
        if not api_key:
            raise ValueError("api_key 不能为空 (从 https://golddigger.gold/ui/ 获取)")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
            "User-Agent": f"Golddigger-DiggerKit/{__version__}",
        })

    def search(self, query: str, country: str = "", limit: int = 50) -> Tuple[List[Dict], int]:
        """搜索 B2B 买家"""
        resp = self.session.post(
            f"{self.base_url}/api/search",
            json={"query": query, "country": country, "limit": limit},
            timeout=30,
        )
        if resp.status_code == 429:
            raise QuotaExhausted(-1, -1, "daily")
        resp.raise_for_status()
        data = resp.json()
        return data.get("leads", []), data.get("total_found", 0)

    def distill(self, product_desc: str, max_keywords: int = 30) -> List[str]:
        """蒸馏: 从产品描述提取搜索关键词"""
        resp = self.session.post(
            f"{self.base_url}/api/distill",
            json={"text": product_desc, "max_keywords": max_keywords},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("keywords", [])

    def match_leads(self, keywords: List[str], country: str = "") -> List[Dict]:
        """根据关键词匹配真实买家 leads"""
        resp = self.session.post(
            f"{self.base_url}/api/match",
            json={"keywords": keywords, "country": country},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("leads", [])

    def whoami(self) -> Dict:
        """查询当前账户信息 (plan / quota / credits)"""
        resp = self.session.get(f"{self.base_url}/api/tenants/me", timeout=10)
        resp.raise_for_status()
        return resp.json().get("tenant", {})


# ══════════════════════════════════════════════════════════════
# AgentTokenClient (DiggerKit v1.1 新增 - PAI 管理模式)
# ══════════════════════════════════════════════════════════════
class AgentTokenClient:
    """AI Agent 模式客户端 (租客授权 PAI 用)
    
    用法:
        a = AgentTokenClient(agent_token="agt_xxx")
        
        # 1. 调前先 check_quota, 避免 429
        status = a.check_quota(country="AE")
        if not status["allowed"]:
            print(f"拒绝: {status.get('reason')}")
            return
        
        # 2. search 返回 leads + 扣后 quota 信息
        result = a.search("smart lock", country="AE")
        print(f"拿到 {result['count']} 条, 剩 {result['quota_remaining']}/{result['quota_limit']}")
    
    设计原则:
        - Fail fast: 调用前预检, 不发无效请求
        - Specific errors: 区分 quota/country/industry/revoked
        - 一次扣一次: 每次 search 扣 1 quota
        - 可审计: 所有调用记在服务端, 租客可看
    """
    
    def __init__(self, agent_token: str, base_url: str = DEFAULT_BASE,
                 auto_check: bool = True):
        if not agent_token or not agent_token.startswith("agt_"):
            raise ValueError("agent_token 必须是 'agt_' 开头的字符串")
        self.agent_token = agent_token
        self.base_url = base_url.rstrip("/")
        self.auto_check = auto_check  # 调用 search 前自动 check_quota
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": f"Golddigger-DiggerKit-Agent/{__version__}",
        })
    
    def check_quota(self, country: str = None, industry: str = None) -> dict:
        """预检 quota, 不消耗."""
        resp = self.session.get(
            f"{self.base_url}/api/agent/quota",
            params={"token": self.agent_token, "country": country or "", "industry": industry or ""},
            timeout=10,
        )
        if resp.status_code == 400:
            raise InvalidToken(resp.text)
        resp.raise_for_status()
        data = resp.json()
        # 服务端对无效 token 返回 200 + reason=invalid_token, 也当作 InvalidToken
        if data.get("reason") == "invalid_token":
            raise InvalidToken(f"agent token not found: {self.agent_token[:12]}...")
        return data
    
    def search(self, query: str, country: str = "", industry: str = "",
               limit: int = 20, raise_on_block: bool = True) -> dict:
        """Agent 搜索. 返回 dict (含 leads + quota info).
        
        raise_on_block=False: 越权返回 dict 而不抛异常 (适合批量 Agent)
        """
        # 预检
        if self.auto_check:
            status = self.check_quota(country=country, industry=industry)
            if not status["allowed"]:
                reason = status.get("reason", "unknown")
                if reason == "revoked":
                    raise TokenRevoked()
                if reason == "quota_exhausted":
                    raise QuotaExhausted(status.get("used",0), status.get("limit",0), "period")
                if "country" in reason:
                    if raise_on_block:
                        raise CountryBlocked(country or "?", reason)
                    return {"ok": False, "denied": True, **status}
                if "industry" in reason:
                    if raise_on_block:
                        raise IndustryBlocked(industry or "?")
                    return {"ok": False, "denied": True, **status}
        # 实际调用
        resp = self.session.post(
            f"{self.base_url}/api/agent/search",
            json={
                "agent_token": self.agent_token,
                "query": query, "country": country, "industry": industry,
                "limit": limit,
            },
            timeout=30,
        )
        if resp.status_code == 401:
            raise InvalidToken(resp.text)
        if resp.status_code == 403:
            data = resp.json()
            reason = data.get("reason", "")
            if reason == "revoked": raise TokenRevoked()
            if "country" in reason: raise CountryBlocked(country or "?", reason)
            if "industry" in reason: raise IndustryBlocked(industry or "?")
            if "quota" in reason: raise QuotaExhausted(data.get("used",0), data.get("limit",0), "period")
            raise GolddiggerError(reason)
        resp.raise_for_status()
        return resp.json()
    
    def whoami(self) -> dict:
        """查询当前 Agent 状态 (剩余 quota 等)"""
        return self.check_quota()


def save_leads_to_csv(leads: List[Dict], filename: str = "leads.csv") -> str:
    """保存 leads 到 CSV 文件 (utf-8, Excel 友好)"""
    if not leads:
        print(f"⚠️  没有 leads 可保存")
        return filename
    path = os.path.join(os.path.dirname(__file__) or ".", filename)
    keys = ["company", "country", "contact", "email", "phone", "website", "score"]
    write_header = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for lead in leads:
            w.writerow(lead)
    print(f"✅ 已保存 {len(leads)} 条 leads → {filename}")
    return path


# ── CLI ──

def main():
    parser = argparse.ArgumentParser(description="Golddigger DiggerKit CLI v1.1")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--api-key", help="租客 API key (传统模式)")
    group.add_argument("--agent-token", help="Agent token (PAI 模式)")
    parser.add_argument("--query", required=True, help="搜索关键词, 如 'modular steel buildings'")
    parser.add_argument("--country", default="", help="国家代码, 如 UAE/US/DE")
    parser.add_argument("--limit", type=int, default=20, help="返回数量 (默认 20)")
    parser.add_argument("--out", default="leads.csv", help="输出 CSV 文件")
    args = parser.parse_args()

    if args.api_key:
        client = GolddiggerClient(api_key=args.api_key)
        try:
            me = client.whoami()
            print(f"👤 账户: {me.get('name')} ({me.get('email')})")
            print(f"📦 方案: {me.get('plan')} | 今日配额: {me.get('quota_used')}/{me.get('quota_daily')}")
            print()
        except Exception as e:
            print(f"⚠️  无法获取账户信息: {e}\n")
        try:
            leads, total = client.search(args.query, args.country, args.limit)
        except QuotaExhausted:
            print("❌ 今日配额用完, 升级方案 https://golddigger.gold/")
            return 1
    else:
        client = AgentTokenClient(agent_token=args.agent_token)
        try:
            me = client.whoami()
            print(f"🤖 Agent: quota {me.get('used',0)}/{me.get('limit',0)}")
            print()
        except InvalidToken:
            print("❌ Agent token 无效")
            return 1
        try:
            result = client.search(args.query, args.country, limit=args.limit)
        except TokenRevoked:
            print("❌ Agent 授权已被撤销")
            return 1
        except CountryBlocked as e:
            print(f"❌ 国家 {e.country} 不在授权范围: {e.reason}")
            return 1
        except QuotaExhausted as e:
            print(f"❌ Agent quota 用完: {e.used}/{e.limit} ({e.period})")
            return 1
        leads = result.get("leads", [])
        total = result.get("count", 0)
        print(f"  quota_remaining: {result.get('quota_remaining')}/{result.get('quota_limit')}")

    print(f"🔍 搜索: '{args.query}' (国家: {args.country or 'ALL'}, 上限: {args.limit})")
    print(f"📊 找到 {total} 个买家, 返回 {len(leads)} 条\n")

    if not leads:
        print("💡 建议: 换关键词 / 放宽国家 / 提高 --limit")
        return 0

    for i, lead in enumerate(leads[:10], 1):
        score = lead.get("score", "—")
        company = lead.get("company", "—")
        country = lead.get("country", "—")
        contact = lead.get("contact") or "—"
        email = lead.get("email") or "—"
        print(f"  {i:>3}. [{score}分] {company}")
        print(f"       🌍 {country} | 👤 {contact} | ✉️  {email}")

    if len(leads) > 10:
        print(f"  ... 还有 {len(leads) - 10} 条, 见 CSV")

    save_leads_to_csv(leads, args.out)
    return 0


if __name__ == "__main__":
    exit(main())
