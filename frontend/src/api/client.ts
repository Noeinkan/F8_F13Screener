const API_BASE = "";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Read an error response body once. `response.json()` consumes the stream, so
 * falling back to `response.text()` after a failed parse throws a TypeError and
 * the HTTP status is lost (an nginx 502 page, an empty proxy 500). Read the
 * text first, then try to parse it.
 */
async function readErrorBody(response: Response): Promise<unknown> {
  let text = "";
  try {
    text = await response.text();
  } catch {
    return undefined;
  }
  if (!text) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
  });
  if (!response.ok) {
    const body = await readErrorBody(response);
    throw new ApiError(`Request failed: ${response.status}`, response.status, body);
  }
  return response.json() as Promise<T>;
}

export async function apiPost<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    const body = await readErrorBody(response);
    throw new ApiError(`Request failed: ${response.status}`, response.status, body);
  }
  return response.json() as Promise<T>;
}

export type ErrorDescription = {
  /** One short sentence for the user. */
  message: string;
  /** HTTP status, when the API answered at all. */
  status?: number;
  /** What the API said went wrong (FastAPI `detail`). */
  detail?: string;
  /** What to do about it (the 503 `recovery_hint`). */
  hint?: string;
};

function detailText(detail: unknown): { detail?: string; hint?: string } {
  if (typeof detail === "string") return { detail };
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{ loc: [...], msg: "..." }, ...]
    const messages = detail
      .map((item) => {
        if (!item || typeof item !== "object") return "";
        const entry = item as { loc?: unknown[]; msg?: unknown };
        const field = Array.isArray(entry.loc) ? entry.loc[entry.loc.length - 1] : undefined;
        const msg = typeof entry.msg === "string" ? entry.msg : "";
        return field !== undefined && msg ? `${String(field)}: ${msg}` : msg;
      })
      .filter(Boolean);
    return messages.length ? { detail: messages.join("; ") } : {};
  }
  if (detail && typeof detail === "object") {
    const entry = detail as { message?: unknown; recovery_hint?: unknown };
    return {
      detail: typeof entry.message === "string" ? entry.message : undefined,
      hint: typeof entry.recovery_hint === "string" ? entry.recovery_hint : undefined,
    };
  }
  return {};
}

/** Turn anything a query or fetch can throw into text a user can act on. */
export function describeError(error: unknown): ErrorDescription {
  if (error instanceof ApiError) {
    const body = error.body;
    const parsed =
      body && typeof body === "object" && "detail" in body
        ? detailText((body as { detail: unknown }).detail)
        : {};
    let message: string;
    if (error.status === 503) message = "The dashboard database is not available right now.";
    else if (error.status >= 500) message = "The API ran into an error.";
    else if (error.status === 404) message = "Not found.";
    else if (error.status === 401 || error.status === 403) message = "You are not signed in, or not allowed to see this.";
    else message = "The request was not accepted.";
    return { message, status: error.status, ...parsed };
  }
  if (error instanceof TypeError) {
    // fetch() rejects with a TypeError when the server cannot be reached.
    return { message: "Could not reach the API. It may be stopped or restarting." };
  }
  if (error instanceof Error) return { message: error.message };
  return { message: String(error) };
}
