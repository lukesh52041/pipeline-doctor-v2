from app.redact import redact
from app.samples import FAKE_AWS_KEY, FAKE_GH_TOKEN


def test_redacts_tokens_keys_emails_ips():
    text = f"token {FAKE_GH_TOKEN}\naws {FAKE_AWS_KEY}\nmail a.b@example.com\nhost 10.1.2.3"
    out, counts = redact(text)
    assert FAKE_GH_TOKEN not in out and FAKE_AWS_KEY not in out
    assert "a.b@example.com" not in out and "10.1.2.3" not in out
    assert counts["github_token"] == 1 and counts["email"] == 1 and counts["ip_address"] == 1


def test_secret_assignment_keeps_name():
    out, counts = redact("DB_PASSWORD=hunter2")
    assert out == "DB_PASSWORD=[REDACTED:secret_assignment]"
    assert counts["secret_assignment"] == 1


def test_line_count_is_preserved_with_private_key_block():
    text = "a\n-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----\nb"
    out, _ = redact(text)
    assert len(out.split("\n")) == len(text.split("\n"))
    assert "MIIabc" not in out


def test_loopback_and_bad_octets_are_kept():
    out, counts = redact("127.0.0.1 and 999.1.1.1")
    assert out == "127.0.0.1 and 999.1.1.1" and not counts
