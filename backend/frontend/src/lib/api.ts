const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export async function getLiveness(): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/live`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error(`API health check failed with HTTP ${response.status}`);
  return (await response.json()) as { status: string };
}
