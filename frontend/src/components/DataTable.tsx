import { CSSProperties, ReactNode } from "react";
import { Link } from "react-router-dom";
import { Badge, Paper, Skeleton, Table } from "@mantine/core";
import { formatDateValue, isDateColumn } from "@/utils/dateFormat";

export type RowStyleHook = (row: Record<string, unknown>) => CSSProperties | undefined;

export type CellLinkBuilder = (row: Record<string, unknown>) => string | undefined;

type DataTableProps = {
  columns: string[];
  rows: Record<string, unknown>[];
  onRowClick?: (row: Record<string, unknown>) => void;
  maxHeight?: number | string;
  stickyHeader?: boolean;
  columnOrder?: string[];
  rowStyle?: RowStyleHook;
  emptyMessage?: string;
  loading?: boolean;
  loadingRows?: number;
  loadingColumns?: number;
  cellLinks?: Record<string, CellLinkBuilder>;
};

const TYPE_BADGE_COLORS: Record<string, string> = {
  purchase: "rgba(46, 160, 67, 0.28)",
  sell: "rgba(248, 81, 73, 0.28)",
  put: "rgba(248, 81, 73, 0.28)",
  call: "rgba(31, 111, 235, 0.28)",
  mixed: "rgba(139, 148, 158, 0.22)",
};

const DEFAULT_BADGE_COLOR = "rgba(139, 148, 158, 0.22)";

const INCREASE_BG = "rgba(46, 160, 67, 0.18)";
const DECREASE_BG = "rgba(248, 81, 73, 0.18)";

const ACCENT_COLUMNS = new Set([
  "Direction",
  "Delta %",
  "Delta Shares",
  "Delta Value %",
  "Delta Value",
]);

function isTypeColumn(column: string): boolean {
  return column === "Type";
}

function resolveTypeBadgeStyle(label: string): { color: string; text: string } {
  const key = label.trim().toLowerCase();
  return {
    color: TYPE_BADGE_COLORS[key] ?? DEFAULT_BADGE_COLOR,
    text: label || "-",
  };
}

function renderCell(column: string, row: Record<string, unknown>) {
  if (isDateColumn(column)) return formatDateValue(row[column]);
  if (isTypeColumn(column)) {
    const raw = row[column];
    const label = raw === null || raw === undefined ? "" : String(raw);
    return label;
  }
  return String(row[column] ?? "-");
}

function resolveColumns(columns: string[], columnOrder?: string[]): string[] {
  if (columnOrder?.length) {
    const known = new Set(columns);
    const ordered = columnOrder.filter((column) => known.has(column));
    const rest = columns.filter((column) => !ordered.includes(column));
    return [...ordered, ...rest];
  }
  return columns;
}

function resolveBaseRowStyle(column: string, row: Record<string, unknown>): CSSProperties | undefined {
  if (isTypeColumn(column)) {
    const raw = row[column];
    const label = raw === null || raw === undefined ? "" : String(raw);
    const { color } = resolveTypeBadgeStyle(label);
    return { backgroundColor: color, fontWeight: 700 };
  }
  return undefined;
}

function resolveIncreaseDecreaseStyle(column: string, row: Record<string, unknown>): CSSProperties | undefined {
  const direction = row["Direction"];
  if (direction !== "Increase" && direction !== "Decrease") return undefined;
  if (ACCENT_COLUMNS.has(column)) {
    return {
      backgroundColor: direction === "Increase" ? "rgba(46, 160, 67, 0.34)" : "rgba(248, 81, 73, 0.34)",
      fontWeight: 600,
    };
  }
  return {
    backgroundColor: direction === "Increase" ? INCREASE_BG : DECREASE_BG,
  };
}

const TICKER_LINK_STYLE: CSSProperties = {
  color: "var(--f8-accent, #1f6feb)",
  textDecoration: "none",
  fontWeight: 600,
  cursor: "pointer",
};

function wrapWithLink(content: ReactNode, href: string | undefined): ReactNode {
  if (!href) return content;
  return (
    <Link
      to={href}
      style={TICKER_LINK_STYLE}
      onClick={(event) => event.stopPropagation()}
    >
      {content}
    </Link>
  );
}

export function DataTable({
  columns,
  rows,
  onRowClick,
  maxHeight,
  stickyHeader,
  columnOrder,
  rowStyle,
  emptyMessage = "No rows to display.",
  loading = false,
  loadingRows = 6,
  loadingColumns,
  cellLinks,
}: DataTableProps) {
  const orderedColumns = resolveColumns(columns, columnOrder);
  const skeletonColumnCount =
    orderedColumns.length > 0
      ? orderedColumns.length
      : loadingColumns ?? columnOrder?.length ?? 5;

  const containerStyle: CSSProperties = {
    overflow: "auto",
  };
  if (maxHeight !== undefined) {
    containerStyle.maxHeight = maxHeight;
  }

  const headerStyle: CSSProperties = stickyHeader
    ? { position: "sticky", top: 0, zIndex: 1, backgroundColor: "white" }
    : {};

  if (loading) {
    const skeletonHeaders =
      orderedColumns.length > 0
        ? orderedColumns
        : Array.from({ length: skeletonColumnCount }, (_, index) => `col-${index}`);
    return (
      <Paper withBorder radius="md" bg="white" style={containerStyle}>
        <Table striped highlightOnHover>
          <Table.Thead style={headerStyle}>
            <Table.Tr>
              {skeletonHeaders.map((column) => (
                <Table.Th key={column}>
                  <Skeleton height={16} width="70%" />
                </Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {Array.from({ length: loadingRows }).map((_, rowIndex) => (
              <Table.Tr key={rowIndex}>
                {Array.from({ length: skeletonColumnCount }).map((_, colIndex) => (
                  <Table.Td key={colIndex}>
                    <Skeleton height={16} width={colIndex === 0 ? "85%" : "60%"} />
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Paper>
    );
  }

  if (rows.length === 0) {
    return (
      <Paper withBorder radius="md" bg="white" p="md">
        <span style={{ color: "var(--f8-muted)", fontSize: "0.9rem" }}>{emptyMessage}</span>
      </Paper>
    );
  }

  return (
    <Paper withBorder radius="md" bg="white" style={containerStyle}>
      <Table striped highlightOnHover>
        <Table.Thead style={headerStyle}>
          <Table.Tr>
            {orderedColumns.map((column) => (
              <Table.Th key={column}>{column}</Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row, index) => {
            const userStyle = rowStyle?.(row);
            const clickable = Boolean(onRowClick);
            return (
              <Table.Tr
                key={index}
                onClick={clickable ? () => onRowClick!(row) : undefined}
                style={{
                  cursor: clickable ? "pointer" : undefined,
                  ...userStyle,
                }}
              >
                {orderedColumns.map((column) => {
                  const baseStyle = resolveBaseRowStyle(column, row);
                  const directionStyle = resolveIncreaseDecreaseStyle(column, row);
                  const cellStyle = baseStyle ?? directionStyle;
                  const linkHref = cellLinks?.[column]?.(row);
                  if (isTypeColumn(column)) {
                    const raw = row[column];
                    const label = raw === null || raw === undefined ? "" : String(raw);
                    const { color } = resolveTypeBadgeStyle(label);
                    return (
                      <Table.Td key={column} style={cellStyle}>
                        <Badge
                          variant="filled"
                          radius="sm"
                          styles={{
                            root: {
                              backgroundColor: color,
                              color: "#1a1f2e",
                              textTransform: "none",
                              fontWeight: 700,
                            },
                          }}
                        >
                          {label || "-"}
                        </Badge>
                      </Table.Td>
                    );
                  }
                  return (
                    <Table.Td key={column} style={cellStyle}>
                      {wrapWithLink(renderCell(column, row), linkHref)}
                    </Table.Td>
                  );
                })}
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Paper>
  );
}