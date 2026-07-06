<script setup lang="ts">
import { ref, h, onMounted, onUnmounted, computed } from 'vue'
import {
  NCard,
  NButton,
  NSpace,
  NSwitch,
  NCheckbox,
  NIcon,
  NDataTable,
  NInput,
  NTag,
  NModal,
  NProgress,
  NEmpty,
  NSpin,
  NText,
  useMessage,
  type DataTableColumn,
} from 'naive-ui'
import {
  AddOutlined,
  DeleteOutlined,
  RefreshOutlined,
  VisibilityOutlined,
  SearchOutlined,
  FileUploadOutlined,
  DescriptionOutlined,
} from '@/icons'
import * as documentsApi from '@/api/documents'
import { hybridSearch } from '@/api/search'
import type {
  Document,
  Chunk,
  DocStatus,
  SearchResultItem,
  InitUploadResponse,
  CompleteUploadResponse,
  PaginatedResponse,
} from '@/types'

const message = useMessage()

// ── Document list state ──
const documents = ref<Document[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

// ── File input ref ──
const fileInput = ref<HTMLInputElement | null>(null)

// ── Upload modal state ──
const showUploadModal = ref(false)
const uploadLoading = ref(false)
const uploadProgress = ref(0)
const uploadQueue = ref<File[]>([])
const uploadingIndex = ref(-1) // -1 = not started
const isDragOver = ref(false)

function addFilesToQueue(files: FileList | File[]) {
  const allowedExtensions = new Set([
    'pdf', 'docx', 'xlsx', 'xls', 'pptx', 'txt', 'md', 'csv',
    'py', 'js', 'ts', 'java', 'c', 'cpp', 'h', 'hpp', 'go', 'rs', 'rb', 'php', 'swift', 'kt',
  ])
  for (const file of Array.from(files)) {
    const ext = file.name.split('.').pop()?.toLowerCase()
    if (ext && allowedExtensions.has(ext)) {
      // Avoid duplicates by name + size
      if (!uploadQueue.value.some(f => f.name === file.name && f.size === file.size)) {
        uploadQueue.value.push(file)
      }
    } else {
      message.warning(`不支持的文件类型: ${file.name}`)
    }
  }
}

function removeFileFromQueue(index: number) {
  uploadQueue.value.splice(index, 1)
}

function onDropHandler(event: DragEvent) {
  isDragOver.value = false
  const files = event.dataTransfer?.files
  if (files && files.length > 0) {
    addFilesToQueue(files)
  }
}

function onDragOverHandler(event: DragEvent) {
  event.preventDefault()
  isDragOver.value = true
}

function onDragLeaveHandler() {
  isDragOver.value = false
}

// ── Detail modal state ──
const showDetailModal = ref(false)
const detailDocument = ref<Document | null>(null)
const detailLoading = ref(false)
const chunks = ref<Chunk[]>([])
const chunksTotal = ref(0)
const expandedChunks = ref<Set<number>>(new Set())

// ── Delete confirm state ──
const showDeleteConfirm = ref(false)
const deletingDocId = ref<number | null>(null)
const deleteLoading = ref(false)

// ── Search state ──
const searchQuery = ref('')
const searchResults = ref<SearchResultItem[]>([])
const searchTotal = ref(0)
const searchLoading = ref(false)
const showSearchPanel = ref(false)

async function handleSearch() {
  const q = searchQuery.value.trim()
  if (!q) return
  searchLoading.value = true
  showSearchPanel.value = true
  try {
    const res = await hybridSearch({ query: q, page: 1, size: 20 })
    const data = res.data as { items: SearchResultItem[]; total: number }
    searchResults.value = data.items || []
    searchTotal.value = data.total || 0
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(err?.response?.data?.detail || '搜索失败')
    searchResults.value = []
    searchTotal.value = 0
  } finally {
    searchLoading.value = false
  }
}

function handleSearchKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Enter') {
    handleSearch()
  }
}

function closeSearchPanel() {
  showSearchPanel.value = false
}

// ── Preview modal state ──
const showPreviewModal = ref(false)
const previewUrl = ref<string | null>(null)
const previewTitle = ref('')
const previewLoading = ref(false)

// ── Previewable MIME types (matches backend DocumentParser.ALLOWED_TYPES) ──
const PREVIEWABLE_TYPES: string[] = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'text/plain',
  'text/markdown',
  'text/x-markdown',
  'text/csv',
  'application/csv',
]

function isPreviewable(contentType: string): boolean {
  if (contentType.startsWith('text/')) return true
  return PREVIEWABLE_TYPES.includes(contentType)
}

// ── Preview ──
async function handlePreview(id: number, filename: string) {
  const isPdf = filename.toLowerCase().endsWith('.pdf')
  previewTitle.value = filename

  // PDF: open in new tab (Chrome's PDF viewer doesn't work in iframe/embed with blob URLs)
  if (isPdf) {
    try {
      const res = await documentsApi.previewDocument(id)
      const contentType = (res.headers?.['content-type'] as string | undefined) || 'application/pdf'
      const blob = new Blob([res.data as BlobPart], { type: contentType })
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank')
      // Clean up blob URL after a delay (tab needs time to load it)
      setTimeout(() => URL.revokeObjectURL(url), 60000)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err?.response?.data?.detail || '预览失败')
    }
    return
  }

  // Text files: show in modal via iframe
  showPreviewModal.value = true
  previewLoading.value = true
  try {
    const res = await documentsApi.previewDocument(id)
    const contentType = (res.headers?.['content-type'] as string | undefined) || 'text/plain; charset=utf-8'
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    const blob = new Blob([res.data as BlobPart], { type: contentType })
    previewUrl.value = URL.createObjectURL(blob)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(err?.response?.data?.detail || '预览失败')
    showPreviewModal.value = false
  } finally {
    previewLoading.value = false
  }
}

function handleClosePreview() {
  showPreviewModal.value = false
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = null
  }
}

// ── File size formatting ──
function formatFileSize(bytes: number | null | undefined): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return `${size.toFixed(i === 0 ? 0 : 2)} ${units[i]}`
}

// ── Status tag config ──
const statusConfig: Record<DocStatus, { label: string; color: string }> = {
  uploading: { label: '上传中', color: 'warning' },
  processing: { label: '处理中', color: 'info' },
  ready: { label: '就绪', color: 'success' },
  failed: { label: '失败', color: 'error' },
}

// ── Load documents ──
async function loadDocuments() {
  loading.value = true
  try {
    const res = await documentsApi.listDocuments(page.value, pageSize.value)
    const data = res.data as PaginatedResponse<Document>
    documents.value = data.items
    total.value = data.total
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(err?.response?.data?.detail || '获取文档列表失败')
  } finally {
    loading.value = false
  }
}

// ── Delete document ──
function confirmDelete(id: number) {
  deletingDocId.value = id
  showDeleteConfirm.value = true
}

async function handleDelete() {
  if (deletingDocId.value === null) return
  deleteLoading.value = true
  try {
    await documentsApi.deleteDocument(deletingDocId.value)
    message.success('文档已删除')
    showDeleteConfirm.value = false
    deletingDocId.value = null
    await loadDocuments()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(err?.response?.data?.detail || '删除失败')
  } finally {
    deleteLoading.value = false
  }
}

// ── Reprocess document ──
async function handleReprocess(id: number) {
  try {
    const res = await documentsApi.reprocessDocument(id)
    const data = res.data as CompleteUploadResponse
    message.success('重新处理已提交，正在处理…')
    await loadDocuments()
    startPolling([data.document_id])
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(err?.response?.data?.detail || '重新处理失败')
  }
}

// ── View document detail ──
async function viewDocumentDetail(id: number) {
  detailLoading.value = true
  showDetailModal.value = true
  expandedChunks.value = new Set()
  try {
    const docRes = await documentsApi.getDocument(id)
    detailDocument.value = docRes.data as Document

    const chunkRes = await documentsApi.getDocumentChunks(id)
    const chunkData = chunkRes.data as { chunks: Chunk[]; total: number }
    chunks.value = chunkData.chunks
    chunksTotal.value = chunkData.total
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(err?.response?.data?.detail || '获取文档详情失败')
    showDetailModal.value = false
  } finally {
    detailLoading.value = false
  }
}

// ── Batch operations ──
const checkedDocIds = ref<number[]>([])

const hasChecked = computed(() => checkedDocIds.value.length > 0)
const checkedCount = computed(() => checkedDocIds.value.length)

function handleCheckAll(checked: boolean) {
  checkedDocIds.value = checked ? documents.value.map(d => d.id) : []
}

async function handleBatchDelete() {
  const ids = checkedDocIds.value
  if (!ids.length) return
  try {
    const res = await documentsApi.batchDelete(ids)
    const data = res.data as unknown as { deleted_ids: number[]; errors: Array<{document_id: number; error: string}>; succeeded?: number }
    checkedDocIds.value = []
    await loadDocuments()
    if (data.errors?.length) {
      message.warning(`删除了 ${data.deleted_ids.length} 个，${data.errors.length} 个失败`)
    } else {
      message.success(`成功删除 ${data.deleted_ids.length} 个文档`)
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(err?.response?.data?.detail || '批量删除失败')
  }
}

async function handleBatchReprocess() {
  const ids = checkedDocIds.value
  if (!ids.length) return
  try {
    const res = await documentsApi.batchReprocess(ids)
    const data = res.data as unknown as { queued: Array<{document_id: number; task_id: string}>; errors: Array<{document_id: number; error: string}>; succeeded?: number }
    checkedDocIds.value = []
    await loadDocuments()
    if (data.errors?.length) {
      message.warning(`提交了 ${data.queued.length} 个，${data.errors.length} 个失败`)
    } else {
      message.success(`已提交 ${data.queued.length} 个文档重新处理`)
    }
    startPolling(data.queued.map(q => q.document_id))
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(err?.response?.data?.detail || '批量重新处理失败')
  }
}

// ── Polling for document status after upload ──
const pollingTimer = ref<ReturnType<typeof setInterval> | null>(null)
const pendingDocIds = ref<Set<number>>(new Set())

function stopPolling() {
  if (pollingTimer.value !== null) {
    clearInterval(pollingTimer.value)
    pollingTimer.value = null
  }
  pendingDocIds.value = new Set()
}

async function pollDocuments() {
  if (pendingDocIds.value.size === 0) {
    stopPolling()
    return
  }
  try {
    const res = await documentsApi.listDocuments(page.value, pageSize.value)
    const data = res.data as PaginatedResponse<Document>
    documents.value = data.items
    total.value = data.total

    // Check if all pending docs have reached a terminal state
    for (const doc of data.items) {
      if (pendingDocIds.value.has(doc.id)) {
        if (doc.doc_status === 'ready' || doc.doc_status === 'failed') {
          pendingDocIds.value.delete(doc.id)
          if (doc.doc_status === 'ready') {
            message.success(`"${doc.filename}" 处理完成`)
          } else {
            message.error(`"${doc.filename}" 处理失败`)
          }
        }
      }
    }

    if (pendingDocIds.value.size === 0) {
      stopPolling()
    }
  } catch {
    // Silently retry on next poll
  }
}

function startPolling(docIds: number[]) {
  stopPolling()
  docIds.forEach(id => pendingDocIds.value.add(id))
  pollingTimer.value = setInterval(pollDocuments, 3000)
}

// ── File selection ──
function onFileSelected(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files && input.files.length > 0) {
    addFilesToQueue(input.files)
  }
  // Reset input so the same file can be re-selected
  input.value = ''
}

// ── Chunked upload for a single file ──
async function uploadSingleFile(file: File): Promise<number | null> {
  try {
    const initRes = await documentsApi.initUpload(file.name, file.size, file.type)
    const initData = initRes.data as InitUploadResponse

    if (initData.duplicate) {
      message.warning(`"${file.name}" 文件已存在，跳过`)
      return null
    }

    const upload_id = initData.upload_id as string
    const chunk_size = initData.chunk_size as number
    if (!upload_id) {
      message.error(`${file.name}: 初始化上传失败`)
      return null
    }

    const totalChunks = Math.ceil(file.size / chunk_size)

    for (let i = 0; i < totalChunks; i++) {
      const start = i * chunk_size
      const end = Math.min(start + chunk_size, file.size)
      const blob = file.slice(start, end)
      await documentsApi.uploadChunk(upload_id, i, blob)
      uploadProgress.value = Math.round(((i + 1) / totalChunks) * 100)
    }

    const completeRes = await documentsApi.completeUpload(upload_id)
    const completeData = completeRes.data as CompleteUploadResponse

    // Poll this doc
    startPolling([completeData.document_id])
    return completeData.document_id
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(`${file.name} 上传失败: ${err?.response?.data?.detail || '未知错误'}`)
    return null
  }
}

// ── Upload all files in queue ──
async function startUpload() {
  if (uploadQueue.value.length === 0) return

  uploadLoading.value = true
  uploadProgress.value = 0
  let uploadedCount = 0

  for (let i = 0; i < uploadQueue.value.length; i++) {
    uploadingIndex.value = i
    const file = uploadQueue.value[i]
    const docId = await uploadSingleFile(file)
    if (docId !== null) {
      uploadedCount++
    }
  }

  // Done
  uploadingIndex.value = -1
  uploadLoading.value = false
  uploadProgress.value = 0

  await loadDocuments()

  if (uploadedCount === uploadQueue.value.length) {
    message.success(`全部 ${uploadedCount} 个文件上传成功，正在处理…`)
  } else {
    message.info(`上传完成：${uploadedCount}/${uploadQueue.value.length} 个成功`)
  }

  // Auto-close if all succeeded
  if (uploadedCount > 0) {
    showUploadModal.value = false
    uploadQueue.value = []
  }
}

// ── Close upload modal ──
function handleCloseUpload() {
  if (!uploadLoading.value) {
    showUploadModal.value = false
    uploadQueue.value = []
    uploadingIndex.value = -1
    uploadProgress.value = 0
  }
}

// ── Detail modal update handler ──
function handleDetailModalUpdate(val: boolean | null) {
  if (!val) showDetailModal.value = false
}

// ── Toggle chunk expand ──
function toggleChunkExpand(index: number) {
  if (expandedChunks.value.has(index)) {
    expandedChunks.value.delete(index)
  } else {
    expandedChunks.value.add(index)
  }
}

// ── Toggle visibility ──
async function handleToggleVisibility(row: Document) {
  try {
    await documentsApi.toggleDocumentVisibility(row.id, !row.is_public)
    // Reload from server so NSwitch state stays in sync
    await loadDocuments()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(err?.response?.data?.detail || '切换公开状态失败')
  }
}

// ── Pagination handler ──
function handlePageChange(newPage: number) {
  page.value = newPage
  loadDocuments()
}

// ── Table columns ──
const columns = computed<DataTableColumn<Document>[]>(() => [
  {
    type: 'selection',
    width: 40,
    multiple: true,
    checkedRowKeys: checkedDocIds.value,
    onUpdateCheckedRowKeys: (keys: (string | number)[]) => {
      checkedDocIds.value = keys as number[]
    },
  } as DataTableColumn<Document>,
  {
    title: '文件名',
    key: 'filename',
    ellipsis: { tooltip: true },
    minWidth: 180,
    render(row: Document) {
      return h(
        'div',
        { class: 'flex items-center gap-2' },
        [
          h(NIcon, { size: 18, color: '#18a058' }, {
            default: () => h(DescriptionOutlined),
          }),
          h('span', row.filename),
        ],
      )
    },
  },
  {
    title: '类型',
    key: 'content_type',
    width: 120,
    render(row: Document) {
      const ct = row.content_type || ''
      if (ct.startsWith('application/pdf')) return 'PDF'
      if (ct.includes('word') || ct.includes('docx')) return 'DOCX'
      if (ct.includes('text')) return 'TXT'
      if (ct.includes('markdown')) return 'MD'
      return ct.split('/').pop() || ct
    },
  },
  {
    title: '大小',
    key: 'file_size',
    width: 100,
    render(row: Document) {
      return formatFileSize(row.file_size)
    },
  },
  {
    title: '状态',
    key: 'doc_status',
    width: 100,
    render(row: Document) {
      const config = statusConfig[row.doc_status]
      return h(NTag, { type: config.color as 'success' | 'warning' | 'info' | 'error', size: 'small' }, {
        default: () => config.label,
      })
    },
  },
  {
    title: '公开',
    key: 'is_public',
    width: 80,
    align: 'center',
    render(row: Document) {
      return h(NSwitch, {
        value: row.is_public,
        size: 'small',
        onUpdateValue: () => handleToggleVisibility(row),
      })
    },
  },
  {
    title: '组织',
    key: 'org_tag',
    width: 140,
    render(row: Document) {
      if (!row.org_tag) return null
      const tags = row.org_tag.split(';').map(t => t.trim()).filter(Boolean)
      return h('div', { style: 'display: flex; gap: 4px; flex-wrap: wrap;' },
        tags.map(t => h(NTag, { size: 'tiny', type: 'info' }, { default: () => t }))
      )
    },
  },
  {
    title: '上传者',
    key: 'owner_username',
    width: 100,
    render(row: Document) {
      return row.owner_username || '-'
    },
  },
  {
    title: '分片数',
    key: 'chunk_count',
    width: 90,
    align: 'center',
  },
  {
    title: '上传时间',
    key: 'created_at',
    width: 170,
    render(row: Document) {
      return row.created_at
        ? new Date(row.created_at).toLocaleString('zh-CN')
        : '-'
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 220,
    fixed: 'right',
    render(row: Document) {
      return h(NSpace, { size: 'small' }, {
        default: () => [
          h(
            NButton,
            { size: 'tiny', secondary: true, onClick: () => viewDocumentDetail(row.id) },
            { default: () => '查看', icon: () => h(NIcon, null, { default: () => h(VisibilityOutlined) }) },
          ),
          row.doc_status === 'ready'
            ? h(
                NButton,
                { size: 'tiny', quaternary: true, onClick: () => handleReprocess(row.id) },
                { default: () => '重新处理', icon: () => h(NIcon, null, { default: () => h(RefreshOutlined) }) },
              )
            : null,
          row.content_type && isPreviewable(row.content_type)
            ? h(
                NButton,
                { size: 'tiny', quaternary: true, onClick: () => handlePreview(row.id, row.filename) },
                { default: () => '预览', icon: () => h(NIcon, null, { default: () => h(SearchOutlined) }) },
              )
            : null,
          h(
            NButton,
            { size: 'tiny', tertiary: true, type: 'error', onClick: () => confirmDelete(row.id) },
            { default: () => '删除', icon: () => h(NIcon, null, { default: () => h(DeleteOutlined) }) },
          ),
        ],
      })
    },
  },
])

// ── Init ──
onMounted(() => {
  loadDocuments()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div>
    <!-- Header -->
    <div class="flex-between mb-6">
      <h2 class="text-2xl font-bold">知识库</h2>
      <div class="flex items-center gap-3">
        <NInput
          v-model:value="searchQuery"
          placeholder="搜索文档内容…"
          clearable
          style="width: 260px"
          @keydown="handleSearchKeydown"
        >
          <template #prefix>
            <NIcon><SearchOutlined /></NIcon>
          </template>
        </NInput>
        <NButton type="primary" @click="showUploadModal = true">
          <template #icon>
            <NIcon><AddOutlined /></NIcon>
          </template>
          上传文档
        </NButton>
      </div>
    </div>

    <!-- Document table -->
    <NCard :bordered="true">
      <!-- Batch action bar -->
      <div v-if="hasChecked" class="flex items-center gap-3 mb-3 px-1">
        <NText depth="3">已选择 {{ checkedCount }} 项</NText>
        <NButton size="tiny" quaternary @click="checkedDocIds = []">取消选择</NButton>
        <NButton size="small" type="error" secondary @click="handleBatchDelete">
          <template #icon>
            <NIcon><DeleteOutlined /></NIcon>
          </template>
          批量删除
        </NButton>
        <NButton size="small" type="warning" secondary @click="handleBatchReprocess">
          <template #icon>
            <NIcon><RefreshOutlined /></NIcon>
          </template>
          批量重新处理
        </NButton>
      </div>
      <NSpin :show="loading">
        <NDataTable
          :columns="columns"
          :data="documents"
          :bordered="true"
          :striped="true"
          :row-key="(row: Document) => row.id"
          :loading="loading"
          :pagination="{
            page: page,
            pageSize: pageSize,
            itemCount: total,
            onChange: handlePageChange,
            pageSizes: [10, 20, 50],
            showSizePicker: true,
            onUpdatePageSize: (size: number) => { pageSize = size; loadDocuments() },
          }"
          size="small"
          remote
        >
          <template #empty>
            <NEmpty description="暂无文档" />
          </template>
        </NDataTable>
      </NSpin>
    </NCard>

    <!-- Search results panel -->
    <NModal
      :show="showSearchPanel"
      @update:show="(val: boolean | null) => { if (!val) closeSearchPanel() }"
      title="搜索结果"
      preset="card"
      style="max-width: 800px"
      closable
      :mask-closable="!searchLoading"
    >
      <NSpin :show="searchLoading">
        <template v-if="searchResults.length === 0 && !searchLoading">
          <NEmpty description="无结果" />
        </template>
        <template v-else>
          <NText depth="3" class="text-sm block mb-3">
            共 {{ searchTotal }} 条结果
          </NText>
          <div class="flex flex-col gap-3 max-h-96 overflow-y-auto">
            <div
              v-for="item in searchResults"
              :key="item.chunk_id"
              class="border border-gray-200 rounded-lg p-4 hover:border-green-200 transition-colors"
            >
              <div class="flex items-center gap-2 mb-1">
                <NText class="text-xs font-medium">{{ item.filename || '未知文档' }}</NText>
                <NTag size="tiny" :type="item.score > 0.1 ? 'success' : 'default'">
                  {{ item.score.toFixed(3) }}
                </NTag>
              </div>
              <NText depth="2" class="text-sm whitespace-pre-wrap leading-relaxed">
                {{ item.content.length > 300 ? item.content.slice(0, 300) + '...' : item.content }}
              </NText>
            </div>
          </div>
        </template>
      </NSpin>
    </NModal>

    <!-- Upload modal -->
    <NModal
      :show="showUploadModal"
      :on-update:show="(val: boolean) => { if (!val) handleCloseUpload() }"
      title="上传文档"
      preset="card"
      style="max-width: 560px"
      :mask-closable="!uploadLoading"
      :closeable="!uploadLoading"
    >
      <div class="flex flex-col gap-4">

        <!-- Drag & drop zone -->
        <div
          class="drop-zone"
          :class="{ 'drop-zone--active': isDragOver, 'drop-zone--disabled': uploadLoading }"
          @drop.prevent="onDropHandler"
          @dragover.prevent="onDragOverHandler"
          @dragleave.prevent="onDragLeaveHandler"
          @click="!uploadLoading && fileInput?.click()"
        >
          <div class="drop-zone-content">
            <NIcon size="40" class="drop-zone-icon"><FileUploadOutlined /></NIcon>
            <NText depth="3" class="drop-zone-text">
              拖拽文件到此处，或点击选择
            </NText>
            <NText depth="3" class="text-xs">
              支持 PDF / DOCX / XLSX / PPTX / TXT / MD / CSV / 代码文件
            </NText>
          </div>
          <input
            ref="fileInput"
            type="file"
            multiple
            class="hidden"
            @change="onFileSelected"
          />
        </div>

        <!-- File queue -->
        <div v-if="uploadQueue.length > 0" class="file-queue">
          <NText depth="2" class="text-sm font-medium">待上传文件 ({{ uploadQueue.length }})</NText>
          <div
            v-for="(file, fIdx) in uploadQueue"
            :key="fIdx"
            class="file-queue-item"
            :class="{ 'file-queue-item--uploading': fIdx === uploadingIndex }"
          >
            <div class="file-queue-item-info">
              <NText class="text-sm">{{ file.name }}</NText>
              <NText depth="3" class="text-xs">{{ formatFileSize(file.size) }}</NText>
            </div>
            <NButton
              v-if="!uploadLoading"
              quaternary circle size="tiny" type="error"
              @click="removeFileFromQueue(fIdx)"
            >
              <template #icon>
                <NIcon size="14"><DeleteOutlined /></NIcon>
              </template>
            </NButton>
            <NTag v-if="fIdx === uploadingIndex" size="tiny" type="info">上传中</NTag>
          </div>
        </div>

        <!-- Progress bar -->
        <div v-if="uploadLoading" class="flex flex-col gap-2">
          <NText depth="3" class="text-sm">
            上传进度: {{ uploadProgress }}%
            ({{ uploadingIndex + 1 }} / {{ uploadQueue.length }})
          </NText>
          <NProgress
            :percentage="uploadProgress"
            :height="20"
            :rail-style="{ borderRadius: '4px' }"
            :indicator-placement="'inside'"
            processing
          />
        </div>

        <div class="flex justify-end gap-3 mt-2">
          <NButton
            :disabled="uploadLoading"
            quaternary
            @click="handleCloseUpload"
          >
            取消
          </NButton>
          <NButton
            type="primary"
            :disabled="uploadQueue.length === 0 || uploadLoading"
            :loading="uploadLoading"
            @click="startUpload"
          >
            上传 ({{ uploadQueue.length }})
          </NButton>
        </div>
      </div>
    </NModal>

    <!-- Detail modal -->
    <NModal
      :show="showDetailModal"
      :on-update:show="handleDetailModalUpdate"
      title="文档详情"
      preset="card"
      style="max-width: 800px"
      closable
    >
      <NSpin :show="detailLoading">
        <template v-if="detailDocument">
          <!-- Metadata -->
          <div class="grid grid-cols-2 gap-4 mb-6">
            <div>
              <NText depth="3" class="text-xs block">文件名</NText>
              <NText>{{ detailDocument.filename }}</NText>
            </div>
            <div>
              <NText depth="3" class="text-xs block">文件大小</NText>
              <NText>{{ formatFileSize(detailDocument.file_size) }}</NText>
            </div>
            <div>
              <NText depth="3" class="text-xs block">类型</NText>
              <NText>{{ detailDocument.content_type }}</NText>
            </div>
            <div>
              <NText depth="3" class="text-xs block">状态</NText>
              <NTag
                :type="statusConfig[detailDocument.doc_status]?.color as 'success' | 'warning' | 'info' | 'error'"
                size="small"
              >
                {{ statusConfig[detailDocument.doc_status]?.label }}
              </NTag>
            </div>
            <div>
              <NText depth="3" class="text-xs block">MD5</NText>
              <NText>{{ detailDocument.file_md5 || '-' }}</NText>
            </div>
            <div>
              <NText depth="3" class="text-xs block">分片数</NText>
              <NText>{{ detailDocument.chunk_count }}</NText>
            </div>
            <div>
              <NText depth="3" class="text-xs block">上传时间</NText>
              <NText>{{ detailDocument.created_at ? new Date(detailDocument.created_at).toLocaleString('zh-CN') : '-' }}</NText>
            </div>
            <div>
              <NText depth="3" class="text-xs block">更新时间</NText>
              <NText>{{ detailDocument.updated_at ? new Date(detailDocument.updated_at).toLocaleString('zh-CN') : '-' }}</NText>
            </div>
          </div>

          <!-- Preview button for text files -->
          <div v-if="detailDocument.content_type && isPreviewable(detailDocument.content_type)" class="mb-4">
            <NButton size="small" secondary @click="handlePreview(detailDocument.id, detailDocument.filename)">
              <template #icon>
                <NIcon><VisibilityOutlined /></NIcon>
              </template>
              预览文档
            </NButton>
          </div>

          <!-- Chunks section -->
          <NText class="text-base font-semibold block mb-3">
            文档分片 ({{ chunksTotal }})
          </NText>

          <div v-if="(chunks?.length ?? 0) === 0" class="py-4">
            <NEmpty description="暂无分片数据" />
          </div>

          <div v-else-if="chunks" class="flex flex-col gap-3 max-h-96 overflow-y-auto">
            <div
              v-for="chunk in chunks"
              :key="chunk.id"
              class="border border-gray-200 rounded-lg p-4"
              :class="{ 'border-green-200': expandedChunks.has(chunk.chunk_index) }"
            >
              <div class="flex items-center justify-between mb-1">
                <NText depth="3" class="text-xs">#{{ chunk.chunk_index }}</NText>
                <NButton
                  size="tiny"
                  quaternary
                  @click="toggleChunkExpand(chunk.chunk_index)"
                >
                  {{ expandedChunks.has(chunk.chunk_index) ? '收起' : '查看全文' }}
                </NButton>
              </div>
              <NText depth="2" class="text-sm whitespace-pre-wrap leading-relaxed">
                {{ expandedChunks.has(chunk.chunk_index) ? chunk.content : (chunk.content.length > 200 ? chunk.content.slice(0, 200) + '...' : chunk.content) }}
              </NText>
            </div>
          </div>
        </template>
      </NSpin>
    </NModal>

    <!-- Delete confirm modal -->
    <NModal
      :show="showDeleteConfirm"
      :on-update:show="(val: boolean) => { if (!val) showDeleteConfirm = false }"
      title="确认删除"
      preset="dialog"
      type="warning"
      :loading="deleteLoading"
      positive-text="删除"
      negative-text="取消"
      @positive-click="handleDelete"
      @negative-click="showDeleteConfirm = false"
    >
      确定要删除此文档吗？此操作不可恢复。
    </NModal>

    <!-- Preview modal -->
    <NModal
      :show="showPreviewModal"
      @update:show="(val: boolean | null) => { if (!val) handleClosePreview() }"
      :title="'预览: ' + previewTitle"
      preset="card"
      style="max-width: 90vw; width: 900px"
      closable
      :mask-closable="!previewLoading"
    >
      <NSpin :show="previewLoading">
        <iframe
          v-if="previewUrl"
          :src="previewUrl"
          style="width: 100%; height: 70vh; border: none; border-radius: 4px"
        />
        <NEmpty v-else description="加载失败" />
      </NSpin>
    </NModal>
  </div>
</template>

<style scoped>
.flex-between {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.hidden {
  display: none;
}

/* ── Drag & drop zone ── */
.drop-zone {
  border: 2px dashed #d9d9d9;
  border-radius: 8px;
  padding: 32px 16px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  background: #fafafa;
}
.drop-zone:hover,
.drop-zone--active {
  border-color: #18a058;
  background: #f0faf5;
}
.drop-zone--active {
  border-style: solid;
  background: #e8f8ef;
}
.drop-zone--disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.drop-zone-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  pointer-events: none;
}
.drop-zone-icon {
  color: #18a058;
  opacity: 0.6;
}

/* ── File queue ── */
.file-queue {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 200px;
  overflow-y: auto;
}
.file-queue-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  border-radius: 4px;
  background: #fafafa;
  border: 1px solid #f0f0f0;
}
.file-queue-item--uploading {
  background: #e6f7ff;
  border-color: #91d5ff;
}
.file-queue-item-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.file-queue-item-info .text-sm {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
