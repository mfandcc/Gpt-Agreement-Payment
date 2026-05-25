import json

from core.sms_bower import SMSBowerClient


class FakeSMSBowerClient(SMSBowerClient):
    def __init__(self, **kwargs):
        super().__init__(
            api_key="test-key",
            api_url="https://example.invalid/smsbower",
            timeout_s=1,
            poll_interval_s=1,
            **kwargs,
        )
        self.next_id = 1
        self.status_calls = []
        self.status_queue = []

    def _request(self, action: str, **params):
        if action == "getNumber":
            activation_id = str(self.next_id)
            self.next_id += 1
            return f"ACCESS_NUMBER:{activation_id}:1555000{activation_id}"
        if action == "setStatus":
            self.status_calls.append((params["id"], params["status"]))
            return "ACCESS_READY"
        if action == "getStatus":
            if self.status_queue:
                return self.status_queue.pop(0)
            return "STATUS_WAIT_CODE"
        raise AssertionError(action)


def test_sms_bower_pool_reuses_number_until_max_uses(tmp_path):
    client = FakeSMSBowerClient(pool_path=str(tmp_path / "pool.json"), pool_max_uses=3)

    first = client.get_number_from_pool()
    assert first.activation_id == "1"
    assert first.reused is False

    client.release_pool_lock(first.activation_id)
    second = client.get_number_from_pool()
    assert second.activation_id == "1"
    assert second.reused is True

    client.mark_code_received(second.activation_id, "111111")
    third = client.get_number_from_pool()
    assert third.activation_id == "1"
    assert third.use_count == 1

    client.mark_code_received(third.activation_id, "222222")
    fourth = client.get_number_from_pool()
    assert fourth.activation_id == "1"
    client.mark_code_received(fourth.activation_id, "333333")

    fifth = client.get_number_from_pool()
    assert fifth.activation_id == "2"

    data = json.loads((tmp_path / "pool.json").read_text())
    old_record = next(r for r in data["records"] if r["activation_id"] == "1")
    assert old_record["use_count"] == 3
    assert old_record["status"] == "exhausted"


def test_prepare_for_sms_requests_next_code_for_reused_number(tmp_path):
    client = FakeSMSBowerClient(pool_path=str(tmp_path / "pool.json"))

    activation = client.get_number_from_pool()
    assert client.prepare_for_sms(activation) == "ACCESS_READY"
    assert client.status_calls[-1] == ("1", 1)
    client.mark_code_received(activation.activation_id, "123456")

    reused = client.get_number_from_pool()
    assert client.prepare_for_sms(reused) == "ACCESS_READY"
    assert client.status_calls[-1] == ("1", 3)


def test_wait_code_ignores_previous_code(tmp_path):
    client = FakeSMSBowerClient(pool_path=str(tmp_path / "pool.json"))
    client.status_queue = ["STATUS_OK:123456", "STATUS_OK:654321"]

    code = client.wait_code("1", previous_code="123456")

    assert code == "654321"
