import { memo, useCallback, useDeferredValue, useId, useMemo, type ReactNode } from 'react'
import { CopyStatusAnnouncement } from '@/components/accessibility/copy-status-announcement'
import {
  InlineCitationBadge,
  SourcesList,
  SourcesToggle,
  useSourcesExpanded
} from '@/components/chat/message-sources-view'
import { renderUserParts } from '@/components/chat/message-user-parts'
import { AppIconButton } from '@/components/common/app-button'
import { ButtonWithTooltip } from '@/components/common/button-with-tooltip'
import { Markdown } from '@/components/markdown/markdown'
import { Skeleton } from '@/components/ui/skeleton'
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard'
import { useInViewport } from '@/hooks/use-in-viewport'
import { getTextFromParts, type ChatStreamPhase } from '@/lib/chat-utils'
import { splitReasoningText } from '@/lib/local-reasoning'
import type { ChatMessage, ChatMessageSource } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Check, ChevronDown, Clock3, Copy, Loader2, Search } from 'lucide-react'

import { getSourcesFromParts, stripTrailingSourceMarkdownLinks } from './message-sources'

interface MessageProps {
  message: ChatMessage
  isThinking?: boolean
  streamPhase?: ChatStreamPhase
}

type SourceUrlMap = Map<string, { index: number; source: ChatMessageSource }>

function istTime(value: unknown): string | null {
  if (typeof value !== 'string' && !(value instanceof Date)) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return (
    new Intl.DateTimeFormat('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: true
    }).format(date) + ' IST'
  )
}

function MessageTiming({ message }: { message: ChatMessage }): React.JSX.Element | null {
  const timing =
    message.role === 'assistant' && message.metadata && typeof message.metadata === 'object'
      ? message.metadata.liteTiming
      : undefined
  const value =
    timing && typeof timing === 'object' && !Array.isArray(timing)
      ? (timing as Record<string, unknown>)
      : null
  const sent = istTime(value?.sentAt)
  const first = istTime(value?.firstTokenAt)
  const finished = istTime(value?.completedAt)
  const total =
    value && typeof value.totalMs === 'number' && Number.isFinite(value.totalMs)
      ? (value.totalMs / 1000).toFixed(2)
      : null
  if (!value) {
    const date = istTime(message.createdAt)
    return date ? (
      <div className="text-muted-foreground mt-1 text-[11px]" title="Local time, Asia/Kolkata">
        {message.role === 'user' ? 'Sent' : 'Received'}: {date}
      </div>
    ) : null
  }
  return (
    <div
      className="text-muted-foreground mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]"
      aria-label="Message response timing in IST"
    >
      <Clock3 aria-hidden="true" className="size-3" />
      {sent && <span>Sent: {sent}</span>}
      {first && <span>First visible response: {first}</span>}
      {finished && <span>Received: {finished}</span>}
      {total && <span>Total: {total}s</span>}
    </div>
  )
}

function HiddenReasoning({ text }: { text: string }): React.JSX.Element | null {
  if (!text.trim()) return null
  return (
    <details className="border-border/60 mt-2 w-full max-w-full rounded-lg border p-2 text-sm">
      <summary className="text-muted-foreground flex cursor-pointer items-center gap-2 font-medium">
        <ChevronDown aria-hidden="true" className="size-3.5" />
        Show thinking (hidden by default)
      </summary>
      <div className="text-muted-foreground mt-2 max-h-80 overflow-y-auto text-xs break-words whitespace-pre-wrap">
        {text}
      </div>
    </details>
  )
}

function StreamStatusIndicator({
  icon,
  label
}: {
  icon: ReactNode
  label: string
}): React.JSX.Element {
  return (
    <span
      className="text-muted-foreground inline-flex items-center gap-2 text-sm leading-relaxed"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {icon}
      <span className="sr-only">{label}</span>
    </span>
  )
}

function StreamingCursor(): React.JSX.Element {
  const [cursorRef, isInView] = useInViewport<HTMLDivElement>()

  return (
    <div
      ref={cursorRef}
      aria-hidden="true"
      className="pointer-events-none absolute right-3 bottom-3"
    >
      <Skeleton
        className={cn(
          'bg-card-foreground/50 h-4 w-1 rounded-full',
          isInView ? 'motion-reduce:animate-none' : 'animate-none'
        )}
      />
    </div>
  )
}

function UserMessage({ message }: MessageProps): React.JSX.Element {
  return (
    <div className="flex w-full justify-end">
      <div className="flex max-w-[92%] min-w-0 flex-col items-end md:max-w-[88%]">
        <div className="bg-secondary text-secondary-foreground max-w-full rounded-2xl rounded-br-md px-4 py-3 break-words">
          <div className="text-base leading-relaxed whitespace-pre-wrap">
            {renderUserParts(message.parts)}
          </div>
        </div>
        <MessageTiming message={message} />
      </div>
    </div>
  )
}

interface AssistantMessageBodyProps {
  isThinking?: boolean
  phase?: ChatStreamPhase
  hasRenderedText: boolean
  markdownSource: string
  showCursor: boolean
  sourceUrlMap: SourceUrlMap
  renderLinkAnnotation: (href: string) => ReactNode | null
}

function AssistantMessageBody({
  isThinking,
  phase,
  hasRenderedText,
  markdownSource,
  showCursor,
  sourceUrlMap,
  renderLinkAnnotation
}: AssistantMessageBodyProps): React.JSX.Element {
  const showWaitingState = isThinking && !hasRenderedText
  const showToolCallIndicator = showWaitingState && phase === 'tool-calling'
  const showThinkingIndicator = showWaitingState && !showToolCallIndicator
  let bodyContent: ReactNode

  if (showThinkingIndicator) {
    bodyContent = (
      <StreamStatusIndicator
        icon={<Loader2 className="size-3.5 animate-spin" aria-hidden="true" />}
        label="Thinking"
      />
    )
  } else if (showToolCallIndicator) {
    bodyContent = (
      <StreamStatusIndicator
        icon={<Search className="size-3.5" aria-hidden="true" />}
        label="Using tools"
      />
    )
  } else {
    bodyContent = (
      <Markdown renderLinkAnnotation={sourceUrlMap.size > 0 ? renderLinkAnnotation : undefined}>
        {markdownSource}
      </Markdown>
    )
  }

  return (
    <div className="text-foreground relative max-w-full break-words">
      <div className="text-base leading-relaxed">{bodyContent}</div>
      {showCursor && <StreamingCursor />}
    </div>
  )
}

interface AssistantMessageActionsProps {
  hasCopyText: boolean
  copied: boolean
  onCopy: () => void
  sources: ChatMessageSource[]
  sourcesExpanded: boolean
  onToggleSources: () => void
  sourceListId: string
}

function AssistantMessageActions({
  hasCopyText,
  copied,
  onCopy,
  sources,
  sourcesExpanded,
  onToggleSources,
  sourceListId
}: AssistantMessageActionsProps): React.JSX.Element | null {
  if (!hasCopyText && sources.length === 0) {
    return null
  }

  return (
    <>
      <div className="mt-1 flex w-full max-w-full items-center">
        {hasCopyText && (
          <>
            <ButtonWithTooltip label={copied ? 'Copied' : 'Copy'}>
              <AppIconButton
                variant="ghost"
                size="icon-sm"
                touch={false}
                mutedDisabled={false}
                className={cn(
                  'text-muted-foreground size-11 transition-colors duration-200 md:size-7',
                  copied ? 'text-accent-foreground' : 'hover:text-foreground'
                )}
                disabled={copied}
                onClick={onCopy}
                aria-label={copied ? 'Message copied to clipboard' : 'Copy to clipboard'}
              >
                {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
              </AppIconButton>
            </ButtonWithTooltip>
            <CopyStatusAnnouncement copied={copied} message="Message copied to clipboard." />
          </>
        )}
        <SourcesToggle
          sources={sources}
          expanded={sourcesExpanded}
          onToggle={onToggleSources}
          sourceListId={sourceListId}
        />
      </div>
      <SourcesList sources={sources} expanded={sourcesExpanded} sourceListId={sourceListId} />
    </>
  )
}

function AssistantMessage({ message, isThinking, streamPhase }: MessageProps): React.JSX.Element {
  const parts = message.parts
  const sources = useMemo(() => getSourcesFromParts(parts), [parts])
  const { copy, copied } = useCopyToClipboard()
  const { expanded: sourcesExpanded, toggle: toggleSources } = useSourcesExpanded()
  const sourceListId = useId()

  const fullText = useMemo(() => getTextFromParts(parts), [parts])
  const deferredText = useDeferredValue(fullText)
  const separated = useMemo(() => splitReasoningText(deferredText), [deferredText])
  const structuredThinking = useMemo(
    () =>
      parts
        .filter((p) => p.type === 'reasoning')
        .map((p) => (p.type === 'reasoning' ? p.text : ''))
        .filter(Boolean)
        .join('\n\n'),
    [parts]
  )
  const thinkingText = [structuredThinking, separated.thinking].filter(Boolean).join('\n\n')
  const markdownSource = useMemo(() => {
    return sources.length > 0
      ? stripTrailingSourceMarkdownLinks(separated.answer, sources)
      : separated.answer
  }, [separated.answer, sources])
  const sourceUrlMap = useMemo<SourceUrlMap>(() => {
    const urlMap: SourceUrlMap = new Map()

    for (let index = 0; index < sources.length; index += 1) {
      const source = sources[index]

      if (source.type === 'url') {
        urlMap.set(source.url, { index, source })
      }
    }

    return urlMap
  }, [sources])
  const renderLinkAnnotation = useCallback(
    function renderLinkAnnotation(href: string): ReactNode | null {
      const match = sourceUrlMap.get(href)

      if (!match) {
        return null
      }

      return <InlineCitationBadge index={match.index} source={match.source} />
    },
    [sourceUrlMap]
  )

  const hasCopyText = separated.answer.trim().length > 0
  const hasRenderedText = separated.answer.trim().length > 0
  const phase = isThinking ? (streamPhase ?? 'thinking') : undefined
  const showCursor = Boolean(isThinking && phase === 'streaming' && hasRenderedText)

  const handleCopy = useCallback(() => {
    void copy(separated.answer)
  }, [copy, separated.answer])

  return (
    <div className="flex w-full justify-start">
      <div className="flex w-full max-w-full min-w-0 flex-col items-start">
        <AssistantMessageBody
          isThinking={isThinking}
          phase={phase}
          hasRenderedText={hasRenderedText}
          markdownSource={markdownSource}
          showCursor={showCursor}
          sourceUrlMap={sourceUrlMap}
          renderLinkAnnotation={renderLinkAnnotation}
        />
        <HiddenReasoning text={thinkingText} />
        <AssistantMessageActions
          hasCopyText={hasCopyText}
          copied={copied}
          onCopy={handleCopy}
          sources={sources}
          sourcesExpanded={sourcesExpanded}
          onToggleSources={toggleSources}
          sourceListId={sourceListId}
        />
        <MessageTiming message={message} />
      </div>
    </div>
  )
}

function MessageComponent({ message, isThinking, streamPhase }: MessageProps): React.JSX.Element {
  if (message.role === 'user') {
    return <UserMessage message={message} />
  }

  return <AssistantMessage message={message} isThinking={isThinking} streamPhase={streamPhase} />
}

export const Message = memo(MessageComponent)
Message.displayName = 'Message'
