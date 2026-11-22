import { useState } from "react";
import { Card, Container, TextInput } from "@mantine/core";
import { FaHistory } from "react-icons/fa";

import { DataTable } from "../../../ui/components/DataTable";
import { ErrorState } from "../../../ui/components/ErrorState";
import { PageHeader } from "../../../ui/components/PageHeader";
import { useAudit } from "../api/hooks";
import type { AuditEvent } from "../api/types";
import { formatWhen } from "./format";

/** The SysAdmin's audit trail (UC-BA-012): timestamp, actor, action, outcome. */
export default function AuditPage() {
  const [action, setAction] = useState("");
  const { data, isPending, error } = useAudit(action || undefined);

  if (error) return <Container size="xl"><ErrorState error={error} /></Container>;

  return (
    <Container size="xl">
      <PageHeader title="Audit Logs"
        subtitle="User, administrative, system and security events" />
      <Card padding="lg">
        <TextInput
          mb="sm" w={320} placeholder="Filter by action"
          value={action} onChange={(e) => setAction(e.currentTarget.value)} />
        <DataTable<AuditEvent>
          rows={data ?? []}
          loading={isPending}
          rowKey={(r) => r.id}
          minWidth={900}
          columns={[
            { key: "created_at", header: "When",
              render: (r) => formatWhen(r.created_at) },
            { key: "actor", header: "Actor",
              render: (r) => r.actor_user_id != null
                ? `user ${r.actor_user_id}`
                : r.actor_label || "system" },
            { key: "kind", header: "Kind", render: (r) => r.actor_kind },
            { key: "action", header: "Action", render: (r) => r.action },
            { key: "outcome", header: "Outcome", render: (r) => r.outcome },
            { key: "object", header: "Object",
              render: (r) => r.object_type
                ? `${r.object_type} ${r.object_id}` : "—" },
            { key: "detail", header: "Detail",
              render: (r) => r.detail || "—" },
          ]}
          empty={{ icon: FaHistory, title: "No audit events match" }}
        />
      </Card>
    </Container>
  );
}
