"""Small SMSBower client for SMS-Activate compatible endpoints."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

import requests


DEFAULT_API_URL = "https://smsbower.online/stubs/handler_api.php"
DEFAULT_POOL_TTL_S = 25 * 60
DEFAULT_POOL_MAX_USES = 3
ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_POOL_PATH = ROOT_DIR / "output" / "sms_bower_pool.json"


class SMSBowerError(RuntimeError):
    pass


@dataclass(frozen=True)
class SMSActivation:
    activation_id: str
    number: str
    acquired_at: float = 0.0
    use_count: int = 0
    last_code: str = ""
    reused: bool = False

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


def _positive_int(value: Any, default: int, minimum: int = 1) -> int:
    parsed = _int(value, default)
    return max(minimum, parsed)


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
        pool_path: str = "",
        pool_ttl_s: int = DEFAULT_POOL_TTL_S,
        pool_max_uses: int = DEFAULT_POOL_MAX_USES,
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
        self.pool_owner = sha256(self.api_key.encode("utf-8")).hexdigest()[:16]
        self.timeout_s = max(30, int(timeout_s or 180))
        self.poll_interval_s = max(1.0, float(poll_interval_s or 5.0))
        self.pool_path = Path(
            pool_path
            or os.environ.get("SMS_BOWER_POOL_PATH", "")
            or DEFAULT_POOL_PATH
        )
        self.pool_ttl_s = _positive_int(pool_ttl_s, DEFAULT_POOL_TTL_S, 60)
        self.pool_max_uses = _positive_int(pool_max_uses, DEFAULT_POOL_MAX_USES, 1)
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
            pool_path=_text(cfg.get("pool_path")),
            pool_ttl_s=_int(
                cfg.get("pool_ttl_s")
                or cfg.get("reuse_window_s")
                or cfg.get("pool_ttl")
                or DEFAULT_POOL_TTL_S,
                DEFAULT_POOL_TTL_S,
            ),
            pool_max_uses=_int(
                cfg.get("pool_max_uses")
                or cfg.get("max_verifications_per_number")
                or cfg.get("max_uses")
                or DEFAULT_POOL_MAX_USES,
                DEFAULT_POOL_MAX_USES,
            ),
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

    @contextmanager
    def _pool_file_lock(self):
        self.pool_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.pool_path.with_suffix(self.pool_path.suffix + ".lock")
        with open(lock_path, "a+") as lock_fp:
            try:
                import fcntl

                fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX)
            except Exception:
                pass
            try:
                yield
            finally:
                try:
                    import fcntl

                    fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass

    def _read_pool_unlocked(self) -> dict[str, Any]:
        if not self.pool_path.exists():
            return {"version": 1, "records": []}
        try:
            data = json.loads(self.pool_path.read_text(encoding="utf-8"))
        except Exception:
            return {"version": 1, "records": []}
        if not isinstance(data, dict):
            return {"version": 1, "records": []}
        records = data.get("records")
        if not isinstance(records, list):
            data["records"] = []
        return data

    def _write_pool_unlocked(self, data: dict[str, Any]) -> None:
        data["version"] = 1
        data["updated_at"] = time.time()
        tmp_path = self.pool_path.with_suffix(self.pool_path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self.pool_path)

    def _record_to_activation(self, rec: dict[str, Any], *, reused: bool) -> SMSActivation:
        return SMSActivation(
            activation_id=_text(rec.get("activation_id")),
            number=_text(rec.get("number")),
            acquired_at=_float(rec.get("acquired_at"), 0.0),
            use_count=_int(rec.get("use_count"), 0),
            last_code=_text(rec.get("last_code")),
            reused=reused,
        )

    def get_number_from_pool(self) -> SMSActivation:
        """
        Return a reusable SMSBower activation.

        SMSBower activations can keep receiving SMS for a short window. We keep
        local records and never finish/cancel the remote activation; a record is
        reused until it receives pool_max_uses codes or exceeds pool_ttl_s.
        """
        now = time.time()
        lock_s = self.timeout_s + 120
        with self._pool_file_lock():
            data = self._read_pool_unlocked()
            records = data["records"]
            reusable: dict[str, Any] | None = None
            for rec in records:
                acquired_at = _float(rec.get("acquired_at"), 0.0)
                use_count = _int(rec.get("use_count"), 0)
                locked_until = _float(rec.get("locked_until"), 0.0)
                if now - acquired_at >= self.pool_ttl_s:
                    if rec.get("status") != "expired":
                        rec["status"] = "expired"
                    continue
                if use_count >= self.pool_max_uses:
                    if rec.get("status") != "exhausted":
                        rec["status"] = "exhausted"
                    continue
                if locked_until > now:
                    continue
                if _text(rec.get("pool_owner")) != self.pool_owner:
                    continue
                if _text(rec.get("service")) != self.service:
                    continue
                if _text(rec.get("country")) != self.country:
                    continue
                if _text(rec.get("activation_id")) and _text(rec.get("number")):
                    reusable = rec
                    break

            if reusable is None:
                activation = self.get_number()
                reusable = {
                    "activation_id": activation.activation_id,
                    "number": activation.number,
                    "acquired_at": now,
                    "use_count": 0,
                    "last_code": "",
                    "last_used_at": 0.0,
                    "locked_until": 0.0,
                    "status": "active",
                    "pool_owner": self.pool_owner,
                    "service": self.service,
                    "country": self.country,
                    "operator": self.operator,
                    "max_price": self.max_price,
                }
                records.insert(0, reusable)
                reused = False
            else:
                reused = True

            reusable["locked_until"] = now + lock_s
            reusable["status"] = "active"
            self._write_pool_unlocked(data)
            return self._record_to_activation(reusable, reused=reused)

    def prepare_for_sms(self, activation: SMSActivation) -> str:
        """
        Mark an activation as ready without finishing/canceling it.

        For reused numbers, ask the provider for the next SMS so wait_code can
        ignore the old code and wait for a fresh one.
        """
        if activation.use_count > 0 or activation.last_code:
            return self.set_status(activation.activation_id, 3)
        return self.set_status(activation.activation_id, 1)

    def mark_code_received(self, activation_id: str, code: str) -> None:
        now = time.time()
        with self._pool_file_lock():
            data = self._read_pool_unlocked()
            for rec in data["records"]:
                if _text(rec.get("activation_id")) != _text(activation_id):
                    continue
                use_count = _int(rec.get("use_count"), 0) + 1
                rec["use_count"] = use_count
                rec["last_code"] = _text(code)
                rec["last_used_at"] = now
                rec["locked_until"] = 0.0
                rec["status"] = "exhausted" if use_count >= self.pool_max_uses else "active"
                self._write_pool_unlocked(data)
                return

    def release_pool_lock(self, activation_id: str) -> None:
        with self._pool_file_lock():
            data = self._read_pool_unlocked()
            changed = False
            for rec in data["records"]:
                if _text(rec.get("activation_id")) != _text(activation_id):
                    continue
                rec["locked_until"] = 0.0
                changed = True
                break
            if changed:
                self._write_pool_unlocked(data)

    def set_status(self, activation_id: str, status: int) -> str:
        return self._request("setStatus", id=activation_id, status=int(status))

    def get_status(self, activation_id: str) -> str:
        return self._request("getStatus", id=activation_id)

    def wait_code(self, activation_id: str, *, previous_code: str = "") -> str:
        import re

        deadline = time.time() + self.timeout_s
        last_status = ""
        previous_code = _text(previous_code)
        while time.time() < deadline:
            raw = self.get_status(activation_id)
            last_status = raw
            if raw.startswith("STATUS_OK:"):
                code = raw.split(":", 1)[1].strip()
                match = re.search(r"(?<!\d)(\d{4,8})(?!\d)", code)
                parsed = match.group(1) if match else code
                if previous_code and parsed == previous_code:
                    time.sleep(self.poll_interval_s)
                    continue
                return parsed
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
