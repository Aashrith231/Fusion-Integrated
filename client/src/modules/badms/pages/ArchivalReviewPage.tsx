import { useState } from "react";
import {
  Button, Card, Container, Group, Stack, Text, Textarea,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { FaInbox } from "react-icons/fa";

import { errorMessage } from "../../../lib/http";
import { DataTable } from "../../../ui/components/DataTable";
import { ErrorState } from "../../../ui/components/ErrorState";
import { FormModal } from "../../../ui/components/FormModal";
import { PageHeader } from "../../../ui/components/PageHeader";
import { StatusBadge } from "../../../ui/components/StatusBadge";
import { useArchivalQueue, useDecideArchival } from "../api/hooks";
import type { ArchivalRequest } from "../api/types";
import { formatWhen } from "./format";

/** The HoD's review desk: only the department's own requests arrive here,
 *  because the server scopes the queue before it is sent. */
export default function ArchivalReviewPage() {
  const { data, isPending, error } = useArchivalQueue();
  const decide = useDecideArchival();
  const [deciding, setDeciding] = useState<
    { row: ArchivalRequest; decision: "approve" | "reject" } | null>(null);
  const [note, setNote] = useState("");

  if (error) return <Container size="xl"><ErrorState error={error} /></Container>;

  function submit() {
    if (!deciding) return;
    decide.mutateAsync({
      id: deciding.row.id, decision: deciding.decision, note,
    }).then(() => {
      notifications.show({ color: "green", title: "Decision recorded",
        message: deciding.decision === "approve"
          ? "Routed to the SysAdmin for classification."
          : "The requester has been notified." });
      setDeciding(null);
      setNote("");
    }).catch((e) => notifications.show({
      color: "red", title: "Not recorded", message: errorMessage(e) }));
  }

  const queue = (data ?? []).filter((r) => r.status === "submitted");

  return (
    <Container size="xl">
      <PageHeader title="Archival Review"
        subtitle="Secure archival requests from your department" />
      <Card padding="lg">
        <DataTable<ArchivalRequest>
          rows={queue}
          loading={isPending}
          rowKey={(r) => r.id}
          columns={[
            { key: "file_name", header: "File",
              render: (r) => (
                <Stack gap={0}>
                  <Text fw={600}>{r.file_name}</Text>
                  <Text size="xs" c="dimmed">
                    {r.owners} — {formatWhen(r.created_at)}
                  </Text>
                </Stack>
              ) },
            { key: "reason", header: "Reason", render: (r) => r.reason },
            { key: "initial", header: "Initial classification",
              render: (r) => r.initial_classification || "routine" },
            { key: "status", header: "Status",
              render: (r) => <StatusBadge status={r.status} /> },
            { key: "actions", header: "",
              render: (r) => (
                <Group gap="xs">
                  <Button size="xs" onClick={() =>
                    setDeciding({ row: r, decision: "approve" })}>
                    Approve
                  </Button>
                  <Button size="xs" color="red" variant="light" onClick={() =>
                    setDeciding({ row: r, decision: "reject" })}>
                    Reject
                  </Button>
                </Group>
              ) },
          ]}
          empty={{ icon: FaInbox, title: "Nothing awaiting review",
            description: "Requests from your department appear here." }}
        />
      </Card>
      {deciding && (
        <FormModal
          opened onClose={() => setDeciding(null)}
          title={deciding.decision === "approve" ? "Approve request"
            : "Reject request"}
          subtitle={deciding.row.file_name}
          onSubmit={submit} submitting={decide.isPending}
          danger={deciding.decision === "reject"}
          submitLabel={deciding.decision === "approve" ? "Approve" : "Reject"}>
          <Textarea label="Note (optional)" value={note}
            onChange={(e) => setNote(e.currentTarget.value)} />
        </FormModal>
      )}
    </Container>
  );
}
