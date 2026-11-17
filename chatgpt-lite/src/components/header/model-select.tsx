'use client'

import { useCallback, useEffect, useState } from 'react'

type Model = { id: string; label: string }

export function ModelSelect(): React.JSX.Element {
  const [models, setModels] = useState<Model[]>([])
  const [webSearch, setWebSearch] = useState(false)
  const [model, setModel] = useState('')
  const [status, setStatus] = useState<'checking' | 'connected' | 'offline'>('checking')
  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await fetch('/api/chat-models', {
        signal,
        credentials: 'same-origin',
        cache: 'no-store'
      })
      if (!res.ok) throw new Error('Model discovery failed')
      const data: { models?: Model[] } = await res.json()
      if (!Array.isArray(data.models) || !data.models.length)
        throw new Error('No registered models')
      const permitted = data.models.filter(
        (m) =>
          typeof m.id === 'string' &&
          /^[A-Za-z0-9_.:-]{1,80}$/.test(m.id) &&
          typeof m.label === 'string'
      )
      if (!permitted.length) throw new Error('No valid models')
      setModels(permitted)
      setModel((current) => {
        const next = permitted.some((m) => m.id === current) ? current : permitted[0].id
        try {
          localStorage.setItem('ai-lite-model', next)
        } catch {}
        return next
      })
      setStatus('connected')
    } catch {
      if (!signal?.aborted) setStatus('offline')
    }
  }, [])
  useEffect(() => {
    const ctrl = new AbortController()
    queueMicrotask(() => {
      if (ctrl.signal.aborted) return
      try {
        setModel(localStorage.getItem('ai-lite-model') || '')
        setWebSearch(localStorage.getItem('ai-lite-web-search') === 'on')
      } catch {}
      void refresh(ctrl.signal)
    })
    return () => ctrl.abort()
  }, [refresh])
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        aria-pressed={webSearch}
        title="When enabled, general search queries are sent to DuckDuckGo. Latest Laravel releases are checked against official docs when enabled. Do not include secrets."
        onClick={() => {
          const enabled = !webSearch
          setWebSearch(enabled)
          try {
            localStorage.setItem('ai-lite-web-search', enabled ? 'on' : 'off')
          } catch {}
        }}
        className="border-border bg-background text-foreground rounded-md border px-2 py-1.5 text-xs"
      >
        Web {webSearch ? 'On' : 'Off'}
      </button>
      <label className="text-muted-foreground flex min-w-0 items-center gap-2 text-xs">
        <span className="hidden sm:inline">Model</span>
        <select
          aria-label="Local model"
          value={model}
          disabled={!models.length}
          onFocus={() => void refresh()}
          onChange={(e) => {
            const next = e.target.value
            if (!models.some((m) => m.id === next)) return
            setModel(next)
            try {
              localStorage.setItem('ai-lite-model', next)
            } catch {}
          }}
          className="border-border bg-background text-foreground max-w-60 rounded-md border px-2 py-1.5"
        >
          {!models.length && <option value="">No local model</option>}
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        aria-label="Refresh local models"
        title="Refresh installed router models"
        onClick={() => void refresh()}
        className="border-border rounded-md border px-2 py-1.5 text-xs"
      >
        Refresh
      </button>
      <span role="status" className="text-muted-foreground text-xs">
        {status === 'connected'
          ? 'Connected'
          : status === 'checking'
            ? 'Checking…'
            : 'Server unavailable'}
      </span>
    </div>
  )
}
