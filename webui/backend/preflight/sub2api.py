import httpx
from pydantic import BaseModel

from ._common import CheckResult, PreflightResult, aggregate


class Sub2ApiInput(BaseModel):
    base_url: str
    admin_api_key: str


def _accounts_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/api"):
        return f"{base}/v1/admin/accounts"
    return f"{base}/api/v1/admin/accounts"


def _headers(admin_api_key: str) -> dict[str, str]:
    token = admin_api_key.strip()
    bearer = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    raw_token = token.split(None, 1)[1].strip() if token.lower().startswith("bearer ") else token
    return {
        "Authorization": bearer,
        "x-api-key": raw_token,
        "X-API-Key": raw_token,
        "Accept": "application/json",
    }


def check(body: dict) -> PreflightResult:
    cfg = Sub2ApiInput.model_validate(body)
    try:
        with httpx.Client(timeout=15.0) as c:
            r = c.get(_accounts_url(cfg.base_url), headers=_headers(cfg.admin_api_key))
    except httpx.HTTPError as e:
        return aggregate([CheckResult(name="admin_accounts", status="fail", message=str(e))])

    if r.status_code == 200:
        try:
            data = r.json()
            if isinstance(data, dict):
                n = data.get("total") or data.get("count") or len(data.get("items") or data.get("data") or [])
            elif isinstance(data, list):
                n = len(data)
            else:
                n = "?"
        except Exception:
            n = "?"
        return aggregate([CheckResult(
            name="admin_accounts",
            status="ok",
            message=f"sub2api admin reachable ({n} accounts)",
        )])
    if r.status_code in (401, 403):
        return aggregate([CheckResult(
            name="admin_accounts",
            status="fail",
            message=f"HTTP {r.status_code} - admin_api_key 无效或被拒",
            details=r.text[:500],
        )])
    if r.status_code in (404, 405):
        return aggregate([CheckResult(
            name="admin_accounts",
            status="warn",
            message=f"HTTP {r.status_code} - 服务可达，但账号列表预检端点不可用",
            details=r.text[:500],
        )])
    return aggregate([CheckResult(
        name="admin_accounts",
        status="fail",
        message=f"HTTP {r.status_code}",
        details=r.text[:1000],
    )])
