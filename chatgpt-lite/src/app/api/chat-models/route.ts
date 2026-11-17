import { listModels } from '@/services/ai-provider'

export async function GET(): Promise<Response> {
  try {
    const models = (await listModels()).map((id) => ({ id, label: id }))
    return Response.json({ models })
  } catch {
    return Response.json({ error: 'Local llama.cpp model discovery failed' }, { status: 503 })
  }
}
