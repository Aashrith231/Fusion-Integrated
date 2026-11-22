"""What the server tells the shell about BADMS (ADR-0010).

Role boundaries follow the synchronised problem statement: IT Security owns
security/encryption/RBAC policy, the Super Admin owns institution-wide global
backup schedules and default backup policy, the SysAdmin owns local schedules
and technical execution, and a HoD acts only within their department.
"""
MODULE = {
    "code": "badms", "label": "Backup & Archive", "icon": "FaDatabase",
    "base_path": "/badms", "nav_section": "Data Management", "sort_order": 20,
    "status": "active",
}

NAV_ITEMS = [
    {"code": "badms.backups", "label": "Backup Status",
     "icon": "FaDatabase", "to": "/badms/backups",
     "required_permission": "badms.backup.view", "sort_order": 5},
    {"code": "badms.schedules", "label": "Backup Schedules",
     "icon": "FaCalendarAlt", "to": "/badms/schedules",
     "required_permission": "badms.schedule.manage", "sort_order": 10},
    {"code": "badms.archival", "label": "Secure Archival",
     "icon": "FaBoxOpen", "to": "/badms/archival",
     "required_permission": "badms.archival.submit", "sort_order": 15},
    {"code": "badms.archival_review", "label": "Archival Review",
     "icon": "FaInbox", "to": "/badms/archival-review",
     "required_permission": "badms.archival.decide", "sort_order": 20},
    {"code": "badms.classification", "label": "Classification",
     "icon": "FaTags", "to": "/badms/classification",
     "required_permission": "badms.archival.classify", "sort_order": 25},
    {"code": "badms.encryption", "label": "Encryption",
     "icon": "FaLock", "to": "/badms/encryption",
     "required_permission": "badms.encryption.manage", "sort_order": 30},
    {"code": "badms.special_archival", "label": "Special Archival",
     "icon": "FaArchive", "to": "/badms/special-archival",
     "required_permission": "badms.special_archival.perform",
     "sort_order": 35},
    {"code": "badms.restoration", "label": "Restoration",
     "icon": "FaUndo", "to": "/badms/restoration",
     "required_permission": "badms.restoration.request", "sort_order": 40},
    {"code": "badms.storage", "label": "My Storage",
     "icon": "FaHdd", "to": "/badms/storage",
     "required_permission": "badms.storage.request", "sort_order": 45},
    {"code": "badms.storage_approvals", "label": "Storage Approvals",
     "icon": "FaClipboardCheck", "to": "/badms/storage-approvals",
     "required_permission": "badms.storage.decide", "sort_order": 50},
    {"code": "badms.audit", "label": "Audit Logs",
     "icon": "FaHistory", "to": "/badms/audit",
     "required_permission": "badms.audit.view", "sort_order": 55},
    {"code": "badms.security", "label": "Security",
     "icon": "FaShieldAlt", "to": "/badms/security",
     "required_permission": "badms.security.audit", "sort_order": 60},
    {"code": "badms.reports", "label": "Department Reports",
     "icon": "FaChartBar", "to": "/badms/reports",
     "required_permission": "badms.report.department", "sort_order": 65},
]

#: Every permission this module recognises; ROLE_GRANTS below says who holds each.
PERMISSIONS = [
    ("badms.backup.view", "View backup status and history"),
    ("badms.backup.trigger", "Trigger a manual backup"),
    ("badms.schedule.manage", "Create and modify local backup schedules"),
    ("badms.schedule.manage_global",
     "Define institution-wide global backup schedules and defaults"),
    ("badms.archival.submit", "Submit secure archival requests"),
    ("badms.archival.decide",
     "Approve or reject archival requests for one's own department"),
    ("badms.archival.classify",
     "Assign the authoritative archival classification"),
    ("badms.encryption.manage", "Configure encryption for Sensitive data"),
    ("badms.special_archival.perform", "Perform special archival operations"),
    ("badms.restoration.request", "Request restoration of archived data"),
    ("badms.restoration.approve", "Approve Sensitive data restoration"),
    ("badms.restoration.execute", "Execute technical restoration"),
    ("badms.storage.request", "Submit storage-extension requests"),
    ("badms.storage.decide",
     "Decide storage-extension requests for one's own department"),
    ("badms.audit.view", "View audit logs and activity history"),
    ("badms.security.audit", "Audit data activity and review security reports"),
    ("badms.rbac.manage", "Manage BADMS RBAC permission assignments"),
    ("badms.security_policy.manage", "Define and enforce security policies"),
    ("badms.report.department", "View departmental operational reports"),
]

#: Performed by a service or a scheduled task, so no designation holds them.
SYSTEM_PERMISSIONS = [
    "badms.backup.run_scheduled",
    "badms.storage.monitor",
    "badms.audit.record",
]

_STAFF_ALERT = "badms.audit.view"


def _user_perms() -> list[str]:
    return [
        "badms.backup.view",
        "badms.archival.submit",
        "badms.restoration.request",
        "badms.storage.request",
    ]


def _hod_perms() -> list[str]:
    return [
        *_user_perms(),
        "badms.archival.decide",
        "badms.storage.decide",
        "badms.report.department",
    ]


def _sysadmin_perms() -> list[str]:
    return [
        "badms.backup.view",
        "badms.backup.trigger",
        "badms.schedule.manage",
        "badms.archival.classify",
        "badms.restoration.approve",
        "badms.restoration.execute",
        "badms.audit.view",
    ]


def _it_security_perms() -> list[str]:
    return [
        "badms.backup.view",
        "badms.encryption.manage",
        "badms.security.audit",
        "badms.rbac.manage",
        "badms.security_policy.manage",
    ]


def _super_admin_perms() -> list[str]:
    return [
        *_sysadmin_perms(),
        "badms.schedule.manage_global",
        "badms.special_archival.perform",
    ]


#: Keyed by the designation name as it exists in the IAM.
ROLE_GRANTS = {
    "student": _user_perms(),
    "faculty": _user_perms(),
    "staff": _user_perms(),
    "hod": _hod_perms(),
    "sysadmin": _sysadmin_perms(),
    "it_security": _it_security_perms(),
    "super_admin": _super_admin_perms(),
}
