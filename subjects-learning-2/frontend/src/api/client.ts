const API_BASE =
  import.meta.env.VITE_API_BASE_URL || "/api/v1";

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(
      payload?.error?.message || `请求失败（${response.status}）`,
    );
  return payload as T;
}

export function apiUrl(path: string) {
  return `${API_BASE}${path}`;
}
