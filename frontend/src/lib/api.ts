import type {
  AuthTokenResponse,
  Conversation,
  ConversationPage,
  GenerationEvent,
  GenerationStatus,
  LLMModel,
  LLMProvider,
  MessagePage,
  User,
} from "./types";
import { consumeSseStream } from "./sse";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const API_PREFIX = "/api/v1";

let accessToken: string | null = null;
let csrfToken: string | null = null;
let refreshInFlight: Promise<AuthTokenResponse | null> | null = null;
const SESSION_EXPIRED_EVENT = "ask-ai:session-expired";

let authChannel: BroadcastChannel | null = null;
if (typeof BroadcastChannel !== "undefined") {
  try {
    authChannel = new BroadcastChannel("ask-ai-auth");
    authChannel.addEventListener("message", (event: MessageEvent<{ type?: string }>) => {
      if (event.data?.type === "signed-out" || event.data?.type === "session-expired") {
        clearSession();
        if (typeof window !== "undefined") window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
      }
    });
  } catch {
    authChannel = null;
  }
}

function notifySessionExpired(): void {
  clearSession();
  if (typeof window !== "undefined") window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  authChannel?.postMessage({ type: "session-expired" });
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(
    message: string,
    options: { status: number; code?: string; details?: unknown; requestId?: string | null },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code ?? "request_failed";
    this.details = options.details;
    this.requestId = options.requestId ?? null;
  }
}

export function setSession(response: AuthTokenResponse): void {
  accessToken = response.access_token;
  csrfToken = response.csrf_token;
}

export function clearSession(): void {
  accessToken = null;
  csrfToken = null;
}

function apiUrl(path: string): string {
  return `${API_BASE_URL}${API_PREFIX}${path}`;
}

async function responseError(response: Response): Promise<ApiError> {
  let payload: { error?: { code?: string; message?: string; details?: unknown; request_id?: string } } = {};
  try {
    payload = (await response.json()) as typeof payload;
  } catch {
    // Non-JSON gateway and proxy errors are represented without exposing their body.
  }
  const error = payload.error;
  return new ApiError(error?.message ?? `Request failed with HTTP ${response.status}.`, {
    status: response.status,
    code: error?.code,
    details: error?.details,
    requestId: error?.request_id,
  });
}

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw await responseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function refreshSession(): Promise<AuthTokenResponse | null> {
  if (refreshInFlight) return refreshInFlight;
  const hadAccessToken = accessToken !== null;

  const performRefresh = async (): Promise<AuthTokenResponse | null> => {
    try {
      // Fetch CSRF only after acquiring the cross-tab lock. Another tab may have
      // rotated the shared HttpOnly refresh cookie while this tab was waiting.
      const csrfResponse = await fetch(apiUrl("/auth/csrf"), {
        method: "GET",
        credentials: "include",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!csrfResponse.ok) {
        if (csrfResponse.status === 401) {
          clearSession();
          if (hadAccessToken) notifySessionExpired();
        }
        return null;
      }
      const csrfPayload = (await csrfResponse.json()) as { csrf_token: string };
      csrfToken = csrfPayload.csrf_token;

      const response = await fetch(apiUrl("/auth/refresh"), {
        method: "POST",
        credentials: "include",
        headers: {
          Accept: "application/json",
          "X-CSRF-Token": csrfToken,
        },
        cache: "no-store",
      });
      if (!response.ok) {
        if (response.status === 401) {
          clearSession();
          if (hadAccessToken) notifySessionExpired();
        }
        return null;
      }
      const tokens = (await response.json()) as AuthTokenResponse;
      setSession(tokens);
      return tokens;
    } catch {
      // A network or temporary server failure is not proof that the session is invalid.
      return null;
    }
  };

  const run = async (): Promise<AuthTokenResponse | null> => {
    if (typeof navigator !== "undefined" && navigator.locks) {
      return navigator.locks.request("ask-ai-refresh-session", { mode: "exclusive" }, performRefresh);
    }
    return performRefresh();
  };

  refreshInFlight = run().finally(() => { refreshInFlight = null; });
  return refreshInFlight;
}

async function ensureAccessToken(): Promise<string> {
  if (accessToken) return accessToken;
  const refreshed = await refreshSession();
  if (!refreshed) throw new ApiError("Your session has expired. Please sign in again.", {
    status: 401,
    code: "authentication_required",
  });
  return refreshed.access_token;
}

async function publicJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  const response = await fetch(apiUrl(path), {
    ...init,
    headers,
    credentials: "include",
    cache: "no-store",
  });
  return parseJson<T>(response);
}

async function authenticatedJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await ensureAccessToken();
  const send = (bearer: string) => {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    headers.set("Authorization", `Bearer ${bearer}`);
    return fetch(apiUrl(path), {
      ...init,
      headers,
      credentials: "include",
      cache: "no-store",
    });
  };

  let response = await send(token);
  if (response.status === 401) {
    const refreshed = await refreshSession();
    if (refreshed) response = await send(refreshed.access_token);
  }
  return parseJson<T>(response);
}

export async function getLiveness(): Promise<{ status: string }> {
  return publicJson<{ status: string }>("/health/live");
}

export async function getAuthProviders(): Promise<string[]> {
  const response = await publicJson<{ providers: string[] }>("/auth/providers");
  return response.providers;
}

export async function restoreSession(): Promise<User | null> {
  const tokens = await refreshSession();
  return tokens?.user ?? null;
}

export async function login(email: string, password: string): Promise<User> {
  const response = await publicJson<AuthTokenResponse>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  setSession(response);
  return response.user;
}

export async function register(
  email: string,
  password: string,
  displayName: string,
): Promise<User> {
  const response = await publicJson<AuthTokenResponse>("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, display_name: displayName || null }),
  });
  setSession(response);
  return response.user;
}

export async function exchangeOAuthCode(code: string): Promise<User> {
  const response = await publicJson<AuthTokenResponse>("/auth/oauth/exchange", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  setSession(response);
  return response.user;
}

export function startOAuth(provider: string): void {
  window.location.assign(apiUrl(`/auth/${encodeURIComponent(provider)}/login`));
}

export async function logout(): Promise<void> {
  try {
    const token = await ensureAccessToken();
    const headers = new Headers({ Authorization: `Bearer ${token}` });
    if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
    const response = await fetch(apiUrl("/auth/logout"), {
      method: "POST",
      credentials: "include",
      headers,
      cache: "no-store",
    });
    if (!response.ok && response.status !== 401) throw await responseError(response);
  } finally {
    clearSession();
    authChannel?.postMessage({ type: "signed-out" });
  }
}

export async function getCurrentUser(): Promise<User> {
  return authenticatedJson<User>("/auth/me");
}

export async function listConversations(options: {
  limit?: number;
  cursor?: string | null;
} = {}): Promise<ConversationPage> {
  const params = new URLSearchParams({ limit: String(options.limit ?? 50) });
  if (options.cursor) params.set("cursor", options.cursor);
  return authenticatedJson<ConversationPage>(`/conversations?${params.toString()}`);
}

export async function createConversation(title?: string): Promise<Conversation> {
  return authenticatedJson<Conversation>("/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(title ? { title } : {}),
  });
}

export async function renameConversation(id: string, title: string): Promise<Conversation> {
  return authenticatedJson<Conversation>(`/conversations/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export async function deleteConversation(id: string): Promise<void> {
  return authenticatedJson<void>(`/conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function listMessages(
  conversationId: string,
  options: { limit?: number; beforeSequence?: number | null } = {},
): Promise<MessagePage> {
  const params = new URLSearchParams({ limit: String(options.limit ?? 50) });
  if (options.beforeSequence) params.set("before_sequence", String(options.beforeSequence));
  return authenticatedJson<MessagePage>(
    `/conversations/${encodeURIComponent(conversationId)}/messages?${params.toString()}`,
  );
}

export async function listProviders(): Promise<LLMProvider[]> {
  return authenticatedJson<LLMProvider[]>("/providers");
}

export async function listModels(providerId?: string): Promise<LLMModel[]> {
  const query = providerId ? `?provider_id=${encodeURIComponent(providerId)}` : "";
  return authenticatedJson<LLMModel[]>(`/models${query}`);
}

export async function getGeneration(id: string): Promise<GenerationStatus> {
  return authenticatedJson<GenerationStatus>(`/generations/${encodeURIComponent(id)}`);
}

export async function cancelGeneration(id: string): Promise<{
  generation_id: string;
  status: GenerationStatus["status"];
  cancellation_requested: boolean;
}> {
  return authenticatedJson(`/generations/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
  });
}

export interface StreamGenerationInput {
  conversationId: string;
  content: string;
  modelId: string;
  idempotencyKey: string;
  maxOutputTokens?: number;
  temperature?: number;
  signal: AbortSignal;
  onEvent: (event: GenerationEvent) => void;
}

async function streamResponse(input: StreamGenerationInput, token: string): Promise<Response> {
  const body = {
    content: input.content,
    model_id: input.modelId,
    ...(input.maxOutputTokens ? { max_output_tokens: input.maxOutputTokens } : {}),
    ...(input.temperature !== undefined ? { temperature: input.temperature } : {}),
  };
  return fetch(apiUrl(`/conversations/${encodeURIComponent(input.conversationId)}/messages/stream`), {
    method: "POST",
    credentials: "include",
    cache: "no-store",
    signal: input.signal,
    headers: {
      Accept: "text/event-stream",
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      "Idempotency-Key": input.idempotencyKey,
    },
    body: JSON.stringify(body),
  });
}

export async function streamGeneration(input: StreamGenerationInput): Promise<void> {
  let token = await ensureAccessToken();
  let response = await streamResponse(input, token);
  if (response.status === 401) {
    const refreshed = await refreshSession();
    if (refreshed) {
      token = refreshed.access_token;
      response = await streamResponse(input, token);
    }
  }
  if (!response.ok) throw await responseError(response);
  if (!response.body) {
    throw new ApiError("The server did not provide a readable stream.", {
      status: 502,
      code: "stream_unavailable",
    });
  }
  await consumeSseStream(response.body, (eventName, data) => {
    input.onEvent({ type: eventName, data } as GenerationEvent);
  }, input.signal);
}
