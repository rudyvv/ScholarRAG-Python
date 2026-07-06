import client from './client'
import type {
  ModelProvider,
  ModelProviderCreate,
  ModelProviderUpdate,
} from '@/types'

export function listModels() {
  return client.get<{ items: ModelProvider[]; total: number }>('/models/')
}

export function getModel(id: number) {
  return client.get<ModelProvider>(`/models/${id}`)
}

export function createModel(data: ModelProviderCreate) {
  return client.post<ModelProvider>('/models/', data)
}

export function updateModel(id: number, data: ModelProviderUpdate) {
  return client.put<ModelProvider>(`/models/${id}`, data)
}

export function deleteModel(id: number) {
  return client.delete(`/models/${id}`)
}

export function testProviderConnection(id: number) {
  return client.post<{ success: boolean; model_name: string; latency_ms: number }>(`/models/${id}/test`)
}
