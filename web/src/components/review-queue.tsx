import { Button } from "@/components/ui/button"
import { RefChip } from "@/components/ref-chip"
import { Spinner } from "@/components/status"
import type { ReviewPair } from "@/lib/api"
import { when } from "@/lib/utils"
import { usePost, useWorkspace } from "@/lib/workspace"

function Side({ label, reference, text, quote, at, record }: { label: string; reference: string; text: string; quote: string | null; at: string | null; record: string | null }) {
  const { openRecord } = useWorkspace()
  return (
    <div className="min-w-0 space-y-2 rounded-xl bg-muted p-3">
      <p className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">{label}</span>
        {at && <span>{when(at)}</span>}
      </p>
      <p className="text-sm">{text}</p>
      {quote && quote !== text && <blockquote className="border-l-2 border-brand pl-2 text-sm text-muted-foreground">{quote}</blockquote>}
      <p className="flex flex-wrap items-center gap-1.5">
        <RefChip reference={reference} />
        {record && (
          <button type="button" className="text-xs text-muted-foreground underline-offset-2 hover:underline" onClick={() => openRecord(record)}>
            Where it was written
          </button>
        )}
      </p>
    </div>
  )
}

export function ReviewQueue({ pairs }: { pairs: ReviewPair[] }) {
  const { tenant, user } = useWorkspace()
  const settle = usePost()
  return (
    <div className="space-y-3">
      {pairs.map((pair) => {
        const busy = settle.isPending && (settle.variables.body as { newer: string }).newer === pair.newer
        const decide = (replace: boolean) => settle.mutate({ path: `/${tenant}/review`, body: { newer: pair.newer, older: pair.older, replace, user: user.id } })
        return (
          <div key={`${pair.newer}|${pair.older}`} className="space-y-3 rounded-2xl border bg-card p-4">
            <p className="text-sm">
              {pair.kind === "Commitment" ? `Two promises${pair.customer_name ? ` to ${pair.customer_name}` : ""} look like they disagree.` : "A newer decision looks like it changes an older one."}
              <span className="text-muted-foreground"> Both stay in force until you choose.</span>
            </p>
            {pair.found_by === "rule" && <p className="text-sm text-muted-foreground">{`Found by a rule, not a language model. ${pair.reason}`}</p>}
            <div className="grid gap-3 md:grid-cols-2">
              <Side label="Older" reference={`${pair.kind}:${pair.older}`} text={pair.older_text} quote={pair.older_quote} at={pair.older_at} record={pair.older_record} />
              <Side label="Newer" reference={`${pair.kind}:${pair.newer}`} text={pair.newer_text} quote={pair.newer_quote} at={pair.newer_at} record={pair.newer_record} />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" className="rounded-full" disabled={settle.isPending} onClick={() => decide(true)}>
                {busy && <Spinner />}
                The newer one replaces the older
              </Button>
              <Button size="sm" variant="outline" className="rounded-full" disabled={settle.isPending} onClick={() => decide(false)}>
                Both stand
              </Button>
            </div>
          </div>
        )
      })}
    </div>
  )
}
