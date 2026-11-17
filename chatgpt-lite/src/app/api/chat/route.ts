import { readFile } from 'node:fs/promises'
import type { NextRequest } from 'next/server'
import { MAX_IMAGE_SIZE, SUPPORTED_API_IMAGE_TYPES } from '@/lib/chat-attachment-shared'
import { isDataUrl, normalizeMediaType, parseBase64DataUrl } from '@/lib/chat-message-part-utils'
import { AppError } from '@/lib/errors'
import {
  compactHistory,
  FALLBACK_MODEL_CONTEXT,
  standaloneGreeting,
  type BudgetMessage
} from '@/lib/model-context-budget'
import { asksForLatestLaravel, getVerifiedLaravelAnswer } from '@/lib/verified-web'
import { getModel } from '@/services/ai-provider'
import { isJsonObject } from '@/types/json'
import {
  APICallError,
  convertToModelMessages,
  createUIMessageStream,
  createUIMessageStreamResponse,
  smoothStream,
  streamText,
  type UIMessage
} from 'ai'

import { chatRequestSchema, type ChatRequest } from './schema'

// 4 * ceil(10 MiB / 3) = 13,981,016. Base64 expands bytes by ~4/3 and rounds up to 4-char blocks.
const MAX_IMAGE_BASE64_LENGTH = 4 * Math.ceil(MAX_IMAGE_SIZE / 3)

// Expand each data-document part into regular text/file parts before calling
// convertToModelMessages, so one document can contribute multiple parts.
const GENERIC_STREAM_ERROR_MESSAGE = 'Something went wrong. Please try again.'
const GENERIC_INTERNAL_ERROR_MESSAGE = 'Something went wrong'

type MessageLike = { role: 'user' | 'assistant' | 'system'; parts: unknown[] }
function normalizeMessageParts(messages: MessageLike[]): MessageLike[] {
  return messages.map((msg) => {
    if (msg.role !== 'user') return msg

    let changed = false
    const normalizedParts: unknown[] = []

    for (const part of msg.parts) {
      if (!isJsonObject(part)) {
        normalizedParts.push(part)
        continue
      }

      // Convert data: URL file parts to inline base64 so the AI SDK does not
      // attempt to download them (its downloadAssets step rejects data: URLs).
      if (part.type === 'file' && typeof part.url === 'string') {
        if (!isDataUrl(part.url)) {
          changed = true
          normalizedParts.push({ type: 'text', text: '[Remote attachment omitted]' })
          continue
        }

        const parsed = parseBase64DataUrl(part.url)
        if (!parsed || !parsed.base64) {
          changed = true
          continue
        }

        const mediaTypeFromPart = normalizeMediaType(part.mediaType)
        const mediaTypeFromDataUrl = normalizeMediaType(parsed.mimeType)
        const mediaType = mediaTypeFromPart || mediaTypeFromDataUrl

        if (!mediaType || !SUPPORTED_API_IMAGE_TYPES.has(mediaType)) {
          changed = true
          normalizedParts.push({ type: 'text', text: '[Unsupported image format]' })
          continue
        }

        if (parsed.base64.length > MAX_IMAGE_BASE64_LENGTH) {
          changed = true
          normalizedParts.push({ type: 'text', text: '[Image too large]' })
          continue
        }

        // Qwen3.5 2B/4B GGUF deployment is text-only; do not send image parts.
        changed = true
        normalizedParts.push({
          type: 'text',
          text: '[Image attached but this local model cannot interpret images]'
        })
        continue
      }

      if (part.type !== 'data-document' || !isJsonObject(part.data)) {
        normalizedParts.push(part)
        continue
      }

      changed = true
      const data = part.data
      const name = typeof data.name === 'string' ? data.name : 'Unknown'
      const content = typeof data.content === 'string' ? data.content : ''

      normalizedParts.push({ type: 'text', text: `[Document: ${name}]\n\n${content}` })

      if (Array.isArray(data.images) && data.images.length > 0) {
        normalizedParts.push({
          type: 'text',
          text: `\n\n[This document contains ${data.images.length} image(s)]`
        })

        for (const img of data.images) {
          if (!isJsonObject(img) || typeof img.dataUrl !== 'string') continue

          const parsed = parseBase64DataUrl(img.dataUrl)
          if (!parsed) {
            normalizedParts.push({ type: 'text', text: '[Unsupported image source]' })
            continue
          }

          const mimeType = normalizeMediaType(parsed.mimeType)
          if (!mimeType || !SUPPORTED_API_IMAGE_TYPES.has(mimeType)) {
            const label = mimeType
              ? `[Unsupported image format: ${mimeType}]`
              : '[Unsupported image format]'
            normalizedParts.push({ type: 'text', text: label })
          } else if (parsed.base64.length > MAX_IMAGE_BASE64_LENGTH) {
            normalizedParts.push({ type: 'text', text: '[Image too large]' })
          } else {
            normalizedParts.push({
              type: 'text',
              text: '[PDF image omitted: text-only local model]'
            })
          }
        }
      }
    }

    return changed ? { ...msg, parts: normalizedParts } : msg
  })
}

function getPublicStreamErrorMessage(error: unknown): string {
  if (APICallError.isInstance(error)) {
    switch (error.statusCode) {
      case 401:
      case 403:
        return 'Model provider authentication failed. Please check your API settings.'
      case 429:
        return 'Rate limit reached. Please try again shortly.'
      case 400:
        return 'The selected model rejected this prompt. Try a new chat or choose a larger context model; saved chat history is unchanged.'
      default:
        if (typeof error.statusCode === 'number' && error.statusCode >= 500) {
          return 'Model provider is temporarily unavailable. Please try again later.'
        }
    }
  }

  if (error instanceof Error && error.name === 'AbortError') {
    return 'Request cancelled.'
  }

  return GENERIC_STREAM_ERROR_MESSAGE
}

// --- Validation ---

async function parseRequest(req: NextRequest): Promise<ChatRequest | Response> {
  let payload: unknown

  try {
    payload = await req.json()
  } catch {
    return new AppError('invalid_json', 'Invalid JSON in request body').toResponse()
  }

  const parsed = chatRequestSchema.safeParse(payload)
  if (!parsed.success) {
    return new AppError('invalid_request', 'Invalid request body').toResponse()
  }

  return parsed.data
}

// Keyless opt-in web lookup. This sends only the *user's question*, not the
// conversation or files, to DuckDuckGo. No scraping is guaranteed: an
// unavailable search service is reported instead of inventing citations.
function stripHtml(text: string): string {
  return text
    .replace(/<[^>]*>/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/\s+/g, ' ')
    .trim()
}
async function optionalWebContext(prompt: string): Promise<string> {
  const query = prompt.replace(/\s+/g, ' ').trim().slice(0, 180)
  if (query.length < 3) return 'Web search requested but question was too short.'
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 5000)
  try {
    const res = await fetch('https://html.duckduckgo.com/html/?q=' + encodeURIComponent(query), {
      signal: controller.signal,
      headers: { 'User-Agent': 'Mozilla/5.0 AI-Server-Lite/1.0', Accept: 'text/html' }
    })
    if (!res.ok) throw new Error('Search provider unavailable')
    const html = (await res.text()).slice(0, 350_000)
    const regex = /<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g
    const results: string[] = []
    for (const m of html.matchAll(regex)) {
      const raw = m[1] || ''
      let link: string
      try {
        const parsed = new URL(raw, 'https://duckduckgo.com')
        link = parsed.searchParams.get('uddg') || parsed.href
      } catch {
        continue
      }
      if (!link.startsWith('https://')) continue
      const title = stripHtml(m[2] || '').slice(0, 200)
      if (title) results.push(title + ' — ' + link.slice(0, 500))
      if (results.length >= 5) break
    }
    if (!results.length) throw new Error('No parseable search results')
    return (
      'Web search excerpts (unverified; use sources for cross-checking):\n' +
      results.join('\n') +
      '\nCite source URLs for current claims and acknowledge uncertain details.'
    )
  } catch {
    return (
      'Web lookup was requested, but current results could not be retrieved. ' +
      'Do not present current information as verified.'
    )
  } finally {
    clearTimeout(timer)
  }
}

// Serve verified release facts directly. A 2B/4B LLM might override even a
// correct injected source, so avoid asking it to restate an exact version.
function verifiedAnswerStream(content: string): Response {
  const stream = createUIMessageStream({
    execute: ({ writer }) => {
      writer.write({ type: 'text-start', id: 'verified-release' })
      writer.write({ type: 'text-delta', id: 'verified-release', delta: content })
      writer.write({ type: 'text-end', id: 'verified-release' })
    }
  })
  return createUIMessageStreamResponse({ stream })
}

// --- Local llama.cpp provider ---
// The upstream never leaves loopback. Models are selected explicitly; llama.cpp
// router (--models-max 1) unloads the other GPU model when required.
/** Managed router configuration is the source of truth after context tuning.
 * Read-only; never expose the config (or any API credentials) to the browser.
 */
async function modelContextSize(model: string): Promise<number> {
  const fallback = FALLBACK_MODEL_CONTEXT[model] ?? 4096
  try {
    const config = JSON.parse(await readFile('/etc/automation-ai/llamacpp.json', 'utf8')) as Record<
      string,
      unknown
    >
    const field =
      config.alias === model
        ? 'context'
        : (
            {
              'qwen3.5-2b': 'context',
              'qwen3.5-4b': 'router_context_4b',
              'deepseek-coder-6.7b': 'router_context_deepseek'
            } as Record<string, string>
          )[model]
    const value = Number(config[field])
    return Number.isInteger(value) && value >= 2048 && value <= 1048576 ? value : fallback
  } catch {
    return fallback
  }
}

export async function POST(req: NextRequest): Promise<Response> {
  const parsed = await parseRequest(req)
  if (parsed instanceof Response) return parsed
  try {
    // Web lookup runs only when explicitly enabled for this request.
    // Only the question is inspected; no chat history or file content is sent.
    const question = (parsed.messages.filter((m) => m.role === 'user').at(-1)?.parts ?? [])
      .map((part) =>
        part.type === 'text' && 'text' in part && typeof part.text === 'string' ? part.text : ''
      )
      .join(' ')
      .slice(0, 350)
    if (parsed.web_search && asksForLatestLaravel(question)) {
      return verifiedAnswerStream(await getVerifiedLaravelAnswer())
    }
    const greeting = standaloneGreeting(question)
    // Do not inject failed/irrelevant web-search text into a simple greeting.
    const prompt =
      parsed.web_search && !greeting
        ? parsed.prompt +
          '\n\n' +
          (await optionalWebContext(
            // Do not send uploaded document text or chat history to web search.
            (parsed.messages.filter((m) => m.role === 'user').at(-1)?.parts ?? [])
              .map((part) =>
                part.type === 'text' && 'text' in part && typeof part.text === 'string'
                  ? part.text
                  : ''
              )
              .join(' ')
              .slice(0, 180)
          ))
        : parsed.prompt
    let selectedModel
    let modelId: string
    try {
      const selected = await getModel(parsed.model)
      selectedModel = selected.model
      modelId = selected.modelId
    } catch {
      return Response.json(
        { error: 'Model is not registered or the local router is unavailable' },
        { status: 503 }
      )
    }
    const context = await modelContextSize(modelId)
    const latestQuestion = question.trim()
    const isGreeting = standaloneGreeting(latestQuestion)
    const maxOutput = isGreeting ? 128 : context <= 4096 ? 512 : 1024
    let selected
    try {
      // DeepSeek-Coder is a code-specialized checkpoint. A brief greeting
      // should not be interpreted as a request to complete arbitrary source.
      const systemText =
        modelId === 'deepseek-coder-6.7b' && isGreeting
          ? prompt +
            '\nThe user is greeting you. Reply briefly and naturally in words. Do not output code or invent other conversation turns.'
          : prompt
      const normalized = normalizeMessageParts([
        { role: 'system', parts: [{ type: 'text', text: systemText }] },
        ...(parsed.messages as MessageLike[])
      ])
      selected = compactHistory(normalized as BudgetMessage[], context, maxOutput)
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Prompt does not fit the selected model'
      return Response.json({ error: message }, { status: 413 })
    }
    const modelMessages = await convertToModelMessages(
      selected.messages as Array<Omit<UIMessage, 'id'>>
    )
    const result = streamText({
      model: selectedModel,
      messages: modelMessages,
      abortSignal: req.signal,
      maxOutputTokens: maxOutput,
      ...(modelId === 'deepseek-coder-6.7b' ? { temperature: 0.1, topP: 0.9 } : {}),
      // DeepSeek-Coder 6.7B Instruct terminates on <|EOT|>.
      // Also stop if an incompatible legacy ChatML turn marker is emitted.
      // Scope these stops to DeepSeek: Qwen uses a different chat template.
      ...(modelId === 'deepseek-coder-6.7b'
        ? {
            stopSequences: ['<|EOT|>', '<|im_end|>', '<|im_start|>user', '### Instruction:']
          }
        : {}),
      experimental_transform: smoothStream({ chunking: 'word' })
    })
    const stream = createUIMessageStream({
      execute: async ({ writer }) => {
        for await (const part of result.toUIMessageStream({
          sendSources: false,
          sendReasoning: true,
          onError: getPublicStreamErrorMessage
        }))
          writer.write(part)
      },
      onError: (err) => getPublicStreamErrorMessage(err)
    })
    return createUIMessageStreamResponse({ stream })
  } catch (err) {
    if (process.env.AUTOMATION_CHAT_DEBUG === '1') {
      console.error('[Local Chat] Request failed', {
        kind: err instanceof Error ? err.name : 'unknown'
      })
    }
    return new AppError('internal_error', GENERIC_INTERNAL_ERROR_MESSAGE).toResponse()
  }
}
