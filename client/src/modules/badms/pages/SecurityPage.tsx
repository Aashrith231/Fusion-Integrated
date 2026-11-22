import { useState } from "react";
import {
  Button, Card, Container, Group, NumberInput, Select, Stack, Switch, Text,
  Textarea, TextInput, Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { FaShieldAlt } from "react-icons/fa";

import { errorMessage } from "../../../lib/http";
import { DataTable } from "../../../ui/components/DataTable";
import { ErrorState } from "../../../ui/components/ErrorState";
import { FormModal } from "../../../ui/components/FormModal";
import { PageHeader } from "../../../ui/components/PageHeader";
import { StatusBadge } from "../../../ui/components/StatusBadge";
import {
  useDefinePolicy, useManageRbac, usePolicies, useRbac, useSecurityAudit,
  useUpdatePolicy,
} from "../api/hooks";
import type { AuditEvent, RbacAssignment, SecurityPolicy } from "../api/types";
import { formatWhen } from "./format";

const PERMISSION_CODES = [
  "badms.backup.trigger", "badms.schedule.manage",
  "badms.schedule.manage_global", "badms.archival.submit",
  "badms.archival.decide", "badms.archival.classify",
  "badms.encryption.manage", "badms.special_archival.perform",
  "badms.restoration.request", "badms.restoration.approve",
  "badms.restoration.execute", "badms.storage.request",
  "badms.storage.decide", "badms.audit.view", "badms.security.audit",
  "badms.report.department",
];

function PolicyForm({ onClose }: { onClose: () => void }) {
  const define = useDefinePolicy();
  const [name, setName] = useState("");
  const [statement, setStatement] = useState("");
  const [applies, setApplies] = useState("");

  function submit() {
    define.mutateAsync({ name, statement, applies_to: applies }).then(() => {
      notifications.show({ color: "green", title: "Policy defined",
        message: "The policy is active and audited." });
      onClose();
    }).catch((e) => notifications.show({
      color: "red", title: "Not defined", message: errorMessage(e) }));
  }

  return (
    <FormModal opened onClose={onClose} title="Define security policy"
      subtitle="Governs encryption, access and related security controls."
      onSubmit={submit} submitting={define.isPending}>
      <Stack>
        <TextInput label="Name" value={name}
          onChange={(e) => setName(e.currentTarget.value)} />
        <Textarea label="Statement" value={statement}
          onChange={(e) => setStatement(e.currentTarget.value)} />
        <TextInput label="Applies to (optional)" value={applies}
          onChange={(e) => setApplies(e.currentTarget.value)} />
      </Stack>
    </FormModal>
  );
}

export default function SecurityPage() {
  const policies = usePolicies();
  const rbac = useRbac();
  const audit = useSecurityAudit();
  const updatePolicy = useUpdatePolicy();
  const manageRbac = useManageRbac();
  const [open, setOpen] = useState(false);
  const [rbacUser, setRbacUser] = useState<number | undefined>();
  const [rbacCode, setRbacCode] = useState<string | null>(null);

  if (policies.error || rbac.error || audit.error) {
    return (
      <Container size="xl">
        <ErrorState error={policies.error ?? rbac.error ?? audit.error} />
      </Container>
    );
  }

  function setRbac(action: "grant" | "revoke") {
    if (!rbacUser || !rbacCode) return;
    manageRbac.mutateAsync({ user_id: rbacUser, permission_code: rbacCode,
      action }).then(() => {
      notifications.show({ color: "green", title: `Permission ${action}ed`,
        message: "RBAC changes are audited." });
    }).catch((e) => notifications.show({
      color: "red", title: "Not applied", message: errorMessage(e) }));
  }

  return (
    <Container size="xl">
      <PageHeader
        title="Security"
        subtitle="Policies, RBAC assignments and the security audit trail"
        action={(
          <Button leftSection={<FaShieldAlt size={12} />}
            onClick={() => setOpen(true)}>
            Define policy
          </Button>
        )}
      />
      <Card padding="lg" mb="md">
        <Title order={4} mb="sm">Security policies</Title>
        <DataTable<SecurityPolicy>
          rows={policies.data ?? []}
          loading={policies.isPending}
          rowKey={(r) => r.id}
          columns={[
            { key: "name", header: "Name", render: (r) => r.name },
            { key: "statement", header: "Statement",
              render: (r) => r.statement },
            { key: "applies_to", header: "Applies to",
              render: (r) => r.applies_to || "—" },
            { key: "active", header: "Active",
              render: (r) => (
                <Switch size="sm" checked={r.is_active}
                  onChange={(e) => updatePolicy.mutateAsync({
                    id: r.id, is_active: e.currentTarget.checked })} />
              ) },
            { key: "created_at", header: "Defined",
              render: (r) => formatWhen(r.created_at) },
          ]}
          empty={{ icon: FaShieldAlt, title: "No security policies defined" }}
        />
      </Card>
      <Card padding="lg" mb="md">
        <Title order={4} mb="sm">RBAC assignments</Title>
        <Group align="end" mb="sm">
          <NumberInput label="User id" min={1} value={rbacUser}
            onChange={(v) => setRbacUser(Number(v) || undefined)} />
          <Select label="Permission" w={280} searchable
            data={PERMISSION_CODES.map((c) => ({ value: c, label: c }))}
            value={rbacCode} onChange={setRbacCode} />
          <Button onClick={() => setRbac("grant")}>Grant</Button>
          <Button color="red" variant="light" onClick={() => setRbac("revoke")}>
            Revoke
          </Button>
        </Group>
        <DataTable<RbacAssignment>
          rows={rbac.data ?? []}
          loading={rbac.isPending}
          rowKey={(r) => r.id}
          columns={[
            { key: "user_id", header: "User",
              render: (r) => String(r.user_id) },
            { key: "permission_code", header: "Permission",
              render: (r) => r.permission_code },
            { key: "is_active", header: "Active",
              render: (r) => (r.is_active ? "yes" : "revoked") },
            { key: "granted_by_user_id", header: "Granted by",
              render: (r) => String(r.granted_by_user_id) },
          ]}
          empty={{ icon: FaShieldAlt, title: "No RBAC assignments yet" }}
        />
      </Card>
      <Card padding="lg">
        <Title order={4} mb="sm">Unauthorised-access candidates</Title>
        <Text size="sm" c="dimmed" mb="sm">
          Denied and failed actions across the audit trail.
        </Text>
        <DataTable<AuditEvent>
          rows={audit.data?.recent ?? []}
          loading={audit.isPending}
          rowKey={(r) => r.id}
          minWidth={820}
          columns={[
            { key: "created_at", header: "When",
              render: (r) => formatWhen(r.created_at) },
            { key: "actor", header: "Actor",
              render: (r) => r.actor_user_id != null
                ? `user ${r.actor_user_id}` : r.actor_label },
            { key: "action", header: "Action", render: (r) => r.action },
            { key: "outcome", header: "Outcome",
              render: (r) => <StatusBadge status={r.outcome} /> },
            { key: "detail", header: "Detail",
              render: (r) => r.detail || "—" },
          ]}
          empty={{ icon: FaShieldAlt, title: "Nothing suspicious recorded" }}
        />
      </Card>
      {open && <PolicyForm onClose={() => setOpen(false)} />}
    </Container>
  );
}
