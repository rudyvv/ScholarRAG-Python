<script setup lang="ts">
import { ref, onMounted, nextTick, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import {
  NLayout,
  NLayoutSider,
  NLayoutHeader,
  NButton,
  NIcon,
  NInput,
  NList,
  NListItem,
  NSpin,
  NEmpty,
  NTable,
  NCollapse,
  NCollapseItem,
  NTag,
  NText,
  NModal,
  NSpace,
} from 'naive-ui'
import {
  AddOutlined,
  ChatOutlined,
  SendRound,
  DeleteOutlined,
  PersonOutlined,
  CopyOutlined,
  ThumbUpOutlined,
  ThumbDownOutlined,
  RefreshOutlined,
} from '@/icons'
import { listSessions, createSession, deleteSession, updateSession, listMessages, askQuestionStream } from '@/api/chat'
import { renderMarkdown } from '@/utils/markdown'
import type { ConversationSession, ConversationMessage, SearchResultItem } from '@/types'

const route = useRoute()
const router = useRouter()
const message = useMessage()

// ── State ──
const sessions = ref<ConversationSession[]>([])
const activeSessionId = ref<number | null>(null)
const messages = ref<(ConversationMessage & { sources?: SearchResultItem[] })[]>([])
const newMessage = ref('')
const sending = ref(false)
const sessionsLoading = ref(false)
const messagesLoading = ref(false)
const messageListEl = ref<HTMLDivElement | null>(null)

// ── Delete confirm state ──
const showDeleteConfirm = ref(false)
const deletingSession = ref<ConversationSession | null>(null)
const deleteLoading = ref(false)

const activeSession = computed(() =>
  sessions.value.find((s) => s.id === activeSessionId.value) ?? null
)

// ── Session operations ──
async function loadSessions() {
  sessionsLoading.value = true
  try {
    const res = await listSessions()
    sessions.value = res.data.items
  } catch {
    message.error('加载会话列表失败')
  } finally {
    sessionsLoading.value = false
  }
}

async function loadMessagesForSession(sessionId: number) {
  messagesLoading.value = true
  messages.value = []
  try {
    const res = await listMessages(sessionId)
    messages.value = res.data.items
    await nextTick()
    scrollToBottom()
  } catch {
    message.error('加载消息失败')
  } finally {
    messagesLoading.value = false
  }
}

async function handleCreateSession() {
  try {
    const res = await createSession()
    const session: ConversationSession = res.data
    sessions.value.unshift(session)
    activeSessionId.value = session.id
    messages.value = []
    router.replace({ name: 'ChatDetail', params: { id: session.id } })
  } catch {
    message.error('创建会话失败')
  }
}

function handleDeleteClick(session: ConversationSession, ev: MouseEvent) {
  ev.stopPropagation()
  deletingSession.value = session
  showDeleteConfirm.value = true
}

async function handleConfirmDelete() {
  if (!deletingSession.value) return
  deleteLoading.value = true
  try {
    await deleteSession(deletingSession.value.id)
    sessions.value = sessions.value.filter((s) => s.id !== deletingSession.value!.id)
    if (activeSessionId.value === deletingSession.value.id) {
      activeSessionId.value = null
      messages.value = []
      router.replace({ name: 'ChatList' })
    }
    message.success('会话已删除')
    showDeleteConfirm.value = false
    deletingSession.value = null
  } catch {
    message.error('删除会话失败')
  } finally {
    deleteLoading.value = false
  }
}

function handleSelectSession(session: ConversationSession) {
  if (activeSessionId.value === session.id) return
  activeSessionId.value = session.id
  messages.value = []
  router.replace({ name: 'ChatDetail', params: { id: session.id } })
  loadMessagesForSession(session.id)
}

// ── Track the active stream controller for cancellation ──
const streamController = ref<AbortController | null>(null)

// ── Feedback (thumbs up/down) state ──
const feedbackMap = ref<Record<number, 'up' | 'down' | null>>({})

function setFeedback(msgId: number, value: 'up' | 'down') {
  const current = feedbackMap.value[msgId]
  feedbackMap.value[msgId] = current === value ? null : value
}

// ── Regenerate a single assistant message ──
async function regenerateMessage(msgIndex: number) {
  const msg = messages.value[msgIndex]
  if (!msg || msg.role !== 'assistant' || msgIndex < 1) return

  // Find the preceding user message
  let userMsgIndex = msgIndex - 1
  while (userMsgIndex >= 0 && messages.value[userMsgIndex].role !== 'user') {
    userMsgIndex--
  }
  if (userMsgIndex < 0) return

  const userQuery = messages.value[userMsgIndex].content
  if (!userQuery.trim()) return

  // Clear the assistant message content and re-send
  const sessionId = msg.session_id
  msg.content = ''

  streamController.value = askQuestionStream(
    { query: userQuery, session_id: sessionId },
    (token) => {
      msg.content += token
      nextTick(scrollToBottom)
    },
    (sources) => {
      msg.sources = sources
    },
    (errMsg) => {
      if (!msg.content) {
        msg.content = '抱歉，回答时出现错误，请稍后重试。'
      }
      message.error(errMsg)
    },
    () => {
      streamController.value = null
    },
  )
}

// ── Message sending ──
async function handleSend() {
  const query = newMessage.value.trim()
  if (!query || sending.value) return

  // Auto-create session if none active
  let sessionId = activeSessionId.value
  let isNewSession = false
  if (!sessionId) {
    try {
      const res = await createSession()
      const session: ConversationSession = res.data
      sessions.value.unshift(session)
      sessionId = session.id
      activeSessionId.value = session.id
      isNewSession = true
      router.replace({ name: 'ChatDetail', params: { id: session.id } })
    } catch {
      message.error('创建会话失败')
      return
    }
  }

  newMessage.value = ''
  sending.value = true

  // Add user message
  messages.value.push({
    id: -Date.now(),
    session_id: sessionId,
    role: 'user',
    content: query,
    metadata: null,
    created_at: new Date().toISOString(),
  })
  await nextTick()
  scrollToBottom()

  // Add placeholder assistant message
  messages.value.push({
    id: -Date.now() - 1,
    session_id: sessionId,
    role: 'assistant',
    content: '',
    metadata: null,
    created_at: new Date().toISOString(),
    sources: [] as SearchResultItem[],
  })

  const msgIdx = messages.value.length - 1
  await nextTick()
  scrollToBottom()

  // Auto-update session title with first question
  if (isNewSession && sessionId) {
    const title = query.length > 30 ? query.slice(0, 30) + '...' : query
    updateSession(sessionId, { title }).then(() => {
      const idx = sessions.value.findIndex(s => s.id === sessionId)
      if (idx !== -1) sessions.value[idx].title = title
    }).catch(() => { /* silent */ })
  }

  // Stream the answer via SSE instead of fake setTimeout
  streamController.value = askQuestionStream(
    { query, session_id: sessionId },
    // onToken: append each token to the assistant message
    (token) => {
      messages.value[msgIdx].content += token
      nextTick(scrollToBottom)
    },
    // onSources: attach sources
    (sources) => {
      messages.value[msgIdx].sources = sources
    },
    // onError
    (errMsg) => {
      if (!messages.value[msgIdx].content) {
        messages.value[msgIdx].content = '抱歉，回答时出现错误，请稍后重试。'
      }
      message.error(errMsg)
    },
    // onDone
    () => {
      sending.value = false
      streamController.value = null
    },
  )
}

// ── Keyboard ──
function handleKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Enter' && !ev.shiftKey) {
    ev.preventDefault()
    handleSend()
  }
}

// ── Utils ──
function scrollToBottom() {
  if (messageListEl.value) {
    messageListEl.value.scrollTop = messageListEl.value.scrollHeight
  }
}

function formatTime(ts: string): string {
  const d = new Date(ts)
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).then(
    () => message.success('已复制到剪贴板'),
    () => message.error('复制失败'),
  )
}

// ── Route integration ──
watch(
  () => route.params.id,
  (newId) => {
    if (typeof newId === 'string' && newId) {
      const id = Number(newId)
      if (!isNaN(id) && id !== activeSessionId.value) {
        activeSessionId.value = id
        loadMessagesForSession(id)
      }
    }
  },
)

onMounted(async () => {
  await loadSessions()
  const idParam = route.params.id
  if (typeof idParam === 'string' && idParam) {
    const id = Number(idParam)
    if (!isNaN(id)) {
      activeSessionId.value = id
      await loadMessagesForSession(id)
    }
  }
})
</script>

<template>
  <div class="chat-wrapper">
    <NLayout has-sider position="absolute" class="chat-layout">
      <!-- Sidebar: session list -->
      <NLayoutSider
        width="240"
        bordered
        :native-scrollbar="false"
        class="chat-sider"
      >
        <div class="sider-inner">
          <div class="sider-header">
            <NButton type="primary" block @click="handleCreateSession">
              <template #icon>
                <NIcon><AddOutlined /></NIcon>
              </template>
              新对话
            </NButton>
          </div>

          <div class="sider-list">
            <NSpin :show="sessionsLoading">
              <template v-if="sessions.length === 0 && !sessionsLoading">
                <NEmpty description="暂无对话，点击上方按钮创建" />
              </template>

              <NList v-else bordered>
                <NListItem
                  v-for="session in sessions"
                  :key="session.id"
                  :class="{
                    'session-item': true,
                    'session-item--active': session.id === activeSessionId,
                  }"
                  @click="handleSelectSession(session)"
                >
                  <div class="session-item-content">
                    <div class="session-item-title">
                      <NIcon size="16" color="#18a058">
                        <ChatOutlined />
                      </NIcon>
                      <span class="session-title-text">{{ session.title }}</span>
                    </div>
                    <div class="session-item-meta">
                      <NText depth="3" class="text-xs">{{ formatTime(session.created_at) }}</NText>
                      <NButton
                        quaternary
                        circle
                        size="tiny"
                        class="session-delete-btn"
                        @click="(ev: MouseEvent) => handleDeleteClick(session, ev)"
                      >
                        <template #icon>
                          <NIcon size="14"><DeleteOutlined /></NIcon>
                        </template>
                      </NButton>
                    </div>
                  </div>
                </NListItem>
              </NList>
            </NSpin>
          </div>
        </div>
      </NLayoutSider>

      <!-- Main: chat area (flex column to pin footer at bottom) -->
      <div class="main-area">
        <!-- Session title header -->
        <NLayoutHeader
          v-if="activeSession"
          bordered
          class="chat-header"
        >
          <div class="chat-header-inner">
            <NText strong depth="1">{{ activeSession.title }}</NText>
          </div>
        </NLayoutHeader>

        <!-- Messages area (scrollable, flex: 1 fills remaining space) -->
        <div class="messages-scroll" ref="messageListEl">
          <!-- Loading state for messages -->
          <div v-if="messagesLoading" class="messages-loading">
            <NSpin size="small" />
            <NText depth="3" class="ml-2">加载消息中...</NText>
          </div>

          <!-- No session selected -->
          <div
            v-else-if="!activeSession"
            class="messages-empty"
          >
            <div class="messages-empty-inner">
              <NIcon size="64" color="#d9d9d9">
                <ChatOutlined />
              </NIcon>
              <NText depth="3" class="text-lg mt-4">选择或创建一个对话开始聊天</NText>
            </div>
          </div>

          <!-- Message list -->
          <TransitionGroup
            v-else
            name="msg"
            tag="div"
            class="message-list"
          >
            <div
              v-for="(msg, msgIdx) in messages"
              :key="msg.id"
              class="message-item"
              :class="{ 'message-item--user': msg.role === 'user', 'message-item--assistant': msg.role === 'assistant' }"
            >
              <div
                class="message-bubble"
                :class="{
                  'message-bubble--user': msg.role === 'user',
                  'message-bubble--assistant': msg.role === 'assistant',
                }"
              >
                <!-- Role header -->
                <div class="message-role">
                  <template v-if="msg.role === 'user'">
                    <NIcon size="16" color="#18a058"><PersonOutlined /></NIcon>
                    <NText depth="2" class="text-xs ml-1">你</NText>
                  </template>
                  <template v-else>
                    <NIcon size="16" color="#18a058"><ChatOutlined /></NIcon>
                    <NText depth="2" class="text-xs ml-1">AI</NText>
                  </template>
                </div>

                <!-- Message content -->
                <div class="message-content" :class="{ 'message-content--streaming': msg.role === 'assistant' && msg.content === '' && sending }">
                  <template v-if="msg.role === 'assistant' && msg.content === '' && sending && msgIdx === messages.length - 1">
                    <div class="streaming-placeholder">
                      <NSpin size="small" />
                      <span class="ml-2">正在思考...</span>
                    </div>
                  </template>
                  <template v-else-if="msg.role === 'assistant'">
                    <div class="markdown-body" v-html="renderMarkdown(msg.content)"></div>
                  </template>
                  <template v-else>
                    {{ msg.content }}
                  </template>
                </div>

                <!-- Action buttons for assistant messages -->
                <div v-if="msg.role === 'assistant' && msg.content" class="message-actions">
                  <!-- Copy -->
                  <NButton
                    quaternary circle size="tiny"
                    @click="copyToClipboard(msg.content)"
                    :title="'复制'"
                  >
                    <template #icon>
                      <NIcon size="14"><CopyOutlined /></NIcon>
                    </template>
                  </NButton>
                  <!-- Thumbs up -->
                  <NButton
                    quaternary circle size="tiny"
                    :type="feedbackMap[msg.id] === 'up' ? 'primary' : 'default'"
                    @click="setFeedback(msg.id, 'up')"
                    :title="'有用'"
                  >
                    <template #icon>
                      <NIcon size="14"><ThumbUpOutlined /></NIcon>
                    </template>
                  </NButton>
                  <!-- Thumbs down -->
                  <NButton
                    quaternary circle size="tiny"
                    :type="feedbackMap[msg.id] === 'down' ? 'warning' : 'default'"
                    @click="setFeedback(msg.id, 'down')"
                    :title="'没用'"
                  >
                    <template #icon>
                      <NIcon size="14"><ThumbDownOutlined /></NIcon>
                    </template>
                  </NButton>
                  <!-- Regenerate -->
                  <NButton
                    quaternary circle size="tiny"
                    @click="regenerateMessage(msgIdx)"
                    :title="'重新生成'"
                    :disabled="streamController !== null"
                  >
                    <template #icon>
                      <NIcon size="14"><RefreshOutlined /></NIcon>
                    </template>
                  </NButton>
                </div>

                <!-- Sources for assistant messages -->
                <div
                  v-if="msg.role === 'assistant' && msg.sources && msg.sources.length > 0"
                  class="message-sources"
                >
                  <NCollapse>
                    <NCollapseItem title="查看来源" name="sources">
                      <NTable size="small" bordered class="sources-table">
                        <thead>
                          <tr>
                            <th style="width: 30%">文件名</th>
                            <th>内容片段</th>
                            <th style="width: 80px">相关度</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr v-for="source in msg.sources" :key="source.chunk_id">
                            <td>
                              <NText class="text-xs">{{ source.filename }}</NText>
                            </td>
                            <td>
                              <NText class="text-xs" depth="2">
                                {{ source.content.length > 120 ? source.content.slice(0, 120) + '...' : source.content }}
                              </NText>
                            </td>
                            <td>
                              <NTag size="tiny" :type="source.score > 0.7 ? 'success' : source.score > 0.4 ? 'warning' : 'default'">
                                {{ source.score.toFixed(3) }}
                              </NTag>
                            </td>
                          </tr>
                        </tbody>
                      </NTable>
                    </NCollapseItem>
                  </NCollapse>
                </div>

                <!-- Timestamp -->
                <div v-if="msg.created_at" class="message-time">
                  <NText depth="3" class="text-xs">{{ formatTime(msg.created_at) }}</NText>
                </div>
              </div>
            </div>
          </TransitionGroup>
        </div>

        <!-- Input area (pinned at bottom by flex column) -->
        <div class="input-area">
          <div class="input-area-inner">
            <NInput
              v-model:value="newMessage"
              type="textarea"
              placeholder="输入消息，按 Enter 发送，Shift+Enter 换行"
              :autosize="{ minRows: 2, maxRows: 6 }"
              :disabled="sending"
              @keydown="handleKeydown"
            />
            <NButton
              type="primary"
              :disabled="!newMessage.trim() || sending"
              :loading="sending"
              class="send-btn"
              @click="handleSend"
            >
              <template #icon>
                <NIcon><SendRound /></NIcon>
              </template>
              发送
            </NButton>
          </div>
        </div>
      </div>
      <!-- Delete confirm modal -->
      <NModal
        :show="showDeleteConfirm"
        @update:show="(val: boolean) => { if (!val && !deleteLoading) { showDeleteConfirm = false; deletingSession = null } }"
        title="确认删除"
        preset="dialog"
        type="warning"
        :loading="deleteLoading"
        positive-text="删除"
        negative-text="取消"
        @positive-click="handleConfirmDelete"
        @negative-click="showDeleteConfirm = false"
      >
        确定要删除会话"{{ deletingSession?.title }}"吗？此操作不可恢复，会话内的所有消息将被永久删除。
      </NModal>
    </NLayout>
  </div>
</template>

<style scoped>
.chat-wrapper {
  margin: -1.5rem;
  height: calc(100vh - 56px);
  position: relative;
}

.chat-layout {
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
}

/* ── Sidebar ── */
.chat-sider {
  background: #f5f7fa;
}

.sider-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.sider-header {
  padding: 12px;
  border-bottom: 1px solid #e5e7eb;
}

.sider-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

/* Session list items */
.session-item {
  cursor: pointer;
  border-radius: 6px;
  margin-bottom: 2px;
  transition: all 0.2s ease;
}

.session-item:hover {
  background: #e8f5e9;
  transform: translateX(2px);
}

.session-item--active {
  background: #c8e6c9 !important;
}

.session-item-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 0;
}

.session-item-title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.session-title-text {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.session-item-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.session-delete-btn {
  opacity: 0;
  transition: all 0.2s ease;
}

.session-item:hover .session-delete-btn {
  opacity: 1;
}

/* ── Chat main area (flex column — header, messages, input) ── */
.main-area {
  display: flex;
  flex-direction: column;
  height: 100%;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  background: #f0f2f5;
}

/* ── Messages scroll area (flex: 1 to fill remaining space) ── */
.messages-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  min-height: 0;
}

/* ── Chat header ── */
.chat-header {
  height: 48px;
  background: #fff;
}

.chat-header-inner {
  display: flex;
  align-items: center;
  height: 100%;
  padding: 0 16px;
}

/* ── Messages ── */
.messages-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.messages-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
}

.messages-empty-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.message-item {
  display: flex;
  max-width: 85%;
}

.message-item--user {
  align-self: flex-end;
}

.message-item--assistant {
  align-self: flex-start;
}

.message-bubble {
  border-radius: 12px;
  padding: 12px 16px;
  min-width: 0;
}

.message-bubble--user {
  background: #e8f5e9;
  border-bottom-right-radius: 4px;
}

.message-bubble--assistant {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-bottom-left-radius: 4px;
}

.message-role {
  display: flex;
  align-items: center;
  margin-bottom: 6px;
}

.message-content {
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.message-sources {
  margin-top: 12px;
  border-top: 1px solid #f0f0f0;
  padding-top: 8px;
}

.message-time {
  margin-top: 6px;
  text-align: right;
}

.sources-table {
  font-size: 12px;
}

/* ── Input area (NLayoutFooter) ── */
.input-area {
  padding: 12px 16px;
  background: #fff;
}

.input-area-inner {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

.input-area-inner .n-input {
  flex: 1;
}

.send-btn {
  flex-shrink: 0;
}

/* ── Markdown rendered content ── */
.markdown-body {
  line-height: 1.7;
  word-break: break-word;
}
.markdown-body p {
  margin: 0.4em 0;
}
.markdown-body p:first-child {
  margin-top: 0;
}
.markdown-body p:last-child {
  margin-bottom: 0;
}
.markdown-body ul,
.markdown-body ol {
  padding-left: 1.5em;
  margin: 0.4em 0;
}
.markdown-body li {
  margin: 0.2em 0;
}
.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4,
.markdown-body h5,
.markdown-body h6 {
  margin: 0.8em 0 0.4em;
  font-weight: 600;
}
.markdown-body h1 { font-size: 1.3em; }
.markdown-body h2 { font-size: 1.2em; }
.markdown-body h3 { font-size: 1.1em; }
.markdown-body code {
  background: #f5f5f5;
  padding: 0.15em 0.4em;
  border-radius: 3px;
  font-size: 0.9em;
}
.markdown-body pre {
  position: relative;
  margin: 0.6em 0;
  border-radius: 6px;
  overflow: hidden;
}
.markdown-body pre code {
  display: block;
  padding: 1em;
  overflow-x: auto;
  background: #f6f8fa;
  font-size: 0.85em;
  line-height: 1.5;
}
.markdown-body blockquote {
  border-left: 3px solid #e0e0e0;
  padding-left: 1em;
  margin: 0.6em 0;
  color: #666;
}
.markdown-body table {
  border-collapse: collapse;
  margin: 0.6em 0;
  width: 100%;
}
.markdown-body th,
.markdown-body td {
  border: 1px solid #e0e0e0;
  padding: 0.4em 0.6em;
  text-align: left;
}
.markdown-body th {
  background: #f5f5f5;
  font-weight: 600;
}
/* Code copy button */
.code-copy-btn {
  position: absolute;
  top: 4px;
  right: 4px;
  padding: 2px 8px;
  font-size: 12px;
  border: none;
  border-radius: 4px;
  background: rgba(0,0,0,0.06);
  color: #666;
  cursor: pointer;
  z-index: 1;
  opacity: 0;
  transition: opacity 0.2s;
}
.code-block-wrapper:hover .code-copy-btn {
  opacity: 1;
}
.code-copy-btn:hover {
  background: rgba(0,0,0,0.12);
}

/* ── Assistant message action buttons ── */
.message-actions {
  display: flex;
  gap: 2px;
  margin-top: 6px;
  opacity: 0;
  transition: opacity 0.2s;
}
.message-item--assistant:hover .message-actions {
  opacity: 1;
}

/* ── Message enter animation ── */
.msg-enter-active {
  transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.msg-enter-from {
  opacity: 0;
  transform: translateY(16px) scale(0.97);
}

/* ── Streaming pulse ── */
/* ── Session list item slide animation ── */
.session-item {
  cursor: pointer;
  border-radius: 6px;
  margin-bottom: 2px;
  transition: all 0.2s ease;
}

.session-item:hover {
  background: #e8f5e9;
  transform: translateX(2px);
}

/* ── Enhanced delete button appearance ── */
.session-delete-btn {
  opacity: 0;
  transition: all 0.2s ease;
}

.session-item:hover .session-delete-btn {
  opacity: 1;
}

.session-delete-btn:hover {
  transform: scale(1.15);
  color: #d32f2f !important;
}

/* ── Input area subtle animation ── */
.input-area {
  padding: 12px 16px;
  background: #fff;
  border-top: 1px solid #e8e8e8;
  transition: box-shadow 0.3s ease;
}

.input-area:focus-within {
  box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.06);
}

/* ── Send button animation ── */
.send-btn {
  flex-shrink: 0;
  transition: all 0.2s ease;
}

.send-btn:not(:disabled):hover {
  transform: scale(1.05);
}

.send-btn:not(:disabled):active {
  transform: scale(0.95);
}
</style>
