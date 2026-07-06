<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  NForm,
  NFormItem,
  NInput,
  NButton,
  NCard,
  NSpace,
  useMessage,
} from 'naive-ui'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const message = useMessage()

const formRef = ref<InstanceType<typeof NForm>>()
const formData = ref({ email: '', password: '' })
const loading = ref(false)

async function handleSubmit() {
  loading.value = true
  try {
    await authStore.login(formData.value)
    message.success('登录成功')
    const redirect = (route.query.redirect as string) || '/'
    router.push(redirect)
  } catch (err: unknown) {
    const data = (err as { response?: { data?: Record<string, unknown> } })?.response?.data
    const detail = data?.detail
    const msg = Array.isArray(detail) ? (detail[0] as Record<string, unknown>)?.msg as string : (detail as string) || '登录失败'
    message.error(msg)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex-center min-h-screen" style="background: #f0f2f5">
    <NCard
      title="登录"
      style="width: 400px"
      :bordered="true"
    >
      <NForm
        ref="formRef"
        :model="formData"
        label-placement="top"
        @submit.prevent="handleSubmit"
      >
        <NFormItem label="邮箱" path="email">
          <NInput
            v-model:value="formData.email"
            placeholder="请输入邮箱"
            :disabled="loading"
          />
        </NFormItem>
        <NFormItem label="密码" path="password">
          <NInput
            v-model:value="formData.password"
            type="password"
            placeholder="请输入密码"
            show-password-on="click"
            :disabled="loading"
          />
        </NFormItem>
        <NSpace vertical>
          <NButton
            type="primary"
            block
            attr-type="submit"
            :loading="loading"
          >
            登录
          </NButton>
          <NButton
            quaternary
            block
            @click="router.push('/register')"
          >
            注册账号
          </NButton>
        </NSpace>
      </NForm>
    </NCard>
  </div>
</template>
