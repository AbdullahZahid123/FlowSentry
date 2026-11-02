// Typed client for the FlowSentry API (same-origin via Next.js rewrites).

export type Envelope<T> = {
  data?: T;
  error?: ApiErrorBody;
  meta?: Record<string, unknown>;
};
export type ApiErrorBody = {
  code: string;
  message: string;
  details?: { field?: string; issue?: string }[];
};

export function readCookie(name: string): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : "";
}

export type ApiResult<T> = {
  ok: boolean;
  status: number;
  data?: T;
  error?: ApiErrorBody;
  meta?: {
    next_cursor?: string | null;
    has_more?: boolean;
    [key: string]: unknown;
  };
};

export async function api<T = unknown>(
  path: string,
  opts: {
    method?: string;
    body?: unknown;
    workspaceId?: string;
    query?: Record<string, string | number | undefined>;
  } = {},
): Promise<ApiResult<T>> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (["POST", "PATCH", "PUT", "DELETE"].includes(method)) {
    headers["X-CSRF-Token"] = readCookie("flowsentry_csrf");
  }
  let url = path.startsWith("/api") ? path : `/api${path}`;
  const params = new URLSearchParams();
  if (opts.workspaceId) params.set("workspace_id", opts.workspaceId);
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v !== undefined) params.set(k, String(v));
  }
  const qs = params.toString();
  if (qs) url += (url.includes("?") ? "&" : "?") + qs;

  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers,
      credentials: "include",
      signal: AbortSignal.timeout(20000),
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch (e) {
    return {
      ok: false,
      status: 0,
      error: {
        code: "network_error",
        message: "Could not reach the FlowSentry backend.",
      } as ApiErrorBody,
    };
  }
  let body: Envelope<T> | unknown = undefined;
  try {
    body = res.status === 204 ? undefined : await res.json();
  } catch {
    /* empty body */
  }
  const env = (body ?? {}) as Envelope<T>;
  if (!res.ok) {
    return {
      ok: false,
      status: res.status,
      error: env.error ?? {
        code: "unknown",
        message: `Request failed (${res.status}).`,
      },
    };
  }
  return { ok: true, status: res.status, data: env.data, meta: env.meta };
}

export async function getJson<T>(
  path: string,
  workspaceId?: string,
  query?: Record<string, string | number | undefined>,
): Promise<T | undefined> {
  const r = await api<T>(path, { workspaceId, query });
  if (!r.ok) throw new ApiClientError(r.error!);
  return r.data;
}

export class ApiClientError extends Error {
  code: string;
  details?: { field?: string; issue?: string }[];
  constructor(e: ApiErrorBody) {
    super(e.message);
    this.code = e.code;
    this.details = e.details;
  }
}

export function fmtDateTime(iso?: string | null, timeZone="UTC"): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    timeZone,
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtDuration(ms?: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  const m = Math.floor(ms / 60000),
    s = Math.round((ms % 60000) / 1000);
  return `${m}m ${s}s`;
}
