"""HSTS and the Content-Security-Policy (security check of 23 Nov 2026). No network."""

import base64
import hashlib
import re

from backend.access import (FRONTEND, SCRIPT_PAGES, SECURITY_HEADERS, content_security_policy,
                            inline_script_hashes)


def _sha(body: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode() + "'"


def test_browsers_are_told_to_use_https_only():
    assert SECURITY_HEADERS["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


def test_every_inline_script_compass_ships_is_allowed_and_nothing_else():
    csp = SECURITY_HEADERS["Content-Security-Policy"]
    script_src = next(part for part in csp.split("; ") if part.startswith("script-src "))
    expected = []
    for page in SCRIPT_PAGES:
        text = (FRONTEND / page).read_text(encoding="utf-8")
        expected += [_sha(b) for b in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", text, re.S | re.I)]
    assert expected and all(h in script_src for h in expected)
    assert "'unsafe-inline'" not in script_src and "'unsafe-eval'" not in script_src
    assert script_src.split()[1:3] == ["'self'", "https://esm.sh"]


def test_the_policy_closes_the_usual_doors():
    csp = content_security_policy([])
    for rule in ("default-src 'self'", "object-src 'none'", "base-uri 'self'", "form-action 'self'",
                 "frame-ancestors 'self'", "img-src 'self' data:"):
        assert rule in csp


def test_a_changed_script_changes_its_hash(tmp_path):
    (tmp_path / "index.html").write_text('<script type="importmap">{"a":1}</script><script src="/x.js"></script>'
                                         "<script>let x = 1;</script>", encoding="utf-8")
    hashes = inline_script_hashes(("index.html", "missing.html"), tmp_path)
    assert hashes == [_sha('{"a":1}'), _sha("let x = 1;")]     # external and missing files skipped
