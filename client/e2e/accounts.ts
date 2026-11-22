// Synthetic fusion-dev.dump accounts. Global setup grants each one its `grants` in the IAM.
export const PASSWORD = process.env.E2E_PASSWORD ?? "fusion123";

export interface Account {
  username: string;
  role: string;
  grants: readonly string[];
}

export const ACCOUNTS = {
  student: { username: "stu00001", role: "ug_student", grants: [] },
  placementOfficer: {
    username: "stf00062", role: "placement_officer", grants: ["placement_officer"],
  },
  // BADMS: the sysadmin runs backups, schedules and classification
  // (registry.py ROLE_GRANTS). `hod` decides department queues.
  badmsSysadmin: {
    username: "stf00063", role: "sysadmin", grants: ["sysadmin"],
  },
  badmsHod: {
    username: "stf00064", role: "hod", grants: ["hod"],
  },
} as const satisfies Record<string, Account>;

export type AccountKey = keyof typeof ACCOUNTS;
