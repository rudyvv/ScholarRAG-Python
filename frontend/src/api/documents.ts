import client from './client'
import type {
  Document,
  Chunk,
  InitUploadResponse,
  CompleteUploadResponse,
  PaginatedResponse,
} from '@/types'

export function listDocuments(page = 1, pageSize = 20) {
  return client.get<PaginatedResponse<Document>>('/documents/', {
    params: { page, page_size: pageSize },
  })
}

export function getDocument(id: number) {
  return client.get<Document>(`/documents/${id}`)
}

export function deleteDocument(id: number) {
  return client.delete(`/documents/${id}`)
}

export function toggleDocumentVisibility(id: number, isPublic: boolean) {
  return client.put(`/documents/${id}/visibility`, { is_public: isPublic })
}

export function reprocessDocument(id: number) {
  return client.post<CompleteUploadResponse>(`/documents/${id}/reprocess`)
}

export function initUpload(filename: string, fileSize: number, contentType: string, fileMd5 = '') {
  return client.post<InitUploadResponse>('/documents/upload/init', {
    filename,
    file_size: fileSize,
    file_md5: fileMd5,
    content_type: contentType,
  })
}

export function uploadChunk(uploadId: string, chunkNumber: number, blob: Blob) {
  const formData = new FormData()
  formData.append('upload_id', uploadId)
  formData.append('chunk_number', String(chunkNumber))
  formData.append('file', blob)
  return client.post('/documents/upload/chunk', formData)
}

export function completeUpload(uploadId: string) {
  return client.post<CompleteUploadResponse>('/documents/upload/complete', {
    upload_id: uploadId,
  })
}

export function getUploadStatus(uploadId: string) {
  return client.get(`/documents/upload/status/${uploadId}`)
}

export function getDocumentChunks(id: number) {
  return client.get<{ chunks: Chunk[]; total: number }>(`/documents/${id}/chunks`)
}

export function getDocumentDownloadUrl(id: number) {
  return client.get<{ url: string }>(`/documents/${id}/download`)
}

export function previewDocument(id: number) {
  return client.get(`/documents/${id}/preview`, {
    responseType: 'blob',
  })
}

export function getPreviewUrl(id: number) {
  return `/api/v1/documents/${id}/preview`
}

// ===== Batch operations =====

export function batchDelete(documentIds: number[]) {
  return client.post<{ deleted_ids: number[]; errors: Array<{document_id: number; error: string}> }>(
    '/documents/batch/delete',
    { document_ids: documentIds },
  )
}

export function batchReprocess(documentIds: number[]) {
  return client.post<{ queued: Array<{document_id: number; task_id: string; status: string}>; errors: Array<{document_id: number; error: string}> }>(
    '/documents/batch/reprocess',
    { document_ids: documentIds },
  )
}
