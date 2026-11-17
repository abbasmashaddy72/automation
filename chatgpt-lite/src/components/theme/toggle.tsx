'use client'

import { ButtonWithTooltip } from '@/components/common/button-with-tooltip'
import { Button } from '@/components/ui/button'
import { useHydrated } from '@/hooks/use-hydrated'
import { cn } from '@/lib/utils'
import { Moon, Sun } from 'lucide-react'
import { useTheme } from 'next-themes'

export default function ThemeToggle(): React.JSX.Element | null {
  const { resolvedTheme, setTheme } = useTheme()
  const mounted = useHydrated()

  if (!mounted) {
    return null
  }

  const isDark = resolvedTheme === 'dark'
  const nextTheme = isDark ? 'light' : 'dark'
  const nextThemeLabel = nextTheme === 'dark' ? 'Dark' : 'Light'

  return (
    <ButtonWithTooltip label={`Switch to ${nextThemeLabel} Theme`} placement="bottom">
      <Button
        variant="ghost"
        size="icon"
        onClick={() => setTheme(nextTheme)}
        className="text-foreground hover:bg-accent border-border/70 relative overflow-hidden rounded-lg border transition-colors duration-200"
        aria-label={`Switch to ${nextThemeLabel} Theme`}
      >
        <span className="relative flex size-5 items-center justify-center">
          <Sun
            aria-hidden="true"
            style={{ width: '100%', height: '100%' }}
            className={cn(
              'absolute inset-0 transition-[transform,opacity] duration-150 ease-out motion-reduce:transition-none',
              isDark ? 'scale-100 rotate-0 opacity-100' : 'scale-0 rotate-90 opacity-0'
            )}
          />
          <Moon
            aria-hidden="true"
            style={{ width: '100%', height: '100%' }}
            className={cn(
              'absolute inset-0 transition-[transform,opacity] duration-150 ease-out motion-reduce:transition-none',
              isDark ? 'scale-0 -rotate-90 opacity-0' : 'scale-100 rotate-0 opacity-100'
            )}
          />
        </span>
      </Button>
    </ButtonWithTooltip>
  )
}
