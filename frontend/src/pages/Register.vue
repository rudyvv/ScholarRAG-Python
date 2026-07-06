<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
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
const authStore = useAuthStore()
const message = useMessage()

const formRef = ref<InstanceType<typeof NForm>>()
const formData = ref({ username: '', email: '', password: '', confirmPassword: '' })
const loading = ref(false)

async function handleSubmit() {
  if (formData.value.password !== formData.value.confirmPassword) {
    message.error('两次密码输入不一致')
    return
  }
  loading.value = true
  try {
    await authStore.register({
      username: formData.value.username,
      email: formData.value.email,
      password: formData.value.password,
    })
    message.success('注册成功，请登录')
    router.push('/login')
  } catch (err: unknown) {
    const data = (err as { response?: { data?: Record<string, unknown> } })?.response?.data
    const detail = data?.detail
    const msg = Array.isArray(detail) ? (detail[0] as Record<string, unknown>)?.msg as string : (detail as string) || '注册失败'
    message.error(msg)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex-center min-h-screen" style="background: #f0f2f5">
    <NCard
      title="注册"
      style="width: 400px"
      :bordered="true"
    >
      <NForm
        ref="formRef"
        :model="formData"
        label-placement="top"
        @submit.prevent="handleSubmit"
      >
        <NFormItem label="用户名" path="username">
          <NInput
            v-model:value="formData.username"
            placeholder="请输入用户名"
            :disabled="loading"
          />
        </NFormItem>
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
        <NFormItem label="确认密码" path="confirmPassword">
          <NInput
            v-model:value="formData.confirmPassword"
            type="password"
            placeholder="请再次输入密码"
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
            注册
          </NButton>
          <NButton
            quaternary
            block
            @click="router.push('/login')"
          >
            返回登录
          </NButton>
        </NSpace>
      </NForm>
    </NCard>
  </div>
</template>
