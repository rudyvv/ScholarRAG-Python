<script setup lang="ts">
import { ref, computed, h, onMounted } from 'vue'
import {
  NCard,
  NButton,
  NDataTable,
  NModal,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSwitch,
  NSpace,
  NTag,
  NIcon,
  NPopconfirm,
  useMessage,
  type DataTableColumn,
} from 'naive-ui'
import { AddOutlined, EditOutlined, DeleteOutlined, PlayArrowOutlined, SettingsOutlined } from '@/icons'
import { listModels, getModel, createModel, updateModel, deleteModel, testProviderConnection } from '@/api/models'
import type { ModelProvider, ModelProviderCreate, ModelProviderUpdate } from '@/types'

const message = useMessage()

// ── Table state ──
const providers = ref<ModelProvider[]>([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(10)

// ── Modal state ──
const modalVisible = ref(false)
const modalMode = ref<'create' | 'edit'>('create')
const editingId = ref<number | null>(null)
const submitting = ref(false)

const formValues = ref({
  provider_name: '',
  api_base_url: '',
  api_key: '',
  model_name: '',
  embedding_model: '',
  embedding_dim: 1024 as number | null,
  is_active: true,
})

// ── Row number helper ──
function rowIndex(index: number): number {
  return (page.value - 1) * pageSize.value + index + 1
}

// ── Pagination ──
const pagination = computed(() => ({
  page: page.value,
  pageSize: pageSize.value,
  itemCount: providers.value.length,
  onChange: (p: number) => { page.value = p },
  pageSizes: [5, 10, 20, 50],
  showSizePicker: true,
  onUpdatePageSize: (size: number) => { pageSize.value = size; page.value = 1 },
}))

// ── Load providers ──
async function loadProviders() {
  loading.value = true
  try {
    const res = await listModels()
    providers.value = res.data.items || []
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(err?.response?.data?.detail || '获取提供商列表失败')
  } finally {
    loading.value = false
  }
}

// ── Open create modal ──
function openCreateModal() {
  modalMode.value = 'create'
  editingId.value = null
  formValues.value = {
    provider_name: '',
    api_base_url: '',
    api_key: '',
    model_name: '',
    embedding_model: '',
    embedding_dim: 1024,
    is_active: true,
  }
  modalVisible.value = true
}

// ── Open edit modal ──
function openEditModal(row: ModelProvider) {
  modalMode.value = 'edit'
  editingId.value = row.id
  formValues.value = {
    provider_name: row.provider_name,
    api_base_url: row.api_base_url,
    api_key: '',
    model_name: row.model_name,
    embedding_model: row.embedding_model,
    embedding_dim: row.embedding_dim,
    is_active: row.is_active,
  }
  modalVisible.value = true
}

// ── Delete ──
async function handleDelete(id: number) {
  try {
    await deleteModel(id)
    message.success('删除成功')
    await loadProviders()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(err?.response?.data?.detail || '删除失败')
  }
}

// ── Submit ──
async function handleSubmit() {
  // Basic validation
  if (modalMode.value === 'create') {
    if (!formValues.value.provider_name || !formValues.value.api_base_url || !formValues.value.api_key || !formValues.value.model_name || !formValues.value.embedding_model || formValues.value.embedding_dim === null) {
      message.warning('请完善表单信息')
      return
    }
  } else {
    if (!formValues.value.api_base_url || !formValues.value.model_name || !formValues.value.embedding_model || formValues.value.embedding_dim === null) {
      message.warning('请完善表单信息')
      return
    }
  }

  submitting.value = true
  try {
    if (modalMode.value === 'create') {
      const payload: ModelProviderCreate = {
        provider_name: formValues.value.provider_name,
        api_base_url: formValues.value.api_base_url,
        api_key: formValues.value.api_key,
        model_name: formValues.value.model_name,
        embedding_model: formValues.value.embedding_model,
        embedding_dim: formValues.value.embedding_dim!,
        is_active: formValues.value.is_active,
      }
      await createModel(payload)
      message.success('创建成功')
    } else {
      const payload: ModelProviderUpdate = {}
      if (formValues.value.api_base_url) payload.api_base_url = formValues.value.api_base_url
      if (formValues.value.api_key) payload.api_key = formValues.value.api_key
      if (formValues.value.model_name) payload.model_name = formValues.value.model_name
      if (formValues.value.embedding_model) payload.embedding_model = formValues.value.embedding_model
      if (formValues.value.embedding_dim !== null) payload.embedding_dim = formValues.value.embedding_dim
      payload.is_active = formValues.value.is_active
      await updateModel(editingId.value!, payload)
      message.success('更新成功')
    }
    modalVisible.value = false
    await loadProviders()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(err?.response?.data?.detail || '操作失败')
  } finally {
    submitting.value = false
  }
}

// ── Test connection ──
const testingIds = ref(new Set<number>())

async function testConnection(id: number) {
  testingIds.value.add(id)
  testingIds.value = new Set(testingIds.value) // force reactivity
  try {
    const res = await testProviderConnection(id)
    if (res.data.success) {
      message.success(`连接成功 (${res.data.latency_ms}ms)`)
    } else {
      const errorMsg = (res.data as any).error || '未知错误'
      message.error(`连接失败: ${errorMsg}`)
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(err?.response?.data?.detail || '连接测试失败')
  } finally {
    testingIds.value.delete(id)
    testingIds.value = new Set(testingIds.value) // force reactivity
  }
}

// ── Table columns ──
const columns = computed<DataTableColumn<ModelProvider>[]>(() => [
  {
    title: '#',
    key: 'rowIndex',
    width: 60,
    render(_row: ModelProvider, index: number) {
      return rowIndex(index)
    },
  },
  {
    title: '提供商',
    key: 'provider_name',
    width: 120,
  },
  {
    title: '模型',
    key: 'model_name',
    minWidth: 200,
    render(row: ModelProvider) {
      return h('div', { class: 'flex flex-col leading-5' }, [
        h('span', { class: 'font-medium' }, row.model_name),
        h('span', { class: 'text-xs text-gray-400' }, `embedding: ${row.embedding_model}`),
      ])
    },
  },
  {
    title: 'API 地址',
    key: 'api_base_url',
    minWidth: 200,
    ellipsis: { tooltip: true },
    render(row: ModelProvider) {
      const url = row.api_base_url
      return url.length > 50 ? url.slice(0, 50) + '...' : url
    },
  },
  {
    title: '状态',
    key: 'is_active',
    width: 80,
    align: 'center',
    render(row: ModelProvider) {
      return h(NTag, { type: row.is_active ? 'success' : 'default', size: 'small' }, {
        default: () => row.is_active ? '启用' : '停用',
      })
    },
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 170,
    render(row: ModelProvider) {
      return row.created_at ? new Date(row.created_at).toLocaleString('zh-CN') : '-'
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 180,
    fixed: 'right',
    render(row: ModelProvider) {
      const isTesting = testingIds.value.has(row.id)
      return h('div', { class: 'flex items-center gap-1' }, [
        h(NButton, {
          quaternary: true,
          size: 'tiny',
          loading: isTesting,
          disabled: isTesting,
          onClick: () => testConnection(row.id),
          renderIcon: () => h(NIcon, null, { default: () => h(PlayArrowOutlined) }),
        }),
        h(NButton, {
          quaternary: true,
          size: 'tiny',
          onClick: () => openEditModal(row),
          renderIcon: () => h(NIcon, null, { default: () => h(EditOutlined) }),
        }),
        h(NPopconfirm, {
          onPositiveClick: () => handleDelete(row.id),
          positiveText: '确定',
          negativeText: '取消',
        }, {
          trigger: () => h(NButton, {
            quaternary: true,
            size: 'tiny',
            type: 'error',
            renderIcon: () => h(NIcon, null, { default: () => h(DeleteOutlined) }),
          }),
          default: () => '确定要删除此提供商？',
        }),
      ])
    },
  },
])

// ── Modal title ──
const modalTitle = computed(() =>
  modalMode.value === 'create' ? '添加 LLM 提供商' : '编辑 LLM 提供商',
)

onMounted(() => {
  loadProviders()
})
</script>

<template>
  <div>
    <!-- Header -->
    <div class="flex-between mb-6">
      <div class="flex items-center gap-2">
        <NIcon size="24" color="#18a058"><SettingsOutlined /></NIcon>
        <h2 class="text-2xl font-bold">LLM 提供商管理</h2>
      </div>
      <NButton type="primary" @click="openCreateModal">
        <template #icon>
          <NIcon><AddOutlined /></NIcon>
        </template>
        添加提供商
      </NButton>
    </div>

    <!-- Table -->
    <NCard :bordered="true">
      <NDataTable
        :columns="columns"
        :data="providers"
        :bordered="true"
        :striped="true"
        :row-key="(row: ModelProvider) => row.id"
        :loading="loading"
        :pagination="pagination"
        size="small"
      />
    </NCard>

    <!-- Create / Edit Modal -->
    <NModal
      :show="modalVisible"
      :on-update:show="(val: boolean) => { if (!val) modalVisible = false }"
      :title="modalTitle"
      preset="card"
      style="max-width: 600px"
      closable
      :mask-closable="!submitting"
    >
      <NForm :model="formValues" label-placement="left" label-width="100">
        <NFormItem label="提供商名称" path="provider_name" required>
          <NInput
            v-model:value="formValues.provider_name"
            :disabled="modalMode === 'edit'"
            placeholder="请输入提供商名称"
          />
        </NFormItem>
        <NFormItem label="API 地址" path="api_base_url" required>
          <NInput
            v-model:value="formValues.api_base_url"
            placeholder="https://api.siliconflow.cn/v1"
          />
        </NFormItem>
        <NFormItem label="API Key" :required="modalMode === 'create'">
          <NInput
            v-model:value="formValues.api_key"
            type="password"
            show-password-on="click"
            :placeholder="modalMode === 'edit' ? '留空则不修改' : '请输入 API Key'"
          />
        </NFormItem>
        <NFormItem label="模型名称" path="model_name" required>
          <NInput
            v-model:value="formValues.model_name"
            placeholder="Qwen/Qwen3-8B"
          />
        </NFormItem>
        <NFormItem label="嵌入模型" path="embedding_model" required>
          <NInput
            v-model:value="formValues.embedding_model"
            placeholder="BAAI/bge-m3"
          />
        </NFormItem>
        <NFormItem label="向量维度" path="embedding_dim" required>
          <NInputNumber
            v-model:value="formValues.embedding_dim"
            :min="128"
            :max="4096"
            :step="128"
            class="w-full"
          />
        </NFormItem>
        <NFormItem label="启用状态" path="is_active">
          <NSwitch v-model:value="formValues.is_active" />
        </NFormItem>
      </NForm>

      <template #footer>
        <NSpace justify="end">
          <NButton quaternary @click="modalVisible = false" :disabled="submitting">
            取消
          </NButton>
          <NButton type="primary" :loading="submitting" @click="handleSubmit">
            保存
          </NButton>
        </NSpace>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.flex-between {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
