from __future__ import annotations

import pytest

from sf_mcp.auth.keys import generate_key, hash_secret, is_key_id, parse_key, secret_matches


def test_generated_key_parses_back() -> None:
    key_id, secret, full = generate_key("dev")
    parsed = parse_key(full)
    assert parsed is not None
    assert (parsed.environment, parsed.key_id, parsed.secret) == ("dev", key_id, secret)
    assert is_key_id(key_id)


def test_secret_may_contain_the_separator_character() -> None:
    raw = "sfmcp_prod_0123456789ab_" + "a_b-" * 10 + "abc"
    parsed = parse_key(raw)
    assert parsed is not None
    assert parsed.secret == "a_b-" * 10 + "abc"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "Bearer sfmcp_dev_0123456789ab_" + "a" * 43,
        "sfmcp_qa_0123456789ab_" + "a" * 43,
        "sfmcp_dev_0123456789AB_" + "a" * 43,
        "sfmcp_dev_0123456789ab_" + "a" * 42,
        "sfmcp_dev_0123456789ab_" + "a" * 44,
        "other_dev_0123456789ab_" + "a" * 43,
        "sfmcp_dev_0123456789ab_" + "a" * 42 + "=",
    ],
)
def test_malformed_keys_do_not_parse(raw: str) -> None:
    assert parse_key(raw) is None


def test_hmac_verification() -> None:
    pepper = b"x" * 40
    stored = hash_secret(pepper, "secret-value")
    assert secret_matches(pepper, "secret-value", stored)
    assert not secret_matches(pepper, "secret-valuf", stored)
    assert not secret_matches(b"y" * 40, "secret-value", stored)


def test_two_generated_keys_differ() -> None:
    assert generate_key("dev")[2] != generate_key("dev")[2]
