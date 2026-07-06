import client from './client'
import type {
  ConversationSession,
  ConversationMessage,
  AskRequest,
  AskResponse,
  SearchResultItem,
} from '@/types'

export function listSessions() {
  return client.get<{ items: ConversationSession[]; total: number }>('/chat/sessions')
}

export function createSession() {
  return client.post<ConversationSession>('/chat/sessions', {
    title: '新对话',
  })
}

export function deleteSession(id: number) {
  return client.delete(`/chat/sessions/${id}`)
}

export function listMessages(sessionId: number) {
  return client.get<{ items: ConversationMessage[]; total: number }>(`/chat/sessions/${sessionId}/messages`)
}

export function updateSession(id: number, data: { title: string }) {
  return client.put<ConversationSession>(`/chat/sessions/${id}`, data)
}

export function askQuestion(data: AskRequest) {
  return client.post<AskResponse>('/chat/ask', data)
}

/**
 * Ask a question and stream the answer via SSE.
 *
 * Returns an abort controller so the caller can cancel the request.
 *
 * @param data - The ask request payload.
 * @param onToken - Called with each text token.
 * @param onSources - Called with the final source list.
 * @param onError - Called on error.
 * @param onDone - Called when the stream completes.
 * @returns An AbortController to cancel the stream.
 */
export function askQuestionStream(
  data: AskRequest,
  onToken: (token: string) => void,
  onSources: (sources: SearchResultItem[]) => void,
  onError: (message: string) => void,
  onDone: () => void,
): AbortController {
  const controller = new AbortController()
  const accessToken = localStorage.getItem('access_token')

  fetch('/api/v1/chat/ask/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    body: JSON.stringify(data),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        onError(`HTTP ${response.status}`)
        return
      }

      const reader = response.body?.getReader()
      if (!reader) {
        onError('No response body')
        return
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? '' // keep incomplete line

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))
            switch (event.type) {
              case 'token':
                onToken(event.token)
                break
              case 'sources':
                onSources(event.sources ?? [])
                break
              case 'error':
                onError(event.message ?? 'Unknown error')
                break
              case 'done':
                onDone()
                break
            }
          } catch {
            // skip malformed JSON
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onError(err.message ?? 'Network error')
      }
    })

  return controller
}
