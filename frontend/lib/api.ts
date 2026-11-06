export type Article = {
  title: string;
  author?: string | null;
  section?: string | null;
  date?: string | null;
  url?: string | null;
  image_url?: string | null;
  description?: string | null;
  summary?: string | null;
  author_role?: string | null;
  author_bio?: string | null;
  author_email?: string | null;
  twitter?: string | null;
  linkedin?: string | null;
  outlet?: string | null;
  source_url?: string | null;
  job_id?: string;
  article_index?: number;
  recorded_at?: string;
};

export type JobEvent = {
  stage: string;
  detail: string;
  current: number;
  total: number;
  at: string;
};

export type DiscoveryJob = {
  job_id: string;
  outlet: string;
  source_url?: string | null;
  status: "queued" | "running" | "complete" | "partial" | "failed" | "interrupted";
  stage: string;
  detail: string;
  current: number;
  total: number;
  events: JobEvent[];
  parameters: Record<string, string | number | boolean>;
  stats: Record<string, number | string | object>;
  warnings: string[];
  error?: string | null;
  created_at: string;
  updated_at: string;
  finished_at?: string | null;
};

export type DiscoveryResults = {
  job_id: string;
  status: string;
  outlet: string;
  source_url?: string | null;
  articles: Article[];
  stats: Record<string, number | string | object>;
  warnings: string[];
  total: number;
  offset: number;
  limit: number;
};

export type Journalist = {
  name: string;
  article_count: number;
  sections: string[];
  sources: string[];
  latest_article?: { title?: string; date?: string; url?: string } | null;
  email?: string | null;
  role?: string | null;
  linkedin?: string | null;
  twitter?: string | null;
  bio?: string | null;
};

export type Coverage = {
  total_articles: number;
  identified_journalists: number;
  sections: { name: string; count: number }[];
  top_journalists: { name: string; count: number }[];
  sources: { name: string; count: number }[];
};

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(API_BASE + path, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
    signal: init?.signal ?? AbortSignal.timeout(25_000),
    cache: "no-store",
  });
  if (!response.ok) {
    let message = "NewsTrace could not complete this request.";
    try {
      const payload = await response.json();
      message = payload.detail || payload.message || message;
    } catch {
      // Keep the plain-language fallback for non-JSON server errors.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function formatDate(value?: string | null): string {
  if (!value) return "DATE NOT REPORTED";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 32);
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date).toUpperCase();
}

export function safeExternalUrl(value?: string | null): string {
  if (!value) return "";
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}
