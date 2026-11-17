/** Browser-safe identifiers on HTTPS, LAN HTTP and SSR. */
export function generateId(): string {
  const cryptoApi = globalThis.crypto
  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
    return cryptoApi.randomUUID()
  }
  // randomUUID() is hidden on plain HTTP LAN origins. getRandomValues() is
  // available in these contexts and still provides CSPRNG-derived UUIDv4 IDs.
  if (cryptoApi && typeof cryptoApi.getRandomValues === 'function') {
    const bytes = cryptoApi.getRandomValues(new Uint8Array(16))
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
  }
  // Fail safely rather than creating predictable identifiers for persisted chats.
  throw new Error('Secure randomness unavailable; the browser cannot create a chat ID')
}
