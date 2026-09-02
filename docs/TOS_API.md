# The TOS 6 API

TOS has no public API. These notes come from reverse-engineering the TOS 6
frontend bundle and are the part most likely to break on a firmware update.
Re-run `tools/probe_tos.py` after any TOS upgrade to check for drift.

## Transport

nginx → a Go backend. Every path is prefixed `/v2` (the frontend's axios
interceptor prepends it automatically). Responses are **plaintext JSON** wrapped
as `{is_login, code, msg, data, code_num}`; `code: true` means success.

## Authentication and the request envelope

Every response — including unauthenticated `403`s and `404`s — hands out all the
crypto material needed:

| Header / cookie | Meaning |
|---|---|
| `X-Rsa-Token` | base64 of the RSA public key PEM (PKCS#1, 2048-bit) |
| `X-Csrf-Token` | set as a cookie; must be echoed as a header on **every** request, GETs included |
| `Date` | drives both the AES key salt and `X-Security-Code` |

There is no key exchange — the AES key is *derived*:

```
hour   = UTC hour of the server Date header      # 0..23
bucket = 10 * (UTC minute // 10)                 # 0,10,...,50
s   = pem[:hour]   + str(hour)   + pem[hour:]    # splice, then splice again
s   = s[:bucket]   + str(bucket) + s[bucket:]
key = md5(s).hexdigest().encode()                # 32 hex chars used as ASCII bytes
```

The last step looks odd but is faithful to the frontend: it uses
[js-md5](https://github.com/emn178/js-md5), which returns a hex *string*, and
Node's `createCipheriv` then reads that string as UTF-8 — which is exactly why a
32-character digest is a valid 256-bit key.

Only requests **with a body** are encrypted:

```
X-Security-Code: base64(<the same Date header string>)
body:            {"enc": hex( iv[12] || aes-256-gcm(ciphertext) || tag[16] )}
```

The salt and `X-Security-Code` must derive from the *same* `Date` string, or the
server cannot reconstruct the key.

`POST /v2/login` takes `{username, password}` where the password is separately
RSA-encrypted (PKCS#1 v1.5, base64) under the `X-Rsa-Token` key — matching
`JSEncrypt.encryptLong`, which only chunks above `keybytes - 11` (245 bytes).

## Endpoints used

| Purpose | Endpoint |
|---|---|
| Auth | `POST /v2/login`, `GET /v2/login/state` |
| Fan + buzzer + standby | `GET /v2/hardware/`, `POST /v2/hardware/set` |
| CPU / system temp, fan RPM | `GET /v2/resource/temperature` |
| Per-drive temp, hours, status | `GET /v2/disk/GetDiskStatus` |
| Drive models | `GET /v2/disk/GetDiskListData` |
| Bay layout, model, capacities | `GET /v2/disk/GetOverview` |
| Volumes / pools | `GET /v2/storage/list/volume`, `GET /v2/storage/list/pool` |
| CPU model | `GET /v2/systemStatus/NasProcessorInfo` |

`POST /v2/hardware/set` expects the **whole** hardware object back, not a delta —
so writes are read-modify-write.

## Result codes

Failures come back as **HTTP 200** with `code: false`, so the status code alone is
not enough. Once a CSRF token is being sent, TOS stops answering `403` altogether.

| `code_num` | Meaning |
|---|---|
| `0` | success (`code: true`) |
| `14`, `27`, `28`, `41`, `97` | session invalid / logged out |
| `117` | `please login` — what an expired session returns |
| `90` | insufficient privileges; the account is valid but lacks rights |

`90` must not be treated as a session problem: re-authenticating as the same user
cannot fix it. A non-administrator account reads every endpoint here but gets `90`
from `POST /v2/hardware/set`.

Gotchas worth knowing:

- `GET /v2/disk/IhmInfoList` only covers Seagate IronWolf drives, so it is not a
  usable health source for a mixed array. `GetDiskStatus.status` (`0` = healthy)
  covers every bay.
- `/v2/resource/temperature` reports `disk_temperature` for only **one** drive.
  Per-drive temperatures come from `GetDiskStatus`.
- Names come back as i18n placeholders like `${global,storagepool}1`; the client
  renders them to English.
- Cookies are set by a bare IP address, so the client needs
  `aiohttp.CookieJar(unsafe=True)` — the default jar silently drops them.
- You write `{is_auto: true, level: -1}` to select automatic mode, but reads then
  report the level the firmware is *currently driving* (e.g. `{is_auto: true,
  level: 4}`), not `-1`. Always trust `is_auto` before `level`.
