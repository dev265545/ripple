import { useQuery } from "@tanstack/react-query"

import { Problem, SkeletonLines } from "@/components/status"
import { Fragment } from "react"

import { Eyebrow } from "@/components/page"
import { RefChip } from "@/components/ref-chip"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { get, type RecordTrace } from "@/lib/api"
import { when } from "@/lib/utils"
import { useWorkspace } from "@/lib/workspace"

export function RecordTraceDrawer({ record, onClose }: { record: string | null; onClose: () => void }) {
  const { tenant } = useWorkspace()
  const trace = useQuery({
    queryKey: [tenant, "record", record],
    queryFn: () => get<RecordTrace>(`/${tenant}/records/${record}`),
    enabled: record !== null,
  })
  return (
    <Sheet open={record !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="gap-0 overflow-y-auto data-[side=right]:w-[40rem] data-[side=right]:sm:max-w-none">
        <SheetHeader>
          <SheetDescription>{trace.data ? `Source record · ${trace.data.source}` : "Source record"}</SheetDescription>
          <SheetTitle className="font-mono text-sm break-all">{trace.data?.uri ?? record}</SheetTitle>
        </SheetHeader>
        {trace.isError && <Problem error={trace.error} retry={() => void trace.refetch()} className="mx-4" />}
        {trace.isPending && record && <SkeletonLines label="Loading the record" count={10} className="px-4" />}
        {trace.data && <TraceBody trace={trace.data} />}
      </SheetContent>
    </Sheet>
  )
}

function highlighted(text: string, quotes: string[]) {
  const found = quotes.filter((quote) => text.includes(quote)).sort((a, b) => text.indexOf(a) - text.indexOf(b))
  const pieces: { text: string; quoted: boolean }[] = []
  let cursor = 0
  for (const quote of found) {
    const start = text.indexOf(quote, cursor)
    if (start < 0) continue
    pieces.push({ text: text.slice(cursor, start), quoted: false }, { text: quote, quoted: true })
    cursor = start + quote.length
  }
  pieces.push({ text: text.slice(cursor), quoted: false })
  return pieces
}

function TraceBody({ trace }: { trace: RecordTrace }) {
  const quotes = [...new Set([...trace.nodes, ...trace.edges].flatMap((item) => (item.quote ? [item.quote] : [])))]
  return (
    <div className="space-y-6 px-4 pb-8 text-sm">
      <p className="font-mono text-[11px] text-muted-foreground">{`sha1 ${trace.hash.slice(0, 12)} · read ${when(trace.fetched_at)}`}</p>
      {trace.text && (
        <section className="space-y-2">
          <Eyebrow>{quotes.length > 0 ? "The record, with the passages facts were taken from" : "The record"}</Eyebrow>
          <pre className="max-h-80 overflow-auto rounded-md border bg-card p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
            {highlighted(trace.text, quotes).map((piece, index) =>
              piece.quoted ? (
                <mark key={index} className="rounded-sm bg-brand/20 px-0.5 text-foreground">
                  {piece.text}
                </mark>
              ) : (
                <Fragment key={index}>{piece.text}</Fragment>
              ),
            )}
          </pre>
        </section>
      )}
      <section className="space-y-2">
        <Eyebrow>{`What it put in the graph · ${trace.nodes.length}`}</Eyebrow>
        {trace.nodes.map((node) => (
          <div key={`${node.kind}:${node.id}`} className="space-y-1 border-b pb-2">
            <div className="flex items-center gap-2">
              <RefChip reference={`${node.kind}:${node.id}`} label={node.name} />
              {node.inferred && <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">extracted</span>}
            </div>
            {node.quote && <blockquote className="border-l-2 border-brand pl-2 text-muted-foreground">{node.quote}</blockquote>}
          </div>
        ))}
      </section>
      <section className="space-y-2">
        <Eyebrow>{`Relationships it stated · ${trace.edges.length}`}</Eyebrow>
        {trace.edges.map((edge) => (
          <div key={`${edge.source}:${edge.relation}:${edge.target}`} className="space-y-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <RefChip reference={edge.source} />
              <span className="font-mono text-[11px] text-muted-foreground">{`${edge.relation} →`}</span>
              <RefChip reference={edge.target} />
            </div>
            {edge.quote && <blockquote className="border-l-2 border-brand pl-2 text-muted-foreground">{edge.quote}</blockquote>}
          </div>
        ))}
      </section>
    </div>
  )
}
