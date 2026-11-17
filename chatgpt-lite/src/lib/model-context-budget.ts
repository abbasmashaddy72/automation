/** Defensive, model-aware chat history compaction before llama.cpp inference.
 * Estimates are intentionally conservative, not a replacement for tokenizer verification.
 */
import { splitReasoningText } from './local-reasoning'

export type BudgetMessage = { role: 'system' | 'user' | 'assistant'; parts: unknown[] }
export const FALLBACK_MODEL_CONTEXT: Record<string, number> = {
  'qwen3.5-2b': 81920,
  'qwen3.5-4b': 32768,
  'deepseek-coder-6.7b': 4096
}

export function standaloneGreeting(text: string): boolean {
  return /^(?:(?:hi|hey|hello|hi there|hey there|good morning|good afternoon|good evening|thanks|thank you)[.!?\s]*)$/i.test(
    text.trim()
  )
}

export function answerOnlyParts(message: BudgetMessage): BudgetMessage {
  if (message.role !== 'assistant') return message
  const parts: unknown[] = []
  for (const part of message.parts) {
    if (!part || typeof part !== 'object' || !('type' in part)) continue
    const item = part as { type?: unknown; text?: unknown }
    if (item.type === 'text' && typeof item.text === 'string') {
      const visible = splitReasoningText(item.text).answer
      if (visible) parts.push({ type: 'text', text: visible })
    }
    // Deliberately exclude structured reasoning and prior assistant tool traces.
  }
  return { role: 'assistant', parts }
}

function cost(message: BudgetMessage): number {
  const text = JSON.stringify(message.parts)
  // Code, punctuation and non-ASCII scripts often tokenize more densely than prose.
  // A 1.7 char/token allowance plus message-format overhead is conservative.
  return text.length + 96
}

export function compactHistory(
  messages: BudgetMessage[],
  contextTokens: number,
  outputTokens: number
): { messages: BudgetMessage[]; dropped: number; promptChars: number; greeting: boolean } {
  if (messages.length < 2 || messages[0]?.role !== 'system') {
    throw new Error('Missing chat system instruction or latest user message')
  }
  const recent = messages[messages.length - 1]
  if (recent?.role !== 'user') throw new Error('Latest chat message must be from the user')
  const configuredContext = Number.isFinite(contextTokens) ? Math.floor(contextTokens) : 4096
  const available = Math.max(0, configuredContext - outputTokens - 384)
  const budgetChars = Math.max(700, Math.floor(available * 1.7))
  const system = messages[0]
  const newestText = recent.parts
    .filter(
      (part): part is { type: 'text'; text: string } =>
        !!part &&
        typeof part === 'object' &&
        'type' in part &&
        part.type === 'text' &&
        'text' in part &&
        typeof part.text === 'string'
    )
    .map((p) => p.text)
    .join(' ')
  const greeting =
    standaloneGreeting(newestText) &&
    recent.parts.every((p) => !!p && typeof p === 'object' && 'type' in p && p.type === 'text')
  let remaining = budgetChars - cost(system) - cost(recent)
  if (remaining < 0)
    throw new Error(
      'Latest prompt or attachments exceed this model context. Shorten the input, or select a model with more context.'
    )
  const selected: BudgetMessage[] = [recent]
  if (!greeting) {
    for (let i = messages.length - 2; i >= 1; i--) {
      const item = answerOnlyParts(messages[i])
      if (!item.parts.length) continue
      const itemCost = cost(item)
      if (itemCost > remaining) break
      selected.unshift(item)
      remaining -= itemCost
    }
  }
  const result = [system, ...selected]
  return {
    messages: result,
    dropped: messages.length - result.length,
    promptChars: budgetChars - remaining,
    greeting
  }
}
