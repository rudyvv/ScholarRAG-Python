import client from './client'
import type { SearchRequest, SearchResponse } from '@/types'

export function hybridSearch(data: SearchRequest) {
  return client.post<SearchResponse>('/search', data)
}
