/** BADMS data shapes, mirroring the serializers in modules/badms/api. */

export interface Backup {
  id: number;
  kind: "manual" | "scheduled";
  status: "running" | "success" | "failed";
  repository: number;
  dataset: string;
  classification_filter: string[];
  trigger_user_id: number | null;
  started_at: string;
  finished_at: string | null;
  integrity_verified: boolean;
  artifact_ref?: string;
  error: string;
  consecutive_failures: number;
  created_at: string;
}

export interface Repository {
  id: number;
  name: string;
  kind: string;
  reachable: boolean;
  capacity_bytes: number | null;
}

export interface Schedule {
  id: number;
  scope: "local" | "global";
  dataset: string;
  frequency: "daily" | "weekly" | "monthly";
  run_at: string;
  weekday: number | null;
  classification_filter: string[];
  repository: number;
  repository_name: string;
  is_active: boolean;
  created_by_user_id: number;
  created_at: string;
}

export interface ScheduleChange {
  action: string;
  changed_by_user_id: number;
  summary: string;
  at: string;
}

export interface ArchivalDecisionRow {
  stage: string;
  decision: string;
  note: string;
  at: string;
  decided_by_user_id: number;
}

export interface ArchivalRequest {
  id: number;
  user_id: number;
  file_name: string;
  file_date: string;
  owners: string;
  file_type: string;
  reason: string;
  attachment: string;
  attachment_size_bytes: number;
  initial_classification: string;
  department: string;
  classification: string;
  status: string;
  retention_rule: string;
  encryption_algorithm: string;
  encrypted_at: string | null;
  created_at: string;
  history?: ArchivalDecisionRow[];
}

export interface SpecialArchival {
  id: number;
  performed_by_user_id: number;
  data_reference: string;
  reason: string;
  outcome: string;
  note: string;
  created_at: string;
}

export interface Restoration {
  id: number;
  user_id: number;
  archival: number;
  archival_file_name: string;
  classification: string;
  status: string;
  note: string;
  decided_by_user_id: number | null;
  decided_at: string | null;
  executed_by_user_id: number | null;
  executed_at: string | null;
  error: string;
  created_at: string;
}

export interface StorageProfile {
  quota_bytes: number;
  used_bytes: number;
  full: boolean;
  checked_at: string | null;
}

export interface StorageExtension {
  id: number;
  user_id: number;
  department: string;
  requested_bytes: number;
  justification: string;
  attachment: string;
  usage_at_request: number;
  quota_at_request: number;
  status: string;
  decided_by_user_id: number | null;
  decided_at: string | null;
  created_at: string;
}

export interface Infrastructure {
  name: string;
  capacity_bytes: number;
  allocated_bytes: number;
  available_bytes: number;
}

export interface SecurityPolicy {
  id: number;
  name: string;
  statement: string;
  applies_to: string;
  is_active: boolean;
  defined_by_user_id: number;
  created_at: string;
}

export interface RbacAssignment {
  id: number;
  user_id: number;
  permission_code: string;
  is_active: boolean;
  granted_by_user_id: number;
}

export interface AuditEvent {
  id: number;
  actor_user_id: number | null;
  actor_kind: string;
  actor_label: string;
  action: string;
  outcome: string;
  object_type: string;
  object_id: string;
  detail: string;
  created_at: string;
}

export interface SecurityAudit {
  candidates: {
    action: string;
    outcome: string;
    at: string;
    actor_user_id: number | null;
    actor_kind: string;
    detail: string;
  }[];
  recent: AuditEvent[];
}

export interface DepartmentReport {
  department: string;
  archival_by_status: Record<string, number>;
  storage_extensions_by_status: Record<string, number>;
  archival_total: number;
  storage_extension_total: number;
  backup_operations: Record<string, number>;
}

export interface MyRequest {
  kind: string;
  id: number;
  title: string;
  status: string;
  updated_at: string;
}
