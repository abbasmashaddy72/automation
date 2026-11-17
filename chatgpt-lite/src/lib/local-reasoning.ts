/** Split explicit llama.cpp <think>/<analysis>/<reasoning> blocks from final content.
 * Handles streamed, unclosed tags without displaying partial thoughts as the answer.
 * Never guesses that ordinary natural-language sentences are secret reasoning.
 */
export function splitReasoningText(input: string): { answer: string; thinking: string } {
  let answer = ''
  const thoughts: string[] = []
  let cursor = 0
  const open = /<(think|analysis|reasoning)>/gi
  while (cursor < input.length) {
    open.lastIndex = cursor
    const match = open.exec(input)
    if (!match) {
      // Do not flash partial opening tags across streaming chunks.
      const rest = input.slice(cursor)
      const partial = rest.match(
        /<(?:t(?:h(?:i(?:n(?:k)?)?)?)?|a(?:n(?:a(?:l(?:y(?:s(?:i(?:s)?)?)?)?)?)?)?|r(?:e(?:a(?:s(?:o(?:n(?:i(?:n(?:g)?)?)?)?)?)?)?)?)?$/i
      )
      if (partial) {
        answer += rest.slice(0, -partial[0].length)
        thoughts.push(partial[0])
      } else answer += rest
      break
    }
    answer += input.slice(cursor, match.index)
    const endTag = new RegExp(`</${match[1]}>`, 'gi')
    endTag.lastIndex = open.lastIndex
    const close = endTag.exec(input)
    if (!close) {
      thoughts.push(input.slice(open.lastIndex))
      break
    }
    thoughts.push(input.slice(open.lastIndex, close.index))
    cursor = endTag.lastIndex
  }
  return { answer: truncateFakeConversation(answer), thinking: thoughts.join('\n\n').trim() }
}

/** One model can emit *new fabricated turns* after an answer.  Keep the
 * authentic text before the first unambiguous ChatML boundary. Do not strip
 * arbitrary role words or fenced code samples documenting a chat protocol.
 * Applied to the display and copy path; original stored message stays intact.
 */
export function truncateFakeConversation(input: string): string {
  const text = input.trim()
  const first = /<\|im_end\|>\s*<\|im_start\|>\s*(?:user|assistant|system)\b/i.exec(text)
  if (first && !isInsideCodeFence(text, first.index)) return text.slice(0, first.index).trim()
  // A partial token can arrive before the second half of a streaming frame.
  // Hide it until the next render instead of flashing a raw protocol marker.
  if (!text.includes('```')) {
    const partial = text.match(/<\|(?:im_(?:end|start)?|EOT)?(?:\|>)?$/i)
    if (partial && partial.index !== undefined && partial.index > 0)
      return text.slice(0, partial.index).trim()
  }
  return text
}

function isInsideCodeFence(text: string, offset: number): boolean {
  const before = text.slice(0, offset)
  return (before.match(/```/g) ?? []).length % 2 === 1
}
