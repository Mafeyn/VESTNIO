/** Typed client for the VESTNIO REST API, resilient to flaky mobile networks. */

export type CategoryId = "gaming" | "world" | "technology";
export type Sort = "newest" | "oldest" | "relevance";

export interface SourceRef {
  id: string;
  name: string;
  homepage: string | null;
}

export interface Article {
  id: number;
  title: string;
  summary: string | null;
  image_url: string | null;
  url: string;
  published_at: string;
  published_estimated: boolean;
  language: string | null;
  category: CategoryId;
  source: SourceRef;
}

export interface Category {
  id: CategoryId;
  label: string;
  article_count: number;
  last_24h: number;
  source_count: number;
  latest_published_at: string | null;
}

export interface Source {
  id: string;
  name: string;
  homepage: string | null;
  category: CategoryId;
  method: "rss" | "api" | "html" | "telegram";
  enabled: boolean;
  status: "pending" | "healthy" | "degraded" | "failing" | "disabled";
  poll_minutes: number;
  last_success_at: string | null;
  last_polled_at: string | null;
  last_error: string | null;
  article_count: number;
}

export interface ListMeta {
  count: number;
  limit?: number | null;
  next_cursor?: string | null;
  sort?: Sort | null;
}

interface Envelope<T> {
  data: T;
  meta?: ListMeta;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
  ) {
    super(message);
  }
  get isNetwork() {
    return this.status === 0;
  }
}

const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";
const TIMEOUT_MS = 12_000;

async function request<T>(path: string, signal?: AbortSignal): Promise<Envelope<T>> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(new DOMException("timeout", "TimeoutError")), TIMEOUT_MS);
  signal?.addEventListener("abort", () => ctrl.abort(signal.reason), { once: true });
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { signal: ctrl.signal, headers: { Accept: "application/json" } });
  } catch (e) {
    if (signal?.aborted) throw e;
    throw new ApiError("Network unavailable", 0, "network");
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let code = "http_error";
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      code = body?.error?.code ?? code;
      message = body?.error?.message ?? message;
    } catch {
      /* non-JSON error page from a proxy */
    }
    throw new ApiError(message, res.status, code);
  }
  return res.json();
}

export interface FeedParams {
  category?: CategoryId | null;
  sources?: string[];
  q?: string;
  sort?: Sort;
  cursor?: string | null;
  limit?: number;
}

export function feedQueryString(p: FeedParams): string {
  const qs = new URLSearchParams();
  if (p.category) qs.set("category", p.category);
  if (p.sources?.length) qs.set("source", p.sources.join(","));
  if (p.q?.trim()) qs.set("q", p.q.trim());
  if (p.sort && p.sort !== "newest") qs.set("sort", p.sort);
  if (p.cursor) qs.set("cursor", p.cursor);
  qs.set("limit", String(p.limit ?? 20));
  return qs.toString();
}

export const api = {
  articles: (p: FeedParams, signal?: AbortSignal) =>
    request<Article[]>(`/api/v1/articles?${feedQueryString(p)}`, signal),
  article: (id: number, signal?: AbortSignal) => request<Article>(`/api/v1/articles/${id}`, signal),
  categories: (signal?: AbortSignal) => request<Category[]>("/api/v1/categories", signal),
  sources: (signal?: AbortSignal) => request<Source[]>("/api/v1/sources", signal),
};
