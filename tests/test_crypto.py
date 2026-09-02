"""Tests for the TOS request-envelope crypto."""

import base64
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "terramaster"))

from tos import crypto  # noqa: E402

# 2026-09-02 19:14:11 UTC -> hour 19, ten-minute bucket 10
DATE = "Wed, 02 Sep 2026 19:14:11 GMT"
PEM = "-----BEGIN RSA PUBLIC KEY-----\nAAAA\n-----END RSA PUBLIC KEY-----\n"


def test_salt_matches_javascript_splice_order():
    """R() inserts the hour at index=hour, then the bucket at index=bucket."""
    # "-----BEGIN RSA PUBL" + "19" + "IC KEY-----..." then "-----BEGIN" + "10" + rest
    expected = "-----BEGIN10 RSA PUBL19IC KEY-----\nAAAA\n-----END RSA PUBLIC KEY-----\n"
    assert crypto.salt(PEM, DATE) == expected


def test_salt_normalises_offset_dates_to_utc():
    """21:14 +0200 is the same instant as 19:14 GMT and must salt identically."""
    assert crypto.salt(PEM, "Wed, 02 Sep 2026 21:14:11 +0200") == crypto.salt(PEM, DATE)


def test_salt_at_midnight_splices_twice_at_index_zero():
    assert crypto.salt(PEM, "Wed, 02 Sep 2026 00:05:00 GMT") == "00" + PEM


def _reference_salt(text: str, hour: int, bucket: int) -> str:
    """Straight transcription of the JS, used to check the real implementation."""
    out = text[:hour] + str(hour) + text[hour:]
    return out[:bucket] + str(bucket) + out[bucket:]


@pytest.mark.parametrize("minute,bucket", [(0, 0), (9, 0), (10, 10), (37, 30), (59, 50)])
def test_minute_buckets_round_down_to_ten(minute, bucket):
    date = f"Wed, 02 Sep 2026 05:{minute:02d}:00 GMT"
    assert crypto.salt(PEM, date) == _reference_salt(PEM, 5, bucket)


def test_derive_key_is_hex_digest_as_ascii():
    """js-md5 returns a hex string that Node reads as UTF-8 -- 32 ASCII bytes."""
    key = crypto.derive_key(PEM, DATE)
    assert len(key) == 32
    assert key == hashlib.md5(crypto.salt(PEM, DATE).encode()).hexdigest().encode()


def test_encrypt_body_layout_and_roundtrip():
    key = crypto.derive_key(PEM, DATE)
    blob = crypto.encrypt_body('{"a":1}', key)
    raw = bytes.fromhex(blob)
    # iv(12) || ciphertext || tag(16)
    assert len(raw) == crypto.IV_LEN + len('{"a":1}') + crypto.TAG_LEN
    assert crypto.decrypt_body(blob, key) == '{"a":1}'


def test_encrypt_body_uses_a_fresh_iv():
    key = crypto.derive_key(PEM, DATE)
    assert crypto.encrypt_body("x", key) != crypto.encrypt_body("x", key)


def test_security_code_is_base64_of_the_date_header():
    assert base64.b64decode(crypto.security_code(DATE)).decode() == DATE
