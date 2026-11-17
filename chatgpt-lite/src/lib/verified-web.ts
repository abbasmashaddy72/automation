/** Release facts retrieved from canonical publisher docs, not invented by the local LLM. */
export const LARAVEL_RELEASES_URL = 'https://laravel.com/docs/releases'

export type LaravelRelease = {
  major: number
  released: string | null
  source: string
}

export function asksForLatestLaravel(question: string): boolean {
  return (
    /\blaravel\b/i.test(question) &&
    /\b(latest|current|newest|most\s+recent|up\s+to\s+date)\b/i.test(question)
  )
}

function plainText(html: string): string {
  return html
    .replace(/<(script|style|noscript)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, ' ')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&(?:nbsp|#160);/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&(?:ndash|mdash|#8211|#8212);/gi, '-')
    .replace(/&#(?:39|x27);/gi, "'")
    .replace(/&quot;/gi, '"')
    .replace(/\s+/g, ' ')
    .trim()
}

/** Parse the *release table*, not random version numbers in code examples. */
export function parseLaravelReleaseNotes(
  html: string,
  url: string = LARAVEL_RELEASES_URL
): LaravelRelease | null {
  if (!/^https:\/\/laravel\.com\//i.test(url)) return null
  if (html.length > 2_500_000 || html.length < 50) return null
  const rows: Array<{ major: number; released: string | null }> = []
  for (const match of html.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
    const cells = [...match[1].matchAll(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi)].map((item) =>
      plainText(item[1])
    )
    if (cells.length < 4 || !/^\d{1,2}$/.test(cells[0])) continue
    const major = Number(cells[0])
    if (major < 1 || major > 99 || !/\b(?:PHP|\d\.\d)\b/i.test(cells[1])) continue
    const released = cells[2] || null
    if (!released || !/\b(?:19|20)\d{2}\b/.test(released)) continue
    rows.push({ major, released })
  }
  // Some versions of laravel.com render the table through a page template.
  // The redirect target and matching release heading must then corroborate it.
  if (!rows.length) {
    const target = new URL(url).pathname.match(/^\/docs\/(\d{1,2})\.x\/releases\/?$/)
    if (!target) return null
    const major = Number(target[1])
    const text = plainText(html)
    if (!/Release Notes/i.test(text) || !new RegExp(`\\bLaravel ${major}\\b`, 'i').test(text))
      return null
    const release = text.match(
      new RegExp(
        `\\b${major}\\s+(?:\\d+\\.\\d+\\s*[-–]\\s*\\d+\\.\\d+\\s+)?([A-Za-z]+\\s+\\d{1,2}(?:st|nd|rd|th)?,?\\s+20\\d{2})`,
        'i'
      )
    )
    return { major, released: release?.[1] ?? null, source: url }
  }
  const latest = rows.reduce((max, item) => (item.major > max.major ? item : max))
  return { ...latest, source: url }
}

/** Never silently fall back to a guessed framework version. */
export async function getVerifiedLaravelAnswer(
  fetcher: typeof fetch = fetch,
  now: () => Date = () => new Date()
): Promise<string> {
  const abort = new AbortController()
  const timeout = setTimeout(() => abort.abort(), 7_000)
  try {
    const response = await fetcher(LARAVEL_RELEASES_URL, {
      signal: abort.signal,
      cache: 'no-store',
      redirect: 'follow',
      headers: { Accept: 'text/html', 'User-Agent': 'AI-Server-Lite-Release-Check/1.0' }
    })
    if (!response.ok || !/^https:\/\/laravel\.com\//i.test(response.url)) {
      throw new Error('Official source not accessible')
    }
    const type = response.headers.get('content-type') ?? ''
    if (!type.toLowerCase().includes('text/html')) throw new Error('Not a release-notes page')
    const html = (await response.text()).slice(0, 2_500_000)
    const result = parseLaravelReleaseNotes(html, response.url)
    if (!result) throw new Error('Cannot validate official release table')
    const date = now().toISOString().slice(0, 10)
    return (
      `**Verified from Laravel’s official documentation (${date}):** The latest major release is **Laravel ${result.major}**.\n\n` +
      (result.released ? `- **Official release date:** ${result.released}\n` : '') +
      `- **Official source:** ${result.source}\n\n` +
      `This answer comes from a live official release-notes lookup, not from the local model’s training data. ` +
      `For the newest patch release within Laravel ${result.major}, consult the official changelog.`
    )
  } catch {
    return (
      `**Unable to verify the latest Laravel version right now.** ` +
      `The official release notes could not be retrieved and validated, so I won't guess. ` +
      `Please check ${LARAVEL_RELEASES_URL}.`
    )
  } finally {
    clearTimeout(timeout)
  }
}
