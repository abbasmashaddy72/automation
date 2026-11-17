import { chatMessageSchema } from '@/lib/chat-message-contract'
import { z } from 'zod'

// --- Request schema ---

export const chatRequestSchema = z.object({
  prompt: z.string().trim().min(1),
  model: z
    .string()
    .regex(/^[A-Za-z0-9_.:-]{1,80}$/)
    .optional(),
  web_search: z.boolean().default(false),
  messages: z.array(chatMessageSchema)
})

export type ChatRequest = z.infer<typeof chatRequestSchema>
