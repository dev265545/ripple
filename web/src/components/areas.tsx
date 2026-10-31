import { useQuery } from "@tanstack/react-query"

import { Eyebrow } from "@/components/page"
import { RefChip } from "@/components/ref-chip"
import { Problem, SkeletonRows, Spinner } from "@/components/status"
import { Button } from "@/components/ui/button"
import { get, type Area } from "@/lib/api"
import { useModel, usePost, useWorkspace } from "@/lib/workspace"

export function Areas() {
  const { tenant } = useWorkspace()
  const model = useModel()
  const areas = useQuery({ queryKey: [tenant, "areas"], queryFn: () => get<Area[]>(`/${tenant}/areas`) })
  const write = usePost()
  if (areas.isError) return <Problem error={areas.error} retry={() => void areas.refetch()} />
  if (!areas.data) return <SkeletonRows label="Clustering the graph" count={3} />
  const unwritten = areas.data.filter((area) => !area.written_by).length
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <Eyebrow>{`Areas · ${areas.data.length}`}</Eyebrow>
          <p className="max-w-2xl text-sm text-muted-foreground">
            FalkorDB's label propagation groups things that are more connected to each other than to the rest. Mail and chats that only some people can read are left out. Ask Ripple uses these for questions about the company as a whole.
          </p>
        </div>
        {model && unwritten > 0 && (
          <Button size="sm" variant="outline" className="rounded-full" disabled={write.isPending} onClick={() => write.mutate({ path: `/${tenant}/areas` })}>
            {write.isPending && <Spinner />}
            {`Write ${unwritten === 1 ? "the summary" : `${unwritten} summaries`} with ${model}`}
          </Button>
        )}
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        {areas.data.map((area) => (
          <article key={area.id} className="space-y-3 rounded-2xl border bg-card p-4 text-sm">
            <div>
              <h3 className="flex items-baseline justify-between gap-3 text-base font-medium">
                {area.title}
                <span className="shrink-0 text-xs font-normal text-muted-foreground tabular-nums">{`${area.size} things`}</span>
              </h3>
              <p className="mt-1 leading-relaxed">{area.summary}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {area.written_by ? `Written by ${area.written_by} from the relationships inside this area. A summary, not a quote.` : "Counted from the graph. No model wrote this."}
              </p>
            </div>
            {area.findings.length > 0 && (
              <ul className="space-y-2">
                {area.findings.map((finding) => (
                  <li key={finding.text} className="space-y-1 rounded-xl bg-muted p-3">
                    <p>{finding.text}</p>
                    <p className="flex flex-wrap gap-1">
                      {finding.refs.map((ref) => (
                        <RefChip key={ref} reference={ref} />
                      ))}
                    </p>
                  </li>
                ))}
              </ul>
            )}
            {area.open_incidents.length > 0 && (
              <p className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="text-brand">Open incidents here</span>
                {area.open_incidents.map((incident) => (
                  <RefChip key={incident} reference={`Incident:${incident}`} />
                ))}
              </p>
            )}
            <p className="flex flex-wrap items-center gap-1">
              <span className="mr-1 text-xs text-muted-foreground">Most connected</span>
              {area.members.map((ref) => (
                <RefChip key={ref} reference={ref} />
              ))}
            </p>
          </article>
        ))}
      </div>
      {areas.data.length === 0 && <p className="text-sm text-muted-foreground">Nothing to cluster yet. Sync a source on the Connect page.</p>}
    </section>
  )
}
