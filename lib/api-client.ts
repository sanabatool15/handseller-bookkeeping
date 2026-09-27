// Same-origin by default (frontend + backend are one Vercel deployment,
// backend reachable under /api -- see vercel.json's rewrite and
// api/index.py). Override NEXT_PUBLIC_API_URL for local dev against a
// backend on a different origin/port than next.config.ts's dev proxy.
const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "/api").replace(/\/+$/, "");

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

async function request<T>(
  path: string,
  options: RequestInit & { auth?: boolean; idempotent?: boolean } = {}
): Promise<T> {
  const { auth = true, idempotent = false, headers, ...rest } = options;
  const finalHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...(headers as Record<string, string>),
  };

  if (auth) {
    const token = getToken();
    if (token) finalHeaders["Authorization"] = `Bearer ${token}`;
  }

  if (idempotent) {
    finalHeaders["Idempotency-Key"] =
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random()}`;
  }

  const res = await fetch(`${API_URL}${path}`, {
    ...rest,
    headers: finalHeaders,
  });

  if (res.status === 204) return undefined as T;

  let body: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!res.ok) {
    const message =
      (body && typeof body === "object" && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : null) ?? res.statusText;

    if (res.status === 401 && auth && typeof window !== "undefined") {
      localStorage.removeItem("access_token");
      localStorage.removeItem("user");
      localStorage.removeItem("org");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }

    throw new ApiError(res.status, message || "Request failed");
  }

  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, data?: unknown, opts?: { auth?: boolean }) =>
    request<T>(path, {
      method: "POST",
      body: data !== undefined ? JSON.stringify(data) : undefined,
      idempotent: true,
      ...opts,
    }),
  put: <T>(path: string, data?: unknown) =>
    request<T>(path, {
      method: "PUT",
      body: data !== undefined ? JSON.stringify(data) : undefined,
      idempotent: true,
    }),
  delete: <T>(path: string) =>
    request<T>(path, { method: "DELETE", idempotent: true }),
};
