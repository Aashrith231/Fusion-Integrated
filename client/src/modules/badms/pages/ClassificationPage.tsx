import { useState } from "react";
import { Button, Card, Container, Select, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { FaTags } from "react-icons/fa";

import { errorMessage } from "../../../lib/http";
import { DataTable } from "../../../ui/components/DataTable";
import { ErrorState } from "../../../ui/components/ErrorState";
import { FormModal } from "../../../ui/components/FormModal";
import { PageHeader } from "../../../ui/components/PageHeader";
import { StatusBadge } from "../../../ui/components/StatusBadge";
import { useArchivalQueue, useClassifyArchival } from "../api/hooks";
import type { ArchivalRequest } from "../api/types";
import { formatWhen } from "./format";

const CLASSIFICATIONS = [
  { value: "critical", label: "Critical" },
  { value: "sensitive", label: "Sensitive — routes to IT Security" },
  { value: "routine", label: "Routine" },
  { value: "archival", label: "Archival" },
];

/** The SysAdmin's classification desk: HoD-approved requests only. */
export default function ClassificationPage() {
  const { data, isPending, error } = useArchivalQueue();
  const classify = useClassifyArchival();
  const [target, setTarget] = useState<ArchivalRequest | null>(null);
  const [value, setValue] = useState<string | null>(null);
  const [note, setNote] = useState("");

  if (error) return <Container size="xl"><ErrorState error={error} /></Container>;

  const queue = (data ?? []).filter((r) => r.status === "hod_approved");

  function submit() {
    if (!target || !value) return;
    classify.mutateAsync({ id: target.id, classification: value, note })
      .then(() => {
        notifications.show({ color: "green", title: "Classification recorded",
          message: value === "sensitive"
            ? "Routed to IT Security for encryption."
            : "Security and retention treatment applied." });
        setTarget(null);
        setValue(null);
        setNote("");
      }).catch((e) => notifications.show({
        color: "red", title: "Not recorded", message: errorMessage(e) }));
  }

  return (
    <Container size="xl">
      <PageHeader title="Classification"
        subtitle={"Assign the authoritative classification: Critical, " +
          "Sensitive, Routine or Archival"} />
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
                    {r.department} — {formatWhen(r.created_at)}
                  </Text>
                </Stack>
              ) },
            { key: "owners", header: "Owners", render: (r) => r.owners },
            { key: "status", header: "Status",
              render: (r) => <StatusBadge status={r.status} /> },
            { key: "actions", header: "",
              render: (r) => (
                <Button size="xs" onClick={() => setTarget(r)}>
                  Classify
                </Button>
              ) },
          ]}
          empty={{ icon: FaTags, title: "Nothing to classify",
            description: "HoD-approved requests arrive here." }}
        />
      </Card>
      {target && (
        <FormModal opened onClose={() => setTarget(null)}
          title="Authoritative classification" subtitle={target.file_name}
          onSubmit={submit} submitting={classify.isPending}>
          <Select label="Classification" data={CLASSIFICATIONS}
            value={value} onChange={setValue} />
        </FormModal>
      )}
    </Container>
  );
}
