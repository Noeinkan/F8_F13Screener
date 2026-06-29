const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}/;
const DATE_FIELDS = new Set([
  "Filing Date",
  "Latest Filing",
  "filing_date",
  "filingDate",
  "latest_filing_date",
  "latest_filing",
  "FilingDate",
  "Period",
  "period_of_report",
  "Period of Report",
  "As of",
  "AsOf",
]);

export function isDateColumn(column: string): boolean {
  return DATE_FIELDS.has(column) || /date|filing|period/i.test(column);
}

export function formatDateValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  const raw = String(value).trim();
  if (!raw) return "-";

  if (ISO_DATE_RE.test(raw)) {
    const parsed = new Date(raw);
    if (!Number.isNaN(parsed.getTime())) {
      const day = String(parsed.getUTCDate()).padStart(2, "0");
      const month = String(parsed.getUTCMonth() + 1).padStart(2, "0");
      const year = parsed.getUTCFullYear();
      return `${day}/${month}/${year}`;
    }
  }
  return raw;
}

export function formatChartDate(value: string | number): string {
  if (typeof value !== "string") return String(value);
  return formatDateValue(value);
}

export function formatAccessionLabel(label: string): string {
  if (!label) return label;
  const [head, ...rest] = label.split("|");
  if (!rest.length) return formatDateValue(head);
  return `${formatDateValue(head)} |${rest.join("|")}`;
}