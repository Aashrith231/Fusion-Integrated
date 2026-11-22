import { useState } from "react";
import { Button, Card, Container, Select, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { FaPlay } from "react-icons/fa";

import { useAuth } from "../../../auth/AuthProvider";
import { errorMessage } from "../../../lib/http";
import { DataTable } from "../../../ui/components/DataTable";
import { ErrorState } from "../../../ui/components/ErrorState";
import { PageHeader } from "../../../ui/components/PageHeader";
import { StatusBadge } from "../../../ui/components/StatusBadge";
import { useBackups, useRepositories, useTriggerBackup } from "../api/hooks";
import type { Backup } from "../api/types";
import { formatWhen } from "./format";

export default function BackupsPage() {
  const { can } = useAuth();
  const { data, isPending, error } = useBackups();
  const repositories = useRepositories();
  const trigger = useTriggerBackup();
  const [repository, setRepository] = useState<string | null>(null);

  if (error) return <Container size="xl"><ErrorState error={error} /></Container>;
  const canTrigger = can("badms.backup.trigger");

  function run() {
    trigger.mutate(repository ? { repository: Number(repository) } : {}, {
      onSuccess: () => notifications.show({
        color: "green", title: "Backup finished",
        message: "The manual backup completed and was recorded.",
      }),
      onError: (e) => notifications.show({
        color: "red", title: "Backup failed", message: errorMessage(e),
      }),
    });
  }

  return (
    <Container size="xl">
      <PageHeader
        title="Backup Status"
        subtitle="History and current status of every backup"
        action={canTrigger && (
          <Button
            leftSection={<FaPlay size={12} />}
            loading={trigger.isPending}
            onClick={run}
          >
            Trigger backup
          </Button>
        )}
      />
      {canTrigger && (
        <Card mb="md" padding="sm">
          <Select
            w={320}
            placeholder="Repository (default: first reachable)"
            data={(repositories.data ?? []).map((r) => ({
              value: String(r.id), label: `${r.name}${r.reachable ? "" : " (unreachable)"}`,
            }))}
            value={repository}
            onChange={setRepository}
            clearable
          />
        </Card>
      )}
      <Card padding="lg">
        <DataTable<Backup>
          rows={data ?? []}
          loading={isPending}
          rowKey={(r) => r.id}
          columns={[
            { key: "kind", header: "Kind", render: (r) => r.kind },
            { key: "dataset", header: "Dataset",
              render: (r) => r.dataset || "platform" },
            { key: "status", header: "Status",
              render: (r) => <StatusBadge status={r.status} /> },
            { key: "started_at", header: "Started",
              render: (r) => formatWhen(r.started_at) },
            { key: "finished_at", header: "Finished",
              render: (r) => formatWhen(r.finished_at) },
            { key: "integrity", header: "Integrity",
              render: (r) => (r.integrity_verified ? "verified" : "—") },
            { key: "failures", header: "Consecutive failures",
              render: (r) => String(r.consecutive_failures) },
            { key: "error", header: "Error",
              render: (r) => (r.error
                ? <Text size="xs" c="red">{r.error}</Text> : "—") },
          ]}
          empty={{ icon: FaPlay, title: "No backups yet",
            description: "Trigger one, or wait for the schedule." }}
        />
      </Card>
    </Container>
  );
}
