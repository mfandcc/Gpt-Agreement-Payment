"""Small SMSBower client for SMS-Activate compatible endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import requests


DEFAULT_API_URL = "https://smsbower.online/stubs/handler_api.php"


class SMSBowerError(RuntimeError):
    pass


@dataclass(frozen=True)
class SMSActivation:
    activation_id: str
    number: str

    def display_number(self, prefix: str = "+") -> str:
        raw = str(self.number or "").strip()
        if not raw:
            return ""
        if raw.startswith("+") or not prefix:
            return raw
        return f"{prefix}{raw}"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class SMSBowerClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_url: str = DEFAULT_API_URL,
        service: str = "dr",
        country: str = "0",
        operator: str = "",
        max_price: str = "",
        timeout_s: int = 180,
        poll_interval_s: float = 5.0,
        log: Callable[[str], None] | None = None,
    ):
        if not api_key:
            raise SMSBowerError("sms_bower.api_key is empty")
        self.api_key = api_key
        self.api_url = api_url or DEFAULT_API_URL
        self.service = service or "dr"
        self.country = country or "0"
        self.operator = operator or ""
        self.max_price = max_price or ""
        self.timeout_s = max(30, int(timeout_s or 180))
        self.poll_interval_s = max(1.0, float(poll_interval_s or 5.0))
        self.log = log or (lambda _msg: None)
        self.session = requests.Session()

    @classmethod
    def from_config(cls, cfg: dict, *, log: Callable[[str], None] | None = None) -> "SMSBowerClient":
        cfg = cfg or {}
        return cls(
            api_key=_text(cfg.get("api_key")),
            api_url=_text(cfg.get("api_url") or cfg.get("base_url") or DEFAULT_API_URL),
            service=_text(cfg.get("service") or "dr"),
            country=_text(cfg.get("country") or "0"),
            operator=_text(cfg.get("operator")),
            max_price=_text(cfg.get("max_price") or cfg.get("maxPrice")),
            timeout_s=_int(cfg.get("timeout_s") or cfg.get("timeout"), 180),
            poll_interval_s=_float(cfg.get("poll_interval_s") or cfg.get("interval"), 5.0),
            log=log,
        )

    def _request(self, action: str, **params: Any) -> str:
        payload = {
            "api_key": self.api_key,
            "action": action,
            **{k: v for k, v in params.items() if v not in (None, "")},
        }
        try:
            resp = self.session.get(self.api_url, params=payload, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            raise SMSBowerError(f"{action} transport failed: {exc}") from exc
        return resp.text.strip()

    def get_number(self) -> SMSActivation:
        params: dict[str, Any] = {
            "service": self.service,
            "country": self.country,
        }
        if self.operator and self.operator.lower() != "any":
            params["operator"] = self.operator
        if self.max_price:
            params["maxPrice"] = self.max_price
        raw = self._request("getNumber", **params)
        if raw.startswith("ACCESS_NUMBER:"):
            parts = raw.split(":")
            if len(parts) >= 3 and parts[1] and parts[2]:
                return SMSActivation(activation_id=parts[1], number=parts[2])
        raise SMSBowerError(f"getNumber failed: {raw}")

    def set_status(self, activation_id: str, status: int) -> str:
        return self._request("setStatus", id=activation_id, status=int(status))

    def get_status(self, activation_id: str) -> str:
        return self._request("getStatus", id=activation_id)

    def wait_code(self, activation_id: str) -> str:
        import re
        import time

        deadline = time.time() + self.timeout_s
        last_status = ""
        while time.time() < deadline:
            raw = self.get_status(activation_id)
            last_status = raw
            if raw.startswith("STATUS_OK:"):
                code = raw.split(":", 1)[1].strip()
                match = re.search(r"(?<!\d)(\d{4,8})(?!\d)", code)
                return match.group(1) if match else code
            if raw in {
                "STATUS_WAIT_CODE",
                "STATUS_WAIT_RETRY",
                "STATUS_WAIT_RESEND",
                "STATUS_WAITING",
            }:
                time.sleep(self.poll_interval_s)
                continue
            if raw.startswith("STATUS_"):
                raise SMSBowerError(f"activation ended: {raw}")
            raise SMSBowerError(f"getStatus failed: {raw}")
        raise SMSBowerError(f"SMS code timeout after {self.timeout_s}s; last_status={last_status}")
