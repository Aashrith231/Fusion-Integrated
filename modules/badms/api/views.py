"""HTTP layer: parse, scope, delegate, serialise.

Every view takes its queryset from `selectors.scoping`, so authorisation is
never re-derived per endpoint. Anything out of scope is simply absent, which
is why detail views 404 rather than 403. Services raise domain errors; the
shared exception envelope turns them into the right status.
"""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.exceptions import BadRequestError, NotFoundError
from fusion_auth.permissions import HasModuleGrant, HasPermission
from modules.badms.api import serializers as s
from modules.badms.models import (
    ArchivalRequest,
    AuditEvent,
    BackupRepository,
    BackupSchedule,
    RbacAssignment,
    RestorationRequest,
    SecurityPolicy,
    StorageExtensionRequest,
)
from modules.badms.selectors import authz, scoping
from modules.badms.services import archival as archival_service
from modules.badms.services import backups as backup_service
from modules.badms.services import reports
from modules.badms.services import restoration as restoration_service
from modules.badms.services import schedules as schedule_service
from modules.badms.services import security as security_service
from modules.badms.services import special as special_service
from modules.badms.services import storage as storage_service

MODULE = HasModuleGrant("badms")

P_BACKUP_VIEW = "badms.backup.view"
P_BACKUP_TRIGGER = "badms.backup.trigger"
P_SCHEDULE_MANAGE = "badms.schedule.manage"
P_SCHEDULE_GLOBAL = "badms.schedule.manage_global"
P_ARCHIVAL_SUBMIT = "badms.archival.submit"
P_DECIDE = "badms.archival.decide"
P_CLASSIFY = "badms.archival.classify"
P_ENCRYPT = "badms.encryption.manage"
P_SPECIAL = "badms.special_archival.perform"
P_REST_REQUEST = "badms.restoration.request"
P_REST_APPROVE = "badms.restoration.approve"
P_REST_EXECUTE = "badms.restoration.execute"
P_STORAGE_REQUEST = "badms.storage.request"
P_STORAGE_DECIDE = "badms.storage.decide"
P_AUDIT_VIEW = "badms.audit.view"
P_SECURITY_AUDIT = "badms.security.audit"
P_RBAC_MANAGE = "badms.rbac.manage"
P_POLICY_MANAGE = "badms.security_policy.manage"
P_REPORT = "badms.report.department"


def _actor(request):
    return getattr(request, "principal", None)


def _int_param(params, name):
    raw = params.get(name)
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise BadRequestError(f"{name} must be a number.",
                              code="invalid_filter") from exc


class LookupAwareView(APIView):
    """A service raising LookupError means "the caller may not see that
    row" — mapped to 404 here, once, instead of in every view."""

    def handle_exception(self, exc):
        if isinstance(exc, LookupError):
            exc = NotFoundError("Not found.")
        return super().handle_exception(exc)


# -- Backups ---------------------------------------------------------------------
@extend_schema(responses=s.BackupSerializer(many=True))
class BackupListView(LookupAwareView):
    """GET /badms/backups — history and current status (UC-BA-014).

    Status and history are visible in scope; the artifact path is
    operational detail for those who run backups (BR-BA-020).
    """

    permission_classes = [MODULE, HasPermission(P_BACKUP_VIEW)]

    def get(self, request):
        actor = _actor(request)
        rows = scoping.backups_for(actor)[:200]
        cls = s.BackupStaffSerializer \
            if authz.has_permission(actor, P_BACKUP_TRIGGER) \
            else s.BackupSerializer
        return Response(cls(rows, many=True).data)


class ManualBackupView(LookupAwareView):
    """POST /badms/backups/manual — trigger an on-demand backup
    (UC-BA-001, BR-BA-001)."""

    permission_classes = [MODULE, HasPermission(P_BACKUP_TRIGGER)]

    @extend_schema(request=s.ManualBackupSerializer,
                   responses=s.BackupSerializer)
    def post(self, request):
        data = s.ManualBackupSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        payload = data.validated_data
        repo = None
        if payload.get("repository"):
            repo = BackupRepository.objects.filter(
                pk=payload["repository"]).first()
            if repo is None:
                raise BadRequestError("Unknown backup repository.",
                                      code="invalid_backup")
        backup = backup_service.trigger_manual_backup(
            actor=_actor(request), repository=repo,
            dataset=payload.get("dataset", ""),
            classification_filter=payload.get("classification_filter") or [])
        body = s.BackupSerializer(backup).data
        code = status.HTTP_200_OK if backup.status == "success" \
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        return Response(body, status=code)


@extend_schema(responses=s.RepositorySerializer(many=True))
class RepositoryListView(LookupAwareView):
    """GET /badms/repositories — the targets schedules and manual runs name."""

    permission_classes = [MODULE, HasPermission(
        P_BACKUP_TRIGGER, P_SCHEDULE_MANAGE, P_SCHEDULE_GLOBAL)]

    def get(self, request):
        rows = BackupRepository.objects.all().order_by("name")
        return Response(s.RepositorySerializer(rows, many=True).data)


# -- Schedules ---------------------------------------------------------------------
@extend_schema(responses=s.ScheduleSerializer(many=True))
class ScheduleListView(LookupAwareView):
    """GET /badms/schedules — current schedules (AFR-BA-012)."""

    permission_classes = [MODULE, HasPermission(
        P_SCHEDULE_MANAGE, P_SCHEDULE_GLOBAL)]

    def get(self, request):
        rows = BackupSchedule.objects.all().order_by("scope", "dataset")
        return Response(s.ScheduleSerializer(rows, many=True).data)


class ScheduleCreateView(LookupAwareView):
    """POST /badms/schedules — create a local dataset schedule
    (UC-BA-009 A1)."""

    permission_classes = [MODULE, HasPermission(P_SCHEDULE_MANAGE)]

    @extend_schema(request=s.ScheduleWriteSerializer,
                   responses=s.ScheduleSerializer)
    def post(self, request):
        data = s.ScheduleWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        p = data.validated_data
        schedule = schedule_service.create_local_schedule(
            actor=_actor(request), dataset=p.get("dataset", ""),
            frequency=p["frequency"], run_at=p["run_at"], weekday=p.get("weekday"),
            classification_filter=p.get("classification_filter") or [],
            repository_id=p["repository"])
        return Response(s.ScheduleSerializer(schedule).data,
                        status=status.HTTP_201_CREATED)


class ScheduleModifyView(LookupAwareView):
    """PATCH /badms/schedules/<pk> — modify a local schedule (UC-BA-009 A2)."""

    permission_classes = [MODULE, HasPermission(P_SCHEDULE_MANAGE)]

    @extend_schema(request=s.ScheduleWriteSerializer,
                   responses=s.ScheduleSerializer)
    def patch(self, request, pk):
        data = s.ScheduleWriteSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        p = data.validated_data
        if not p:
            raise BadRequestError("Nothing to change.", code="invalid_schedule")
        schedule = schedule_service.modify_local_schedule(
            actor=_actor(request), schedule_id=pk,
            frequency=p.get("frequency"),
            run_at=p.get("run_at"),
            weekday=p.get("weekday") if "weekday" in p else None,
            classification_filter=p.get("classification_filter"),
            repository_id=p.get("repository"))
        return Response(s.ScheduleSerializer(schedule).data)


@extend_schema(responses=s.ScheduleSerializer)
class GlobalScheduleView(LookupAwareView):
    """GET/PUT /badms/schedules/global — the institution-wide schedule and
    default policy (UC-BA-011, BR-BA-019)."""

    permission_classes = [MODULE, HasPermission(P_SCHEDULE_GLOBAL)]

    @extend_schema(responses=s.ScheduleSerializer)
    def get(self, request):
        row = BackupSchedule.objects.filter(scope="global").first()
        return Response(s.ScheduleSerializer(row).data if row else None)

    @extend_schema(request=s.GlobalScheduleSerializer,
                   responses=s.ScheduleSerializer)
    def put(self, request):
        data = s.GlobalScheduleSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        p = data.validated_data
        schedule = schedule_service.set_global_schedule(
            actor=_actor(request), frequency=p["frequency"],
            run_at=p["run_at"], weekday=p.get("weekday"),
            classification_filter=p.get("classification_filter") or [],
            repository_id=p["repository"])
        return Response(s.ScheduleSerializer(schedule).data)


@extend_schema(responses=s.ScheduleChangeSerializer(many=True))
class ScheduleChangeLogView(LookupAwareView):
    """GET /badms/schedules/<pk>/changes — the configuration trail
    (AFR-BA-016)."""

    permission_classes = [MODULE, HasPermission(
        P_SCHEDULE_MANAGE, P_SCHEDULE_GLOBAL)]

    def get(self, request, pk):
        rows = schedule_service.change_log_for(pk)
        return Response(s.ScheduleChangeSerializer(rows, many=True).data)


# -- Archival -----------------------------------------------------------------------
@extend_schema(responses=s.ArchivalRequestSerializer(many=True))
class ArchivalListView(LookupAwareView):
    """GET /badms/archival — every request this caller is authorised to see,
    scoped by role and department (BR-BA-020)."""

    permission_classes = [MODULE]

    def get(self, request):
        rows = scoping.archival_requests_for(_actor(request))[:200]
        return Response(
            s.ArchivalRequestSerializer(rows, many=True,
                                        context={"actor": _actor(request)})
            .data)


class ArchivalMineView(LookupAwareView):
    """GET /badms/archival/mine — the requester's own tracking list."""

    permission_classes = [MODULE]

    @extend_schema(responses=s.ArchivalRequestSerializer(many=True))
    def get(self, request):
        actor = _actor(request)
        own = getattr(actor, "user_id", None)
        rows = (ArchivalRequest.objects.filter(user_id=own)
                .order_by("-created_at")[:200])
        return Response(
            s.ArchivalRequestSerializer(rows, many=True,
                                        context={"actor": actor}).data)


class ArchivalSubmitView(LookupAwareView):
    """POST /badms/archival — submit a secure archival request (UC-BA-002)."""

    permission_classes = [MODULE, HasPermission(P_ARCHIVAL_SUBMIT)]

    @extend_schema(request=s.ArchivalSubmitSerializer,
                   responses=s.ArchivalRequestSerializer)
    def post(self, request):
        data = s.ArchivalSubmitSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        p = data.validated_data
        row = archival_service.submit_request(
            actor=_actor(request), file_name=p["file_name"],
            file_date=p["file_date"], owners=p["owners"],
            file_type=p["file_type"], reason=p["reason"],
            attachment=p["attachment"],
            attachment_size_bytes=p.get("attachment_size_bytes", 0),
            initial_classification=p.get("initial_classification", ""))
        return Response(
            s.ArchivalRequestSerializer(row, context={"actor": _actor(request)})
            .data, status=status.HTTP_201_CREATED)


class ArchivalDetailView(LookupAwareView):
    """GET /badms/archival/<pk> — detail with decision history
    (UC-BA-015)."""

    permission_classes = [MODULE]

    @extend_schema(responses=s.ArchivalRequestSerializer)
    def get(self, request, pk):
        actor = _actor(request)
        row = scoping.archival_requests_for(actor).filter(pk=pk).first()
        if row is None:
            raise NotFoundError("No such archival request.")
        body = s.ArchivalRequestSerializer(row, context={"actor": actor}).data
        body["history"] = archival_service.track_history(row)
        return Response(body)


class ArchivalDecideView(LookupAwareView):
    """POST /badms/archival/<pk>/decide — the respective HoD approves or
    rejects (UC-BA-003)."""

    permission_classes = [MODULE, HasPermission(P_DECIDE)]

    @extend_schema(request=s.DecisionSerializer,
                   responses=s.ArchivalRequestSerializer)
    def post(self, request, pk):
        data = s.DecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = archival_service.decide_request(
            actor=_actor(request), request_id=pk,
            decision=data.validated_data["decision"],
            note=data.validated_data.get("note", ""))
        return Response(
            s.ArchivalRequestSerializer(row, context={"actor": _actor(request)})
            .data)


class ArchivalClassifyView(LookupAwareView):
    """POST /badms/archival/<pk>/classify — authoritative classification
    (UC-BA-004)."""

    permission_classes = [MODULE, HasPermission(P_CLASSIFY)]

    @extend_schema(request=s.ClassificationSerializer,
                   responses=s.ArchivalRequestSerializer)
    def post(self, request, pk):
        data = s.ClassificationSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = archival_service.classify_request(
            actor=_actor(request), request_id=pk,
            classification=data.validated_data["classification"],
            note=data.validated_data.get("note", ""))
        return Response(
            s.ArchivalRequestSerializer(row, context={"actor": _actor(request)})
            .data)


class ArchivalEncryptionView(LookupAwareView):
    """POST /badms/archival/<pk>/encryption — configure encryption and create
    the encrypted archive (UC-BA-005)."""

    permission_classes = [MODULE, HasPermission(P_ENCRYPT)]

    @extend_schema(request=s.EncryptionSerializer,
                   responses=s.ArchivalRequestSerializer)
    def post(self, request, pk):
        data = s.EncryptionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = archival_service.configure_encryption(
            actor=_actor(request), request_id=pk,
            key_ref=data.validated_data["key_ref"],
            note=data.validated_data.get("note", ""))
        return Response(
            s.ArchivalRequestSerializer(row, context={"actor": _actor(request)})
            .data)


# -- Special archival -------------------------------------------------------------------
@extend_schema(responses=s.SpecialArchivalSerializer(many=True))
class SpecialArchivalListView(LookupAwareView):
    """GET /badms/special-archival — the Super Admin's operation records."""

    permission_classes = [MODULE, HasPermission(P_SPECIAL)]

    def get(self, request):
        rows = scoping.special_archival_for(_actor(request))[:200]
        return Response(s.SpecialArchivalSerializer(rows, many=True).data)


class SpecialArchivalView(LookupAwareView):
    """POST /badms/special-archival — perform a special archival operation
    (UC-BA-010)."""

    permission_classes = [MODULE, HasPermission(P_SPECIAL)]

    @extend_schema(request=s.SpecialArchivalWriteSerializer,
                   responses=s.SpecialArchivalSerializer)
    def post(self, request):
        data = s.SpecialArchivalWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        p = data.validated_data
        row = special_service.perform_special_archival(
            actor=_actor(request), data_reference=p["data_reference"],
            reason=p.get("reason", ""), note=p.get("note", ""))
        return Response(s.SpecialArchivalSerializer(row).data,
                        status=status.HTTP_201_CREATED)


# -- Restoration ---------------------------------------------------------------------
@extend_schema(responses=s.RestorationSerializer(many=True))
class RestorationListView(LookupAwareView):
    """GET /badms/restorations — scoped by role (UC-BA-016/017)."""

    permission_classes = [MODULE, HasPermission(
        P_REST_REQUEST, P_REST_APPROVE, P_REST_EXECUTE)]

    def get(self, request):
        rows = scoping.restorations_for(_actor(request))[:200]
        return Response(s.RestorationSerializer(rows, many=True).data)


class RestorationRequestView(LookupAwareView):
    """POST /badms/restorations — request restoration (UC-BA-016)."""

    permission_classes = [MODULE, HasPermission(P_REST_REQUEST)]

    @extend_schema(request=s.RestorationRequestSerializer,
                   responses=s.RestorationSerializer)
    def post(self, request):
        data = s.RestorationRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        p = data.validated_data
        row = restoration_service.request_restoration(
            actor=_actor(request), archival_id=p["archival"],
            note=p.get("note", ""))
        return Response(s.RestorationSerializer(row).data,
                        status=status.HTTP_201_CREATED)


class RestorationDecideView(LookupAwareView):
    """POST /badms/restorations/<pk>/decide — SysAdmin approval for Sensitive
    data (UC-BA-017, BR-BA-005)."""

    permission_classes = [MODULE, HasPermission(P_REST_APPROVE)]

    @extend_schema(request=s.DecisionSerializer,
                   responses=s.RestorationSerializer)
    def post(self, request, pk):
        data = s.DecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = restoration_service.decide_request(
            actor=_actor(request), request_id=pk,
            decision=data.validated_data["decision"],
            note=data.validated_data.get("note", ""))
        return Response(s.RestorationSerializer(row).data)


class RestorationExecuteView(LookupAwareView):
    """POST /badms/restorations/<pk>/execute — technical execution
    (UC-BA-018)."""

    permission_classes = [MODULE, HasPermission(P_REST_EXECUTE)]

    @extend_schema(request=None, responses=s.RestorationSerializer)
    def post(self, request, pk):
        row = restoration_service.execute_restoration(
            actor=_actor(request), request_id=pk)
        return Response(s.RestorationSerializer(row).data)


# -- Storage --------------------------------------------------------------------------
@extend_schema(responses=s.StorageProfileSerializer)
class MyStorageView(LookupAwareView):
    """GET /badms/storage/me — the caller's usage and threshold status."""

    permission_classes = [MODULE]

    def get(self, request):
        actor = _actor(request)
        profile = storage_service.ensure_profile(
            getattr(actor, "user_id", 0) or 0)
        return Response(s.StorageProfileSerializer(profile).data)


class StorageExtensionSubmitView(LookupAwareView):
    """POST /badms/storage/extensions — submit an extension request
    (UC-BA-007)."""

    permission_classes = [MODULE, HasPermission(P_STORAGE_REQUEST)]

    @extend_schema(request=s.StorageExtensionWriteSerializer,
                   responses=s.StorageExtensionSerializer)
    def post(self, request):
        data = s.StorageExtensionWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        p = data.validated_data
        row = storage_service.submit_extension(
            actor=_actor(request), requested_bytes=p["requested_bytes"],
            justification=p["justification"],
            attachment=p.get("attachment", ""))
        return Response(s.StorageExtensionSerializer(row).data,
                        status=status.HTTP_201_CREATED)


class StorageExtensionMineView(LookupAwareView):
    """GET /badms/storage/extensions/mine — the requester's own requests."""

    permission_classes = [MODULE]

    @extend_schema(responses=s.StorageExtensionSerializer(many=True))
    def get(self, request):
        own = getattr(_actor(request), "user_id", None)
        rows = (StorageExtensionRequest.objects.filter(user_id=own)
                .order_by("-created_at")[:200])
        return Response(s.StorageExtensionSerializer(rows, many=True).data)


class StorageExtensionQueueView(LookupAwareView):
    """GET /badms/storage/extensions — the department's queue for the HoD."""

    permission_classes = [MODULE, HasPermission(P_STORAGE_DECIDE)]

    @extend_schema(responses=s.StorageExtensionSerializer(many=True))
    def get(self, request):
        rows = scoping.storage_extensions_for(_actor(request))[:200]
        return Response(s.StorageExtensionSerializer(rows, many=True).data)


class StorageExtensionDecideView(LookupAwareView):
    """POST /badms/storage/extensions/<pk>/decide — the respective HoD
    approves or rejects (UC-BA-008)."""

    permission_classes = [MODULE, HasPermission(P_STORAGE_DECIDE)]

    @extend_schema(request=s.DecisionSerializer,
                   responses=s.StorageExtensionSerializer)
    def post(self, request, pk):
        data = s.DecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = storage_service.decide_extension(
            actor=_actor(request), request_id=pk,
            decision=data.validated_data["decision"],
            note=data.validated_data.get("note", ""))
        return Response(s.StorageExtensionSerializer(row).data)


@extend_schema(responses=s.InfrastructureSerializer)
class InfrastructureView(LookupAwareView):
    """GET /badms/storage/infrastructure — the picture a HoD reviews a
    request against (BR-BA-017)."""

    permission_classes = [MODULE, HasPermission(P_STORAGE_DECIDE, P_REPORT)]

    def get(self, request):
        pool = storage_service.primary_infrastructure()
        return Response(s.InfrastructureSerializer(pool).data)


# -- Audit and security -----------------------------------------------------------------
@extend_schema(responses=s.AuditEventSerializer(many=True))
class AuditLogView(LookupAwareView):
    """GET /badms/audit — audit logs and activity history (UC-BA-012)."""

    permission_classes = [MODULE, HasPermission(P_AUDIT_VIEW)]

    def get(self, request):
        rows = AuditEvent.objects.all().order_by("-created_at")[:200]
        action = request.query_params.get("action")
        if action:
            rows = AuditEvent.objects.filter(
                action__icontains=action).order_by("-created_at")[:200]
        return Response(s.AuditEventSerializer(rows, many=True).data)


@extend_schema(responses=s.AuditEventSerializer(many=True))
class SecurityAuditView(LookupAwareView):
    """GET /badms/security/audit — the security slice and the unauthorised-
    access candidates (UC-BA-013)."""

    permission_classes = [MODULE, HasPermission(P_SECURITY_AUDIT)]

    def get(self, request):
        body = reports.unauthorised_access_candidates()
        rows = AuditEvent.objects.filter(
            actor_kind__in=("security", "admin")).order_by("-created_at")[:50]
        body["recent"] = s.AuditEventSerializer(rows, many=True).data
        return Response(body)


class SecurityPolicyListView(LookupAwareView):
    """GET/POST /badms/security/policies — define security policies
    (UC-BA-020)."""

    permission_classes = [MODULE, HasPermission(P_POLICY_MANAGE)]

    @extend_schema(responses=s.SecurityPolicySerializer(many=True))
    def get(self, request):
        rows = SecurityPolicy.objects.all().order_by("name")
        return Response(s.SecurityPolicySerializer(rows, many=True).data)

    @extend_schema(request=s.SecurityPolicyWriteSerializer,
                   responses=s.SecurityPolicySerializer)
    def post(self, request):
        data = s.SecurityPolicyWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        p = data.validated_data
        row = security_service.define_policy(
            actor=_actor(request), name=p["name"], statement=p["statement"],
            applies_to=p.get("applies_to", ""))
        return Response(s.SecurityPolicySerializer(row).data,
                        status=status.HTTP_201_CREATED)


class SecurityPolicyDetailView(LookupAwareView):
    """PATCH /badms/security/policies/<pk> — update or retire a policy."""

    permission_classes = [MODULE, HasPermission(P_POLICY_MANAGE)]

    @extend_schema(request=s.SecurityPolicyPatchSerializer,
                   responses=s.SecurityPolicySerializer)
    def patch(self, request, pk):
        data = s.SecurityPolicyPatchSerializer(data=request.data,
                                               partial=True)
        data.is_valid(raise_exception=True)
        p = data.validated_data
        row = security_service.update_policy(
            actor=_actor(request), policy_id=pk,
            statement=p.get("statement"), is_active=p.get("is_active"))
        return Response(s.SecurityPolicySerializer(row).data)


class RbacView(LookupAwareView):
    """GET/POST /badms/security/rbac — manage BADMS RBAC assignments
    (UC-BA-019)."""

    permission_classes = [MODULE, HasPermission(P_RBAC_MANAGE)]

    @extend_schema(responses=s.RbacAssignmentSerializer(many=True))
    def get(self, request):
        rows = RbacAssignment.objects.all().order_by("user_id",
                                                     "permission_code")
        return Response(s.RbacAssignmentSerializer(rows, many=True).data)

    @extend_schema(request=s.RbacWriteSerializer,
                   responses=s.RbacAssignmentSerializer)
    def post(self, request):
        data = s.RbacWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        p = data.validated_data
        if p["action"] == "grant":
            row = security_service.grant_permission(
                actor=_actor(request), user_id=p["user_id"],
                permission_code=p["permission_code"])
            return Response(s.RbacAssignmentSerializer(row).data,
                            status=status.HTTP_201_CREATED)
        security_service.revoke_permission(
            actor=_actor(request), user_id=p["user_id"],
            permission_code=p["permission_code"])
        return Response(status=status.HTTP_200_OK)


# -- Reports and tracking -----------------------------------------------------------------
class DepartmentReportView(LookupAwareView):
    """GET /badms/reports/department?department=… — operational reports for
    the HoD's own department (UC-BA-021)."""

    permission_classes = [MODULE, HasPermission(P_REPORT)]

    @extend_schema(responses=s.DepartmentReportSerializer)
    def get(self, request):
        department = (request.query_params.get("department") or "").strip()
        if not department:
            raise BadRequestError("A department is required.",
                                  code="invalid_filter")
        body = reports.department_report(
            actor=_actor(request), department=department)
        body["backup_operations"] = reports.backup_operations_summary()
        return Response(body)


@extend_schema(responses=s.MyRequestSerializer(many=True))
class MyRequestsView(LookupAwareView):
    """GET /badms/me/requests — one tracking view across archival, storage
    and restoration requests (UC-BA-015)."""

    permission_classes = [MODULE]

    def get(self, request):
        own = getattr(_actor(request), "user_id", None)
        rows: list[dict] = []
        rows.extend(
            {"kind": "archival", "id": r.pk, "title": r.file_name,
             "status": r.status, "updated_at": r.updated_at}
            for r in (ArchivalRequest.objects.filter(user_id=own)
                      .order_by("-updated_at")[:100]))
        rows.extend(
            {"kind": "storage_extension", "id": r.pk,
             "title": f"{r.requested_bytes} bytes", "status": r.status,
             "updated_at": r.updated_at}
            for r in (StorageExtensionRequest.objects.filter(user_id=own)
                      .order_by("-updated_at")[:100]))
        rows.extend(
            {"kind": "restoration", "id": r.pk,
             "title": r.archival.file_name, "status": r.status,
             "updated_at": r.updated_at}
            for r in (RestorationRequest.objects.filter(user_id=own)
                      .select_related("archival")
                      .order_by("-updated_at")[:100]))
        rows.sort(key=lambda row: row["updated_at"], reverse=True)
        return Response(rows)
