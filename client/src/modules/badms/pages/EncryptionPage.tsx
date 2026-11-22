import { useState } from "react";
import {
  Button, Card, Container, Stack, Text, TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { FaLock } from "react-icons/fa";

import { errorMessage } from "../../../lib/http";
import { DataTable } from "../../../ui/components/DataTable";
import { ErrorState } from "../../../ui/components/ErrorState";
import { FormModal } from "../../../ui/components/FormModal";
import { PageHeader } from "../../../ui/components/PageHeader";
import { StatusBadge } from "../../../ui/components/StatusBadge";
import { useArchivalQueue, useConfigureEncryption } from "../api/hooks";
import type { ArchivalRequest } from "../api/types";
import { formatWhen } from "./format";

/** IT Security's encryption desk: Sensitive requests routed here, encrypted
 *  with AES-256 at rest and in transit. */
export default function EncryptionPage() {
  const { data, isPending, error } = useArchivalQueue();
  const encrypt = useConfigureEncryption();
  const [target, setTarget] = useState<ArchivalRequest | null>(null);
  const [keyRef, setKeyRef] = useState("");

  if (error) return <Container size="xl"><ErrorState error={error} /></Container>;

  const queue = (data ?? []).filter((r) =>
    r.status === "routed_to_security" || r.status === "encryption_failed");

  function submit() {
    if (!target) return;
    encrypt.mutateAsync({ id: target.id, key_ref: keyRef }).then(() => {
      notifications.show({ color: "green", title: "Archive created",
        message: "Encrypted with AES-256 at rest and in transit." });
      setTarget(null);
      setKeyRef("");
    }).catch((e) => notifications.show({
      color: "red", title: "Encryption failed", message: errorMessage(e) }));
  }

  return (
    <Container size="xl">
      <PageHeader title="Sensitive-Data Encryption"
        subtitle="Configure encryption and create the encrypted archive" />
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
            { key: "status", header: "Status",
              render: (r) => <StatusBadge status={r.status} /> },
            { key: "algorithm", header: "Encryption",
              render: (r) => r.encryption_algorithm || "not configured" },
            { key: "actions", header: "",
              render: (r) => (r.status === "routed_to_security" ||
                r.status === "encryption_failed") && (
                <Button size="xs" onClick={() => setTarget(r)}>
                  Configure
                </Button>
              ) },
          ]}
          empty={{ icon: FaLock, title: "Nothing awaiting encryption",
            description: "Requests classified Sensitive arrive here." }}
        />
      </Card>
      {target && (
        <FormModal opened onClose={() => setTarget(null)}
          title="Configure encryption" subtitle={target.file_name}
          onSubmit={submit} submitting={encrypt.isPending}>
          <TextInput label="Encryption key reference" value={keyRef}
            placeholder="kms://key-1"
            onChange={(e) => setKeyRef(e.currentTarget.value)} />
          <Text size="xs" c="dimmed" mt="xs">
            AES-256 is applied at rest and in transit; the archive records the
            parameters used.
          </Text>
        </FormModal>
      )}
    </Container>
  );
}
