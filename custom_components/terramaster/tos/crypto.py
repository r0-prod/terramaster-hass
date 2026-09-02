"""Request-envelope crypto for the TOS 6 web API.

Reverse-engineered from the TOS 6 frontend bundle (``app.*.js``, webpack module
``d47c`` for the cipher and ``8237`` = js-md5 0.7.3 for the key hash).

The scheme is fully derivable by the client -- there is no key exchange. Every
TOS response, even an unauthenticated 403, carries the three inputs:

===================  ==========================================================
``X-Rsa-Token``      base64 of the RSA public key PEM (PKCS#1, 2048-bit)
``X-Csrf-Token``     set as a cookie, echoed back as a request header
``Date``             drives both the AES key salt and ``X-Security-Code``
===================  ==========================================================

The original JS, for reference::

    R = e => { let t = new Date(utcDate),
               a = t.getUTCHours(),
               i = 10 * ~~(t.getUTCMinutes() / 10);
               e = e.substring(0,a) + a + e.substring(a);
               return e.substring(0,i) + i + e.substring(i) }

    f.key = md5(R(publicKey))                  // 32-char hex, used as ASCII
    headers['X-Security-Code'] = btoa(utcDate)
    data = { enc: hex(iv[12] || ciphertext || tag[16]) }

Only requests that carry a body are encrypted; GETs go out in the clear and all
responses are plaintext JSON.
"""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import load_pem_public_key

IV_LEN = 12
TAG_LEN = 16


def parse_server_date(date_header: str) -> datetime:
    """Parse an HTTP ``Date`` header the way ``new Date(str)`` does."""
    return parsedate_to_datetime(date_header)


def _as_utc(when: datetime) -> datetime:
    """Mirror ``getUTCHours``/``getUTCMinutes``, which always convert first.

    ``parsedate_to_datetime`` yields an aware datetime, so reading ``.hour`` off
    it directly would use the sender's offset rather than UTC.
    """
    if when.tzinfo is None:
        return when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def salt(public_key_pem: str, server_date: str | datetime) -> str:
    """Reproduce the frontend's ``R()`` salt.

    The UTC hour is spliced into the PEM text at index ``hour``, then the
    10-minute bucket is spliced into the *result* at index ``bucket``. Both
    indices land inside the PEM header line, so the key body is untouched.
    """
    when = _as_utc(
        parse_server_date(server_date)
        if isinstance(server_date, str)
        else server_date
    )
    hour = when.hour
    bucket = 10 * (when.minute // 10)

    out = public_key_pem[:hour] + str(hour) + public_key_pem[hour:]
    return out[:bucket] + str(bucket) + out[bucket:]


def derive_key(public_key_pem: str, server_date: str | datetime) -> bytes:
    """AES-256 key: the lowercase hex MD5 digest taken as its 32 ASCII bytes.

    js-md5 returns a hex *string* and Node's ``createCipheriv`` then reads that
    string as UTF-8 -- which is why a 32-character digest is a valid 256-bit
    key. Encoding the digest instead of using ``.digest()`` is deliberate.
    """
    return hashlib.md5(salt(public_key_pem, server_date).encode()).hexdigest().encode()


def encrypt_body(plaintext: str, key: bytes) -> str:
    """AES-256-GCM, serialised as hex of ``iv || ciphertext || tag``."""
    iv = os.urandom(IV_LEN)
    sealed = AESGCM(key).encrypt(iv, plaintext.encode(), None)
    return (iv + sealed).hex()


def decrypt_body(payload: str, key: bytes) -> str:
    """Inverse of :func:`encrypt_body` (used by the tests, not by the client)."""
    raw = bytes.fromhex(payload)
    return AESGCM(key).decrypt(raw[:IV_LEN], raw[IV_LEN:], None).decode()


def security_code(date_header: str) -> str:
    """``X-Security-Code``: base64 of the raw ``Date`` header string."""
    return base64.b64encode(date_header.encode()).decode()


def load_public_key(pem: str) -> rsa.RSAPublicKey:
    """Load the PKCS#1 ``BEGIN RSA PUBLIC KEY`` PEM that TOS serves."""
    return load_pem_public_key(pem.encode())


def rsa_encrypt(public_key_pem: str, text: str) -> str:
    """Match ``JSEncrypt.encryptLong`` for inputs below one block.

    ``encryptLong`` chunks only when the input exceeds ``keybytes - 11`` (245
    bytes for this 2048-bit key), so a password is a single PKCS#1 v1.5 block.
    jsencrypt emits hex and the caller runs it through ``hex2b64``, so the wire
    format is base64.
    """
    key = load_public_key(public_key_pem)
    block = (key.key_size + 7) // 8 - 11
    data = text.encode()
    if len(data) > block:
        raise ValueError(
            f"{len(data)} bytes exceeds the single-block limit of {block}; "
            "chunked encryptLong is not implemented"
        )
    return base64.b64encode(key.encrypt(data, padding.PKCS1v15())).decode()
