import type { Metadata, Viewport } from 'next'
import Script from 'next/script'
import { SkipToContentLink } from '@/components/accessibility/skip-to-content-link'
import { THEME_STYLE_ELEMENT_ID } from '@/lib/themes/constants'
import { getThemePresetCss } from '@/lib/themes/theme-preset'
import { THEME_PRESET_STYLE_SCRIPT } from '@/lib/themes/theme-preset-style-script'
import { ThemeProvider } from '@/providers/themes-provider'

import './globals.css'

export const metadata: Metadata = {
  title: {
    default: 'AI Server · Lite',
    template: `%s - Local AI Lite`
  },
  description: 'Local, private llama.cpp coding assistant',
  icons: {
    icon: '/favicon.ico',
    shortcut: '/favicon-16x16.png',
    apple: '/apple-touch-icon.png'
  }
}

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: 'oklch(0.993 0.003 80)' },
    { media: '(prefers-color-scheme: dark)', color: 'oklch(0.1 0.005 285)' }
  ]
}

const DEFAULT_THEME_PRESET_CSS = getThemePresetCss()

type RootLayoutProps = {
  children: React.ReactNode
}

export default function RootLayout({ children }: RootLayoutProps): React.JSX.Element {
  return (
    <html lang="en" suppressHydrationWarning className="h-full">
      <head>
        <style
          id={THEME_STYLE_ELEMENT_ID}
          suppressHydrationWarning
          dangerouslySetInnerHTML={{ __html: DEFAULT_THEME_PRESET_CSS }}
        />
      </head>
      <body className="h-dvh overflow-hidden text-sm antialiased">
        <SkipToContentLink />
        <Script id="theme-preset-style" strategy="beforeInteractive">
          {THEME_PRESET_STYLE_SCRIPT}
        </Script>
        <ThemeProvider>
          <main
            id="main-content"
            className="bg-background text-foreground flex h-full flex-1 flex-col overflow-hidden"
          >
            {children}
          </main>
        </ThemeProvider>
      </body>
    </html>
  )
}
