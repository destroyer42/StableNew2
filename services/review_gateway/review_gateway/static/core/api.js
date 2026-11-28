// The gateway's JSON API, and the key that makes a resent request the same request.

export class ApiError extends Error {
  constructor(status, code) {
    super(code);
    this.status = status;
    this.code = code;
  }
}

export async function api(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "X-Review-Gateway": "1", "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  }).catch((error) => {
    error.offline = true; // no answer at all; still the same error to whoever retries
    throw error;
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, data.error || "failed");
  return data;
}

export function idempotencyKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
