'use client'

import LocalThemePicker from '@/components/theme/local-theme-picker'
import ThemeToggle from '@/components/theme/toggle'
import { SidebarTrigger, useSidebar } from '@/components/ui/sidebar'

import { ModelSelect } from './model-select'

/** Compact and predictable header; avoids extra dropdowns and unused GitHub buttons. */
export function Header(): React.JSX.Element {
  const { open, isMobile } = useSidebar()
  return (
    <header className="bg-background/95 border-border sticky top-0 z-20 w-full border-b backdrop-blur-xl">
      <div className="mx-auto flex min-h-14 max-w-screen-2xl flex-wrap items-center gap-3 px-3 py-2 sm:px-5">
        <div className="flex min-w-0 items-center gap-2 sm:gap-3">
          {(!open || isMobile) && (
            <SidebarTrigger aria-label="Show conversations" className="size-9 rounded-lg" />
          )}
          <div className="flex min-w-0 flex-col">
            <strong className="text-sm leading-tight font-semibold tracking-tight">
              ChatGPT Lite
            </strong>
            <span className="text-muted-foreground hidden text-[11px] sm:block">
              Private workspace · llama.cpp
            </span>
          </div>
        </div>
        <div className="ml-auto flex min-w-0 flex-wrap items-center gap-2 sm:gap-3">
          <ModelSelect />
          <span aria-hidden="true" className="bg-border hidden h-6 w-px lg:block" />
          <LocalThemePicker />
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}
