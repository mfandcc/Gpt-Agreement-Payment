"""
HTTP 客户端 - 使用 curl_cffi 实现 TLS 指纹模拟
支持 Cloudflare 绕过，降级到 requests
"""
import logging
import os
import ssl
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 尝试使用 curl_cffi（推荐，自带 TLS 指纹模拟）
try:
    from curl_cffi.requests import Session as CffiSession

    _HAS_CFFI = True
    logger.debug("curl_cffi 可用，使用 TLS 指纹模拟")
except ImportError:
    _HAS_CFFI = False
    logger.debug("curl_cffi 不可用，降级到 requests")

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 通用 UA
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


def _is_https_proxy(proxy: str) -> bool:
    try:
        return urlparse(proxy).scheme.lower() == "https"
    except Exception:
        return False


def _disable_https_proxy_verify(proxy: Optional[str]) -> bool:
    if not proxy or not _is_https_proxy(proxy):
        return False
    value = os.environ.get("CTF_PROXY_SSL_VERIFY", "").strip().lower()
    return value not in {"1", "true", "yes", "on"}


def _curl_cffi_proxy_options(proxy: Optional[str]) -> dict:
    """curl --proxy-insecure equivalent for HTTPS proxies only."""
    if not _disable_https_proxy_verify(proxy):
        return {}
    try:
        from curl_cffi import CurlOpt

        return {
            CurlOpt.PROXY_SSL_VERIFYPEER: 0,
            CurlOpt.PROXY_SSL_VERIFYHOST: 0,
        }
    except Exception as e:
        logger.warning("无法设置 HTTPS 代理证书放宽选项: %s", e)
        return {}


def _new_cffi_session(proxy: Optional[str], impersonate: str):
    curl_options = _curl_cffi_proxy_options(proxy)
    if curl_options:
        try:
            return CffiSession(impersonate=impersonate, curl_options=curl_options)
        except TypeError:
            session = CffiSession(impersonate=impersonate)
            try:
                session.curl_options.update(curl_options)
            except Exception:
                logger.warning("当前 curl_cffi 版本不支持 curl_options，HTTPS 代理证书仍会校验")
            return session
    return CffiSession(impersonate=impersonate)


class _HTTPSProxyInsecureAdapter(HTTPAdapter):
    def proxy_manager_for(self, proxy, **proxy_kwargs):
        if _disable_https_proxy_verify(proxy):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            proxy_kwargs["proxy_ssl_context"] = ctx
            proxy_kwargs["proxy_assert_hostname"] = False
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def create_http_session(proxy: Optional[str] = None, impersonate: str = "chrome136"):
    """
    创建 HTTP 会话。优先使用 curl_cffi 模拟浏览器 TLS 指纹，
    不可用时降级到 requests。
    """
    if _HAS_CFFI:
        session = _new_cffi_session(proxy, impersonate)
        # 使用显式配置，避免被系统 HTTP(S)_PROXY 隐式污染。
        session.trust_env = False
        if proxy:
            # curl_cffi 在 SOCKS 代理下建议使用 socks5h，让 DNS 走代理端解析。
            # 这能减少本地 DNS/链路导致的 TLS 握手异常。
            normalized_proxy = proxy
            if proxy.startswith("socks5://"):
                normalized_proxy = "socks5h://" + proxy[len("socks5://"):]
                logger.info("代理协议已标准化: socks5:// -> socks5h://")
            session.proxies = {"https": normalized_proxy, "http": normalized_proxy}
        else:
            # 显式设置空代理，覆盖系统环境变量 (trust_env=False 对 libcurl 不够)
            session.proxies = {"https": "", "http": ""}
        return session
    else:
        session = requests.Session()
        session.trust_env = False
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST"],
        )
        adapter = _HTTPSProxyInsecureAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        if proxy:
            session.proxies = {"https": proxy, "http": proxy}
        session.headers["User-Agent"] = USER_AGENT
        return session
