import type { ChatMessage } from '@/lib/types'
import { DefaultChatTransport } from 'ai'

export function createChatTransport() {
  return new DefaultChatTransport<ChatMessage>({
    api: '/api/chat',
    prepareSendMessagesRequest: ({ messages, body, headers }) => {
      const prompt = typeof body?.prompt === 'string' ? body.prompt : ''

      return {
        headers: {
          ...headers,
          Accept: 'text/event-stream'
        },
        body: {
          prompt,
          model:
            typeof window === 'undefined'
              ? undefined
              : localStorage.getItem('ai-lite-model') || undefined,
          web_search:
            typeof window !== 'undefined' && localStorage.getItem('ai-lite-web-search') === 'on',
          messages: messages.map(({ role, parts }) => ({ role, parts }))
        }
      }
    }
  })
}
