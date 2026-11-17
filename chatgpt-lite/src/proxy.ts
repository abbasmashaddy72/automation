import { NextResponse, type NextRequest } from 'next/server'

export function proxy(request: NextRequest) {
  const host = request.headers.get('host') ?? ''
  const origin = request.headers.get('origin')
  const localHost = /^(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?$/.test(host)
  if (
    !localHost ||
    (origin && origin !== 'http://' + host) ||
    request.headers.get('sec-fetch-site') === 'cross-site'
  ) {
    return new NextResponse('ChatGPT Lite is available only to local clients.', { status: 403 })
  }
  return NextResponse.next()
}

export const config = { matcher: ['/((?!_next/static|_next/image).*)'] }
