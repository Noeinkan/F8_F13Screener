import { Paper, SimpleGrid, Skeleton, Stack, Text } from "@mantine/core";

type ChartLoadingProps = {
  height?: number;
  label?: string;
  title?: string;
};

export function ChartLoading({
  height = 360,
  label = "Loading chart…",
  title,
}: ChartLoadingProps) {
  return (
    <Paper withBorder p="md" radius="md" bg="white">
      <Stack gap="sm">
        {title ? (
          <Text size="sm" fw={700}>
            {title}
          </Text>
        ) : null}
        <Text size="xs" c="dimmed">
          {label}
        </Text>
        <Skeleton height={height} radius="md" />
      </Stack>
    </Paper>
  );
}

type KpiLoadingProps = {
  count?: number;
};

export function KpiLoading({ count = 4 }: KpiLoadingProps) {
  return (
    <SimpleGrid cols={{ base: 1, sm: 2, lg: count }} spacing="md" mb="lg">
      {Array.from({ length: count }).map((_, index) => (
        <Paper key={index} withBorder p="md" radius="md" bg="white">
          <Stack gap="xs">
            <Skeleton height={12} width="60%" />
            <Skeleton height={22} width="40%" />
          </Stack>
        </Paper>
      ))}
    </SimpleGrid>
  );
}
