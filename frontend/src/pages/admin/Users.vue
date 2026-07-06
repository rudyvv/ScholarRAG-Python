<script setup lang="ts">
import { ref, computed, h, onMounted } from 'vue'
import {
  NCard,
  NButton,
  NDataTable,
  NTabs,
  NTabPane,
  NModal,
  NForm,
  NFormItem,
  NInput,
  NSelect,
  NSwitch,
  NPopconfirm,
  NIcon,
  NSpace,
  NTag,
  NInputGroup,
  NInputGroupLabel,
  useMessage,
  type DataTableColumn,
} from 'naive-ui'
import { EditOutlined, DeleteOutlined, PersonOutlined } from '@/icons'
import { getAdminUsers, updateUserRole, toggleUserActive, updateUser, deleteUser } from '@/api/admin'
import type { AdminUser } from '@/types'

const message = useMessage()

// ── Data ──
const users = ref<AdminUser[]>([])
const loading = ref(false)

// ── Tab ──
const activeTab = ref<'admin' | 'user'>('admin')

// ── Pagination per tab ──
const adminPage = ref(1)
const adminPageSize = ref(10)
const userPage = ref(1)
const userPageSize = ref(10)

// ── Row number helper ──
function rowIndex(index: number, page: number, pageSize: number): number {
  return (page - 1) * pageSize + index + 1
}

// ── Filtered lists ──
const adminUsers = computed(() => users.value.filter(u => u.role === 'admin'))
const regularUsers = computed(() => users.value.filter(u => u.role === 'user'))

// ── Load users ──
async function loadUsers() {
  loading.value = true
  try {
    const res = await getAdminUsers()
    users.value = res.data.items || []
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(err?.response?.data?.detail || '获取用户列表失败')
  } finally {
    loading.value = false
  }
}

// ── Confirm action dialog (reusable for role/active changes) ──
const confirmActionVisible = ref(false)
const confirmActionTitle = ref('')
const confirmActionContent = ref('')
const confirmActionLoading = ref(false)
let confirmActionHandler: (() => Promise<void>) | null = null

function showConfirmAction(title: string, content: string, handler: () => Promise<void>) {
  confirmActionTitle.value = title
  confirmActionContent.value = content
  confirmActionHandler = handler
  confirmActionVisible.value = true
}

async function executeConfirmAction() {
  if (!confirmActionHandler) return
  confirmActionLoading.value = true
  try {
    await confirmActionHandler()
    confirmActionVisible.value = false
  } finally {
    confirmActionLoading.value = false
    confirmActionHandler = null
  }
}

function cancelConfirmAction() {
  confirmActionVisible.value = false
  confirmActionHandler = null
}

// ── Role change (with confirmation) ──
function promptRoleChange(row: AdminUser, newRole: 'admin' | 'user') {
  if (newRole === row.role) return
  const roleName = newRole === 'admin' ? '管理员' : '普通用户'
  showConfirmAction(
    '确认角色变更',
    `确定要将用户 "${row.username}" 的角色变更为「${roleName}」吗？`,
    async () => {
      await updateUserRole(row.id, newRole)
      message.success(`角色已更新为${roleName}`)
      await loadUsers()
    },
  )
}

// ── Toggle active (with confirmation) ──
function promptToggleActive(row: AdminUser, value: boolean) {
  const action = value ? '启用' : '禁用'
  showConfirmAction(
    `确认${action}账号`,
    `确定要${action}用户 "${row.username}" 的账号吗？`,
    async () => {
      await toggleUserActive(row.id, value)
      message.success(`账号已${action}`)
      await loadUsers()
    },
  )
}

// ── Edit modal ──
const editModalVisible = ref(false)
const editingUser = ref<AdminUser | null>(null)
const editSubmitting = ref(false)

const editForm = ref({
  username: '',
  email: '',
  role: 'user' as 'admin' | 'user',
  is_active: true,
  org_tags: '',
})

// ── Org tags helper ──
const tagInput = ref('')

function orgTagList(tags: string): string[] {
  if (!tags) return []
  return tags.split(';').map(t => t.trim()).filter(Boolean)
}

function removeOrgTag(tag: string) {
  const list = orgTagList(editForm.value.org_tags).filter(t => t !== tag)
  editForm.value.org_tags = list.join(';')
}

function addOrgTag() {
  const tag = tagInput.value.trim()
  if (!tag) return
  const list = orgTagList(editForm.value.org_tags)
  if (!list.includes(tag)) {
    list.push(tag)
    editForm.value.org_tags = list.join(';')
  }
  tagInput.value = ''
}

function openEditModal(row: AdminUser) {
  editingUser.value = row
  editForm.value = {
    username: row.username,
    email: row.email || '',
    role: row.role,
    is_active: row.is_active,
    org_tags: row.org_tags || '',
  }
  editModalVisible.value = true
}

async function handleEditSubmit() {
  if (!editingUser.value) return
  editSubmitting.value = true
  try {
    await updateUser(editingUser.value.id, {
      username: editForm.value.username,
      email: editForm.value.email || null,
      role: editForm.value.role,
      is_active: editForm.value.is_active,
      org_tags: editForm.value.org_tags || null,
    })
    message.success('用户信息已更新')
    editModalVisible.value = false
    await loadUsers()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(err?.response?.data?.detail || '更新失败')
  } finally {
    editSubmitting.value = false
  }
}

// ── Delete ──
async function handleDeleteUser(row: AdminUser) {
  try {
    await deleteUser(row.id)
    message.success('用户已删除')
    await loadUsers()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    message.error(err?.response?.data?.detail || '删除失败')
  }
}

// ── Admin table columns ──
const adminColumns = computed<DataTableColumn<AdminUser>[]>(() => [
  {
    title: '#',
    key: 'rowIndex',
    width: 60,
    render(_row: AdminUser, index: number) {
      return rowIndex(index, adminPage.value, adminPageSize.value)
    },
  },
  {
    title: '用户名',
    key: 'username',
    width: 140,
  },
  {
    title: '邮箱',
    key: 'email',
    minWidth: 200,
    ellipsis: { tooltip: true },
  },
  {
    title: '组织标签',
    key: 'org_tags',
    minWidth: 160,
    render(row: AdminUser) {
      const tags = orgTagList(row.org_tags || '')
      if (tags.length === 0) return '-'
      return h('div', { style: 'display: flex; gap: 4px; flex-wrap: wrap' },
        tags.map(t => h(NTag, { size: 'tiny', type: 'info' }, { default: () => t }))
      )
    },
  },
  {
    title: '状态',
    key: 'is_active',
    width: 80,
    align: 'center',
    render(row: AdminUser) {
      return h(NTag, { type: row.is_active ? 'success' : 'default', size: 'small' }, {
        default: () => row.is_active ? '启用' : '停用',
      })
    },
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 160,
    render(row: AdminUser) {
      return row.created_at ? new Date(row.created_at).toLocaleString('zh-CN') : '-'
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    align: 'center',
    render(row: AdminUser) {
      return h(NButton, {
        size: 'tiny',
        quaternary: true,
        onClick: () => openEditModal(row),
        renderIcon: () => h(NIcon, null, { default: () => h(EditOutlined) }),
      })
    },
  },
])

// ── User table columns ──
const userColumns = computed<DataTableColumn<AdminUser>[]>(() => [
  {
    title: '#',
    key: 'rowIndex',
    width: 60,
    render(_row: AdminUser, index: number) {
      return rowIndex(index, userPage.value, userPageSize.value)
    },
  },
  {
    title: '用户名',
    key: 'username',
    width: 140,
  },
  {
    title: '邮箱',
    key: 'email',
    minWidth: 180,
    ellipsis: { tooltip: true },
  },
  {
    title: '组织标签',
    key: 'org_tags',
    minWidth: 160,
    render(row: AdminUser) {
      const tags = orgTagList(row.org_tags || '')
      if (tags.length === 0) return '-'
      return h('div', { style: 'display: flex; gap: 4px; flex-wrap: wrap' },
        tags.map(t => h(NTag, { size: 'tiny', type: 'info' }, { default: () => t }))
      )
    },
  },
  {
    title: '角色',
    key: 'role',
    width: 130,
    align: 'center',
    render(row: AdminUser) {
      return h(NSelect, {
        value: row.role,
        options: [
          { label: '管理员', value: 'admin' },
          { label: '普通用户', value: 'user' },
        ],
        size: 'tiny',
        style: 'width: 100px',
        onUpdateValue: (val: 'admin' | 'user') => promptRoleChange(row, val),
      })
    },
  },
  {
    title: '状态',
    key: 'is_active',
    width: 80,
    align: 'center',
    render(row: AdminUser) {
      return h(NSwitch, {
        value: row.is_active,
        size: 'small',
        onUpdateValue: (val: boolean) => promptToggleActive(row, val),
      })
    },
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 160,
    render(row: AdminUser) {
      return row.created_at ? new Date(row.created_at).toLocaleString('zh-CN') : '-'
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 120,
    align: 'center',
    render(row: AdminUser) {
      return h('div', { class: 'flex items-center justify-center gap-1' }, [
        h(NButton, {
          size: 'tiny',
          quaternary: true,
          onClick: () => openEditModal(row),
          renderIcon: () => h(NIcon, null, { default: () => h(EditOutlined) }),
        }),
        h(NPopconfirm, {
          onPositiveClick: () => handleDeleteUser(row),
        }, {
          trigger: () =>
            h(NButton, {
              size: 'tiny',
              type: 'error',
              quaternary: true,
              renderIcon: () => h(NIcon, null, { default: () => h(DeleteOutlined) }),
            }),
          default: () => `确定删除用户 "${row.username}"？`,
        }),
      ])
    },
  },
])

onMounted(() => {
  loadUsers()
})
</script>

<template>
  <div>
    <!-- Header -->
    <div class="mb-6">
      <div class="flex items-center gap-2">
        <NIcon size="24" color="#18a058"><PersonOutlined /></NIcon>
        <h2 class="text-2xl font-bold">用户管理</h2>
      </div>
      <p class="mt-1 text-sm text-gray-400 ml-9">管理系统用户及其角色权限</p>
    </div>

    <NCard :bordered="true">
      <NTabs
        :value="activeTab"
        @update:value="(val: string) => activeTab = val as 'admin' | 'user'"
        type="line"
        animated
      >
        <!-- Admin tab -->
        <NTabPane name="admin" tab="管理员">
          <NDataTable
            :columns="adminColumns"
            :data="adminUsers"
            :bordered="true"
            :striped="true"
            :row-key="(row: AdminUser) => row.id"
            :loading="loading"
            :pagination="{
              page: adminPage,
              pageSize: adminPageSize,
              itemCount: adminUsers.length,
              onChange: (p: number) => { adminPage = p },
              pageSizes: [5, 10, 20, 50],
              showSizePicker: true,
              onUpdatePageSize: (size: number) => { adminPageSize = size; adminPage = 1 },
            }"
            size="small"
          />
        </NTabPane>

        <!-- User tab -->
        <NTabPane name="user" tab="普通用户">
          <NDataTable
            :columns="userColumns"
            :data="regularUsers"
            :bordered="true"
            :striped="true"
            :row-key="(row: AdminUser) => row.id"
            :loading="loading"
            :pagination="{
              page: userPage,
              pageSize: userPageSize,
              itemCount: regularUsers.length,
              onChange: (p: number) => { userPage = p },
              pageSizes: [5, 10, 20, 50],
              showSizePicker: true,
              onUpdatePageSize: (size: number) => { userPageSize = size; userPage = 1 },
            }"
            size="small"
          />
        </NTabPane>
      </NTabs>
    </NCard>

    <!-- Edit User Modal (shared) -->
    <NModal
      :show="editModalVisible"
      @update:show="(val: boolean) => { if (!val) editModalVisible = false }"
      title="编辑用户"
      preset="card"
      style="max-width: 520px"
      closable
      :mask-closable="!editSubmitting"
    >
      <NForm :model="editForm" label-placement="left" label-width="100">
        <NFormItem label="用户名" path="username">
          <NInput v-model:value="editForm.username" placeholder="请输入用户名" />
        </NFormItem>
        <NFormItem label="邮箱" path="email">
          <NInput v-model:value="editForm.email" placeholder="user@example.com" />
        </NFormItem>
        <NFormItem label="组织标签" path="org_tags">
          <div style="display: flex; flex-direction: column; gap: 8px; width: 100%">
            <div style="display: flex; gap: 4px; flex-wrap: wrap">
              <NTag
                v-for="tag in orgTagList(editForm.org_tags)"
                :key="tag"
                type="info"
                size="small"
                closable
                @close="removeOrgTag(tag)"
              >
                {{ tag }}
              </NTag>
            </div>
            <NInputGroup>
              <NInput
                v-model:value="tagInput"
                placeholder="输入标签按 Enter 添加"
                @keydown.enter.prevent="addOrgTag"
              />
              <NInputGroupLabel>
                <NButton size="tiny" quaternary @click="addOrgTag">+</NButton>
              </NInputGroupLabel>
            </NInputGroup>
          </div>
        </NFormItem>
        <NFormItem label="角色" path="role">
          <NSelect
            v-model:value="editForm.role"
            :disabled="editingUser?.role === 'admin'"
            :options="[
              { label: '管理员', value: 'admin' },
              { label: '普通用户', value: 'user' },
            ]"
          />
        </NFormItem>
        <NFormItem label="启用状态" path="is_active">
          <NSwitch
            v-model:value="editForm.is_active"
            :disabled="editingUser?.role === 'admin'"
          />
        </NFormItem>
      </NForm>

      <template #footer>
        <NSpace justify="end">
          <NButton quaternary @click="editModalVisible = false" :disabled="editSubmitting">
            取消
          </NButton>
          <NButton type="primary" :loading="editSubmitting" @click="handleEditSubmit">
            保存
          </NButton>
        </NSpace>
      </template>
    </NModal>

    <!-- Confirm action dialog (reusable for role change / active toggle) -->
    <NModal
      :show="confirmActionVisible"
      @update:show="(val: boolean) => { if (!val && !confirmActionLoading) cancelConfirmAction() }"
      :title="confirmActionTitle"
      preset="dialog"
      type="warning"
      :loading="confirmActionLoading"
      positive-text="确定"
      negative-text="取消"
      @positive-click="executeConfirmAction"
      @negative-click="cancelConfirmAction"
    >
      {{ confirmActionContent }}
    </NModal>
  </div>
</template>
