import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BadgeCheck, Lock, ArrowUp, ChevronRight, CornerDownRight } from "lucide-react"
import { motion } from "motion/react"
import { useEffect, useRef, useState, type FormEvent } from "react"

import { Mark, Rings } from "@/components/brand"
import { Markdown } from "@/components/markdown"
import { Eyebrow } from "@/components/page"
import { RefChip, RefList } from "@/components/ref-chip"
import { RippleButton } from "@/components/ripple-button"
import { Loading, Skeleton, SkeletonLines, Spinner } from "@/components/status"
import { get, post, type ChatAnswer, type Citation, type QueryStep, type Turn } from "@/lib/api"
import { when } from "@/lib/utils"
import { cn } from "@/lib/utils"
import { useModel, useWorkspace } from "@/lib/workspace"

interface Exchange {
  question: string
  reply?: ChatAnswer
  error?: string
}

export function Chat() {
  const { tenant, user } = useWorkspace()
  const model = useModel()
  const client = useQueryClient()
  const [session] = useState(() => crypto.randomUUID())
  const [thread, setThread] = useState<Exchange[]>([])
  const [draft, setDraft] = useState("")
  const end = useRef<HTMLDivElement>(null)
  const suggestions = useQuery({ queryKey: ["suggestions"], queryFn: () => get<string[]>("/chat/suggestions") })
  const turns = useQuery({ queryKey: [tenant, "turns", user.id], queryFn: () => get<Turn[]>(`/${tenant}/turns?user=${user.id}`) })
  const settle = (question: string, result: Partial<Exchange>) =>
    setThread((current) => current.map((exchange) => (exchange.question === question && !exchange.reply && !exchange.error ? { ...exchange, ...result } : exchange)))
  const ask = useMutation({
    mutationFn: (text: string) => post<ChatAnswer>(`/${tenant}/chat`, { text, user: user.id, session }),
    onSuccess: (reply, question) => {
      settle(question, { reply })
      void client.invalidateQueries({ queryKey: [tenant, "turns"] })
    },
    onError: (error: Error, question) => settle(question, { error: error.message }),
  })
  const earlier = (turns.data ?? []).filter((turn) => turn.role === "user" && turn.session !== session)

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" })
  }, [thread])

  function send(text: string) {
    const question = text.trim()
    if (!question || ask.isPending) return
    setThread((current) => [...current, { question }])
    setDraft("")
    ask.mutate(question)
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    send(draft)
  }

  return (
    <div className="grid h-full grid-cols-[1fr_17rem]">
      <div className="flex min-h-0 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-10 px-10 py-10">
            {thread.length === 0 && <Opening name={user.name.split(" ")[0]} suggestions={suggestions.data} onPick={send} />}
            {thread.map((exchange, index) => (
              <ExchangeView key={index} exchange={exchange} />
            ))}
            <div ref={end} />
          </div>
        </div>
        <form onSubmit={submit} className="mx-auto w-full max-w-3xl px-10 pb-8">
          <div className="flex items-center gap-2 rounded-full border border-input p-1.5 pl-5 shadow-xs focus-within:border-foreground">
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Ask about a service, a customer, a change, a promise…"
              aria-label="Your question"
              className="h-9 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
            <RippleButton type="submit" size="icon" disabled={!draft.trim() || ask.isPending} aria-label="Ask" className="rounded-full">
              {ask.isPending ? <Spinner /> : <ArrowUp />}
            </RippleButton>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            {model
              ? `${model} picks the graph queries your question needs and writes the answer from their rows. If the model is unavailable, the query is chosen by the words in your question.`
              : "Answers come from named graph queries chosen by the words in your question, not from a language model. If nothing matches, Ripple says so."}
          </p>
        </form>
      </div>
      <aside className="min-h-0 space-y-1 overflow-y-auto border-l bg-sidebar px-3 py-8">
        <Eyebrow className="px-2 pb-2">Your earlier questions</Eyebrow>
        {earlier.map((turn) => (
          <button key={`${turn.session}:${turn.seq}`} type="button" onClick={() => send(turn.text)} className="block w-full rounded-lg px-2 py-1.5 text-left text-sm hover:bg-sidebar-accent">
            {turn.text}
            <span className="block text-xs text-muted-foreground">{when(turn.at)}</span>
          </button>
        ))}
        {turns.isPending && <SkeletonLines label="Loading your earlier questions" count={5} className="px-2" />}
        {turns.isError && <p className="px-2 text-xs text-destructive">{turns.error.message}</p>}
        {turns.data && earlier.length === 0 && <p className="px-2 text-xs text-muted-foreground">Nothing yet. Past questions are kept in the graph, linked to what they were about.</p>}
      </aside>
    </div>
  )
}

function Opening({ name, suggestions, onPick }: { name: string; suggestions: string[] | undefined; onPick: (question: string) => void }) {
  return (
    <div className="pt-10">
      <div className="relative size-12 text-foreground/30">
        <Rings count={3} className="-inset-6" />
        <Mark className="relative size-12 rounded-2xl" />
      </div>
      <h1 className="mt-8 font-heading text-3xl">{`What do you need to know, ${name}?`}</h1>
      <p className="mt-2 text-muted-foreground">Every answer shows the records it rests on and the query that produced it.</p>
      {!suggestions && (
        <Loading label="Loading example questions" className="mt-8 grid gap-2 sm:grid-cols-2">
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="h-14 rounded-2xl" />
          ))}
        </Loading>
      )}
      <ul className="mt-8 grid gap-2 sm:grid-cols-2">
        {suggestions?.map((question) => (
          <li key={question}>
            <button type="button" onClick={() => onPick(question)} className="group flex h-full w-full items-start justify-between gap-3 rounded-2xl border p-4 text-left text-[15px] font-medium hover:border-foreground">
              {question}
              <CornerDownRight className="mt-0.5 size-4 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ExchangeView({ exchange: { question, reply, error } }: { exchange: Exchange }) {
  return (
    <motion.article initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
      <h2 className="ml-auto w-fit max-w-[80%] rounded-3xl bg-muted px-4 py-2.5 text-[15px]">{question}</h2>
      {!reply && !error && (
        <p role="status" className="flex items-center gap-3 text-[15px]">
          <span className="relative size-4 text-brand">
            <Rings count={3} className="inset-0" />
          </span>
          <span className="shimmer-text">Reading the graph…</span>
        </p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
      {reply && <Reply reply={reply} />}
    </motion.article>
  )
}

function Reply({ reply }: { reply: ChatAnswer }) {
  const [written, setWritten] = useState(false)
  const steps = reply.steps ?? [reply]
  const rows = steps.reduce((total, step) => total + step.rows.length, 0)
  return (
    <div className="space-y-5">
      {reply.carried && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          Still talking about
          <RefChip reference={reply.carried} />
        </p>
      )}
      <div className="space-y-2">
        <Markdown text={reply.answer} typed onDone={() => setWritten(true)} className={cn(!reply.model && "font-medium")} />
        {written && reply.model && <p className="text-xs text-muted-foreground">{`Written by ${reply.model} from ${rows} rows returned by ${steps.length === 1 ? "one graph query" : `${steps.length} graph queries`}.`}</p>}
        {written && reply.withheld > 0 && (
          <p className="flex items-center gap-2 rounded-xl bg-muted px-3 py-2 text-sm">
            <Lock className="size-4 shrink-0 text-muted-foreground" />
            {reply.withheld === 1 ? "One result was left out: it comes only from mail or chats you are not on." : `${reply.withheld} results were left out: they come only from mail or chats you are not on.`}
          </p>
        )}
        {written && reply.lines.length > 0 && (
          <ul className="space-y-1.5 text-[15px] leading-relaxed">
            {reply.lines.map((line) => (
              <li key={line} className="flex gap-2">
                <span className="mt-2.5 size-1 shrink-0 rounded-full bg-foreground/50" />
                {line}
              </li>
            ))}
          </ul>
        )}
      </div>
      {written && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="space-y-5">
          {reply.citations.length > 0 && <Citations citations={reply.citations} />}
          {reply.refs.length > 0 && (
            <section className="space-y-2">
              <Eyebrow>In this answer</Eyebrow>
              <RefList refs={reply.refs} />
            </section>
          )}
          {reply.tool && steps.map((step, index) => <Working key={index} reply={step} />)}
        </motion.div>
      )}
    </div>
  )
}

function Citations({ citations }: { citations: Citation[] }) {
  const { openRecord } = useWorkspace()
  return (
    <section className="space-y-2">
      <Eyebrow>{`Sources · ${citations.length}`}</Eyebrow>
      <ol className="grid gap-2 sm:grid-cols-2">
        {citations.map((citation, index) => (
          <li key={citation.ref}>
            <button type="button" onClick={() => openRecord(citation.record)} className="h-full w-full rounded-xl border p-3 text-left hover:border-foreground">
              <span className="flex items-baseline gap-2 text-xs text-muted-foreground">
                <span className="grid size-4 place-items-center rounded-full bg-muted text-[10px] font-medium text-foreground">{index + 1}</span>
                <span>{citation.source}</span>
                <span className="ml-auto truncate font-mono text-[10px]">{citation.uri}</span>
              </span>
              <span className="mt-1 block truncate text-sm font-medium">{citation.name}</span>
              {citation.verified_by && <span className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground"><BadgeCheck className="size-3.5" />{`Verified by ${citation.verified_by}`}</span>}
              {citation.quote && <span className="mt-1.5 line-clamp-3 block border-l-2 border-brand pl-2 text-sm text-muted-foreground">{citation.quote}</span>}
            </button>
          </li>
        ))}
      </ol>
    </section>
  )
}

function Working({ reply }: { reply: QueryStep }) {
  const columns = Object.keys(reply.rows[0] ?? {})
  return (
    <details className="group text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ChevronRight className="size-3.5 transition group-open:rotate-90" />
        {`How I got this · ${reply.tool} · ${reply.rows.length} rows`}
      </summary>
      <div className="mt-3 space-y-3">
        <p className="font-mono text-xs text-muted-foreground">{JSON.stringify(reply.params)}</p>
        {reply.cypher && <pre className="overflow-x-auto rounded-md bg-ink p-3 font-mono text-xs leading-relaxed text-background">{reply.cypher.trim()}</pre>}
        {columns.length > 0 && (
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-left font-mono text-[11px]">
              <thead className="bg-muted">
                <tr>
                  {columns.map((column) => (
                    <th key={column} className="px-2 py-1.5 font-medium">{column}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {reply.rows.map((row, index) => (
                  <tr key={index} className="border-t align-top">
                    {columns.map((column) => (
                      <td key={column} className="max-w-64 px-2 py-1.5 break-words">{typeof row[column] === "object" ? JSON.stringify(row[column]) : String(row[column])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </details>
  )
}
