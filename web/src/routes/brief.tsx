import { useQuery } from "@tanstack/react-query"
import type { ReactNode } from "react"

import { Eyebrow, PageHeader } from "@/components/page"
import { RefChip } from "@/components/ref-chip"
import { ReviewQueue } from "@/components/review-queue"
import { Problem, SkeletonRows } from "@/components/status"
import { Button } from "@/components/ui/button"
import { get, type Brief } from "@/lib/api"
import { when } from "@/lib/utils"
import { usePost, useWorkspace } from "@/lib/workspace"

const KEEP_FOR_DAYS = 90
const WHY: Record<string, string> = { unverified: "never verified", expired: "verification ran out", changed: "its source changed after you verified it" }

function Block({ title, empty, children }: { title: string; empty: string | null; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <Eyebrow>{title}</Eyebrow>
      {empty ? <p className="text-sm text-muted-foreground">{empty}</p> : children}
    </section>
  )
}

export function BriefPage() {
  const { tenant, user } = useWorkspace()
  const verify = usePost()
  const brief = useQuery({ queryKey: [tenant, "brief", user.id], queryFn: () => get<Brief>(`/${tenant}/brief/${user.id}`) })
  const header = <PageHeader eyebrow={`For ${user.name}`} title="My brief" subtitle="What the company graph holds about your work right now. Every line is read from a record. The only text a model wrote is marked as a model's note." />
  if (!brief.data) {
    return (
      <div className="mx-auto max-w-4xl space-y-8 px-10 py-8">
        {header}
        {brief.isError ? <Problem error={brief.error} retry={() => void brief.refetch()} /> : <SkeletonRows label="Loading your brief" count={5} />}
      </div>
    )
  }
  const { promises, projects, on_call, only_expert, recent, review, to_check } = brief.data
  return (
    <div className="mx-auto max-w-4xl space-y-8 px-10 py-8">
      {header}
      {review.length > 0 && (
        <Block title="Waiting for a human" empty={null}>
          <ReviewQueue pairs={review} />
        </Block>
      )}
      {to_check.length > 0 && (
        <Block title="Yours to keep current" empty={null}>
          <div className="divide-y rounded-2xl border">
            {to_check.map((item) => (
              <div key={`${item.kind}:${item.id}`} className="flex items-start justify-between gap-4 px-4 py-3 text-sm">
                <div className="min-w-0 space-y-1">
                  <p>{item.name}</p>
                  <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                    <RefChip reference={`${item.kind}:${item.id}`} label="Open" />
                    {WHY[item.state]}
                  </p>
                </div>
                <Button size="sm" variant="outline" className="shrink-0 rounded-full" disabled={verify.isPending} onClick={() => verify.mutate({ path: `/${tenant}/verify`, body: { kind: item.kind, id: item.id, user: user.id, days: KEEP_FOR_DAYS } })}>
                  {`Still right, for ${KEEP_FOR_DAYS} days`}
                </Button>
              </div>
            ))}
          </div>
        </Block>
      )}
      <Block title="Promises you made that are still in force" empty={promises.length === 0 ? "None on record." : null}>
        <div className="divide-y rounded-2xl border">
          {promises.map((promise) => (
            <div key={promise.id} className="space-y-1.5 px-4 py-3 text-sm">
              <p>{promise.text}</p>
              <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                <RefChip reference={`Customer:${promise.customer}`} label={promise.customer_name} />
                <RefChip reference={`Commitment:${promise.id}`} label="Open the promise" />
                <span>{`made ${when(promise.made_at)}${promise.valid_to ? `, ends ${when(promise.valid_to)}` : ", no end date"}`}</span>
              </p>
            </div>
          ))}
        </div>
      </Block>
      <Block title="Projects you lead" empty={projects.length === 0 ? "None on record." : null}>
        <div className="divide-y rounded-2xl border">
          {projects.map((project) => (
            <div key={project.id} className="space-y-1.5 px-4 py-3 text-sm">
              <p className="flex flex-wrap items-center gap-2">
                <RefChip reference={`Project:${project.id}`} label={project.name} />
                <span className="text-xs text-muted-foreground">{`${project.status}${project.due_at ? `, due ${project.due_at}` : ""}`}</span>
              </p>
              <p className="text-muted-foreground">{project.goal}</p>
              {project.open_incidents.length > 0 && (
                <p className="flex flex-wrap items-center gap-1.5 text-xs">
                  <span className="text-brand">Open incidents on its services</span>
                  {project.open_incidents.map((incident) => (
                    <RefChip key={incident} reference={`Incident:${incident}`} />
                  ))}
                </p>
              )}
            </div>
          ))}
        </div>
      </Block>
      <Block title="On call now" empty={on_call.length === 0 ? "You are not on call for anything right now." : null}>
        <p className="flex flex-wrap items-center gap-1.5 text-sm">
          {on_call.map((shift) => (
            <span key={shift.service} className="flex items-center gap-1.5">
              <RefChip reference={`Service:${shift.service}`} />
              <span className="text-xs text-muted-foreground">{`until ${when(shift.until)}`}</span>
            </span>
          ))}
        </p>
      </Block>
      <Block title="Services only you have changed or reviewed" empty={only_expert.length === 0 ? "None. Someone else has worked on everything you have." : null}>
        <p className="flex flex-wrap items-center gap-1.5">
          {only_expert.map((row) => (
            <RefChip key={row.service} reference={`Service:${row.service}`} />
          ))}
        </p>
      </Block>
      <Block title="Latest mail and chats you were part of" empty={recent.length === 0 ? "None read yet. Connect Gmail, Slack or WhatsApp on the Connect page." : null}>
        <div className="divide-y rounded-2xl border">
          {recent.map((item) => (
            <div key={item.id} className="space-y-1 px-4 py-3 text-sm">
              <p className="flex flex-wrap items-center gap-2">
                <RefChip reference={`${item.kind}:${item.id}`} label={item.title} />
                {item.at && <span className="text-xs text-muted-foreground">{when(item.at)}</span>}
              </p>
              {item.note && <p className="text-muted-foreground">{`Model's note: ${item.note}`}</p>}
            </div>
          ))}
        </div>
      </Block>
    </div>
  )
}
