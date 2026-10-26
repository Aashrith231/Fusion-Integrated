import { useState } from "react";
import {
  Badge, Button, Card, Container, Group, Select, Stack, Text, Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";

import { errorMessage } from "../../../lib/http";
import { ErrorState } from "../../../ui/components/ErrorState";
import { FormModal } from "../../../ui/components/FormModal";
import { PageHeader } from "../../../ui/components/PageHeader";
import {
  useDecide, useQueue, useRespondSubstitute, useReviewResumption,
} from "../api/hooks";
import type { LeaveRequest, TaskWithRequest } from "../api/types";

function requestSummary(t: TaskWithRequest): string {
  const r: LeaveRequest | null = t.request;
  if (!r) {
    // A resumption task on offline-recorded leave has no
    // application behind it — it points at the resumption only.
    return `resumption #${t.resumption ?? "?"} (recorded offline)`;
  }
  return `${r.category} · ${r.user_id} · ${r.start_date} → ${r.end_date} · ${r.days} day(s)`;
}

/** BR-EL-016/017: the two vocabularies are state-specific.
 *  A Unit-Head review of CL/RH work — a fresh application, or the
 *  cancellation of a Unit-Head-final leave — decides; everything
 *  higher-sanction recommends, and the recommendation is advice,
 *  never a veto. */
function unitHeadOutcomes(request: LeaveRequest | null) {
  if (request?.category === "CL" || request?.category === "RH") {
    return [
      { value: "approve", label: "Approve" },
      { value: "reject", label: "Reject" },
    ];
  }
  return [
    { value: "recommended", label: "Recommend" },
    { value: "not_recommended", label: "Not recommended" },
  ];
}

const RESUMPTION_OUTCOMES = [
  { value: "normal", label: "Normal — resumed on the approved end date" },
  { value: "early", label: "Early — restore the unused days" },
  { value: "late", label: "Late — charge the extra days" },
];

export default function TasksPage() {
  const { data, isPending, error } = useQueue();
  const decide = useDecide();
  const respond = useRespondSubstitute();
  const reviewResumption = useReviewResumption();
  const [pending, setPending] = useState<
    { task: TaskWithRequest; action: "decide" | "respond" | "review" } | null>(
      null);
  const [outcome, setOutcome] = useState<string>("approve");
  const [reason, setReason] = useState("");

  if (error) return <Container size="xl"><ErrorState error={error} /></Container>;

  const tasks = data ?? [];

  function act() {
    if (!pending) return;
    const { task, action } = pending;
    if (action === "respond") {
      respond.mutate(
        { taskId: task.id, accept: outcome === "accept", reason },
        {
          onSuccess: () => {
            notifications.show({ color: "green", title: "Recorded", message: "Your response was recorded." });
            setPending(null);
            setReason("");
          },
          onError: (e) => notifications.show({ color: "red", title: "Could not respond", message: errorMessage(e) }),
        },
      );
      return;
    }
    if (action === "review") {
      if (!task.resumption) return;
      reviewResumption.mutate(
        { id: task.resumption, outcome, reason },
        {
          onSuccess: () => {
            notifications.show({ color: "green", title: "Resumption reviewed", message: "The record and balance were synchronized." });
            setPending(null);
            setReason("");
          },
          onError: (e) => notifications.show({ color: "red", title: "Could not review", message: errorMessage(e) }),
        },
      );
      return;
    }
    decide.mutate(
      { taskId: task.id, outcome, reason },
      {
        onSuccess: () => {
          notifications.show({ color: "green", title: "Decided", message: "The request advanced." });
          setPending(null);
          setReason("");
        },
        onError: (e) => notifications.show({ color: "red", title: "Could not decide", message: errorMessage(e) }),
      },
    );
  }

  return (
    <Container size="xl">
      <PageHeader
        title="My Tasks"
        subtitle="What waits on you: reviews, routing and sanctioning decisions"
      />
      {isPending ? (
        <Text c="dimmed">Loading…</Text>
      ) : (
        <Stack>
          {tasks.map((t) => (
            <Card key={t.id} withBorder radius="md" p="md">
              <Group justify="space-between">
                <Title order={5}>{t.task_class.replace(/_/g, " ")}</Title>
                <Badge variant="light">{t.assignee_role.replace(/_/g, " ")}</Badge>
              </Group>
              <Text size="sm" c="dimmed">{requestSummary(t)}</Text>
              {t.escalated_at && (
                <Badge color="red" variant="light">escalated</Badge>
              )}
              <Group mt="xs">
                {t.task_class === "substitute_response" ? (
                  <>
                    <Button size="xs" onClick={() => { setOutcome("accept"); setReason(""); setPending({ task: t, action: "respond" }); }}>
                      Accept
                    </Button>
                    <Button size="xs" variant="light" color="red" onClick={() => { setOutcome("decline"); setReason(""); setPending({ task: t, action: "respond" }); }}>
                      Decline
                    </Button>
                  </>
                ) : t.task_class === "establishment_routing" ? (
                  <Button size="xs" onClick={() => { setOutcome("forward"); setPending({ task: t, action: "decide" }); }}>
                    Route
                  </Button>
                ) : t.task_class === "resumption_review" ? (
                  <Button size="xs" onClick={() => { setOutcome("normal"); setReason(""); setPending({ task: t, action: "review" }); }}>
                    Review resumption
                  </Button>
                ) : t.task_class === "final_sanction" ? (
                  <Button size="xs" onClick={() => { setOutcome("approve"); setReason(""); setPending({ task: t, action: "decide" }); }}>
                    Decide
                  </Button>
                ) : (
                  <Button size="xs" onClick={() => {
                    setOutcome(
                      unitHeadOutcomes(t.request)[0]?.value
                      ?? "approve");
                    setReason("");
                    setPending({ task: t, action: "decide" });
                  }}>
                    Review
                  </Button>
                )}
              </Group>
            </Card>
          ))}
          {tasks.length === 0 && (
            <Text c="dimmed">Nothing waits on you right now.</Text>
          )}
        </Stack>
      )}

      <FormModal
        opened={pending !== null}
        onClose={() => setPending(null)}
        title={
          pending?.action === "respond"
            ? "Answer the assignment"
            : pending?.action === "review"
              ? "Review the resumption"
              : `Decision — ${pending?.task.task_class.replace(/_/g, " ")}`
        }
        onSubmit={act}
        submitLabel="Confirm"
        submitting={decide.isPending || respond.isPending
          || reviewResumption.isPending}
      >
        <Stack>
          {pending?.action === "decide"
            && (pending.task.task_class === "unit_head_review"
              || pending.task.task_class === "final_sanction") && (
            <Select
              label="Outcome"
              data={pending.task.task_class === "unit_head_review"
                ? unitHeadOutcomes(pending.task.request)
                : [
                  { value: "approve", label: "Approve" },
                  { value: "reject", label: "Reject" },
                ]}
              value={outcome}
              onChange={(v) => setOutcome(v ?? "approve")}
            />
          )}
          {pending?.action === "review" && (
            <>
              <Select
                label="Outcome"
                data={RESUMPTION_OUTCOMES}
                value={outcome}
                onChange={(v) => setOutcome(v ?? "normal")}
              />
              <Textarea
                label="Reason (optional)" value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </>
          )}
          {pending?.action === "respond" && (
            <Text size="sm">
              {outcome === "accept"
                ? "Accept responsibility for this period."
                : "Decline — the applicant will nominate a replacement or withdraw."}
            </Text>
          )}
          {pending?.action === "decide" && (
            <Textarea
              label="Reason (optional)" value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          )}
        </Stack>
      </FormModal>
    </Container>
  );
}
