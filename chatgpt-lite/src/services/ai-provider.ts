import 'server-only'

import { createOpenAI } from '@ai-sdk/openai'
import type { LanguageModel } from 'ai'

export type LocalModelConfig = { mode: 'local'; model: LanguageModel; modelId: string }
const UPSTREAM = 'http://127.0.0.1:8080'
const SAFE_MODEL_ID = /^[A-Za-z0-9_.:-]{1,80}$/
const provider = createOpenAI({
  apiKey: 'localhost-only', // never an external provider credential
  baseURL: UPSTREAM + '/v1',
  fetch: (input, init) => fetch(input, { ...init, redirect: 'error' })
})

export async function listModels(): Promise<string[]> {
  const response = await fetch(UPSTREAM + '/v1/models', {
    cache: 'no-store',
    redirect: 'error',
    signal: AbortSignal.timeout(5000)
  })
  if (!response.ok) throw new Error('Local llama.cpp server unavailable')
  const payload = (await response.json()) as { data?: { id?: unknown }[] }
  if (!Array.isArray(payload.data)) throw new Error('Invalid model list')
  return [
    ...new Set(
      payload.data.flatMap((m) =>
        m && typeof m.id === 'string' && SAFE_MODEL_ID.test(m.id) ? [m.id] : []
      )
    )
  ].slice(0, 100)
}

export async function getModel(requested?: string): Promise<LocalModelConfig> {
  const models = await listModels()
  const id = requested ?? models[0]
  if (!id || !SAFE_MODEL_ID.test(id) || !models.includes(id)) {
    throw new Error('Unknown local model ID')
  }
  return { mode: 'local', modelId: id, model: provider.chat(id) }
}
