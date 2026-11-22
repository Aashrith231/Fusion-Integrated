import { useState } from "react";
import {
  Button, Card, Container, Group, Select, Stack, Text, Textarea,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { FaUndo } from "react-icons/fa";

import { useAuth } from "../../../auth/AuthProvider";
import { errorMessage } from "../../../lib/http";
import { DataTable } from "../../../ui/components/DataTable";
import { ErrorState } from "../../../ui/components/ErrorState";
import { FormModal } from "../../../ui/components/FormModal";
import { PageHeader } from "../../../ui/components/PageHeader";
import { StatusBadge } from "../../../ui/components/StatusBadge";
import {
  useArchivalQueue, useDecideRestoration, useExecuteRestoration,
  useRequestRestoration, useRestorations,
} from "../api/hooks";
import type { ArchivalRequest, Restoration } from "../api/types";
import { formatWhen } from "./format";

export default function RestorationPage() {
  const { can } = useAuth();
  const restorations = useRestorations();
  const queue = useArchivalQueue();
  const request = useRequestRestoration();
  const decide = useDecideRestoration();
  const execute = useExecuteRestoration();
  const [open, setOpen] = useState(false);
  const [archivalId, setArchivalId] = useState<string | null>(null);
  const [note, setNote] = useState("");

  if (restorations.error) {
    return (
      <Container size="xl"><ErrorState error={restorations.error} /></Container>
    );
  }
  const canApprove = can("badms.restoration.approve");
  const canExecute = can("badms.restoration.execute");

  function submitRequest() {
    request.mutateAsync({ archival: Number(archivalId), note }).then(() => {
      notifications.show({ color: "green", title: "Request recorded",
        message: "Sensitive data waits for SysAdmin approval; the rest runs now." });
      setOpen(false);
      setArchivalId(null);
      setNote("");
    }).catch((e) => notifications.show({
      color: "red", title: "Not recorded", message: errorMessage(e) }));
  }

  function act(id: number, action: "approve" | "reject" | "execute") {
    const call = action === "execute"
      ? execute.mutateAsync(id)
      : decide.mutateAsync({ id, decision: action });
    call.then(() => notifications.show({
      color: "green", title: "Done", message: "Restoration updated.",
    })).catch((e) => notifications.show({
      color: "red", title: "Not recorded", message: errorMessage(e) }));
  }

  const restorable = (queue.data ?? []).filter((r) =>
    r.status === "classified" || r.status === "encrypted");
  const canSeeQueue = canApprove || canExecute;

  return (
    <Container size="xl">
      <PageHeader title="Restoration"
        subtitle={"Sensitive data needs SysAdmin approval before restoration; " +
          "non-Sensitive data takes the standard path"}
        action={can("badms.restoration.request") && (
          <Button leftSection={<FaUndo size={12} />} onClick={() => setOpen(true)}>
            Request restoration
          </Button>
        )}
      />
      <Card padding="lg" mb="md">
        <Text fw={600} mb="sm">Restoration requests</Text>
        <DataTable<Restoration>
          rows={restorations.data ?? []}
          loading={restorations.isPending}
          rowKey={(r) => r.id}
          columns={[
            { key: "file", header: "Archived data",
              render: (r) => (
                <Stack gap={0}>
                  <Text fw={600}>{r.archival_file_name}</Text>
                  <Text size="xs" c="dimmed">{r.classification}</Text>
                </Stack>
              ) },
            { key: "status", header: "Status",
              render: (r) => <StatusBadge status={r.status} /> },
            { key: "decided_at", header: "Decided",
              render: (r) => formatWhen(r.decided_at) },
            { key: "executed_at", header: "Executed",
              render: (r) => formatWhen(r.executed_at) },
            { key: "error", header: "Error",
              render: (r) => (r.error
                ? <Text size="xs" c="red">{r.error}</Text> : "—") },
            { key: "actions", header: "",
              render: (r) => (
                <Group gap="xs">
                  {canApprove && r.status === "pending_approval" && (
                    <>
                      <Button size="xs" onClick={() => act(r.id, "approve")}>
                        Approve
                      </Button>
                      <Button size="xs" color="red" variant="light"
                        onClick={() => act(r.id, "reject")}>Reject</Button>
                    </>
                  )}
                  {canExecute && (r.status === "requested" ||
                    r.status === "approved_for_restoration") && (
                    <Button size="xs" onClick={() => act(r.id, "execute")}>
                      Execute
                    </Button>
                  )}
                </Group>
              ) },
          ]}
          empty={{ icon: FaUndo, title: "No restoration requests" }}
        />
      </Card>
      {canSeeQueue && (
        <Card padding="lg">
          <Text fw={600} mb="sm">Archived data available for restoration</Text>
          <DataTable<ArchivalRequest>
            rows={restorable}
            loading={queue.isPending}
            rowKey={(r) => r.id}
            columns={[
              { key: "file_name", header: "File",
                render: (r) => r.file_name },
              { key: "classification", header: "Classification",
                render: (r) => r.classification },
              { key: "status", header: "State",
                render: (r) => <StatusBadge status={r.status} /> },
            ]}
            empty={{ icon: FaUndo, title: "Nothing archived and restorable" }}
          />
        </Card>
      )}
      {open && (
        <FormModal opened onClose={() => setOpen(false)} title="Request restoration"
          subtitle="Pick an archived dataset you own."
          onSubmit={submitRequest} submitting={request.isPending}>
          <Stack>
            <Select
              label="Archived data"
              data={restorable.map((r) => ({
                value: String(r.id),
                label: `${r.file_name} (${r.classification})`,
              }))}
              value={archivalId} onChange={setArchivalId} />
            <Textarea label="Note (optional)" value={note}
              onChange={(e) => setNote(e.currentTarget.value)} />
          </Stack>
        </FormModal>
      )}
    </Container>
  );
}
