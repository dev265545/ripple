import { useEffect, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

import { cn } from "@/lib/utils"

const TICK_MS = 16
const TICKS = 80
const PROSE =
  "space-y-3 text-[15px] leading-relaxed [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:border-brand [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[13px] [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:text-base [&_h2]:font-semibold [&_h3]:font-semibold [&_li]:pl-1 [&_li::marker]:text-muted-foreground [&_ol]:list-decimal [&_ol]:space-y-1.5 [&_ol]:pl-5 [&_strong]:font-semibold [&_table]:w-full [&_table]:text-left [&_table]:text-sm [&_td]:border-t [&_td]:px-2 [&_td]:py-1.5 [&_th]:px-2 [&_th]:py-1.5 [&_th]:font-medium [&_th]:text-muted-foreground [&_ul]:list-disc [&_ul]:space-y-1.5 [&_ul]:pl-5"

/** Markdown that types itself out once, the way a streamed answer arrives. */
export function Markdown({ text, typed = false, onDone, className }: { text: string; typed?: boolean; onDone?: () => void; className?: string }) {
  const still = !typed || window.matchMedia("(prefers-reduced-motion: reduce)").matches
  const [shown, setShown] = useState(still ? text.length : 0)
  const done = shown >= text.length
  useEffect(() => {
    if (done) return onDone?.()
    const timer = setTimeout(() => setShown((count) => count + Math.max(2, Math.ceil(text.length / TICKS))), TICK_MS)
    return () => clearTimeout(timer)
  }, [shown, done])
  return (
    <div className={cn(PROSE, className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{done ? text : text.slice(0, shown)}</ReactMarkdown>
    </div>
  )
}
