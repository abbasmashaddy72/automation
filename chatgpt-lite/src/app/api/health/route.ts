export async function GET(): Promise<Response> {
  return Response.json({ status: true, app: 'chatgpt-lite-local' })
}
