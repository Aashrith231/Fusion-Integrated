import { Button, Card, Container, Group, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { FaClipboardCheck } from "react-icons/fa";

import { errorMessage } from "../../../lib/http";
import { DataTable } from "../../../ui/components/DataTable";
import { ErrorState } from "../../../ui/components/ErrorState";
import { PageHeader } from "../../../ui/components/PageHeader";
import {
  useDecideExtension, useExtensionQueue, useInfrastructure,
} from "../api/hooks";
import type { StorageExtension } from "../api/types";
import { formatBytes, formatWhen } from "./format";

/** The HoD's storage desk: the department's requests, plus the infrastructure
 *  picture the decision criteria ask for (BR-BA-017). */
export default function StorageApprovalsPage() {
  const { data, isPending, error } = useExtensionQueue();
  const infrastructure = useInfrastructure();
  const decide = useDecideExtension();

  if (error) return <Container size="xl"><ErrorState error={error} /></Container>;

  function act(id: number, decision: "approve" | "reject") {
    decide.mutateAsync({ id, decision }).then(() => notifications.show({
      color: "green", title: "Decision recorded",
      message: "The requester has been notified.",
    })).catch((e) => notifications.show({
      color: "red", title: "Not recorded", message: errorMessage(e) }));
  }

  const queue = (data ?? []).filter((r) => r.status === "submitted");
  const pool = infrastructure.data;

  return (
    <Container size="xl">
      <PageHeader title="Storage Approvals"
        subtitle="Storage-extension requests from your department" />
      {pool && (
        <Card padding="sm" mb="md">
          <Stack gap={2}>
            <Text size="sm" fw={600}>Storage infrastructure</Text>
            <Text size="sm" c="dimmed">
              {pool.name}: {formatBytes(pool.available_bytes)} available of{" "}
              {formatBytes(pool.capacity_bytes)}
            </Text>
          </Stack>
        </Card>
      )}
      <Card padding="lg">
        <DataTable<StorageExtension>
          rows={queue}
          loading={isPending}
          rowKey={(r) => r.id}
          columns={[
            { key: "user", header: "Requester",
              render: (r) => `user ${r.user_id}` },
            { key: "requested", header: "Requested",
              render: (r) => formatBytes(r.requested_bytes) },
            { key: "usage", header: "Usage at request",
              render: (r) =>
                `${formatBytes(r.usage_at_request)} / ` +
                `${formatBytes(r.quota_at_request)}` },
            { key: "justification", header: "Justification",
              render: (r) => r.justification },
            { key: "created_at", header: "Submitted",
              render: (r) => formatWhen(r.created_at) },
            { key: "actions", header: "",
              render: (r) => (
                <Group gap="xs">
                  <Button size="xs" onClick={() => act(r.id, "approve")}>
                    Approve
                  </Button>
                  <Button size="xs" color="red" variant="light"
                    onClick={() => act(r.id, "reject")}>Reject</Button>
                </Group>
              ) },
          ]}
          empty={{ icon: FaClipboardCheck, title: "Nothing awaiting decision" }}
        />
      </Card>
    </Container>
  );
}
