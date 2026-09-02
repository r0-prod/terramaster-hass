"""Tests for the TOS client's error handling.

TOS reports most failures as HTTP 200 with `code: false` in the body, so these
paths cannot be inferred from status codes and are easy to get wrong.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "terramaster"))

from tos.client import TosClient, TosError, TosPermissionError  # noqa: E402


def ok(data=None):
    return {"is_login": True, "code": True, "msg": "", "data": data, "code_num": 0}


def failure(code_num, msg="nope"):
    return {"is_login": False, "code": False, "msg": msg, "data": None,
            "code_num": code_num, "code_msg": msg}


@pytest.mark.parametrize("code_num", [14, 27, 28, 41, 97, 117])
def test_session_loss_codes_trigger_reauth(code_num):
    """117 and 41 in particular: TOS returns HTTP 200 with these once a CSRF
    token is present, so a status-only check would miss them entirely."""
    assert TosClient._needs_reauth(200, failure(code_num)) is True


def test_bare_403_triggers_reauth():
    assert TosClient._needs_reauth(403, {}) is True


def test_success_does_not_trigger_reauth():
    assert TosClient._needs_reauth(200, ok({"fan": {}})) is False


def test_permission_denied_is_not_a_session_problem():
    """Re-logging in as the same user cannot fix a rights problem."""
    assert TosClient._needs_reauth(200, failure(90)) is False


def test_permission_denied_raises_its_own_error():
    with pytest.raises(TosPermissionError, match="no rights"):
        TosClient._raise_for_envelope("/v2/hardware/set", failure(90, "no rights"))


def test_other_failures_raise_toserror_with_the_code():
    with pytest.raises(TosError, match="code_num=55"):
        TosClient._raise_for_envelope("/v2/whatever", failure(55, "broke"))


def test_successful_envelope_passes_through():
    TosClient._raise_for_envelope("/v2/hardware/", ok({"fan": {"level": 4}}))


def test_write_returning_null_data_is_still_success():
    """/v2/hardware/set answers code:true with data:null -- not an error."""
    TosClient._raise_for_envelope("/v2/hardware/set", ok(None))
