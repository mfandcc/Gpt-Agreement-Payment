"""Upload Codex sessions to sub2api.

sub2api imports Codex sessions through:
  POST /api/v1/admin/accounts/import/codex-session

The endpoint needs a fresh access_token.  When a refresh_token is available,
this module refreshes the Codex token set first and uploads the new
access_token/id_token/refresh_token tuple.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any


DEFAULT_CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0 Safari/537.36"
)


class UploadError(RuntimeError):
    pass


def admin_import_url(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if base.endswith("/api"):
        return f"{base}/v1/admin/accounts/import/codex-session"
    return f"{base}/api/v1/admin/accounts/import/codex-session"


def admin_accounts_url(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if base.endswith("/api"):
        return f"{base}/v1/admin/accounts"
    return f"{base}/api/v1/admin/accounts"


def auth_headers(admin_api_key: str) -> dict[str, str]:
    token = (admin_api_key or "").strip()
    bearer = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    raw_token = token.split(None, 1)[1].strip() if token.lower().startswith("bearer ") else token
    return {
        "Authorization": bearer,
        "x-api-key": raw_token,
        "X-API-Key": raw_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def _jwt_payload(token: str) -> dict:
    if not token or "." not in token:
        return {}
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload).decode())
    except Exception:
        return {}


def _chatgpt_account_id(access_token: str) -> str:
    payload = _jwt_payload(access_token)
    auth = payload.get("https://api.openai.com/auth") or {}
    return str(auth.get("chatgpt_account_id") or "")


def _token_email(access_token: str) -> str:
    payload = _jwt_payload(access_token)
    value = payload.get("email") or payload.get("https://api.openai.com/email")
    return str(value or "").strip().lower()


def _token_expired_iso(access_token: str) -> str:
    payload = _jwt_payload(access_token)
    exp = payload.get("exp")
    if not exp:
        return ""
    try:
        return datetime.fromtimestamp(int(exp), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def _exchange_refresh_token(refresh_token: str, client_id: str, timeout: int) -> dict:
    import urllib.error
    import urllib.parse
    import urllib.request

    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id or DEFAULT_CODEX_CLIENT_ID,
        "scope": "openid email profile offline_access",
    }).encode()
    req = urllib.request.Request(
        "https://auth.openai.com/oauth/token",
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()[:300]
        except Exception:
            body = ""
        raise UploadError(f"refresh_token exchange failed http={e.code} body={body}") from e
    except Exception as e:
        raise UploadError(f"refresh_token exchange failed: {type(e).__name__}: {e}") from e


def _required_fields_reason(row: dict) -> str:
    for key in ("email", "refresh_token", "access_token", "id_token"):
        value = row.get(key)
        if not isinstance(value, str) or not value.strip():
            return f"missing_field:{key}"
    if "@" not in row["email"]:
        return "email_invalid"
    if len(row["refresh_token"]) < 30:
        return f"rt_too_short(len={len(row['refresh_token'])})"
    if row["access_token"].count(".") < 2:
        return "access_token_not_jwt"
    if row["id_token"].count(".") < 2:
        return "id_token_not_jwt"
    return ""


def build_payload_row(account: dict) -> dict | None:
    email = str(account.get("email") or "").strip().lower()
    refresh_token = str(account.get("refresh_token") or "").strip()
    access_token = str(account.get("access_token") or "").strip()
    id_token = str(account.get("id_token") or "").strip() or access_token
    if not (email and refresh_token and access_token and id_token):
        return None
    return {
        "type": "codex",
        "email": email,
        "refresh_token": refresh_token,
        "access_token": access_token,
        "id_token": id_token,
        "account_id": _chatgpt_account_id(access_token),
        "last_refresh": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expired": _token_expired_iso(access_token),
    }


def _prepare_payload_row(account: dict, cfg: dict) -> tuple[dict | None, str]:
    refresh_token = str(account.get("refresh_token") or "").strip()
    client_id = str(cfg.get("oauth_client_id") or DEFAULT_CODEX_CLIENT_ID).strip()
    timeout = int(cfg.get("token_timeout_s") or cfg.get("timeout_s") or 30)

    if refresh_token and cfg.get("refresh_tokens", True) is not False:
        try:
            token_data = _exchange_refresh_token(refresh_token, client_id, timeout)
        except UploadError as e:
            if not cfg.get("allow_stale_access_token", False):
                return None, f"fail_refresh:{str(e)[:240]}"
        else:
            access_token = str(token_data.get("access_token") or "").strip()
            if not access_token:
                return None, "fail_refresh:no_access_token"
            id_token = str(token_data.get("id_token") or "").strip() or access_token
            new_refresh_token = str(token_data.get("refresh_token") or "").strip() or refresh_token
            token_email = _token_email(access_token)
            email = str(account.get("email") or "").strip().lower()
            if token_email and email and token_email != email:
                return None, f"fail_refresh:email_mismatch:{token_email}"
            account["access_token"] = access_token
            account["id_token"] = id_token
            account["refresh_token"] = new_refresh_token
            account["_sub2api_token_update"] = {
                "access_token": access_token,
                "id_token": id_token,
                "refresh_token": new_refresh_token,
            }

    row = build_payload_row(account)
    if not row:
        return None, "missing_field:email/refresh_token/access_token/id_token"
    reason = _required_fields_reason(row)
    if reason:
        return None, reason
    return row, ""


def _parse_group_ids(value: Any) -> list[int]:
    if value in (None, "", []):
        return []
    raw_items = value if isinstance(value, list) else str(value).replace(";", ",").split(",")
    out: list[int] = []
    for item in raw_items:
        text = str(item).strip()
        if not text:
            continue
        try:
            out.append(int(text))
        except ValueError:
            continue
    return out


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _import_body(contents: list[str], cfg: dict, *, force_content: bool = False) -> dict:
    body: dict[str, Any] = {}
    if force_content:
        body["content"] = contents[0]
    else:
        body["contents"] = contents

    group_ids = _parse_group_ids(cfg.get("group_ids"))
    if group_ids:
        body["group_ids"] = group_ids

    for key in ("concurrency", "priority"):
        if cfg.get(key) not in (None, ""):
            try:
                body[key] = int(cfg.get(key))
            except (TypeError, ValueError):
                pass

    if "update_existing" in cfg:
        body["update_existing"] = _as_bool(cfg.get("update_existing"))
    else:
        body["update_existing"] = True

    return body


def _post_json(url: str, headers: dict, body: bytes, timeout: int) -> dict:
    import urllib.error
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with opener.open(req, timeout=timeout) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode()[:300]
        except Exception:
            err_body = ""
        raise UploadError(f"http={e.code} body={err_body}") from e
    except Exception as e:
        raise UploadError(f"transport={type(e).__name__}: {e}") from e

    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        raise UploadError(f"non-json response: {raw[:200]}") from e


def _response_ok(data: dict) -> bool:
    if data.get("ok") is False or data.get("success") is False:
        return False
    if any(data.get(k) for k in ("error", "errors")) and not (data.get("ok") or data.get("success")):
        return False
    return True


def _result_status(item: dict) -> tuple[bool, str]:
    status = str(item.get("status") or item.get("state") or "").strip().lower()
    if item.get("ok") is True or item.get("success") is True or item.get("accepted") is True:
        return True, ""
    if item.get("created") is True or item.get("updated") is True or item.get("imported") is True:
        return True, ""
    if status in {"ok", "success", "succeeded", "accepted", "imported", "created", "updated"}:
        return True, ""
    reason = str(item.get("reason") or item.get("error") or item.get("message") or status or "rejected")
    return False, reason[:300]


def _apply_response(chunk: list[tuple[dict, dict]], data: dict, out_results: list[dict],
                    summary: dict) -> None:
    response_results = data.get("results")
    if response_results is None:
        response_results = data.get("accounts") or data.get("items") or data.get("details")
    by_email: dict[str, dict] = {}
    if isinstance(response_results, list):
        for item in response_results:
            if not isinstance(item, dict):
                continue
            email = str(item.get("email") or item.get("account") or "").strip().lower()
            if email:
                by_email[email] = item

    batch_ok = _response_ok(data)
    batch_reason = str(data.get("error") or data.get("message") or data.get("detail") or "rejected")[:300]
    for source, row in chunk:
        item = by_email.get(row["email"])
        if item is None:
            accepted, reason = (batch_ok, "" if batch_ok else batch_reason)
        else:
            accepted, reason = _result_status(item)
        if accepted:
            out_results.append({"id": source.get("id"), "email": row["email"], "status": "ok"})
            summary["accepted"] += 1
        else:
            out_results.append({
                "id": source.get("id"),
                "email": row["email"],
                "status": "rejected",
                "reason": reason,
            })
            summary["rejected"] += 1


def upload_accounts(accounts: list[dict], cfg: dict) -> dict:
    out_results: list[dict] = []
    summary = {
        "total": len(accounts),
        "accepted": 0,
        "rejected": 0,
        "missing_field": 0,
        "fail_refresh": 0,
        "api_error": 0,
    }
    api_errors: list[str] = []

    if not cfg or not cfg.get("enabled"):
        return {"ok": False, "results": [], "summary": summary,
                "batches": 0, "api_errors": ["sub2api not enabled"]}

    base_url = str(cfg.get("base_url") or "").rstrip("/")
    admin_api_key = str(cfg.get("admin_api_key") or cfg.get("api_key") or "").strip()
    if not base_url or not admin_api_key:
        return {"ok": False, "results": [], "summary": summary,
                "batches": 0, "api_errors": ["sub2api base_url/admin_api_key required"]}

    valid_rows: list[tuple[dict, dict]] = []
    for account in accounts:
        row, reason = _prepare_payload_row(account, cfg)
        if not row:
            status_key = "fail_refresh" if reason.startswith("fail_refresh") else "missing_field"
            out_results.append({
                "id": account.get("id"),
                "email": account.get("email", ""),
                "status": status_key,
                "reason": reason,
            })
            summary[status_key] += 1
            continue
        valid_rows.append((account, row))

    if not valid_rows:
        return {"ok": True, "results": out_results, "summary": summary,
                "batches": 0, "api_errors": []}

    timeout = int(cfg.get("timeout_s") or 30)
    batch_size = int(cfg.get("batch_size") or 100)
    if batch_size <= 0 or batch_size > 1000:
        batch_size = 100

    url = admin_import_url(base_url)
    headers = auth_headers(admin_api_key)
    batches = 0
    payload_key = str(cfg.get("payload_key") or "contents").strip().lower()
    fallback_content = cfg.get("fallback_content", True) is not False

    for start in range(0, len(valid_rows), batch_size):
        chunk = valid_rows[start:start + batch_size]
        contents = [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for _, row in chunk]
        if payload_key == "content":
            for item in chunk:
                body = _import_body([json.dumps(item[1], ensure_ascii=False, separators=(",", ":"))], cfg,
                                    force_content=True)
                batches += 1
                try:
                    data = _post_json(url, headers, json.dumps(body).encode(), timeout)
                    _apply_response([item], data, out_results, summary)
                except UploadError as e:
                    api_errors.append(str(e))
                    out_results.append({
                        "id": item[0].get("id"),
                        "email": item[1]["email"],
                        "status": "api_error",
                        "reason": str(e),
                    })
                    summary["api_error"] += 1
            continue

        body = _import_body(contents, cfg)
        batches += 1
        try:
            data = _post_json(url, headers, json.dumps(body).encode(), timeout)
            _apply_response(chunk, data, out_results, summary)
        except UploadError as e:
            if fallback_content:
                recovered = True
                for item in chunk:
                    single_body = _import_body(
                        [json.dumps(item[1], ensure_ascii=False, separators=(",", ":"))],
                        cfg,
                        force_content=True,
                    )
                    batches += 1
                    try:
                        data = _post_json(url, headers, json.dumps(single_body).encode(), timeout)
                        _apply_response([item], data, out_results, summary)
                    except UploadError as single_e:
                        recovered = False
                        out_results.append({
                            "id": item[0].get("id"),
                            "email": item[1]["email"],
                            "status": "api_error",
                            "reason": str(single_e),
                        })
                        summary["api_error"] += 1
                if recovered:
                    continue
            api_errors.append(str(e))
            if not fallback_content:
                for source, row in chunk:
                    out_results.append({
                        "id": source.get("id"),
                        "email": row["email"],
                        "status": "api_error",
                        "reason": str(e),
                    })
                    summary["api_error"] += 1

    return {
        "ok": summary["api_error"] == 0 and summary["fail_refresh"] == 0,
        "results": out_results,
        "summary": summary,
        "batches": batches,
        "api_errors": api_errors,
    }
