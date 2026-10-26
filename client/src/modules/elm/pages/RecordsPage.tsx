import { useState } from "react";
import {
  Badge, Button, Card, Container, Group, Stack, Text, Textarea, Title,
} from "@mantine/core";
import { DateInput } from "@mantine/dates";
import dayjs from "dayjs";
import { notifications } from "@mantine/notifications";

import { errorMessage } from "../../../lib/http";
import { ErrorState } from "../../../ui/components/ErrorState";
import { FormModal } from "../../../ui/components/FormModal";
import { PageHeader } from "../../../ui/components/PageHeader";
import {
  useRecords, useRequestCancellation, useRequestExtension,
  useSubmitResumption, useElmContext,
} from "../api/hooks";
import { isoDate } from "../api/dates";
import type { LeaveRecordItem } from "../api/types";

/** EL-UC-008/009/010: only earned, commuted and vacation leave
 *  carry a cancellation-with-extension lifecycle; CL-style
 *  categories end their story at the record. */
const EXTENSIBLE = ["EL", "COL", "VL"];

type Action = "cancel" | "extend" | "resume";

export default function RecordsPage() {
  const { data: records, isPending, error } = useRecords();
  const { data: context } = useElmContext();
  const cancel = useRequestCancellation();
  const extend = useRequestExtension();
  const resume = useSubmitResumption();
  const [pending, setPending] = useState<{
    record: LeaveRecordItem; action: Action;
  } | null>(null);
  const [form, setForm] = useState({
    effective_date: null as Date | null,
    reason: "",
    start_date: null as Date | null,
    end_date: null as Date | null,
    purpose: "",
    actual_resumption_date: null as Date | null,
    details: "",
  });

  if (error) return <Container size="xl"><ErrorState error={error} /></Container>;

  const today = dayjs();

  function open(record: LeaveRecordItem, action: Action) {
    setForm({
      effective_date: today.toDate(),
      reason: "",
      start_date: action === "extend"
        ? dayjs(record.end_date).add(1, "day").toDate()
        : null,
      end_date: null,
      purpose: "",
      actual_resumption_date: action === "resume"
        ? dayjs(record.end_date).toDate()
        : null,
      details: "",
    });
    setPending({ record, action });
  }

  function act() {
    if (!pending) return;
    const { record, action } = pending;
    if (action === "cancel") {
      cancel.mutate(
        {
          base_request_id: record.source_request ?? record.id,
          effective_date: isoDate(form.effective_date) ?? undefined,
          reason: form.reason,
        },
        {
          onSuccess: () => {
            notifications.show({ color: "green", title: "Cancellation requested", message: "It follows the original approval chain." });
            setPending(null);
          },
          onError: (e) => notifications.show({ color: "red", title: "Could not cancel", message: errorMessage(e) }),
        },
      );
      return;
    }
    if (action === "extend") {
      if (!form.start_date || !form.end_date) {
        notifications.show({ color: "red", title: "Dates required", message: "Pick the extension period." });
        return;
      }
      extend.mutate(
        {
          base_request_id: record.source_request ?? record.id,
          start_date: isoDate(form.start_date)!,
          end_date: isoDate(form.end_date)!,
          purpose: form.purpose,
        },
        {
          onSuccess: () => {
            notifications.show({ color: "green", title: "Extension requested", message: "Only the incremental period posts on approval." });
            setPending(null);
          },
          onError: (e) => notifications.show({ color: "red", title: "Could not extend", message: errorMessage(e) }),
        },
      );
      return;
    }
    if (!form.actual_resumption_date) {
      notifications.show({ color: "red", title: "Date required", message: "Pick the day you resumed duty." });
      return;
    }
    resume.mutate(
      {
        record_id: record.id,
        actual_resumption_date: isoDate(form.actual_resumption_date)!,
        details: form.details,
      },
      {
        onSuccess: () => {
          notifications.show({ color: "green", title: "Resumption submitted", message: "The applicable Sanctioning Authority will review it." });
          setPending(null);
        },
        onError: (e) => notifications.show({ color: "red", title: "Could not submit", message: errorMessage(e) }),
      },
    );
  }

  const titles: Record<Action, string> = {
    cancel: "Cancel the leave",
    extend: "Extend the leave",
    resume: "Resume duty",
  };

  return (
    <Container size="xl">
      <PageHeader
        title="Leave Records"
        subtitle={context?.designation_name
          ? "Your records — Officers see the book"
          : "Leave on the books"}
      />
      {isPending ? (
        <Text c="dimmed">Loading…</Text>
      ) : (
        <Stack>
          {(records ?? []).map((r) => (
            <Card key={r.id} withBorder radius="md" p="md">
              <Group justify="space-between">
                <Title order={5}>
                  {r.category} · {r.start_date} → {r.end_date} · {r.days} day(s)
                </Title>
                <Badge
                  color={r.status === "cancelled" ? "red" : "green"}
                  variant="light"
                >
                  {r.status}
                </Badge>
              </Group>
              <Text size="sm" c="dimmed">
                {r.leave_year}
                {r.station_leave ? " · station leave" : ""}
                {r.actual_end_date ? ` · ended ${r.actual_end_date}` : ""}
              </Text>
              {r.status === "ongoing" && (
                <Group mt="xs">
                  {EXTENSIBLE.includes(r.category) && (
                    <Button size="xs" variant="light"
                      onClick={() => open(r, "resume")}>
                      Resume duty
                    </Button>
                  )}
                  {EXTENSIBLE.includes(r.category)
                    && r.source_request != null && (
                    <>
                      <Button size="xs" variant="light"
                        onClick={() => open(r, "extend")}>
                        Extend
                      </Button>
                      {/* BR-EL-023: cancellation is pre-start only. */}
                      {dayjs(r.start_date).isAfter(today, "day") && (
                        <Button size="xs" variant="light" color="red"
                          onClick={() => open(r, "cancel")}>
                          Cancel
                        </Button>
                      )}
                    </>
                  )}
                </Group>
              )}
            </Card>
          ))}
          {(records ?? []).length === 0 && (
            <Text c="dimmed">No records yet.</Text>
          )}
        </Stack>
      )}

      <FormModal
        opened={pending !== null}
        onClose={() => setPending(null)}
        title={pending ? titles[pending.action] : ""}
        onSubmit={act}
        submitLabel="Confirm"
        submitting={cancel.isPending || extend.isPending
          || resume.isPending}
      >
        <Stack>
          {pending?.action === "cancel" && (
            <>
              <DateInput
                label="Effective from" value={form.effective_date}
                onChange={(d) => setForm({ ...form, effective_date: d })}
              />
              <Textarea
                label="Reason" value={form.reason}
                onChange={(e) => setForm({ ...form, reason: e.target.value })}
              />
            </>
          )}
          {pending?.action === "extend" && (
            <>
              <Group grow>
                <DateInput
                  label="From (day after the leave ends)"
                  value={form.start_date}
                  onChange={(d) => setForm({ ...form, start_date: d })}
                />
                <DateInput
                  label="To" value={form.end_date}
                  onChange={(d) => setForm({ ...form, end_date: d })}
                />
              </Group>
              <Textarea
                label="Purpose" value={form.purpose}
                onChange={(e) => setForm({ ...form, purpose: e.target.value })}
              />
            </>
          )}
          {pending?.action === "resume" && (
            <>
              <DateInput
                label="Actual resumption date" value={form.actual_resumption_date}
                onChange={(d) => setForm({ ...form, actual_resumption_date: d })}
              />
              <Textarea
                label="Details (optional)" value={form.details}
                onChange={(e) => setForm({ ...form, details: e.target.value })}
              />
            </>
          )}
        </Stack>
      </FormModal>
    </Container>
  );
}
