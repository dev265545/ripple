import { useQuery } from "@tanstack/react-query"
import { ChevronRight } from "lucide-react"

import { NeedsAttention } from "@/components/needs-attention"
import { Eyebrow, PageHeader } from "@/components/page"
import { RefChip } from "@/components/ref-chip"
import { ReviewQueue } from "@/components/review-queue"
import { Loading, Problem, Skeleton } from "@/components/status"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { get, type CheckFinding, type Memory, type ReviewPair } from "@/lib/api"
import { useWorkspace } from "@/lib/workspace"

export function MemoryPanel() {
  const { tenant } = useWorkspace()
  const memory = useQuery({ queryKey: [tenant, "memory"], queryFn: () => get<Memory>(`/${tenant}/memory`) })
  const review = useQuery({ queryKey: [tenant, "review"], queryFn: () => get<ReviewPair[]>(`/${tenant}/review`) })
  const checks = useQuery({ queryKey: [tenant, "checks"], queryFn: () => get<CheckFinding[]>(`/${tenant}/checks`) })
  const header = <PageHeader eyebrow="What Ripple has learned" title="Memory" subtitle="Playbooks and facts are kept only after a human confirms a root cause. Notes are written as mail, chat and files are read." />
  if (!memory.data) {
    return (
      <div className="mx-auto max-w-4xl space-y-8 px-10 py-8">
        {header}
        {memory.isError ? (
          <Problem error={memory.error} retry={() => void memory.refetch()} />
        ) : (
          <Loading label="Loading memory" className="space-y-3">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-28 w-full rounded-xl" />
            <Skeleton className="h-28 w-full rounded-xl" />
            <Skeleton className="h-16 w-full rounded-xl" />
          </Loading>
        )}
      </div>
    )
  }
  const { playbooks, facts, notes } = memory.data
  return (
    <div className="mx-auto max-w-4xl space-y-8 px-10 py-8">
      {header}
      {review.data && review.data.length > 0 && (
        <section className="space-y-3">
          <Eyebrow>Waiting for a human</Eyebrow>
          <ReviewQueue pairs={review.data} />
        </section>
      )}
      {checks.data && checks.data.length > 0 && (
        <section className="space-y-3">
          <Eyebrow>Found by rules, without a model</Eyebrow>
          <NeedsAttention findings={checks.data} />
        </section>
      )}
      <section className="space-y-3">
        <Eyebrow>Playbooks</Eyebrow>
        {playbooks.map((playbook) => (
          <Card key={playbook.id} size="sm">
            <CardHeader>
              <CardTitle>{`${playbook.symptom} on ${playbook.service}`}</CardTitle>
              <CardDescription>{`${playbook.id} · reused ${playbook.wins + playbook.losses} times, right ${playbook.wins}`}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              <p className="flex flex-wrap items-center gap-1.5">
                <span className="text-muted-foreground">Checks, in order</span>
                {playbook.tools.map((tool, index) => (
                  <span key={tool} className="flex items-center gap-1.5">
                    {index > 0 && <ChevronRight className="size-3 text-muted-foreground" />}
                    <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs">{tool.replaceAll("_", " ")}</span>
                  </span>
                ))}
              </p>
              {playbook.risk.length > 0 && <p className="text-muted-foreground">{`Look first at changes flagged: ${playbook.risk.join(", ")}`}</p>}
            </CardContent>
          </Card>
        ))}
        {playbooks.length === 0 && <p className="text-sm text-muted-foreground">Nothing learned yet. Confirm a root cause in the incident room.</p>}
      </section>
      <section className="space-y-3">
        <Eyebrow>Facts</Eyebrow>
        {facts.map((fact) => (
          <div key={fact.id} className="rounded-2xl border bg-card px-4 py-3 text-sm">
            <p>{fact.text}</p>
            <p className="mt-1 text-xs text-muted-foreground">{`${fact.id} · about ${fact.services.join(", ")}`}</p>
          </div>
        ))}
        {facts.length === 0 && <p className="text-sm text-muted-foreground">No facts yet. One is written each time a root cause is confirmed.</p>}
      </section>
      <section className="space-y-3">
        <Eyebrow>Notes from what Ripple read</Eyebrow>
        {notes.map((note) => (
          <div key={note.id} className="space-y-2 rounded-2xl border bg-card px-4 py-3 text-sm">
            <p>{note.text}</p>
            <p className="flex flex-wrap items-center gap-1.5">
              <RefChip reference={note.origin} label={note.origin_name} />
              {note.about.map((ref) => (
                <RefChip key={ref} reference={ref} />
              ))}
            </p>
            <p className="text-xs text-muted-foreground">{`Written by ${note.written_by} from the item above. It is a summary, not a quote.`}</p>
          </div>
        ))}
        {notes.length === 0 && <p className="text-sm text-muted-foreground">No notes yet. Connect Gmail, Google Drive, Slack or WhatsApp on the Connect page with a language model configured.</p>}
      </section>
    </div>
  )
}
