import { useState } from "react";
import { Card, Container, Select, Stack, Text, Title } from "@mantine/core";
import { FaChartBar } from "react-icons/fa";

import { DataTable } from "../../../ui/components/DataTable";
import { ErrorState } from "../../../ui/components/ErrorState";
import { PageHeader } from "../../../ui/components/PageHeader";
import { useDepartmentReport } from "../api/hooks";

interface Row {
  key: string;
  label: string;
  count: number;
}

/** The HoD's operational picture (UC-BA-021) — scoped server-side to the
 *  HoD's own department; a foreign department is refused with 403. */
export default function ReportsPage() {
  const [department, setDepartment] = useState("CSE");
  const { data, isPending, error } = useDepartmentReport(department);

  if (error) return <Container size="xl"><ErrorState error={error} /></Container>;

  const rows: Row[] = [
    ...Object.entries(data?.archival_by_status ?? {}).map(([status, n]) => ({
      key: `archival-${status}`, label: `Archival — ${status}`, count: n })),
    ...Object.entries(data?.storage_extensions_by_status ?? {})
      .map(([status, n]) => ({
        key: `ext-${status}`, label: `Storage extensions — ${status}`, count: n })),
    ...Object.entries(data?.backup_operations ?? {}).map(([k, n]) => ({
      key: `backup-${k}`, label: `Backups — ${k}`, count: n })),
  ];

  return (
    <Container size="xl">
      <PageHeader title="Department Reports"
        subtitle="Operational reports for your department" />
      <Card padding="lg">
        <Stack gap="sm">
          <Select
            w={280} label="Department"
            data={["CSE", "ECE", "ME", "Smart Manufacturing"]}
            value={department} onChange={(v) => setDepartment(v ?? "CSE")} />
          <Text size="sm" c="dimmed">
            {data?.archival_total ?? 0} archival requests, {" "}
            {data?.storage_extension_total ?? 0} storage-extension requests in{" "}
            {data?.department ?? department}.
          </Text>
          <Title order={4}>Breakdown</Title>
          <DataTable<Row>
            rows={rows}
            loading={isPending}
            rowKey={(r) => r.key}
            columns={[
              { key: "label", header: "Measure",
                render: (r) => r.label },
              { key: "count", header: "Count",
                render: (r) => String(r.count) },
            ]}
            empty={{ icon: FaChartBar, title: "Nothing to report yet" }}
          />
        </Stack>
      </Card>
    </Container>
  );
}
