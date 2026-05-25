import base64
import json

import pipeline.sub2api as sub2api


def _jwt(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{body}.sig"


def test_sub2api_upload_refreshes_token_and_posts_contents(monkeypatch):
    access_token = _jwt({
        "email": "user@example.com",
        "exp": 2534094400,
        "https://api.openai.com/auth": {"chatgpt_account_id": "acct_123"},
    })
    id_token = _jwt({"email": "user@example.com"})
    captured = {}

    def fake_exchange(refresh_token, client_id, timeout):
        assert refresh_token == "r" * 40
        assert client_id == "app_test"
        return {
            "access_token": access_token,
            "id_token": id_token,
            "refresh_token": "n" * 40,
        }

    def fake_post(url, headers, body, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(body.decode())
        return {"ok": True}

    monkeypatch.setattr(sub2api, "_exchange_refresh_token", fake_exchange)
    monkeypatch.setattr(sub2api, "_post_json", fake_post)

    accounts = [{"id": 7, "email": "user@example.com", "refresh_token": "r" * 40}]
    result = sub2api.upload_accounts(accounts, {
        "enabled": True,
        "base_url": "https://sub2api.example.com",
        "admin_api_key": "secret",
        "oauth_client_id": "app_test",
        "group_ids": "1,2",
        "concurrency": "3",
        "priority": "9",
    })

    assert result["summary"]["accepted"] == 1
    assert captured["url"] == "https://sub2api.example.com/api/v1/admin/accounts/import/codex-session"
    assert captured["headers"]["x-api-key"] == "secret"
    assert captured["body"]["group_ids"] == [1, 2]
    assert captured["body"]["concurrency"] == 3
    assert captured["body"]["priority"] == 9
    row = json.loads(captured["body"]["contents"][0])
    assert row["email"] == "user@example.com"
    assert row["access_token"] == access_token
    assert row["id_token"] == id_token
    assert row["refresh_token"] == "n" * 40
    assert row["account_id"] == "acct_123"
    assert accounts[0]["_sub2api_token_update"]["refresh_token"] == "n" * 40


def test_sub2api_upload_reports_refresh_failure(monkeypatch):
    def fake_exchange(*args, **kwargs):
        raise sub2api.UploadError("bad rt")

    monkeypatch.setattr(sub2api, "_exchange_refresh_token", fake_exchange)

    result = sub2api.upload_accounts([{
        "id": 1,
        "email": "user@example.com",
        "refresh_token": "r" * 40,
    }], {
        "enabled": True,
        "base_url": "https://sub2api.example.com",
        "admin_api_key": "secret",
    })

    assert result["summary"]["fail_refresh"] == 1
    assert result["results"][0]["status"] == "fail_refresh"
