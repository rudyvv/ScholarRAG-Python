// ===== User & Auth =====

export interface User {
  id: number
  username: string
  email: string
  is_active: boolean
  role: 'admin' | 'user'
  created_at: string
  updated_at: string
}

export interface AdminUser {
  id: number
  username: string
  email: string
  role: 'admin' | 'user'
  is_active: boolean
  org_tags: string | null
  created_at: string
  updated_at: string | null
}

export interface DocumentsByStatus {
  ready: number
  processing: number
  failed: number
  uploading: number
}

export interface AdminDashboard {
  total_users: number
  total_documents: number
  total_sessions: number
  documents_by_status: DocumentsByStatus
}

export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  username: string
  email: string
  password: string
}

export interface AuthTokens {
  access_token: string
  refresh_token: string
  token_type: string
}

// ===== Documents =====

export type DocStatus = 'uploading' | 'processing' | 'ready' | 'failed'

export interface Document {
  id: number
  user_id: number
  filename: string
  file_md5: string | null
  file_size: number
  storage_path: string
  content_type: string
  doc_status: DocStatus
  is_public: boolean
  org_tag: string | null
  owner_username?: string
  chunk_count: number
  created_at: string
  updated_at: string
}

export interface Chunk {
  id: number
  document_id: number
  chunk_index: number
  content: string
  chunk_metadata: Record<string, unknown> | null
}

export interface InitUploadResponse {
  upload_id: string
  chunk_size: number
  duplicate?: boolean
  document_id?: number
  message?: string
}

export interface CompleteUploadResponse {
  document_id: number
  task_id: string
  status: string
}

// ===== Chat / Conversation =====

export interface ConversationSession {
  id: number
  title: string
  created_at: string
  updated_at: string
}

export interface ConversationMessage {
  id: number
  session_id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  metadata: Record<string, unknown> | null
  created_at: string
}

export interface AskRequest {
  query: string
  session_id?: number
  doc_id?: number
}

export interface AskResponse {
  answer: string
  sources: SearchResultItem[]
}

// ===== Search =====

export interface SearchRequest {
  query: string
  doc_id?: number
  page?: number
  size?: number
}

export interface SearchResultItem {
  chunk_id: number
  content: string
  score: number
  document_id: number
  filename: string
  chunk_index: number
}

export interface SearchResponse {
  items: SearchResultItem[]
  total: number
}

// ===== Model Provider =====

export interface ModelProvider {
  id: number
  provider_name: string
  api_base_url: string
  api_key_ciphertext: string
  model_name: string
  embedding_model: string
  embedding_dim: number
  is_active: boolean
  org_tag: string | null
  created_at: string
  updated_at: string
}

export interface ModelProviderCreate {
  provider_name: string
  api_base_url: string
  api_key: string
  model_name: string
  embedding_model: string
  embedding_dim: number
  is_active?: boolean
}

export interface ModelProviderUpdate {
  api_base_url?: string
  api_key?: string
  model_name?: string
  embedding_model?: string
  embedding_dim?: number
  is_active?: boolean
}

// ===== Tasks =====

export interface TaskStatusResponse {
  task_id: string
  status: string
  result: Record<string, unknown> | null
}

export interface DocumentProgress {
  document_id: number
  task_id: string
  status: string
}

export interface QueueHealth {
  status: string
  workers: unknown[]
}

// ===== Stats =====

export interface DashboardStats {
  document_count: number
  chunk_count: number
  conversation_count: number
  total_tokens: number
}

// ===== API Response =====

export interface ApiResponse<T = unknown> {
  data: T
  message?: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface ApiError {
  detail: string
}
