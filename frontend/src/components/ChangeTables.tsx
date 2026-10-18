import { Alert, Group, Tabs } from "@mantine/core";
import { DataTable } from "@/components/DataTable";
import { ExportLink } from "@/components/ExportLink";
import { ISSUER_CELL_LINK } from "@/utils/cellLinks";

export type FormattedDiffSection = {
  rows: Record<string, unknown>[];
  count: number;
  value_multiplier?: number;
};

export type FormattedDiff = {
  new_positions?: FormattedDiffSection;
  closed_positions?: FormattedDiffSection;
  share_changes?: FormattedDiffSection;
  has_any?: boolean;
};

export type ChangeTableExport = { href: string; fileName: string };

const NEW_POSITIONS_COLUMN_ORDER = ["Issuer", "CUSIP", "Class", "Put/Call", "Shares", "Value", "Type"];

const CLOSED_POSITIONS_COLUMN_ORDER = [
  "Issuer",
  "CUSIP",
  "Class",
  "Put/Call",
  "Previous Shares",
  "Previous Value",
  "Type",
];

const CHANGES_COLUMN_ORDER = [
  "Issuer",
  "Direction",
  "Delta %",
  "Delta Shares",
  "Delta Value %",
  "Delta Value",
  "Shares Before",
  "Shares After",
  "Value Before",
  "Value After",
  "CUSIP",
  "Class",
  "Put/Call",
  "Type",
];

type ChangeTablesProps = {
  formattedDiff: FormattedDiff | undefined;
  loading: boolean;
  exports?: {
    new_positions?: ChangeTableExport;
    closed_positions?: ChangeTableExport;
    share_changes?: ChangeTableExport;
  };
};

/**
 * The full lists behind one comparison, one tab per kind of change, each with
 * its CSV export. Replaces three stacked tables that pushed the page past
 * 3000px.
 */
export function ChangeTables({ formattedDiff, loading, exports }: ChangeTablesProps) {
  const sections = [
    {
      key: "new_positions" as const,
      label: "New",
      section: formattedDiff?.new_positions,
      order: NEW_POSITIONS_COLUMN_ORDER,
    },
    {
      key: "closed_positions" as const,
      label: "Closed",
      section: formattedDiff?.closed_positions,
      order: CLOSED_POSITIONS_COLUMN_ORDER,
    },
    {
      key: "share_changes" as const,
      label: "Share changes",
      section: formattedDiff?.share_changes,
      order: CHANGES_COLUMN_ORDER,
    },
  ];
  const firstWithRows = sections.find((entry) => entry.section?.count);

  // Only an answer can say "no changes": not a load in progress, not a failure.
  if (!formattedDiff) {
    return loading ? (
      <DataTable columns={[]} rows={[]} loading loadingColumns={NEW_POSITIONS_COLUMN_ORDER.length} />
    ) : null;
  }

  if (!firstWithRows) {
    return (
      <Alert variant="light" color="green" radius="md">
        No position-level changes between these two filings.
      </Alert>
    );
  }

  return (
    <Tabs defaultValue={firstWithRows.key} variant="pills" keepMounted={false}>
      <Tabs.List>
        {sections.map(({ key, label, section }) => (
          <Tabs.Tab key={key} value={key} disabled={!section?.count}>
            {label} ({section?.count ?? 0})
          </Tabs.Tab>
        ))}
      </Tabs.List>

      {sections.map(({ key, section, order }) => {
        const exportLink = exports?.[key];
        return (
          <Tabs.Panel key={key} value={key} pt="md">
            {section?.count ? (
              <>
                <DataTable
                  columns={section.rows[0] ? Object.keys(section.rows[0]) : []}
                  rows={section.rows}
                  columnOrder={order}
                  cellLinks={ISSUER_CELL_LINK}
                  maxHeight={420}
                  stickyHeader
                  loading={loading}
                  loadingColumns={order.length}
                />
                {exportLink ? (
                  <Group justify="flex-end" mt="xs">
                    <ExportLink href={exportLink.href} label="Download CSV" fileName={exportLink.fileName} />
                  </Group>
                ) : null}
              </>
            ) : null}
          </Tabs.Panel>
        );
      })}
    </Tabs>
  );
}
