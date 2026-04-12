const BASE_URL = import.meta.env.VITE_API_URL || "/api/v1";
const TOKEN_STORAGE_KEY = "lexguardian-auth-token";

/** Normalize FastAPI `detail` (string | list | object) for user-visible errors. */
export function formatApiErrorDetail(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const message =
            "msg" in item && typeof item.msg === "string" ? item.msg : null;
          const location =
            "loc" in item && Array.isArray(item.loc)
              ? item.loc
                  .filter((part: unknown) => typeof part === "string" || typeof part === "number")
                  .join(".")
              : null;
          return location ? `${location}: ${message ?? "Invalid value"}` : message;
        }
        return null;
      })
      .filter((value): value is string => Boolean(value));
    if (messages.length) return messages.join("; ");
  }
  if (detail && typeof detail === "object" && "msg" in detail && typeof (detail as { msg: unknown }).msg === "string") {
    return (detail as { msg: string }).msg;
  }
  return `API Error: ${status}`;
}

export function getStoredAuthToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setStoredAuthToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
  else localStorage.removeItem(TOKEN_STORAGE_KEY);
}

class ApiClient {
  private async request<T>(path: string, options?: RequestInit): Promise<T> {
    const token = getStoredAuthToken();
    const response = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options?.headers,
      },
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(formatApiErrorDetail(error.detail, response.status));
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return response.json();
  }

  get<T>(path: string) {
    return this.request<T>(path, { method: "GET" });
  }

  /** Fetch a plain-text (or markdown) response as a string. */
  async getText(path: string): Promise<string> {
    const token = getStoredAuthToken();
    const response = await fetch(`${BASE_URL}${path}`, {
      method: "GET",
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(formatApiErrorDetail(error.detail, response.status));
    }
    return response.text();
  }

  post<T>(path: string, data?: unknown) {
    return this.request<T>(path, {
      method: "POST",
      body: data ? JSON.stringify(data) : undefined,
    });
  }

  put<T>(path: string, data?: unknown) {
    return this.request<T>(path, {
      method: "PUT",
      body: data ? JSON.stringify(data) : undefined,
    });
  }

  patch<T>(path: string, data: unknown) {
    return this.request<T>(path, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  delete(path: string) {
    return this.request(path, { method: "DELETE" });
  }

  async downloadFile(path: string, filename: string): Promise<void> {
    const token = getStoredAuthToken();
    const response = await fetch(`${BASE_URL}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Download failed" }));
      throw new Error(formatApiErrorDetail(error.detail, response.status));
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  async uploadFile<T>(path: string, file: File): Promise<T> {
    const formData = new FormData();
    formData.append("file", file);

    const token = getStoredAuthToken();
    const response = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      body: formData,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Upload failed" }));
      throw new Error(formatApiErrorDetail(error.detail, response.status));
    }

    return response.json();
  }
}

export const api = new ApiClient();
