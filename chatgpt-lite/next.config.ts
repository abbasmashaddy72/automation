import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  logging: { browserToTerminal: false },
  reactCompiler: true,
  output: 'standalone',
  serverExternalPackages: ['@napi-rs/canvas', 'pdf-parse', 'pdfjs-dist'],
  experimental: {
    optimizePackageImports: ['lucide-react', 'radix-ui']
  }
}

export default nextConfig
