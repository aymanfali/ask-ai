export interface User {
  id: string;
  email: string;
  display_name: string | null;
  email_verified: boolean;
  created_at: string;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: "Bearer";
  expires_in: number;
  csrf_token: string;
  user: User;
}

export interface Conversation {
  id: string;
  title: string;
  last_message_sequence: number;
  created_at: string;
  updated_at: string;
}

export interface ConversationPage {
  items: Conversation[];
  next_cursor: string | null;
}

export type MessageRole = "user" | "assistant";
export type MessageStatus =
  | "complete"
  | "pending"
  | "streaming"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface Message {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  status: MessageStatus;
  sequence: number;
  created_at: string;
  optimistic?: boolean;
}

export interface MessagePage {
  items: Message[];
  next_before_sequence: number | null;
}

export interface ModelCapabilities {
  streaming: boolean;
  tools: boolean;
  structured_output: boolean;
  vision: boolean;
  reasoning: boolean;
}

export interface ModelPricing {
  version: string;
  effective_from: string;
  currency: string;
  input_per_million_tokens: string | number | null;
  output_per_million_tokens: string | number | null;
  cached_input_per_million_tokens?: string | number | null;
}

export interface LLMModel {
  id: string;
  provider_id: string;
  provider_name: string;
  name: string;
  provider_model_id: string;
  description: string | null;
  context_window: number;
  max_output_tokens: number;
  capabilities: ModelCapabilities;
  current_pricing: ModelPricing | null;
}

export interface LLMProvider {
  id: string;
  name: string;
  type: string;
  enabled: boolean;
  model_count: number;
}

export interface GenerationUsage {
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  cached_input_tokens?: number | null;
  usage_source: "provider_reported" | "estimated" | "unavailable";
  estimated_cost: string | null;
  currency: string | null;
  pricing_version?: string | null;
}

export interface GenerationStatus {
  id: string;
  conversation_id: string;
  user_message_id: string;
  assistant_message_id: string;
  provider_id: string;
  model_id: string;
  status: "pending" | "streaming" | "completed" | "failed" | "cancelled" | "interrupted";
  error_code: string | null;
  finish_reason: string | null;
  provider_request_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  usage: GenerationUsage | null;
}

export interface GenerationStartedEvent {
  generation_id: string;
  conversation_id: string;
  user_message_id: string;
  assistant_message_id: string;
  assistant_sequence: number;
  replayed: boolean;
}

export interface GenerationUsageEvent {
  generation_id: string;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  source: "provider_reported";
}

export interface GenerationCompletedEvent {
  generation_id: string;
  message_id: string;
  finish_reason: string | null;
  provider_request_id: string | null;
  usage: GenerationUsage | null;
}

export interface GenerationErrorEvent {
  generation_id: string;
  code: string;
}

export interface GenerationCancelledEvent {
  generation_id: string;
  message_id: string;
}

export type GenerationEvent =
  | { type: "generation.started"; data: GenerationStartedEvent }
  | { type: "message.delta"; data: { generation_id: string; message_id: string; text: string } }
  | { type: "generation.usage"; data: GenerationUsageEvent }
  | { type: "stream.heartbeat"; data: { generation_id: string } }
  | { type: "generation.completed"; data: GenerationCompletedEvent }
  | { type: "generation.error"; data: GenerationErrorEvent }
  | { type: "generation.cancelled"; data: GenerationCancelledEvent };

export interface ApiErrorPayload {
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
    request_id?: string | null;
  };
}
