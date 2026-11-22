"""Concurrency: the choke points really do serialize decisions.

Real threads under `transaction=True` with a barrier: two actors decide the
same row at the same time, and the state machine — guarded by
`select_for_update` (services/locking.py) — lets exactly one through.
"""
import threading

import pytest
from django.db import connections

from core.api.exceptions import ConflictError
from modules.badms.services import archival, restoration

from .helpers import DEPT, HOD_PERMS, SYSADMIN_PERMS, actor, give_department, make_archival

pytestmark = pytest.mark.django_db(transaction=True)


def test_two_hods_deciding_one_request_produce_one_decision():
    request = make_archival(uid=4101, status="submitted", department=DEPT)
    give_department(4102, DEPT)
    hod = actor(uid=4102, perms=HOD_PERMS, kind="staff", roles=("hod",))
    barrier = threading.Barrier(2)
    results = {}

    def decide(tag):
        barrier.wait()
        try:
            archival.decide_request(actor=hod, request_id=request.pk,
                                    decision="approve")
            results[tag] = "approved"
        except Exception as exc:                                   # noqa: BLE001
            results[tag] = exc
        finally:
            connections.close_all()

    t1 = threading.Thread(target=decide, args=("t1",))
    t2 = threading.Thread(target=decide, args=("t2",))
    for t in (t1, t2):
        t.start()
    for t in (t1, t2):
        t.join()

    request.refresh_from_db()
    assert "approved" in results.values(), results
    # One approval moved it to hod_approved; the loser sees an illegal state.
    losers = [v for v in results.values() if v != "approved"]
    assert losers and isinstance(losers[0], ConflictError), results
    assert request.status == "hod_approved"


def test_a_second_decision_of_a_decided_request_is_refused():
    """The decision is re-read under lock inside the transaction, so a
    rejected request cannot be approved by a late second caller."""
    request = make_archival(uid=4201, status="submitted", department=DEPT)
    give_department(4202, DEPT)
    hod = actor(uid=4202, perms=HOD_PERMS, kind="staff", roles=("hod",))
    archival.decide_request(actor=hod, request_id=request.pk, decision="reject")
    with pytest.raises(ConflictError):
        archival.decide_request(actor=hod, request_id=request.pk,
                                decision="approve")
    request.refresh_from_db()
    assert request.status == "rejected"


def test_sensitive_restoration_executed_once():
    archival_request = make_archival(uid=4301, status="encrypted",
                                     classification="sensitive")
    rest = restoration.request_restoration(
        actor=actor(uid=4301, perms=("badms.restoration.request",)),
        archival_id=archival_request.pk, note="r")
    assert rest.status == "pending_approval"
    sysadmin = actor(uid=4303, perms=SYSADMIN_PERMS, kind="staff",
                     roles=("sysadmin",))
    restoration.decide_request(actor=sysadmin, request_id=rest.pk,
                               decision="approve")
    barrier = threading.Barrier(2)
    results = {}

    def execute(tag):
        barrier.wait()
        try:
            restoration.execute_restoration(actor=sysadmin, request_id=rest.pk)
            results[tag] = "executed"
        except Exception as exc:                                   # noqa: BLE001
            results[tag] = exc
        finally:
            connections.close_all()

    threads = [threading.Thread(target=execute, args=(f"t{i}",))
               for i in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    outcomes = sorted(v if isinstance(v, str) else "error"
                      for v in results.values())
    assert outcomes == ["error", "executed"], results
    rest.refresh_from_db()
    assert rest.status == "restored"
