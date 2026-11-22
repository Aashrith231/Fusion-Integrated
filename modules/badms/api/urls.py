from django.urls import path

from modules.badms.api import views as v

urlpatterns = [
    # backups
    path("backups", v.BackupListView.as_view(), name="badms-backups"),
    path("backups/manual", v.ManualBackupView.as_view(),
         name="badms-manual-backup"),
    path("repositories", v.RepositoryListView.as_view(),
         name="badms-repositories"),

    # schedules
    path("schedules", v.ScheduleListView.as_view(), name="badms-schedules"),
    path("schedules/create", v.ScheduleCreateView.as_view(),
         name="badms-schedule-create"),
    path("schedules/global", v.GlobalScheduleView.as_view(),
         name="badms-global-schedule"),
    path("schedules/<int:pk>/modify", v.ScheduleModifyView.as_view(),
         name="badms-schedule-modify"),
    path("schedules/<int:pk>/changes", v.ScheduleChangeLogView.as_view(),
         name="badms-schedule-changes"),

    # secure archival
    path("archival", v.ArchivalListView.as_view(), name="badms-archival"),
    path("archival/submit", v.ArchivalSubmitView.as_view(),
         name="badms-archival-submit"),
    path("archival/mine", v.ArchivalMineView.as_view(),
         name="badms-archival-mine"),
    path("archival/<int:pk>", v.ArchivalDetailView.as_view(),
         name="badms-archival-detail"),
    path("archival/<int:pk>/decide", v.ArchivalDecideView.as_view(),
         name="badms-archival-decide"),
    path("archival/<int:pk>/classify", v.ArchivalClassifyView.as_view(),
         name="badms-archival-classify"),
    path("archival/<int:pk>/encryption", v.ArchivalEncryptionView.as_view(),
         name="badms-archival-encryption"),

    # special archival
    path("special-archival", v.SpecialArchivalListView.as_view(),
         name="badms-special-archival-list"),
    path("special-archival/perform", v.SpecialArchivalView.as_view(),
         name="badms-special-archival"),

    # restoration
    path("restorations", v.RestorationListView.as_view(),
         name="badms-restorations"),
    path("restorations/request", v.RestorationRequestView.as_view(),
         name="badms-restoration-request"),
    path("restorations/<int:pk>/decide", v.RestorationDecideView.as_view(),
         name="badms-restoration-decide"),
    path("restorations/<int:pk>/execute", v.RestorationExecuteView.as_view(),
         name="badms-restoration-execute"),

    # storage
    path("storage/me", v.MyStorageView.as_view(), name="badms-my-storage"),
    path("storage/extensions", v.StorageExtensionQueueView.as_view(),
         name="badms-storage-extensions"),
    path("storage/extensions/submit", v.StorageExtensionSubmitView.as_view(),
         name="badms-storage-extension-submit"),
    path("storage/extensions/mine", v.StorageExtensionMineView.as_view(),
         name="badms-storage-extensions-mine"),
    path("storage/extensions/<int:pk>/decide",
         v.StorageExtensionDecideView.as_view(),
         name="badms-storage-extension-decide"),
    path("storage/infrastructure", v.InfrastructureView.as_view(),
         name="badms-infrastructure"),

    # audit and security
    path("audit", v.AuditLogView.as_view(), name="badms-audit"),
    path("security/audit", v.SecurityAuditView.as_view(),
         name="badms-security-audit"),
    path("security/policies", v.SecurityPolicyListView.as_view(),
         name="badms-security-policies"),
    path("security/policies/<int:pk>",
         v.SecurityPolicyDetailView.as_view(),
         name="badms-security-policy"),
    path("security/rbac", v.RbacView.as_view(), name="badms-rbac"),

    # reports and tracking
    path("reports/department", v.DepartmentReportView.as_view(),
         name="badms-department-report"),
    path("me/requests", v.MyRequestsView.as_view(), name="badms-my-requests"),
]
