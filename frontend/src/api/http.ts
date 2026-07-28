const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;

  constructor(status: number, code: string, message: string, details: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  query?: Record<string, unknown>;
  signal?: AbortSignal;
}

function appendQuery(
  url: URL,
  key: string,
  value: unknown,
): void {
  if (value === undefined || value === null) {
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item) => {
      if (item === undefined || item === null) {
        return;
      }
      url.searchParams.append(key, String(item));
    });
    return;
  }
  if (value === "") {
    return;
  }
  url.searchParams.append(key, String(value));
}

function buildUrl(path: string, query?: Record<string, unknown>): string {
  const url = new URL(`${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`, window.location.origin);
  if (query) {
    Object.entries(query).forEach(([key, value]) => {
      appendQuery(url, key, value);
    });
  }
  return url.toString();
}

function parseJsonResponse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    throw new ApiError(
      500,
      "INVALID_JSON",
      "A resposta do servidor nao e JSON valido.",
      null,
    );
  }
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, signal } = options;
  const url = buildUrl(path, query);
  const csrf = document.cookie.split("; ").find((entry) => entry.startsWith("pads_csrf="))?.split("=").slice(1).join("=");
  const response = await fetch(url, {
    method,
    headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...(!["GET"].includes(method) && csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}) },
    body: body ? JSON.stringify(body) : undefined,
    signal,
    credentials: "include",
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const rawText = await response.text();
  const payload: unknown = isJson ? parseJsonResponse(rawText) : parseJsonResponse(rawText);

  if (!response.ok) {
    const errorBody =
      typeof payload === "object" &&
      payload !== null &&
      "error" in payload
        ? (payload as { error: { code: string; message: string; details?: unknown } }).error
        : {
            code: "HTTP_ERROR",
            message: typeof payload === "string" ? payload : "Erro na requisicao.",
            details: null,
          };
    if (response.status === 401) window.dispatchEvent(new CustomEvent("pads:unauthorized", { detail: { path } }));
    throw new ApiError(response.status, errorBody.code, errorBody.message, errorBody.details);
  }

  return payload as T;
}

export const httpClient = {
  buildUrl(path: string, query?: Record<string, unknown>): string {
    return buildUrl(path, query);
  },
  get<T>(path: string, query?: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
    return request<T>(path, { method: "GET", query, signal });
  },
  post<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    return request<T>(path, { method: "POST", body, signal });
  },
  put<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, { method: "PUT", body });
  },
  delete<T>(path: string): Promise<T> {
    return request<T>(path, { method: "DELETE" });
  },
};

export const apiConfig = {
  baseUrl: API_BASE_URL,
};
