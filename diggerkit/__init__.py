"""DiggerKit · GoldDigger SI Agent 的金铲子

最小可用：

    from diggerkit import Client
    c = Client(api_key="gds_你的KEY")
    print(c.quota())

说明：
  - Client / DiggerKitClient = v2.0.0 客户端（纯标准库，无第三方依赖）
  - GolddiggerClient / AgentTokenClient = v1.1 旧版 SDK（需 pip install "diggerkit[legacy]"）

⚠️ 旧版 SDK 依赖 requests，是可选依赖 —— 这里用 PEP 562 延迟导入，
   否则 `from diggerkit import Client` 会因为缺 requests 直接炸，
   「零第三方依赖」的承诺就废了。
"""
from .client import (
    DiggerKitClient,
    DiggerKitError,
    InvalidKey,
    QuotaExceeded,
    RateLimited,
    ServerError,
)

# 客户文档里写的是 `from diggerkit import Client`
Client = DiggerKitClient

__version__ = "2.1.0"

_LEGACY = {
    "AgentTokenClient",
    "CountryBlocked",
    "GolddiggerClient",
    "GolddiggerError",
    "IndustryBlocked",
    "InvalidToken",
    "QuotaExhausted",
    "TokenRevoked",
}

__all__ = [
    "Client",
    "DiggerKitClient",
    "DiggerKitError",
    "InvalidKey",
    "QuotaExceeded",
    "RateLimited",
    "ServerError",
    "__version__",
]


def __getattr__(name):
    """延迟导入旧版 SDK（需要 requests）"""
    if name in _LEGACY:
        try:
            from . import sdk
        except ImportError as exc:
            raise AttributeError(
                '%s 需要 requests：pip install "diggerkit[legacy]"（%s）' % (name, exc)
            ) from exc
        return getattr(sdk, name)
    raise AttributeError("module 'diggerkit' has no attribute %r" % (name,))


def __dir__():
    return sorted(set(__all__) | _LEGACY)


# 装了 requests 才把旧版名字放进 import * 的范围
try:
    import requests  # noqa: F401
except ImportError:
    pass
else:
    __all__ += sorted(_LEGACY)
