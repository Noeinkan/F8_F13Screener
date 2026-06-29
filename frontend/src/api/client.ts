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

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
  });
  if (!response.ok) {
    let body: unknown = undefined;
    try {
      body = await response.json();
    } catch {
      body = await response.text();
    }
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
    throw new ApiError(`Request failed: ${response.status}`, response.status);
  }
  return response.json() as Promise<T>;
}
