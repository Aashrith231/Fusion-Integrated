import { useState } from "react";
import {
  Button, Card, Container, NumberInput, Select, Stack, Text, Textarea,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { FaBoxOpen } from "react-icons/fa";

import { useAuth } from "../../../auth/AuthProvider";
import { errorMessage } from "../../../lib/http";
import { DataTable } from "../../../ui/components/DataTable";
import { FormModal } from "../../../ui/components/FormModal";
import { PageHeader } from "../../../ui/components/PageHeader";
import { StatusBadge } from "../../../ui/components/StatusBadge";
import { useMyArchival, useMyRequests, useSubmitArchival } from "../api/hooks";
import type { ArchivalRequest, MyRequest } from "../api/types";
import { formatWhen } from "./format";

const CLASSIFICATIONS = [
  { value: "critical", label: "Critical" },
  { value: "sensitive", label: "Sensitive" },
  { value: "routine", label: "Routine" },
  { value: "archival", label: "Archival" },
];

function SubmitModal({ onClose }: { onClose: () => void }) {
  const submit = useSubmitArchival();
  const [form, setForm] = useState({
    file_name: "", file_date: "2026-08-01", owners: "", file_type: "pdf",
    reason: "", attachment: "", attachment_size_bytes: 0,
    initial_classification: "",
  });

  function set(field: string, value: string | number) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  function submitRequest() {
    submit.mutateAsync(form).then(() => {
      notifications.show({ color: "green", title: "Request submitted",
        message: "Routed to your department head for review." });
      onClose();
    }).catch((e) => notifications.show({
      color: "red", title: "Not submitted", message: errorMessage(e) }));
  }

  return (
    <FormModal opened onClose={onClose} title="Submit secure archival request"
      subtitle="Missing initial classification defaults to Routine."
      onSubmit={submitRequest} submitting={submit.isPending}>
      <Stack>
        <TextInput label="File name" value={form.file_name}
          onChange={(e) => set("file_name", e.currentTarget.value)} />
        <TextInput label="File date (YYYY-MM-DD)" value={form.file_date}
          onChange={(e) => set("file_date", e.currentTarget.value)} />
        <TextInput label="Owners" value={form.owners}
          onChange={(e) => set("owners", e.currentTarget.value)} />
        <TextInput label="File type" value={form.file_type}
          onChange={(e) => set("file_type", e.currentTarget.value)} />
        <Textarea label="Reason" value={form.reason}
          onChange={(e) => set("reason", e.currentTarget.value)} />
        <TextInput label="Attachment reference" value={form.attachment}
          onChange={(e) => set("attachment", e.currentTarget.value)} />
        <NumberInput label="Attachment size (bytes)" min={0}
          value={form.attachment_size_bytes}
          onChange={(v) => set("attachment_size_bytes", Number(v) || 0)} />
        <Select label="Initial classification (optional)"
          data={CLASSIFICATIONS} clearable
          value={form.initial_classification || null}
          onChange={(v) => set("initial_classification", v ?? "")} />
      </Stack>
    </FormModal>
  );
}

export default function ArchivalPage() {
  const { can } = useAuth();
  const mine = useMyArchival();
  const requests = useMyRequests();
  const [open, setOpen] = useState(false);

  const canSubmit = can("badms.archival.submit");

  return (
    <Container size="xl">
      <PageHeader
        title="Secure Archival"
        subtitle="Submit data for secure archival and track your requests"
        action={canSubmit && (
          <Button leftSection={<FaBoxOpen size={12} />}
            onClick={() => setOpen(true)}>
            New request
          </Button>
        )}
      />
      <Card padding="lg" mb="md">
        <Text fw={600} mb="sm">My archival requests</Text>
        <DataTable<ArchivalRequest>
          rows={mine.data ?? []}
          loading={mine.isPending}
          rowKey={(r) => r.id}
          columns={[
            { key: "file_name", header: "File",
              render: (r) => (
                <Stack gap={0}>
                  <Text fw={600}>{r.file_name}</Text>
                  <Text size="xs" c="dimmed">{r.file_type}, {r.file_date}</Text>
                </Stack>
              ) },
            { key: "status", header: "Status",
              render: (r) => <StatusBadge status={r.status} /> },
            { key: "classification", header: "Classification",
              render: (r) => r.classification || "—" },
            { key: "retention", header: "Retention",
              render: (r) => r.retention_rule || "—" },
            { key: "encrypted", header: "Encryption",
              render: (r) => r.encryption_algorithm || "—" },
            { key: "created_at", header: "Submitted",
              render: (r) => formatWhen(r.created_at) },
          ]}
          empty={{ icon: FaBoxOpen, title: "No archival requests",
            description: "Submit one to start the review chain." }}
        />
      </Card>
      <Card padding="lg">
        <Text fw={600} mb="sm">All my BADMS requests</Text>
        <DataTable<MyRequest>
          rows={requests.data ?? []}
          loading={requests.isPending}
          rowKey={(r) => `${r.kind}-${r.id}`}
          columns={[
            { key: "kind", header: "Type", render: (r) => r.kind },
            { key: "title", header: "Title", render: (r) => r.title },
            { key: "status", header: "Status",
              render: (r) => <StatusBadge status={r.status} /> },
            { key: "updated_at", header: "Updated",
              render: (r) => formatWhen(r.updated_at) },
          ]}
          empty={{ icon: FaBoxOpen, title: "Nothing to track" }}
        />
      </Card>
      {open && <SubmitModal onClose={() => setOpen(false)} />}
    </Container>
  );
}
