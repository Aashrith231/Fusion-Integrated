"""Serializers. Thin, and every write serializer is an explicit allow-list —
`fields = "__all__"` is how `user_id`, `status` or `decided_by` ends up
writable by whoever posts the right JSON."""
from rest_framework import serializers

from modules.badms.models import (
    ArchivalRequest,
    Backup,
    BackupSchedule,
    RestorationRequest,
    SpecialArchivalRecord,
    StorageExtensionRequest,
)


# -- Backups ---------------------------------------------------------------------
class BackupSerializer(serializers.ModelSerializer):
    """What every module member sees. The artifact path is operational
    detail, withheld here and added back by BackupStaffSerializer."""

    class Meta:
        model = Backup
        fields = ("id", "kind", "status", "repository", "dataset",
                  "classification_filter", "trigger_user_id", "started_at",
                  "finished_at", "integrity_verified", "error",
                  "consecutive_failures", "created_at")
        read_only_fields = fields


class BackupStaffSerializer(BackupSerializer):
    class Meta(BackupSerializer.Meta):
        fields = (*BackupSerializer.Meta.fields, "artifact_ref")


class RepositorySerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    kind = serializers.CharField(read_only=True)
    reachable = serializers.BooleanField(read_only=True)
    capacity_bytes = serializers.IntegerField(read_only=True)


class ManualBackupSerializer(serializers.Serializer):
    repository = serializers.IntegerField(required=False)
    dataset = serializers.CharField(max_length=80, required=False,
                                    allow_blank=True, default="")
    classification_filter = serializers.ListField(
        child=serializers.CharField(), required=False, default=list)


# -- Schedules -------------------------------------------------------------------
class ScheduleSerializer(serializers.ModelSerializer):
    repository_name = serializers.CharField(source="repository.name",
                                             read_only=True)

    class Meta:
        model = BackupSchedule
        fields = ("id", "scope", "dataset", "frequency", "run_at", "weekday",
                  "classification_filter", "repository", "repository_name",
                  "is_active", "created_by_user_id", "created_at")
        read_only_fields = fields


class ScheduleWriteSerializer(serializers.Serializer):
    dataset = serializers.CharField(max_length=80, required=False,
                                    allow_blank=True)
    frequency = serializers.ChoiceField(choices=BackupSchedule.FREQUENCY)
    run_at = serializers.TimeField()
    weekday = serializers.IntegerField(required=False, allow_null=True,
                                       min_value=0, max_value=6)
    classification_filter = serializers.ListField(
        child=serializers.CharField(), required=False, default=list)
    repository = serializers.IntegerField()


class GlobalScheduleSerializer(ScheduleWriteSerializer):
    """The institution-wide schedule carries no dataset of its own."""
    dataset = serializers.CharField(required=False, allow_blank=True,
                                    max_length=80)


class ScheduleChangeSerializer(serializers.Serializer):
    action = serializers.CharField(read_only=True)
    changed_by_user_id = serializers.IntegerField(read_only=True)
    summary = serializers.CharField(read_only=True)
    at = serializers.DateTimeField(read_only=True)


# -- Archival ----------------------------------------------------------------------
class ArchivalRequestSerializer(serializers.ModelSerializer):
    # Plain strings: the classification choices would otherwise mint enum
    # components with identical members, one per field.
    initial_classification = serializers.CharField(read_only=True)
    classification = serializers.CharField(read_only=True)

    class Meta:
        model = ArchivalRequest
        fields = ("id", "user_id", "file_name", "file_date", "owners",
                  "file_type", "reason", "attachment",
                  "attachment_size_bytes", "initial_classification",
                  "department", "classification", "status", "retention_rule",
                  "encryption_algorithm", "encryption_key_ref", "encrypted_at",
                  "archive_ref", "created_at")
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # IT Security's key references are operational detail, not for the
        # requester's tracking page (BR-BA-020).
        actor = self.context.get("actor")
        if actor is not None and instance.user_id == getattr(
                actor, "user_id", None):
            data.pop("encryption_key_ref", None)
            data.pop("archive_ref", None)
        return data


class ArchivalSubmitSerializer(serializers.Serializer):
    file_name = serializers.CharField(max_length=200)
    file_date = serializers.DateField()
    owners = serializers.CharField(max_length=300)
    file_type = serializers.CharField(max_length=60)
    reason = serializers.CharField()
    attachment = serializers.CharField(max_length=300)
    attachment_size_bytes = serializers.IntegerField(
        required=False, default=0, min_value=0)
    # Validated by the service against the domain policy; plain string here so
    # the two classification choice sets do not mint duplicate enum components.
    initial_classification = serializers.CharField(required=False,
                                                   allow_blank=True,
                                                   default="")


class DecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"])
    note = serializers.CharField(max_length=300, required=False,
                                 allow_blank=True, default="")


class ClassificationSerializer(serializers.Serializer):
    # Validated by the service against the domain policy.
    classification = serializers.CharField(max_length=12)
    note = serializers.CharField(max_length=300, required=False,
                                 allow_blank=True, default="")


class EncryptionSerializer(serializers.Serializer):
    key_ref = serializers.CharField(max_length=120)
    note = serializers.CharField(max_length=300, required=False,
                                 allow_blank=True, default="")


class SpecialArchivalSerializer(serializers.ModelSerializer):
    class Meta:
        model = SpecialArchivalRecord
        fields = ("id", "performed_by_user_id", "data_reference", "reason",
                  "outcome", "note", "created_at")
        read_only_fields = fields


class SpecialArchivalWriteSerializer(serializers.Serializer):
    data_reference = serializers.CharField(max_length=300)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=300, required=False,
                                 allow_blank=True, default="")


# -- Restoration --------------------------------------------------------------------
class RestorationSerializer(serializers.ModelSerializer):
    archival_file_name = serializers.CharField(source="archival.file_name",
                                               read_only=True)
    # Plain string: same reasoning as ArchivalRequestSerializer above.
    classification = serializers.CharField(read_only=True)

    class Meta:
        model = RestorationRequest
        fields = ("id", "user_id", "archival", "archival_file_name",
                  "classification", "status", "note", "decided_by_user_id",
                  "decided_at", "executed_by_user_id", "executed_at", "error",
                  "created_at")
        read_only_fields = fields


class RestorationRequestSerializer(serializers.Serializer):
    archival = serializers.IntegerField()
    note = serializers.CharField(max_length=300, required=False,
                                 allow_blank=True, default="")


# -- Storage --------------------------------------------------------------------------
class StorageProfileSerializer(serializers.Serializer):
    quota_bytes = serializers.IntegerField(read_only=True)
    used_bytes = serializers.IntegerField(read_only=True)
    full = serializers.BooleanField(read_only=True)
    checked_at = serializers.DateTimeField(read_only=True)


class StorageExtensionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StorageExtensionRequest
        fields = ("id", "user_id", "department", "requested_bytes",
                  "justification", "attachment", "usage_at_request",
                  "quota_at_request", "status", "decided_by_user_id",
                  "decided_at", "created_at")
        read_only_fields = fields


class StorageExtensionWriteSerializer(serializers.Serializer):
    requested_bytes = serializers.IntegerField(min_value=1)
    justification = serializers.CharField()
    attachment = serializers.CharField(max_length=300, required=False,
                                       allow_blank=True, default="")


class InfrastructureSerializer(serializers.Serializer):
    name = serializers.CharField(read_only=True)
    capacity_bytes = serializers.IntegerField(read_only=True)
    allocated_bytes = serializers.IntegerField(read_only=True)
    available_bytes = serializers.IntegerField(read_only=True)


# -- Security and audit -----------------------------------------------------------------
class SecurityPolicySerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    statement = serializers.CharField(read_only=True)
    applies_to = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    defined_by_user_id = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class SecurityPolicyWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    statement = serializers.CharField()
    applies_to = serializers.CharField(max_length=80, required=False,
                                       allow_blank=True, default="")


class SecurityPolicyPatchSerializer(serializers.Serializer):
    statement = serializers.CharField(required=False)
    is_active = serializers.BooleanField(required=False)


class RbacAssignmentSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    user_id = serializers.IntegerField(read_only=True)
    permission_code = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    granted_by_user_id = serializers.IntegerField(read_only=True)


class RbacWriteSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1)
    permission_code = serializers.CharField(max_length=100)
    action = serializers.ChoiceField(choices=["grant", "revoke"])


class AuditEventSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    actor_user_id = serializers.IntegerField(read_only=True)
    actor_kind = serializers.CharField(read_only=True)
    actor_label = serializers.CharField(read_only=True)
    action = serializers.CharField(read_only=True)
    outcome = serializers.CharField(read_only=True)
    object_type = serializers.CharField(read_only=True)
    object_id = serializers.CharField(read_only=True)
    detail = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


# -- Tracking ----------------------------------------------------------------------------
class MyRequestSerializer(serializers.Serializer):
    """One row of the consolidated My-Requests tracking view (UC-BA-015)."""
    kind = serializers.CharField(read_only=True)
    id = serializers.IntegerField(read_only=True)
    title = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class DepartmentReportSerializer(serializers.Serializer):
    """UC-BA-021: the operational picture for the HoD's own department."""
    department = serializers.CharField(read_only=True)
    archival_by_status = serializers.DictField(child=serializers.IntegerField(),
                                               read_only=True)
    storage_extensions_by_status = serializers.DictField(
        child=serializers.IntegerField(), read_only=True)
    archival_total = serializers.IntegerField(read_only=True)
    storage_extension_total = serializers.IntegerField(read_only=True)
    backup_operations = serializers.DictField(
        child=serializers.IntegerField(), read_only=True)
