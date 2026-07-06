<script setup lang="ts">
import { h, ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  NLayout,
  NLayoutSider,
  NLayoutHeader,
  NLayoutContent,
  NMenu,
  NIcon,
  NSpace,
  NButton,
  NDropdown,
  NAvatar,
} from 'naive-ui'
import {
  DashboardOutlined,
  BookOutlined,
  ChatOutlined,
  SettingsOutlined,
  LogOutOutlined,
  MenuOutlined,
  PersonOutlined,
} from '@/icons'
import type { MenuOption } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const collapsed = ref(false)

const menuOptions = computed<MenuOption[]>(() => {
  const items: MenuOption[] = [
    {
      label: '仪表盘',
      key: 'Dashboard',
      icon: () => h(NIcon, null, { default: () => h(DashboardOutlined) }),
    },
    {
      label: '知识库',
      key: 'KBList',
      icon: () => h(NIcon, null, { default: () => h(BookOutlined) }),
    },
    {
      label: '对话',
      key: 'ChatList',
      icon: () => h(NIcon, null, { default: () => h(ChatOutlined) }),
    },
  ]
  if (authStore.user?.role === 'admin') {
    items.push({
      type: 'group',
      label: '管理',
      key: 'AdminGroup',
      icon: () => h(NIcon, null, { default: () => h(SettingsOutlined) }),
      children: [
        { label: '管理面板', key: 'AdminDashboard', icon: () => h(NIcon, null, { default: () => h(DashboardOutlined) }) },
        { label: '用户管理', key: 'AdminUsers', icon: () => h(NIcon, null, { default: () => h(PersonOutlined) }) },
        { label: 'LLM 提供商', key: 'AdminProviders', icon: () => h(NIcon, null, { default: () => h(SettingsOutlined) }) },
      ],
    })
  }
  return items
})

const activeKey = computed(() => route.name as string)

function handleMenuUpdate(key: string) {
  switch (key) {
    case 'Dashboard':
      router.push('/')
      break
    case 'KBList':
      router.push('/kb')
      break
    case 'ChatList':
      router.push('/chat')
      break
    case 'AdminDashboard':
      router.push('/admin/dashboard')
      break
    case 'AdminUsers':
      router.push('/admin/users')
      break
    case 'AdminProviders':
      router.push('/admin/providers')
      break
  }
}

const userDropdownOptions = computed(() => [
  {
    label: authStore.user?.username ?? '用户',
    key: 'profile',
    icon: () => h(NIcon, null, { default: () => h(PersonOutlined) }),
    disabled: true,
  },
  {
    type: 'divider' as const,
  },
  {
    label: '退出登录',
    key: 'logout',
    icon: () => h(NIcon, null, { default: () => h(LogOutOutlined) }),
  },
])

async function handleUserAction(key: string) {
  if (key === 'logout') {
    await authStore.logoutUser()
    router.push('/login')
  }
}
</script>

<template>
  <NLayout has-sider position="absolute">
    <NLayoutSider
      bordered
      :collapsed="collapsed"
      collapse-mode="width"
      :collapsed-width="64"
      :width="220"
      :native-scrollbar="false"
      style="background: #f5f7fa"
    >
      <div class="flex-center h-16 text-lg font-bold" style="color: #18a058">
        <span v-if="!collapsed">Paismart RAG</span>
        <span v-else>P</span>
      </div>
      <NMenu
        :value="activeKey"
        :collapsed="collapsed"
        :collapsed-width="64"
        :collapsed-icon-size="22"
        :options="menuOptions"
        style="border-right: none"
        @update:value="handleMenuUpdate"
      />
    </NLayoutSider>

    <NLayout>
      <NLayoutHeader bordered style="height: 56px; background: #fff">
        <div class="flex-between h-full px-4">
          <NButton quaternary size="small" @click="collapsed = !collapsed">
            <template #icon>
              <NIcon><MenuOutlined /></NIcon>
            </template>
          </NButton>

          <NSpace align="center">
            <NDropdown
              trigger="click"
              :options="userDropdownOptions"
              @select="handleUserAction"
            >
              <NButton quaternary circle>
                <template #icon>
                  <NAvatar
                    size="small"
                    round
                    style="background: #18a058; color: #fff"
                  >
                    {{ authStore.user?.username?.[0]?.toUpperCase() ?? 'U' }}
                  </NAvatar>
                </template>
              </NButton>
            </NDropdown>
          </NSpace>
        </div>
      </NLayoutHeader>

      <NLayoutContent
        :native-scrollbar="false"
        style="height: calc(100vh - 56px); background: #f0f2f5; overflow: hidden"
      >
        <div class="p-6">
          <router-view />
        </div>
      </NLayoutContent>
    </NLayout>
  </NLayout>
</template>
