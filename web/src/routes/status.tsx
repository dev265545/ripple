import { useQuery } from "@tanstack/react-query"
import { useParams } from "@tanstack/react-router"

import { Mark } from "@/components/brand"
import { Problem, SkeletonLines } from "@/components/status"
import { get, type PublicStatus } from "@/lib/api"
import { cn, when } from "@/lib/utils"

export function StatusPage() {
  const { tenant } = useParams({ strict: false }) as { tenant: string }
  const status = useQuery({ queryKey: [tenant, "status"], queryFn: () => get<PublicStatus>(`/${tenant}/status`), refetchInterval: 15_000 })
  const updates = status.data?.updates ?? []
  const investigating = updates.some((update) => update.incident_status === "open")
  return (
    <main className="mx-auto max-w-2xl space-y-8 px-5 py-12">
      <header className="flex items-center gap-3">
        <Mark className="size-7" />
        <h1 className="font-heading text-2xl capitalize">{`${tenant} status`}</h1>
      </header>
      {status.isPending && <SkeletonLines label="Loading status" />}
      {status.isError && <Problem error={status.error} retry={() => void status.refetch()} />}
      {status.data && (
        <>
          <p className={cn("flex items-center gap-2.5 rounded-2xl border px-4 py-3.5 font-medium", investigating ? "border-amber-600/30 bg-amber-500/10" : "bg-card")}>
            <span className={cn("size-2.5 rounded-full", investigating ? "animate-pulse bg-amber-600" : "bg-emerald-600")} />
            {investigating ? "We are investigating an incident" : "No current updates"}
          </p>
          <section className="space-y-4">
            <h2 className="text-sm font-medium text-muted-foreground">Updates</h2>
            {updates.length === 0 && <p className="text-sm text-muted-foreground">Nothing has been published yet.</p>}
            {updates.map((update) => (
              <article key={update.at} className="space-y-1.5 rounded-2xl border bg-card p-4">
                <h3 className="font-medium">{update.title}</h3>
                <p className="text-xs text-muted-foreground">{when(update.at)}</p>
                <p className="text-sm whitespace-pre-wrap">{update.body}</p>
                {update.resolved_at && <p className="text-sm font-medium text-emerald-700">{`Resolved ${when(update.resolved_at)}`}</p>}
              </article>
            ))}
          </section>
        </>
      )}
    </main>
  )
}
