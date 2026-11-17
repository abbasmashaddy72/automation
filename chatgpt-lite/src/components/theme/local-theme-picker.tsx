'use client'

import { useHydrated } from '@/hooks/use-hydrated'
import { getThemePreset, SELECTABLE_THEME_IDS } from '@/lib/themes/theme-preset'
import { selectSetThemePreset, selectThemePreset, useAppStore } from '@/store/app-store'

/** No search, random theme picker or hidden light/dark preview mode. */
export default function LocalThemePicker(): React.JSX.Element {
  const mounted = useHydrated()
  const selected = useAppStore(selectThemePreset)
  const setSelected = useAppStore(selectSetThemePreset)
  return (
    <label className="text-muted-foreground flex items-center gap-2 text-xs" htmlFor="local-theme">
      <span className="hidden lg:inline">Theme</span>
      <select
        id="local-theme"
        aria-label="Choose color theme"
        value={mounted ? selected : 'modern-minimal'}
        onChange={(event) => setSelected(event.target.value)}
        className="border-border/70 bg-background text-foreground w-32 rounded-lg border px-2 py-2 sm:w-40"
      >
        {SELECTABLE_THEME_IDS.map((id) => (
          <option key={id} value={id}>
            {getThemePreset(id).label || id}
          </option>
        ))}
      </select>
    </label>
  )
}
