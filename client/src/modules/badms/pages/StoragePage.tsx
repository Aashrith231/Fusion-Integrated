import { useState } from "react";
import {
  Button, Card, Container, Group, NumberInput, Progress, Stack, Text, Textarea,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { FaHdd } from "react-icons/fa";

import { errorMessage } from "../../../lib/http";
import { DataTable } from "../../../ui/components/DataTable";
import { ErrorState } from "../../../ui/components/ErrorState";
import { FormModal } from "../../../ui/components/FormModal";
import { PageHeader } from "../../../ui/components/PageHeader";
import { StatusBadge } from "../../../ui/components/StatusBadge";
import { useMyExtensions, useMyStorage, useSubmitExtension } from "../api/hooks";
import type { StorageExtension } from "../api/types";
import { formatBytes, formatWhen } from "./format";

export default function StoragePage() {
  const storage = useMyStorage();
  const mine = useMyExtensions();
  const submit = useSubmitExtension();
  const [open, setOpen] = useState(false);
  const [bytes, setBytes] = useState<number | undefined>(1024 * 1024 * 1024);
  const [justification, setJustification] = useState("");

  if (storage.error) {
    return <Container size="xl"><ErrorState error={storage.error} /></Container>;
  }

  const profile = storage.data;
  const percent = profile
    ? Math.min(100, Math.round((profile.used_bytes / profile.quota_bytes) * 100))
    : 0;

  function submitRequest() {
    if (!bytes) return;
    submit.mutateAsync({ requested_bytes: bytes, justification })
      .then(() => {
        notifications.show({ color: "green", title: "Request submitted",
          message: "Routed to your department head." });
        setOpen(false);
        setJustification("");
      }).catch((e) => notifications.show({
        color: "red", title: "Not submitted", message: errorMessage(e) }));
  }

  return (
    <Container size="xl">
      <PageHeader title="My Storage"
        subtitle="Usage against your quota; an extension is requested when the quota is full" />
      <Card padding="lg" mb="md">
        <Stack>
          <Group justify="space-between">
            <Text fw={600}>
              {formatBytes(profile?.used_bytes)} of{" "}
              {formatBytes(profile?.quota_bytes)} used
            </Text>
            {profile?.full && (
              <StatusBadge status="quota_full" />
            )}
          </Group>
          <Progress value={percent} color={profile?.full ? "red" : "blue"} />
          <Text size="xs" c="dimmed">
            Threshold status evaluated by the monitor; last checked{" "}
            {formatWhen(profile?.checked_at)}.
          </Text>
        </Stack>
      </Card>
      <Card padding="lg">
        <Group justify="space-between" mb="sm">
          <Text fw={600}>My extension requests</Text>
          {profile?.full && (
            <Button leftSection={<FaHdd size={12} />} onClick={() => setOpen(true)}>
              Request extension
            </Button>
          )}
        </Group>
        <DataTable<StorageExtension>
          rows={mine.data ?? []}
          loading={mine.isPending}
          rowKey={(r) => r.id}
          columns={[
            { key: "requested", header: "Requested",
              render: (r) => formatBytes(r.requested_bytes) },
            { key: "justification", header: "Justification",
              render: (r) => r.justification },
            { key: "status", header: "Status",
              render: (r) => <StatusBadge status={r.status} /> },
            { key: "decided_at", header: "Decided",
              render: (r) => formatWhen(r.decided_at) },
            { key: "created_at", header: "Submitted",
              render: (r) => formatWhen(r.created_at) },
          ]}
          empty={{ icon: FaHdd, title: "No extension requests",
            description: profile?.full
              ? "Your quota is full — you can request an extension."
              : "Requests are possible once your quota is full." }}
        />
      </Card>
      {open && (
        <FormModal opened onClose={() => setOpen(false)}
          title="Request a storage extension"
          subtitle="Validated against your usage and the available infrastructure."
          onSubmit={submitRequest} submitting={submit.isPending}>
          <Stack>
            <NumberInput label="Requested bytes" min={1} value={bytes}
              onChange={(v) => setBytes(Number(v) || 0)} />
            <Textarea label="Justification" value={justification}
              onChange={(e) => setJustification(e.currentTarget.value)} />
          </Stack>
        </FormModal>
      )}
    </Container>
  );
}
