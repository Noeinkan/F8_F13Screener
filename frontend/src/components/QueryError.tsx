import { Alert, Button, Group, Stack, Text } from "@mantine/core";
import { describeError } from "@/api/client";

type QueryErrorProps = {
  error: unknown;
  /** Called by the Retry button; usually `() => query.refetch()`. */
  onRetry?: () => unknown;
  /** True while the retry is in flight. */
  retrying?: boolean;
  /** What failed to load, e.g. "Could not load the fund list". */
  title?: string;
  mb?: string | number;
  mt?: string | number;
};

/**
 * The one way a failed request shows up on screen. Keeps "the API failed"
 * distinct from "the API answered with nothing", which every page renders as
 * an empty state of its own.
 */
export function QueryError({
  error,
  onRetry,
  retrying = false,
  title = "Could not load this data",
  mb = "md",
  mt,
}: QueryErrorProps) {
  const { message, status, detail, hint } = describeError(error);
  return (
    <Alert variant="light" color="red" radius="md" title={title} mb={mb} mt={mt} role="alert">
      <Stack gap={6}>
        <Text size="sm">
          {message}
          {status ? (
            <Text span size="sm" c="dimmed">
              {" "}
              (HTTP {status})
            </Text>
          ) : null}
        </Text>
        {detail && detail !== message ? (
          <Text size="sm" c="dimmed" style={{ wordBreak: "break-word" }}>
            {detail}
          </Text>
        ) : null}
        {hint ? (
          <Text size="sm" style={{ wordBreak: "break-word" }}>
            {hint}
          </Text>
        ) : null}
        {onRetry ? (
          <Group>
            <Button size="xs" variant="light" color="red" loading={retrying} onClick={() => void onRetry()}>
              Retry
            </Button>
          </Group>
        ) : null}
      </Stack>
    </Alert>
  );
}
