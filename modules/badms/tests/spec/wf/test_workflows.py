"""Frozen design: WF_DESIGN.json — every distinct workflow path."""
import datetime as dt

import pytest

from core.api.exceptions import ConflictError
from modules.badms.services import archival as archival_service
from modules.badms.services import restoration as restoration_service
from modules.badms.services import storage as storage_service

from ..helpers import (
    DEPT,
    give_department,
    hod,
    itsec,
    make_archival,
    student,
    sysadmin,
)

pytestmark = pytest.mark.django_db


def _submitted(owner=None, uid=9301):
    owner = owner or student(uid=uid)
    give_department(owner.user_id, DEPT)
    request = archival_service.submit_request(
        actor=owner, file_name="wf.pdf", file_date=dt.date(2026, 8, 1),
        owners="O", file_type="pdf", reason="r", attachment="a://x")
    return owner, request


def test_wf_001_bw_ba_01_rejection_path():
    """WF-001 / BW-BA-01: the HoD rejection path."""
    _owner, request = _submitted()
    decided = archival_service.decide_request(actor=hod(dept=DEPT),
                                              request_id=request.pk,
                                              decision="reject")
    assert decided.status == "rejected"


def test_wf_002_bw_ba_02_non_sensitive_path():
    """WF-002 / BW-BA-02: approve then classify non-Sensitive."""
    _owner, request = _submitted()
    archival_service.decide_request(actor=hod(dept=DEPT),
                                    request_id=request.pk,
                                    decision="approve")
    request.refresh_from_db()
    classified = archival_service.classify_request(
        actor=sysadmin(), request_id=request.pk, classification="routine")
    assert request.status == "hod_approved"
    assert classified.status == "classified"


def test_wf_003_bw_ba_03_sensitive_path(tmp_path, settings):
    """WF-003 / BW-BA-03: the Sensitive encryption path."""
    _owner, request = _submitted()
    archival_service.decide_request(actor=hod(dept=DEPT),
                                    request_id=request.pk,
                                    decision="approve")
    routed = archival_service.classify_request(
        actor=sysadmin(), request_id=request.pk, classification="sensitive")
    settings.BADMS_ARCHIVE_ROOT = tmp_path
    encrypted = archival_service.configure_encryption(
        actor=itsec(), request_id=request.pk, key_ref="k")
    assert (routed.status, encrypted.status) == \
        ("routed_to_security", "encrypted")


def test_wf_004_cw_ba_01_legal_and_illegal():
    """WF-004 / CW-BA-01: legal transitions work; illegal ones conflict."""
    # legal: submitted -> rejected
    _owner, request = _submitted(uid=9311)
    decided = archival_service.decide_request(actor=hod(dept=DEPT),
                                              request_id=request.pk,
                                              decision="reject")
    assert decided.status == "rejected"
    # illegal: rejecting an already-approved request
    _owner2, request2 = _submitted(uid=9312)
    archival_service.decide_request(actor=hod(dept=DEPT),
                                    request_id=request2.pk,
                                    decision="approve")
    with pytest.raises(ConflictError):
        archival_service.decide_request(actor=hod(dept=DEPT),
                                        request_id=request2.pk,
                                        decision="reject")


def test_wf_005_bw_ba_04_rejected_path(profile_factory):
    """WF-005 / BW-BA-04: the extension rejection path."""
    profile_factory(9001, used=10_000, quota=10_000)
    owner = student()
    give_department(owner.user_id, DEPT)
    submitted = storage_service.submit_extension(actor=owner,
                                                 requested_bytes=1024,
                                                 justification="j")
    decided = storage_service.decide_extension(actor=hod(dept=DEPT),
                                               request_id=submitted.pk,
                                               decision="reject")
    assert decided.status == "rejected"


def test_wf_006_bw_ba_05_approved_path(profile_factory):
    """WF-006 / BW-BA-05: the extension approval path."""
    profile_factory(9001, used=10_000, quota=10_000)
    owner = student()
    give_department(owner.user_id, DEPT)
    submitted = storage_service.submit_extension(actor=owner,
                                                 requested_bytes=1024,
                                                 justification="j")
    decided = storage_service.decide_extension(actor=hod(dept=DEPT),
                                               request_id=submitted.pk,
                                               decision="approve")
    assert decided.status == "approved"


def test_wf_007_cw_ba_02_legal_and_illegal(profile_factory):
    """WF-007 / CW-BA-02: legal transitions; re-decision conflicts."""
    profile_factory(9001, used=10_000, quota=10_000)
    owner = student()
    give_department(owner.user_id, DEPT)
    submitted = storage_service.submit_extension(actor=owner,
                                                 requested_bytes=1024,
                                                 justification="j")
    storage_service.decide_extension(actor=hod(dept=DEPT),
                                     request_id=submitted.pk,
                                     decision="approve")
    with pytest.raises((ConflictError, ValueError)):
        # a decided request cannot be decided again: the transition table
        # refuses the (approved, reject) pair
        storage_service.decide_extension(actor=hod(dept=DEPT),
                                         request_id=submitted.pk,
                                         decision="reject")
    submitted.refresh_from_db()
    assert submitted.status == "approved"


def test_wf_008_bw_ba_06_standard_path():
    """WF-008 / BW-BA-06: non-Sensitive standard restoration."""
    owner = student()
    request = make_archival(uid=owner.user_id, status="classified")
    rest = restoration_service.request_restoration(actor=owner,
                                                   archival_id=request.pk)
    done = restoration_service.execute_restoration(actor=sysadmin(),
                                                   request_id=rest.pk)
    assert (rest.status, done.status) == ("requested", "restored")


def test_wf_009_bw_ba_07_approval_path():
    """WF-009 / BW-BA-07: the Sensitive SysAdmin-approval path."""
    owner = student()
    request = make_archival(uid=owner.user_id, status="encrypted",
                            classification="sensitive")
    rest = restoration_service.request_restoration(actor=owner,
                                                   archival_id=request.pk)
    assert rest.status == "pending_approval"
    restoration_service.decide_request(actor=sysadmin(), request_id=rest.pk,
                                       decision="approve")
    done = restoration_service.execute_restoration(actor=sysadmin(),
                                                   request_id=rest.pk)
    assert done.status == "restored"


def test_wf_010_cw_ba_03_legal_and_illegal():
    """WF-010 / CW-BA-03: legal transitions; premature execution conflicts."""
    owner = student()
    request = make_archival(uid=owner.user_id, status="encrypted",
                            classification="sensitive")
    rest = restoration_service.request_restoration(actor=owner,
                                                   archival_id=request.pk)
    with pytest.raises(ConflictError):
        restoration_service.execute_restoration(actor=sysadmin(),
                                                request_id=rest.pk)
    restoration_service.decide_request(actor=sysadmin(), request_id=rest.pk,
                                       decision="approve")
    done = restoration_service.execute_restoration(actor=sysadmin(),
                                                   request_id=rest.pk)
    assert done.status == "restored"


def test_wf_011_bw_ba_04_usage_validation_gate(profile_factory):
    """WF-011 / BW-BA-04: the flow starts only from a full quota."""
    profile_factory(9001, used=1_000, quota=10_000)
    from core.api.exceptions import DomainError
    with pytest.raises(DomainError):
        storage_service.submit_extension(actor=student(),
                                         requested_bytes=1024,
                                         justification="j")


def test_wf_012_bw_ba_03_encryption_failure_recovery(tmp_path, settings):
    """WF-012 / BW-BA-03: a failed encryption recovers by retry."""
    _owner, request = _submitted(uid=9321)
    archival_service.decide_request(actor=hod(dept=DEPT),
                                    request_id=request.pk,
                                    decision="approve")
    archival_service.classify_request(actor=sysadmin(),
                                      request_id=request.pk,
                                      classification="sensitive")
    blocker = tmp_path / "occupied"
    blocker.write_text("x")
    settings.BADMS_ARCHIVE_ROOT = blocker
    with pytest.raises(ConflictError):
        archival_service.configure_encryption(actor=itsec(),
                                              request_id=request.pk,
                                              key_ref="k")
    request.refresh_from_db()
    assert request.status == "encryption_failed"
    good = tmp_path / "archives"
    good.mkdir()
    settings.BADMS_ARCHIVE_ROOT = good
    retried = archival_service.configure_encryption(
        actor=itsec(), request_id=request.pk, key_ref="k")
    assert retried.status == "encrypted"


def test_wf_013_bw_ba_02_classification_defaults_path():
    """WF-013 / BW-BA-02: the default Routine classification carries through."""
    _owner, request = _submitted()
    assert request.initial_classification == "routine"
    archival_service.decide_request(actor=hod(dept=DEPT),
                                    request_id=request.pk,
                                    decision="approve")
    classified = archival_service.classify_request(
        actor=sysadmin(), request_id=request.pk, classification="routine")
    assert classified.status == "classified"


def test_wf_014_bw_ba_06_restoration_failure_path(tmp_path):
    """WF-014 / BW-BA-06: a missing artifact records a failure."""
    owner = student()
    request = make_archival(uid=owner.user_id, status="classified",
                            classification="routine")
    request.archive_ref = str(tmp_path / "missing.bin")
    request.save(update_fields=["archive_ref"])
    rest = restoration_service.request_restoration(actor=owner,
                                                   archival_id=request.pk)
    done = restoration_service.execute_restoration(actor=sysadmin(),
                                                   request_id=rest.pk)
    assert done.status == "failed" and done.error
