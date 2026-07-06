<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  NCard,
  NGrid,
  NGi,
  NStatistic,
  NIcon,
  NSpace,
  NButton,
} from 'naive-ui'
import {
  PersonOutlined,
  DescriptionOutlined,
  ChatOutlined,
  CheckCircleOutlined,
  RefreshOutlined,
} from '@/icons'
import { getAdminDashboard } from '@/api/admin'
import type { AdminDashboard } from '@/types'
import { useRouter } from 'vue-router'

const router = useRouter()
const dashboard = ref<AdminDashboard | null>(null)
const loading = ref(false)

async function loadDashboard() {
  loading.value = true
  try {
    const res = await getAdminDashboard()
    dashboard.value = res.data
  } catch (e: unknown) {
    console.error('Failed to load admin dashboard:', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadDashboard()
})
</script>

<template>
  <div class="p-6">
    <div class="flex-between mb-6">
      <div>
        <h2 class="text-2xl font-bold text-gray-800">
          管理面板
        </h2>
        <p class="mt-1 text-sm text-gray-400">
          系统运行数据概览
        </p>
      </div>
      <NButton
        quaternary
        :loading="loading"
        @click="loadDashboard"
      >
        <template #icon>
          <NIcon><RefreshOutlined /></NIcon>
        </template>
        刷新
      </NButton>
    </div>

    <NGrid :cols="4" :x-gap="16" :y-gap="16">
      <NGi>
        <NCard>
          <NStatistic label="用户总数" :value="dashboard?.total_users ?? 0">
            <template #prefix>
              <NIcon><PersonOutlined /></NIcon>
            </template>
          </NStatistic>
        </NCard>
      </NGi>
      <NGi>
        <NCard>
          <NStatistic label="文档总数" :value="dashboard?.total_documents ?? 0">
            <template #prefix>
              <NIcon><DescriptionOutlined /></NIcon>
            </template>
          </NStatistic>
        </NCard>
      </NGi>
      <NGi>
        <NCard>
          <NStatistic label="会话总数" :value="dashboard?.total_sessions ?? 0">
            <template #prefix>
              <NIcon><ChatOutlined /></NIcon>
            </template>
          </NStatistic>
        </NCard>
      </NGi>
      <NGi>
        <NCard>
          <NStatistic label="系统状态" value="运行正常">
            <template #prefix>
              <NIcon color="#18a058"><CheckCircleOutlined /></NIcon>
            </template>
          </NStatistic>
        </NCard>
      </NGi>
    </NGrid>

    <NGrid :cols="4" :x-gap="16" :y-gap="16" class="mt-6">
      <NGi>
        <NCard title="就绪文档">
          <div class="text-3xl font-bold text-green-600">
            {{ dashboard?.documents_by_status?.ready ?? 0 }}
          </div>
        </NCard>
      </NGi>
      <NGi>
        <NCard title="处理中">
          <div class="text-3xl font-bold text-orange-500">
            {{ dashboard?.documents_by_status?.processing ?? 0 }}
          </div>
        </NCard>
      </NGi>
      <NGi>
        <NCard title="上传中">
          <div class="text-3xl font-bold text-blue-500">
            {{ dashboard?.documents_by_status?.uploading ?? 0 }}
          </div>
        </NCard>
      </NGi>
      <NGi>
        <NCard title="失败">
          <div class="text-3xl font-bold text-red-500">
            {{ dashboard?.documents_by_status?.failed ?? 0 }}
          </div>
        </NCard>
      </NGi>
    </NGrid>

    <NSpace class="mt-6">
      <NButton type="primary" @click="router.push('/admin/users')">
        用户管理
      </NButton>
      <NButton @click="router.push('/admin/providers')">
        LLM 提供商
      </NButton>
    </NSpace>
  </div>
</template>

<style scoped>
.flex-between {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
