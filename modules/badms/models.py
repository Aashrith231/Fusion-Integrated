"""BADMS domain tables (Backup and Database Archive Management System).

Institute people are referenced by plain `user_id` integers, never foreign
keys — there is no user table in this database. Departments are carried as
plain strings because the IAM directory (modules.directory) is their source.
"""
from django.db import models

from core.db.mixins import TimeStampedModel, UserScopedModel


# -- Backup infrastructure ------------------------------------------------------
class BackupRepository(TimeStampedModel):
    """A storage target a backup can be written to. Reachability is a live
    property the executor checks before transferring anything."""

    KIND = [("primary", "Primary"), ("replica", "Replica"),
            ("offsite", "Offsite")]

    name = models.CharField(max_length=80, unique=True)
    kind = models.CharField(max_length=12, choices=KIND, default="primary")
    location = models.CharField(max_length=200, blank=True)
    reachable = models.BooleanField(default=True)
    capacity_bytes = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "badms_backup_repository"

    def __str__(self) -> str:
        return f"{self.name} ({self.kind})"


class Backup(TimeStampedModel):
    """One backup operation, manual or scheduled (PS 3.1, UC-BA-001/006)."""

    KIND = [("manual", "Manual"), ("scheduled", "Scheduled")]
    STATUS = [("running", "Running"), ("success", "Success"),
              ("failed", "Failed")]

    kind = models.CharField(max_length=10, choices=KIND, db_index=True)
    status = models.CharField(max_length=10, choices=STATUS, default="running",
                              db_index=True)
    repository = models.ForeignKey(BackupRepository, on_delete=models.PROTECT,
                                   related_name="backups")
    #: The actor who triggered a manual backup; null for scheduled runs.
    trigger_user_id = models.IntegerField(null=True, blank=True)
    started_at = models.DateTimeField(db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    dataset = models.CharField(max_length=80, blank=True,
                               help_text="Empty for the whole platform state.")
    classification_filter = models.JSONField(default=list, blank=True)
    #: True once the transferred data passed the integrity/consistency check.
    integrity_verified = models.BooleanField(default=False)
    artifact_ref = models.CharField(max_length=300, blank=True)
    error = models.CharField(max_length=300, blank=True)
    #: Running count of consecutive failures ending with this backup, so the
    #: escalation rule (BR-BA-015) is readable off the row itself.
    consecutive_failures = models.PositiveIntegerField(default=0)
    #: Set once the SysAdmin failure alert has been queued (BR-BA-014).
    failure_alerted_at = models.DateTimeField(null=True, blank=True)
    #: Set once the Director-of-IT escalation has been queued (BR-BA-015).
    escalated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "badms_backup"
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.kind} backup {self.status} @ {self.started_at:%Y-%m-%d %H:%M}"


class BackupSchedule(TimeStampedModel):
    """Local (dataset) and global schedules.

    A local schedule overrides the global one for its dataset (BR-BA-011);
    the global schedule is the institution-wide default (BR-BA-019).
    """

    SCOPE = [("local", "Local"), ("global", "Global")]
    FREQUENCY = [("daily", "Daily"), ("weekly", "Weekly"),
                 ("monthly", "Monthly")]

    scope = models.CharField(max_length=8, choices=SCOPE, db_index=True)
    #: Dataset name for local schedules; "" for the institution-wide default.
    dataset = models.CharField(max_length=80, blank=True, default="")
    frequency = models.CharField(max_length=8, choices=FREQUENCY)
    #: Time of day the schedule is due (local, 24h).
    run_at = models.TimeField()
    #: 0=Monday … 6=Sunday; only meaningful for weekly schedules.
    weekday = models.PositiveSmallIntegerField(null=True, blank=True)
    #: Classification names eligible for this backup; [] means everything.
    classification_filter = models.JSONField(default=list, blank=True)
    repository = models.ForeignKey(BackupRepository, on_delete=models.PROTECT,
                                   related_name="schedules")
    is_active = models.BooleanField(default=True)
    created_by_user_id = models.IntegerField()
    updated_by_user_id = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "badms_backup_schedule"
        constraints = [
            models.UniqueConstraint(
                fields=["scope", "dataset"], condition=models.Q(is_active=True),
                name="badms_schedule_scope_dataset_active"),
        ]
        indexes = [
            models.Index(fields=["scope", "dataset"],
                         name="schedule_scope_ds_idx"),
        ]

    def __str__(self) -> str:
        target = self.dataset or "institution-wide"
        return f"{self.scope} {self.frequency} schedule for {target}"


class ScheduleChangeLog(models.Model):
    """One row per schedule configuration change (AFR-BA-016)."""

    schedule = models.ForeignKey(BackupSchedule, on_delete=models.CASCADE,
                                 related_name="change_log")
    action = models.CharField(max_length=8)          # create | modify
    changed_by_user_id = models.IntegerField()
    summary = models.CharField(max_length=300, blank=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "badms_schedule_change_log"

    def __str__(self) -> str:
        return f"{self.action} on schedule {self.schedule_id}"


# -- Secure archival ------------------------------------------------------------
class ArchivalRequest(TimeStampedModel, UserScopedModel):
    """A secure archival request (PS 3.2, UC-BA-002..005).

    Status paths (CW-BA-01):

        submitted -> hod_approved -> classified   (non-Sensitive)
        submitted -> hod_approved -> routed_to_security -> encrypted
        submitted -> rejected
    """

    STATUS = [
        ("submitted", "Submitted"),
        ("rejected", "Rejected"),
        ("hod_approved", "HoD Approved"),
        ("routed_to_security", "Routed to IT Security"),
        ("classified", "Classified"),
        ("encrypted", "Sensitive Archive Encrypted"),
        ("encryption_failed", "Encryption Failed"),
    ]
    CLASSIFICATION = [
        ("critical", "Critical"), ("sensitive", "Sensitive"),
        ("routine", "Routine"), ("archival", "Archival"),
    ]

    file_name = models.CharField(max_length=200)
    file_date = models.DateField()
    owners = models.CharField(max_length=300)
    file_type = models.CharField(max_length=60)
    reason = models.TextField()
    attachment = models.CharField(max_length=300,
                                  help_text="Drive/file reference.")
    attachment_size_bytes = models.BigIntegerField(default=0)
    #: What the user declared at upload; Routine when omitted (BR-BA-006).
    initial_classification = models.CharField(
        max_length=12, choices=CLASSIFICATION, blank=True, default="")
    department = models.CharField(max_length=80, blank=True)
    #: The authoritative classification assigned by the SysAdmin.
    classification = models.CharField(max_length=12, choices=CLASSIFICATION,
                                      blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS, default="submitted",
                              db_index=True)
    #: Retention treatment applied with the authoritative classification.
    retention_rule = models.CharField(max_length=300, blank=True)
    #: Encryption configuration recorded by IT Security (BR-BA-007).
    encryption_algorithm = models.CharField(max_length=40, blank=True)
    encryption_key_ref = models.CharField(max_length=120, blank=True)
    encrypted_at = models.DateTimeField(null=True, blank=True)
    archive_ref = models.CharField(max_length=300, blank=True)
    hod_decided_by_user_id = models.IntegerField(null=True, blank=True)
    classified_by_user_id = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "badms_archival_request"
        indexes = [
            models.Index(fields=["status", "-created_at"],
                         name="archival_status_idx"),
            models.Index(fields=["department", "status"],
                         name="archival_dept_idx"),
        ]

    def __str__(self) -> str:
        return f"Archival {self.file_name} ({self.status})"


class ArchivalDecision(models.Model):
    """Who decided what, and when (AFR-BA-025, AFR-BA-036)."""

    STAGE = [("hod", "HoD review"), ("classification", "Classification"),
             ("encryption", "Encryption")]

    request = models.ForeignKey(ArchivalRequest, on_delete=models.CASCADE,
                                related_name="decisions")
    stage = models.CharField(max_length=16, choices=STAGE)
    decision = models.CharField(max_length=20)
    decided_by_user_id = models.IntegerField()
    note = models.CharField(max_length=300, blank=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "badms_archival_decision"

    def __str__(self) -> str:
        return f"{self.stage}:{self.decision} on request {self.request_id}"


class SpecialArchivalRecord(TimeStampedModel):
    """A special archival operation performed by the Super Admin for Sensitive
    research data received offline from any authority (PS 3.4, BR-BA-018)."""

    OUTCOME = [("completed", "Completed"), ("failed", "Failed")]

    performed_by_user_id = models.IntegerField()
    data_reference = models.CharField(max_length=300)
    reason = models.TextField(blank=True)
    outcome = models.CharField(max_length=10, choices=OUTCOME)
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "badms_special_archival"


# -- Data restoration -----------------------------------------------------------
class RestorationRequest(TimeStampedModel, UserScopedModel):
    """Restoration of archived data (PS 3.3, CW-BA-03).

    Non-Sensitive data takes the standard path; Sensitive data is blocked
    until a SysAdmin approval is recorded (BR-BA-005). There is no HoD
    restoration-authorization route in this version.
    """

    STATUS = [
        ("requested", "Requested (standard path)"),
        ("pending_approval", "Sensitive — Pending SysAdmin Approval"),
        ("rejected", "Rejected"),
        ("approved_for_restoration", "Approved for Restoration"),
        ("restored", "Restored"),
        ("failed", "Failed"),
    ]

    archival = models.ForeignKey(ArchivalRequest, on_delete=models.PROTECT,
                                 related_name="restorations")
    classification = models.CharField(max_length=12,
                                      choices=ArchivalRequest.CLASSIFICATION)
    status = models.CharField(max_length=24, choices=STATUS, default="requested",
                              db_index=True)
    note = models.CharField(max_length=300, blank=True)
    decided_by_user_id = models.IntegerField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    executed_by_user_id = models.IntegerField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "badms_restoration_request"
        indexes = [models.Index(fields=["status", "-created_at"],
                                name="restoration_status_idx")]

    def __str__(self) -> str:
        return f"Restoration of {self.archival.file_name} ({self.status})"


# -- Storage management ---------------------------------------------------------
class StorageProfile(TimeStampedModel, UserScopedModel):
    """A user's storage usage and quota, kept current by the threshold
    monitor (UC-BA-022, AFR-BA-051)."""

    quota_bytes = models.BigIntegerField(default=10 * 1024 * 1024 * 1024)
    used_bytes = models.BigIntegerField(default=0)
    #: Evaluated usage >= quota; what gates a storage-extension request.
    full = models.BooleanField(default=False, db_index=True)
    checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "badms_storage_profile"
        constraints = [
            models.UniqueConstraint(fields=["user_id"],
                                    name="badms_storage_profile_user")
        ]

    def __str__(self) -> str:
        return f"storage profile for user {self.user_id} ({self.used_bytes}B used)"


class StorageInfrastructure(TimeStampedModel):
    """Institute storage the extension requests are validated against
    (AFR-BA-052). One row per pool; the primary pool backs user quotas."""

    name = models.CharField(max_length=80, unique=True)
    capacity_bytes = models.BigIntegerField()
    allocated_bytes = models.BigIntegerField(default=0)

    class Meta:
        db_table = "badms_storage_infrastructure"

    @property
    def available_bytes(self) -> int:
        return max(self.capacity_bytes - self.allocated_bytes, 0)

    def __str__(self) -> str:
        return f"{self.name} ({self.available_bytes}B available)"


class StorageExtensionRequest(TimeStampedModel, UserScopedModel):
    """A user's request for more storage when the quota is full
    (PS 3.4, CW-BA-02). Processing ends with the recorded HoD decision."""

    STATUS = [("submitted", "Submitted"), ("rejected", "Rejected"),
              ("approved", "Approved")]

    department = models.CharField(max_length=80, blank=True)
    requested_bytes = models.BigIntegerField()
    justification = models.TextField()
    attachment = models.CharField(max_length=300, blank=True)
    #: The usage the request was validated against (BR-BA-016).
    usage_at_request = models.BigIntegerField(default=0)
    quota_at_request = models.BigIntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS, default="submitted",
                              db_index=True)
    decided_by_user_id = models.IntegerField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "badms_storage_extension_request"
        indexes = [models.Index(fields=["department", "status"],
                                name="extension_dept_idx")]

    def __str__(self) -> str:
        return f"Storage extension {self.requested_bytes}B ({self.status})"


# -- Security administration (IT Security) --------------------------------------
class SecurityPolicy(TimeStampedModel):
    """An institute security policy governing encryption, access and related
    controls, defined and enforced by IT Security (UC-BA-020, BR-BA-021)."""

    name = models.CharField(max_length=120, unique=True)
    statement = models.TextField()
    applies_to = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)
    defined_by_user_id = models.IntegerField()

    class Meta:
        db_table = "badms_security_policy"

    def __str__(self) -> str:
        return f"Security policy {self.name}"


class RbacAssignment(TimeStampedModel, UserScopedModel):
    """A BADMS-scoped RBAC permission assignment managed by IT Security
    (UC-BA-019, AFR-BA-066). Module entry itself stays with the IAM."""

    permission_code = models.CharField(max_length=100, db_index=True)
    is_active = models.BooleanField(default=True)
    granted_by_user_id = models.IntegerField()

    class Meta:
        db_table = "badms_rbac_assignment"
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "permission_code"],
                name="badms_rbac_user_permission"),
        ]

    def __str__(self) -> str:
        return f"{self.permission_code} -> user {self.user_id}"


# -- Audit -----------------------------------------------------------------------
class AuditEvent(TimeStampedModel):
    """A timestamped audit record (PS 3.7, UC-BA-023).

    `actor_kind` separates user, administrative, system and security events;
    `actor_user_id` is null for system-originated events, which carry an
    event-source identifier instead.
    """

    ACTOR_KIND = [("user", "User"), ("admin", "Administrative"),
                  ("system", "System"), ("security", "Security")]

    actor_user_id = models.IntegerField(null=True, blank=True)
    actor_kind = models.CharField(max_length=10, choices=ACTOR_KIND,
                                  default="user")
    actor_label = models.CharField(max_length=80, blank=True,
                                   help_text="Event-source identifier when no "
                                             "human actor exists.")
    action = models.CharField(max_length=80, db_index=True)
    outcome = models.CharField(max_length=12)      # success | failure | denied
    object_type = models.CharField(max_length=40, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    detail = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "badms_audit_event"
        indexes = [
            models.Index(fields=["action", "-created_at"],
                         name="audit_action_idx"),
            models.Index(fields=["actor_kind", "-created_at"],
                         name="audit_actor_idx"),
        ]

    def __str__(self) -> str:
        actor = self.actor_user_id if self.actor_user_id is not None \
            else self.actor_label or "system"
        return f"{self.action} by {actor} -> {self.outcome}"


# -- Notification outbox ----------------------------------------------------------
class NotificationOutbox(TimeStampedModel):
    """A notification BADMS decided to send.

    Written in the same transaction as the event that caused it and drained by
    a separate worker; `dedupe_key` makes redelivery idempotent.
    """

    STATUS = [("pending", "Pending"), ("sending", "Sending"), ("sent", "Sent"),
              ("failed", "Failed"), ("suppressed", "Suppressed")]

    topic = models.CharField(max_length=60, db_index=True)
    dedupe_key = models.CharField(max_length=200, unique=True)
    recipient_user_id = models.IntegerField(null=True, blank=True)
    recipient_email = models.EmailField(blank=True)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default="pending")
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=300, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "badms_notification_outbox"
        indexes = [
            models.Index(fields=["status", "created_at"],
                         name="badms_outbox_pending_idx"),
            models.Index(fields=["recipient_user_id", "-created_at"],
                         name="badms_outbox_recip_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.topic} -> {self.recipient_user_id or self.recipient_email}"
