import { SimpleGrid, Paper, Text } from "@mantine/core";

type KpiCardProps = {
  label: string;
  value: string;
  delta?: string | null;
};

export function KpiCard({ label, value, delta }: KpiCardProps) {
  const showDelta = delta !== undefined && delta !== null && delta !== "";
  return (
    <Paper withBorder p="md" radius="md" bg="white">
      <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
        {label}
      </Text>
      <Text size="xl" fw={700} mt={4}>
        {value}
      </Text>
      {showDelta ? (
        <Text size="sm" c="dimmed" mt={4}>
          {delta}
        </Text>
      ) : null}
    </Paper>
  );
}

type KpiGridProps = {
  items: KpiCardProps[];
};

export function KpiGrid({ items }: KpiGridProps) {
  return (
    <SimpleGrid
      // Two per row on a phone (the tiles are short), all on one row on a
      // wide screen so five tiles never leave one orphan below.
      cols={{ base: Math.min(items.length, 2), md: Math.min(items.length, 3), lg: Math.min(items.length, 5) }}
      spacing="md"
      mb="lg"
    >
      {items.map((item) => (
        <KpiCard key={item.label} {...item} />
      ))}
    </SimpleGrid>
  );
}
