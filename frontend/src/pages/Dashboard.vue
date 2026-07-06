<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard,
  NGrid,
  NGi,
  NStatistic,
  NIcon,
  NButton,
  NSpace,
} from 'naive-ui'
import {
  DescriptionOutlined,
  StorageOutlined,
  ChatOutlined,
  CheckCircleOutlined,
} from '@/icons'
import { listDocuments } from '@/api/documents'
import { listSessions } from '@/api/chat'

const router = useRouter()

const documentCount = ref(0)
const chunkCount = ref(0)
const conversationCount = ref(0)
const allReady = ref(true)

onMounted(async () => {
  try {
    const [docRes, sessionRes] = await Promise.all([
      listDocuments(1, 9999),
      listSessions(),
    ])

    const docs = docRes.data.items
    documentCount.value = docRes.data.total
    chunkCount.value = docs.reduce((sum, doc) => sum + (doc.chunk_count || 0), 0)
    conversationCount.value = sessionRes.data.total
    allReady.value = docs.length === 0 || docs.every((doc) => doc.doc_status === 'ready')
  } catch (e) {
    console.error('Failed to load dashboard stats:', e)
  }
})

const statusValue = computed(() => {
  if (documentCount.value === 0) return '等待数据'
  return allReady.value ? '运行正常' : '处理中...'
})

const statusColor = computed(() => {
  if (documentCount.value === 0) return '#909399'
  return allReady.value ? '#18a058' : '#e88020'
})
</script>

<template>
  <div class="p-6">
    <div class="mb-6">
      <h2 class="text-2xl font-bold text-gray-800">
        仪表盘
      </h2>
      <p class="mt-1 text-sm text-gray-400">
        系统运行状态概览
      </p>
    </div>

    <NGrid :cols="4" :x-gap="16" :y-gap="16">
      <NGi>
        <NCard>
          <NStatistic label="文档数" :value="documentCount">
            <template #prefix>
              <NIcon><DescriptionOutlined /></NIcon>
            </template>
          </NStatistic>
        </NCard>
      </NGi>
      <NGi>
        <NCard>
          <NStatistic label="分片数" :value="chunkCount">
            <template #prefix>
              <NIcon><StorageOutlined /></NIcon>
            </template>
          </NStatistic>
        </NCard>
      </NGi>
      <NGi>
        <NCard>
          <NStatistic label="对话数" :value="conversationCount">
            <template #prefix>
              <NIcon><ChatOutlined /></NIcon>
            </template>
          </NStatistic>
        </NCard>
      </NGi>
      <NGi>
        <NCard>
          <NStatistic label="就绪状态" :value="statusValue">
            <template #prefix>
              <NIcon :color="statusColor"><CheckCircleOutlined /></NIcon>
            </template>
          </NStatistic>
        </NCard>
      </NGi>
    </NGrid>

    <NSpace class="mt-6">
      <NButton type="primary" @click="router.push('/kb')">
        管理知识库
      </NButton>
      <NButton @click="router.push('/chat')">
        开始对话
      </NButton>
    </NSpace>

    <div class="mt-12 text-center text-xs text-gray-300">
      Paismart RAG System v1.0
    </div>
  </div>
</template>
