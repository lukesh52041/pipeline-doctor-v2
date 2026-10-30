"""Remove secrets and personal data from a log before it is stored or sent to an AI model.

Redaction works line by line and never adds or removes lines, so line numbers in the
redacted log match the original.
"""
import re
from collections import Counter

_SIMPLE = [
    ("github_token", re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("bearer_token", re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._~+/=-]{16,}")),
]
_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Za-z0-9_.-]*(?:api[_-]?key|secret|token|passwd|password|pwd)[A-Za-z0-9_.-]*)"
    r"(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_KEY_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_KEY_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
_KEEP_IPS = {"127.0.0.1", "0.0.0.0"}


def redact(text: str) -> tuple[str, dict]:
    """Return (redacted_text, counts_by_type)."""
    counts: Counter = Counter()
    out: list[str] = []
    in_key = False
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if in_key:
            if _KEY_END.search(line):
                in_key = False
            out.append("[REDACTED:private_key]")
            continue
        if _KEY_BEGIN.search(line):
            counts["private_key"] += 1
            in_key = not _KEY_END.search(line)
            out.append("[REDACTED:private_key]")
            continue

        for name, pattern in _SIMPLE:
            line = pattern.sub(lambda m, n=name: _hit(counts, n), line)

        def assignment(m):
            if m.group(3).startswith("[REDACTED"):
                return m.group(0)
            counts["secret_assignment"] += 1
            return f"{m.group(1)}{m.group(2)}[REDACTED:secret_assignment]"

        line = _ASSIGNMENT.sub(assignment, line)
        line = _EMAIL.sub(lambda m: _hit(counts, "email"), line)

        def ip(m):
            value = m.group(0)
            if value in _KEEP_IPS or any(int(p) > 255 for p in value.split(".")):
                return value
            return _hit(counts, "ip_address")

        line = _IPV4.sub(ip, line)
        out.append(line)
    return "\n".join(out), dict(counts)


def _hit(counts: Counter, name: str) -> str:
    counts[name] += 1
    return f"[REDACTED:{name}]"
