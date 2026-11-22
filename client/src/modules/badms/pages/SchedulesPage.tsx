import { useState } from "react";
import {
  Button, Card, Container, Group, Select, Stack, Text, TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { FaCalendarAlt, FaGlobe } from "react-icons/fa";

import { useAuth } from "../../../auth/AuthProvider";
import { errorMessage } from "../../../lib/http";
import { DataTable } from "../../../ui/components/DataTable";
import { ErrorState } from "../../../ui/components/ErrorState";
import { FormModal } from "../../../ui/components/FormModal";
import { PageHeader } from "../../../ui/components/PageHeader";
import { StatusBadge } from "../../../ui/components/StatusBadge";
import {
  useCreateSchedule, useGlobalSchedule, useModifySchedule, useRepositories,
  useSchedules, useScheduleChanges, useSetGlobalSchedule,
} from "../api/hooks";
import type { Schedule } from "../api/types";
import { formatWhen } from "./format";

const FREQUENCIES = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
];

const WEEKDAYS = [
  { value: "0", label: "Monday" }, { value: "1", label: "Tuesday" },
  { value: "2", label: "Wednesday" }, { value: "3", label: "Thursday" },
  { value: "4", label: "Friday" }, { value: "5", label: "Saturday" },
  { value: "6", label: "Sunday" },
];

function ScheduleForm({ initial, onClose }: {
  initial?: Schedule | null;
  onClose: () => void;
}) {
  const repositories = useRepositories();
  const create = useCreateSchedule();
  const modify = useModifySchedule();
  const editing = Boolean(initial);
  const [dataset, setDataset] = useState(initial?.dataset ?? "");
  const [frequency, setFrequency] = useState<string>(
    initial?.frequency ?? "daily");
  const [weekday, setWeekday] = useState<string | null>(
    initial?.weekday != null ? String(initial.weekday) : null);
  const [time, setTime] = useState(
    initial ? initial.run_at.slice(0, 5) : "02:00");
  const [repo, setRepo] = useState<string | null>(
    initial ? String(initial.repository) : null);
  const saving = create.isPending || modify.isPending;

  function submit() {
    const payload = {
      dataset,
      frequency,
      run_at: time,
      weekday: weekday === null ? null : Number(weekday),
      repository: Number(repo),
    };
    const action = editing
      ? modify.mutateAsync({ id: initial!.id, ...payload })
      : create.mutateAsync(payload);
    action.then(() => {
      notifications.show({ color: "green", title: "Saved",
        message: "The schedule passed validation and was applied." });
      onClose();
    }).catch((e) => notifications.show({
      color: "red", title: "Not applied", message: errorMessage(e) }));
  }

  return (
    <FormModal
      opened onClose={onClose} title={editing ? "Modify schedule"
        : "New local schedule"}
      subtitle="Invalid or conflicting configurations are never applied."
      onSubmit={submit} submitting={saving}>
      <Stack>
        <TextInput label="Dataset" value={dataset} disabled={editing}
          onChange={(e) => setDataset(e.currentTarget.value)} />
        <Select label="Frequency" data={FREQUENCIES} value={frequency}
          onChange={(v) => setFrequency(v ?? "daily")} />
        <TextInput label="Time of day (HH:MM)" value={time}
          onChange={(e) => setTime(e.currentTarget.value)} />
        {frequency === "weekly" && (
          <Select label="Weekday" data={WEEKDAYS} value={weekday}
            onChange={setWeekday} />
        )}
        <Select label="Repository"
          data={(repositories.data ?? []).map((r) => ({
            value: String(r.id), label: r.name }))}
          value={repo} onChange={setRepo} />
      </Stack>
    </FormModal>
  );
}

function GlobalForm({ initial, onClose }: {
  initial: Schedule | null;
  onClose: () => void;
}) {
  const repositories = useRepositories();
  const save = useSetGlobalSchedule();
  const [frequency, setFrequency] = useState<string>(
    initial?.frequency ?? "daily");
  const [weekday, setWeekday] = useState<string | null>(
    initial?.weekday != null ? String(initial.weekday) : null);
  const [time, setTime] = useState(
    initial ? initial.run_at.slice(0, 5) : "02:00");
  const [repo, setRepo] = useState<string | null>(
    initial ? String(initial.repository) : null);

  function submit() {
    save.mutateAsync({
      frequency, run_at: time,
      weekday: weekday === null ? null : Number(weekday),
      repository: Number(repo),
    }).then(() => {
      notifications.show({ color: "green", title: "Global schedule saved",
        message: "It applies wherever no local schedule overrides it." });
      onClose();
    }).catch((e) => notifications.show({
      color: "red", title: "Not applied", message: errorMessage(e) }));
  }

  return (
    <FormModal opened onClose={onClose} title="Global backup schedule"
      subtitle="Institution-wide; a local dataset schedule overrides it."
      onSubmit={submit} submitting={save.isPending}>
      <Stack>
        <Select label="Frequency" data={FREQUENCIES} value={frequency}
          onChange={(v) => setFrequency(v ?? "daily")} />
        <TextInput label="Time of day (HH:MM)" value={time}
          onChange={(e) => setTime(e.currentTarget.value)} />
        {frequency === "weekly" && (
          <Select label="Weekday" data={WEEKDAYS} value={weekday}
            onChange={setWeekday} />
        )}
        <Select label="Repository"
          data={(repositories.data ?? []).map((r) => ({
            value: String(r.id), label: r.name }))}
          value={repo} onChange={setRepo} />
      </Stack>
    </FormModal>
  );
}

function ChangeLog({ scheduleId, onClose }: {
  scheduleId: number; onClose: () => void;
}) {
  const changes = useScheduleChanges(scheduleId);
  return (
    <FormModal opened onClose={onClose} title="Configuration history"
      onSubmit={onClose} submitLabel="Close">
      {(changes.data ?? []).length === 0
        ? <Text size="sm" c="dimmed">No changes recorded yet.</Text>
        : <Stack gap="xs">
            {(changes.data ?? []).map((c, i) => (
              <Text key={i} size="sm">
                <Text span fw={600}>{c.action}</Text> — {c.summary}{" "}
                <Text span c="dimmed" size="xs">
                  ({formatWhen(c.at)} by {c.changed_by_user_id})
                </Text>
              </Text>
            ))}
          </Stack>}
    </FormModal>
  );
}

export default function SchedulesPage() {
  const { can } = useAuth();
  const { data, isPending, error } = useSchedules();
  const global = useGlobalSchedule();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Schedule | null>(null);
  const [globalOpen, setGlobalOpen] = useState(false);
  const [logFor, setLogFor] = useState<number | null>(null);

  if (error) return <Container size="xl"><ErrorState error={error} /></Container>;
  const canManage = can("badms.schedule.manage");
  const canManageGlobal = can("badms.schedule.manage_global");

  return (
    <Container size="xl">
      <PageHeader
        title="Backup Schedules"
        subtitle="Local dataset schedules; a local schedule overrides the global one"
        action={canManage && (
          <Button leftSection={<FaCalendarAlt size={12} />}
            onClick={() => setCreating(true)}>
            New schedule
          </Button>
        )}
      />
      <Card padding="lg" mb="md">
        <Group justify="space-between" mb="sm">
          <Stack gap={0}>
            <Text fw={600}>Global schedule</Text>
            <Text size="xs" c="dimmed">
              {global.data
                ? `${global.data.frequency} at ${global.data.run_at.slice(0, 5)}`
                : "None defined — no default backup runs"}
            </Text>
          </Stack>
          {canManageGlobal && (
            <Button variant="light" leftSection={<FaGlobe size={12} />}
              onClick={() => setGlobalOpen(true)}>
              {global.data ? "Update global" : "Define global"}
            </Button>
          )}
        </Group>
        <DataTable<Schedule>
          rows={data ?? []}
          loading={isPending}
          rowKey={(r) => r.id}
          columns={[
            { key: "scope", header: "Scope",
              render: (r) => <StatusBadge status={r.scope} /> },
            { key: "dataset", header: "Dataset",
              render: (r) => r.dataset || "institution-wide" },
            { key: "frequency", header: "Frequency",
              render: (r) => `${r.frequency} at ${r.run_at.slice(0, 5)}` +
                (r.weekday != null ? ` (day ${r.weekday})` : "") },
            { key: "repository_name", header: "Repository",
              render: (r) => r.repository_name },
            { key: "active", header: "Active",
              render: (r) => (r.is_active ? "yes" : "no") },
            { key: "actions", header: "",
              render: (r) => (
                <Group gap="xs">
                  {canManage && r.scope === "local" && (
                    <Button variant="light" size="xs"
                      onClick={() => setEditing(r)}>Edit</Button>
                  )}
                  <Button variant="subtle" size="xs"
                    onClick={() => setLogFor(r.id)}>History</Button>
                </Group>
              ) },
          ]}
          empty={{ icon: FaCalendarAlt, title: "No schedules yet",
            description: "Create a local schedule or define the global one." }}
        />
      </Card>
      {creating && <ScheduleForm onClose={() => setCreating(false)} />}
      {editing && <ScheduleForm initial={editing}
        onClose={() => setEditing(null)} />}
      {globalOpen && <GlobalForm initial={global.data ?? null}
        onClose={() => setGlobalOpen(false)} />}
      {logFor !== null && <ChangeLog scheduleId={logFor}
        onClose={() => setLogFor(null)} />}
    </Container>
  );
}
