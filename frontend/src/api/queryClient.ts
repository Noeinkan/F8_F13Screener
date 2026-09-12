import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";

const MAX_RETRIES = 2;

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      // A 4xx will not change by asking again (bad parameters, unknown fund),
      // so fail at once. 5xx and network errors get at most two more tries.
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status < 500) return false;
        return failureCount < MAX_RETRIES;
      },
    },
  },
});
