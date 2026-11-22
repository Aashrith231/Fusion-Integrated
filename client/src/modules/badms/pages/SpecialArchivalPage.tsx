import { useState } from "react";
import { Button, Card, Container, Stack, TextInput } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { FaArchive } from "react-icons/fa";

import { errorMessage } from "../../../lib/http";
import { DataTable } from "../../../ui/components/DataTable";
import { ErrorState } from "../../../ui/components/ErrorState";
import { FormModal } from "../../../ui/components/FormModal";
import { PageHeader } from "../../../ui/components/PageHeader";
import { StatusBadge } from "../../../ui/components/StatusBadge";
import { usePerformSpecialArchival, useSpecialArchival } from "../api/hooks";
import type { SpecialArchival } from "../api/types";
import { formatWhen } from "./format";

/** The Super Admin's offline-triggered operation: the request originated
 *  outside BADMS, so what is recorded here is the operation and its outcome.
 */
export default function SpecialArchivalPage() {
  const { data, isPending, error } = useSpecialArchival();
  const perform = usePerformSpecialArchival();
  const [open, setOpen] = useState(false);
  const [reference, setReference] = useState("");
  const [reason, setReason] = useState("");

  if (error) return <Container size="xl"><ErrorState error={error} /></Container>;

  function submit() {
    perform.mutateAsync({ data_reference: reference, reason }).then(() => {
      notifications.show({ color: "green", title: "Operation recorded",
        message: "The special archival outcome and audit event are stored." });
      setOpen(false);
      setReference("");
      setReason("");
    }).catch((e) => notifications.show({
      color: "red", title: "Not recorded", message: errorMessage(e) }));
  }

  return (
    <Container size="xl">
      <PageHeader
        title="Special Archival"
        subtitle="Extended storage of Sensitive research data, requested offline"
        action={(
          <Button leftSection={<FaArchive size={12} />}
            onClick={() => setOpen(true)}>
            Perform operation
          </Button>
        )}
      />
      <Card padding="lg">
        <DataTable<SpecialArchival>
          rows={data ?? []}
          loading={isPending}
          rowKey={(r) => r.id}
          columns={[
            { key: "data_reference", header: "Data",
              render: (r) => r.data_reference },
            { key: "reason", header: "Reason", render: (r) => r.reason || "—" },
            { key: "outcome", header: "Outcome",
              render: (r) => <StatusBadge status={r.outcome} /> },
            { key: "performed_by_user_id", header: "By",
              render: (r) => String(r.performed_by_user_id) },
            { key: "created_at", header: "At",
              render: (r) => formatWhen(r.created_at) },
          ]}
          empty={{ icon: FaArchive, title: "No special archival operations",
            description: "Offline requests are performed and recorded here." }}
        />
      </Card>
      {open && (
        <FormModal opened onClose={() => setOpen(false)}
          title="Perform special archival"
          subtitle="Identify the data covered by the offline request."
          onSubmit={submit} submitting={perform.isPending}>
          <Stack>
            <TextInput label="Data reference" value={reference}
              onChange={(e) => setReference(e.currentTarget.value)} />
            <TextInput label="Reason" value={reason}
              onChange={(e) => setReason(e.currentTarget.value)} />
          </Stack>
        </FormModal>
      )}
    </Container>
  );
}
