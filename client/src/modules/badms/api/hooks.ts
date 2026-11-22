/** Data access for the BADMS module.
 *
 *  Every mutation invalidates the module's keys; no manual cache surgery.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "../../../lib/http";
import type {
  ArchivalRequest, AuditEvent, Backup, DepartmentReport, Infrastructure,
  MyRequest, Repository, Restoration, RbacAssignment, Schedule,
  ScheduleChange, SecurityAudit, SecurityPolicy, SpecialArchival,
  StorageExtension, StorageProfile,
} from "./types";

const KEY = "badms";

export const keys = {
  backups: () => [KEY, "backups"] as const,
  repositories: () => [KEY, "repositories"] as const,
  schedules: () => [KEY, "schedules"] as const,
  scheduleChanges: (id: number) => [KEY, "schedule-changes", id] as const,
  archival: () => [KEY, "archival"] as const,
  archivalMine: () => [KEY, "archival-mine"] as const,
  archivalDetail: (id: number) => [KEY, "archival", id] as const,
  specialArchival: () => [KEY, "special-archival"] as const,
  restorations: () => [KEY, "restorations"] as const,
  myStorage: () => [KEY, "my-storage"] as const,
  extensions: () => [KEY, "extensions"] as const,
  extensionsMine: () => [KEY, "extensions-mine"] as const,
  infrastructure: () => [KEY, "infrastructure"] as const,
  audit: (action?: string) => [KEY, "audit", action] as const,
  securityAudit: () => [KEY, "security-audit"] as const,
  policies: () => [KEY, "policies"] as const,
  rbac: () => [KEY, "rbac"] as const,
  departmentReport: (dept: string) => [KEY, "report", dept] as const,
  myRequests: () => [KEY, "my-requests"] as const,
};

function invalidateAll(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: [KEY] });
}

/** Common mutation wiring: invalidate the module's keys after any write. */
function useBadmsMutation<TVariables, TData = unknown>(
  fn: (vars: TVariables) => Promise<TData>,
) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => invalidateAll(qc) });
}

// -- Backups ---------------------------------------------------------------------
export function useBackups() {
  return useQuery({
    queryKey: keys.backups(),
    queryFn: async () =>
      (await http.get<Backup[]>("/badms/backups")).data,
  });
}

export function useRepositories() {
  return useQuery({
    queryKey: keys.repositories(),
    queryFn: async () =>
      (await http.get<Repository[]>("/badms/repositories")).data,
  });
}

export function useTriggerBackup() {
  return useBadmsMutation((payload: { repository?: number; dataset?: string }) =>
    http.post("/badms/backups/manual", payload));
}

// -- Schedules ---------------------------------------------------------------------
export function useSchedules() {
  return useQuery({
    queryKey: keys.schedules(),
    queryFn: async () =>
      (await http.get<Schedule[]>("/badms/schedules")).data,
  });
}

export function useCreateSchedule() {
  return useBadmsMutation(
    (payload: Record<string, unknown>) => http.post("/badms/schedules/create",
      payload));
}

export function useModifySchedule() {
  return useBadmsMutation(
    ({ id, ...payload }: { id: number } & Record<string, unknown>) =>
      http.patch(`/badms/schedules/${id}/modify`, payload));
}

export function useGlobalSchedule() {
  return useQuery({
    queryKey: [KEY, "global-schedule"],
    queryFn: async () =>
      (await http.get<Schedule | null>("/badms/schedules/global")).data,
  });
}

export function useSetGlobalSchedule() {
  return useBadmsMutation(
    (payload: Record<string, unknown>) => http.put("/badms/schedules/global",
      payload));
}

export function useScheduleChanges(id: number) {
  return useQuery({
    queryKey: keys.scheduleChanges(id),
    enabled: id > 0,
    queryFn: async () =>
      (await http.get<ScheduleChange[]>(`/badms/schedules/${id}/changes`)).data,
  });
}

// -- Archival ----------------------------------------------------------------------
export function useArchivalQueue() {
  return useQuery({
    queryKey: keys.archival(),
    queryFn: async () =>
      (await http.get<ArchivalRequest[]>("/badms/archival")).data,
  });
}

export function useMyArchival() {
  return useQuery({
    queryKey: keys.archivalMine(),
    queryFn: async () =>
      (await http.get<ArchivalRequest[]>("/badms/archival/mine")).data,
  });
}

export function useArchivalDetail(id: number) {
  return useQuery({
    queryKey: keys.archivalDetail(id),
    enabled: id > 0,
    queryFn: async () =>
      (await http.get<ArchivalRequest>(`/badms/archival/${id}`)).data,
  });
}

export function useSubmitArchival() {
  return useBadmsMutation(
    (payload: Record<string, unknown>) => http.post("/badms/archival/submit",
      payload));
}

export function useDecideArchival() {
  return useBadmsMutation(
    ({ id, decision, note }: { id: number; decision: string; note?: string }) =>
      http.post(`/badms/archival/${id}/decide`, { decision, note }));
}

export function useClassifyArchival() {
  return useBadmsMutation(
    ({ id, classification, note }: {
      id: number; classification: string; note?: string;
    }) => http.post(`/badms/archival/${id}/classify`, { classification, note }));
}

export function useConfigureEncryption() {
  return useBadmsMutation(
    ({ id, key_ref }: { id: number; key_ref: string }) =>
      http.post(`/badms/archival/${id}/encryption`, { key_ref }));
}

// -- Special archival ----------------------------------------------------------------
export function useSpecialArchival() {
  return useQuery({
    queryKey: keys.specialArchival(),
    queryFn: async () =>
      (await http.get<SpecialArchival[]>("/badms/special-archival")).data,
  });
}

export function usePerformSpecialArchival() {
  return useBadmsMutation(
    (payload: { data_reference: string; reason?: string }) =>
      http.post("/badms/special-archival/perform", payload));
}

// -- Restoration -----------------------------------------------------------------------
export function useRestorations() {
  return useQuery({
    queryKey: keys.restorations(),
    queryFn: async () =>
      (await http.get<Restoration[]>("/badms/restorations")).data,
  });
}

export function useRequestRestoration() {
  return useBadmsMutation(
    (payload: { archival: number; note?: string }) =>
      http.post("/badms/restorations/request", payload));
}

export function useDecideRestoration() {
  return useBadmsMutation(
    ({ id, decision }: { id: number; decision: string }) =>
      http.post(`/badms/restorations/${id}/decide`, { decision }));
}

export function useExecuteRestoration() {
  return useBadmsMutation((id: number) =>
    http.post(`/badms/restorations/${id}/execute`, {}));
}

// -- Storage -----------------------------------------------------------------------------
export function useMyStorage() {
  return useQuery({
    queryKey: keys.myStorage(),
    queryFn: async () =>
      (await http.get<StorageProfile>("/badms/storage/me")).data,
  });
}

export function useExtensionQueue() {
  return useQuery({
    queryKey: keys.extensions(),
    queryFn: async () =>
      (await http.get<StorageExtension[]>("/badms/storage/extensions")).data,
  });
}

export function useMyExtensions() {
  return useQuery({
    queryKey: keys.extensionsMine(),
    queryFn: async () =>
      (await http.get<StorageExtension[]>("/badms/storage/extensions/mine"))
        .data,
  });
}

export function useInfrastructure() {
  return useQuery({
    queryKey: keys.infrastructure(),
    queryFn: async () =>
      (await http.get<Infrastructure>("/badms/storage/infrastructure")).data,
  });
}

export function useSubmitExtension() {
  return useBadmsMutation(
    (payload: { requested_bytes: number; justification: string }) =>
      http.post("/badms/storage/extensions/submit", payload));
}

export function useDecideExtension() {
  return useBadmsMutation(
    ({ id, decision }: { id: number; decision: string }) =>
      http.post(`/badms/storage/extensions/${id}/decide`, { decision }));
}

// -- Audit, security, reports ---------------------------------------------------------------
export function useAudit(action?: string) {
  return useQuery({
    queryKey: keys.audit(action),
    queryFn: async () => {
      const params = action ? { action } : undefined;
      return (await http.get<AuditEvent[]>("/badms/audit", { params })).data;
    },
  });
}

export function useSecurityAudit() {
  return useQuery({
    queryKey: keys.securityAudit(),
    queryFn: async () =>
      (await http.get<SecurityAudit>("/badms/security/audit")).data,
  });
}

export function usePolicies() {
  return useQuery({
    queryKey: keys.policies(),
    queryFn: async () =>
      (await http.get<SecurityPolicy[]>("/badms/security/policies")).data,
  });
}

export function useDefinePolicy() {
  return useBadmsMutation(
    (payload: { name: string; statement: string; applies_to?: string }) =>
      http.post("/badms/security/policies", payload));
}

export function useUpdatePolicy() {
  return useBadmsMutation(
    ({ id, ...payload }: { id: number } & Record<string, unknown>) =>
      http.patch(`/badms/security/policies/${id}`, payload));
}

export function useRbac() {
  return useQuery({
    queryKey: keys.rbac(),
    queryFn: async () =>
      (await http.get<RbacAssignment[]>("/badms/security/rbac")).data,
  });
}

export function useManageRbac() {
  return useBadmsMutation(
    (payload: {
      user_id: number; permission_code: string; action: "grant" | "revoke";
    }) => http.post("/badms/security/rbac", payload));
}

export function useDepartmentReport(department: string) {
  return useQuery({
    queryKey: keys.departmentReport(department),
    enabled: department.length > 0,
    queryFn: async () =>
      (await http.get<DepartmentReport>("/badms/reports/department",
        { params: { department } })).data,
  });
}

export function useMyRequests() {
  return useQuery({
    queryKey: keys.myRequests(),
    queryFn: async () =>
      (await http.get<MyRequest[]>("/badms/me/requests")).data,
  });
}
