import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { BellRing, Check, ListFilter, ChevronRight, Circle, CircleAlert, Network, Scale, Send, Stethoscope, Wrench, type LucideIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { Canvas, HIDDEN_KINDS } from "@/components/canvas"
import { Eyebrow, PageHeader, UnderlineTabs } from "@/components/page"
import { ActionCard, RemediationCard } from "@/components/proposals"
import { KIND_COLOR, RefChip, RefList } from "@/components/ref-chip"
import { Loading, Problem, Skeleton, SkeletonLines, Spinner } from "@/components/status"
import { Button } from "@/components/ui/button"
import { get, type Finding, type Hypothesis, type IncidentState, type Step, type Task } from "@/lib/api"
import { cn, when } from "@/lib/utils"
import { usePost, useWorkspace } from "@/lib/workspace"

type Tab = "investigation" | "map" | "fixes" | "messages"

const STAGES: Record<string, { title: string; icon: LucideIcon; agents: string[] }> = {
  triage: { title: "Triage", icon: ListFilter, agents: ["triage"] },
  technical: { title: "Root cause", icon: Stethoscope, agents: ["investigator", "technical"] },
  impact: { title: "Who it reaches", icon: Network, agents: ["impact"] },
  context: { title: "Why it was built this way", icon: Scale, agents: ["context"] },
  remediate: { title: "Ways out", icon: Wrench, agents: ["fixer", "remediate"] },
  notify: { title: "Who needs to hear", icon: Send, agents: ["scribe", "notify"] },
}
const SCORE_FACTORS = ["proximity", "recency", "risk", "prior_incident"]
const REACH_KINDS = ["Service", "Customer", "Contract", "Commitment", "Requirement", "Decision"]

export function IncidentRoom() {
  const { tenant, investigation, incidentsLoaded } = useWorkspace()
  const room = useQuery({
    queryKey: [tenant, "investigation", investigation],
    queryFn: () => get<IncidentState>(`/${tenant}/investigations/${investigation}`),
    enabled: investigation !== null,
    refetchInterval: (query) => (query.state.data?.investigation.status === "running" ? 700 : 5000),
  })
  if (investigation === null && !incidentsLoaded) return <RoomSkeleton />
  if (investigation === null) {
    return (
      <div className="mx-auto max-w-xl px-10 py-24">
        <PageHeader eyebrow="Incident room" title="Nothing is on fire" subtitle="An investigation opens when an alert reaches the webhook. In the demo company, open the Simulator to break something and watch one from alert to proposed fix." />
        <Link to="/app/guide" className="mt-4 inline-block text-sm font-medium underline underline-offset-4">
          New here? Read the two-minute guide
        </Link>
      </div>
    )
  }
  if (room.isError) return <Problem error={room.error} retry={() => void room.refetch()} className="m-10" />
  if (!room.data) return <RoomSkeleton />
  return <Room key={investigation} state={room.data} />
}

function RoomSkeleton() {
  return (
    <Loading label="Loading the incident" className="grid min-h-full grid-cols-[minmax(0,1fr)_20rem]">
      <div className="space-y-8 px-10 py-8">
        <div className="space-y-3">
          <Skeleton className="h-3 w-72" />
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-4 w-56" />
        </div>
        <Skeleton className="h-9 w-96" />
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="grid grid-cols-[27px_1fr] gap-4">
            <Skeleton className="size-[27px] rounded-full" />
            <div className="space-y-2.5 pt-1">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3.5 w-full" />
              <Skeleton className="h-3.5 w-4/5" />
            </div>
          </div>
        ))}
      </div>
      <aside className="space-y-4 border-l bg-card/60 px-5 py-8">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </aside>
    </Loading>
  )
}

function Working({ children }: { children: string }) {
  return (
    <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
      <Spinner className="size-3.5 text-brand" />
      {children}
    </p>
  )
}

function Room({ state }: { state: IncidentState }) {
  const [tab, setTab] = useState<Tab>("investigation")
  const { investigation, incident, hypotheses, remediations, canvas } = state
  const reverts = state.actions.filter((action) => action.kind === "revert_pr")
  const actions = state.actions.filter((action) => action.kind !== "revert_pr")
  const root = investigation.root_id ? `${investigation.root_kind}:${investigation.root_id}` : null
  const running = investigation.status === "running"
  return (
    <div className={cn("grid min-h-full", tab === "map" ? "grid-cols-1" : "grid-cols-[minmax(0,1fr)_20rem]")}>
      <div className="space-y-7 px-10 py-8">
        <PageHeader
          eyebrow={
            <>
              <span className={cn("size-2 rounded-full", incident.status === "resolved" ? "bg-emerald-600" : "animate-pulse bg-brand")} />
              {`${incident.id} · ${incident.status} · alert on ${investigation.service} · ${when(incident.started_at)}`}
            </>
          }
          title={incident.title}
          subtitle={running ? `Agents are working. ${investigation.steps} graph queries so far.` : `Investigated in ${investigation.steps} graph queries.`}
        />
        <NeedsYou state={state} root={root} open={setTab} />
        <UnderlineTabs
          value={tab}
          onChange={setTab}
          tabs={[
            { id: "investigation", label: "Investigation" },
            { id: "map", label: "Incident graph", count: canvas.nodes.length },
            { id: "fixes", label: "Fixes", count: remediations.length + reverts.length },
            { id: "messages", label: "Messages", count: actions.length },
          ]}
        />
        {tab === "investigation" && <Thread state={state} />}
        {tab === "map" && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              The whole incident as one graph, read left to right from the likely cause. The orange lines are the routes from the cause to the customers it hits and what they were promised. Point at anything to see what it is, how the incident gets there and what is reached through it.
            </p>
            <Legend kinds={[...new Set(canvas.nodes.map((node) => node.kind))].filter((kind) => !HIDDEN_KINDS.includes(kind))} />
            <div className="overflow-hidden rounded-2xl border bg-muted/40">
              <Canvas canvas={canvas} centre={root ?? `Service:${investigation.service}`} onProposal={(kind) => setTab(kind === "Fix" ? "fixes" : "messages")} />
            </div>
          </div>
        )}
        {tab === "fixes" && (
          <div className="space-y-4">
            {remediations.map((remediation) => (
              <RemediationCard key={`${remediation.id}:${remediation.status}`} remediation={remediation} />
            ))}
            {reverts.map((revert) => (
              <ActionCard key={`${revert.id}:${revert.status}`} action={revert} />
            ))}
            {remediations.length + reverts.length === 0 && running && <Working>Agents are still working. A rollback and a fix appear here once the cause is found.</Working>}
            {remediations.length + reverts.length === 0 && !running && <p className="text-sm text-muted-foreground">No code change is proposed for {incident.id}.</p>}
          </div>
        )}
        {tab === "messages" && (
          <div className="space-y-4">
            {actions.map((action) => (
              <ActionCard key={`${action.id}:${action.status}`} action={action} />
            ))}
            {actions.length === 0 && running && <Working>Agents are still working. Drafted messages appear here once the impact is known.</Working>}
            {actions.length === 0 && !running && <p className="text-sm text-muted-foreground">No messages were drafted for {incident.id}.</p>}
          </div>
        )}
      </div>
      <aside className={cn("space-y-7 border-l bg-card/60 px-5 py-8", tab === "map" && "hidden")}>
        <section className="space-y-2">
          <Eyebrow>Likely cause</Eyebrow>
          {root ? (
            <>
              <p className="font-heading text-lg leading-snug">{investigation.root_title ?? investigation.root_id}</p>
              <RefChip reference={root} />
              {investigation.playbook && (
                <p className="text-xs text-muted-foreground">
                  Found faster using <RefChip reference={`Playbook:${investigation.playbook}`} />
                </p>
              )}
            </>
          ) : (
            <>{running ? <Working>Still investigating.</Working> : <p className="text-sm text-muted-foreground">Inconclusive: no suspect scored high enough.</p>}</>
          )}
        </section>
        {hypotheses.length > 0 && (
          <section className="space-y-3">
            <Eyebrow>Suspects, ranked</Eyebrow>
            {hypotheses.map((hypothesis) => (
              <Suspect key={hypothesis.id} hypothesis={hypothesis} />
            ))}
          </section>
        )}
        <section className="space-y-2">
          <Eyebrow>What the investigation touched</Eyebrow>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
            {REACH_KINDS.map((kind) => (
              <div key={kind}>
                <dd className="font-heading text-2xl">{canvas.nodes.filter((node) => node.kind === kind).length}</dd>
                <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span className="size-1.5 rounded-full" style={{ background: KIND_COLOR[kind] }} />
                  {`${kind.toLowerCase()}s`}
                </dt>
              </div>
            ))}
          </dl>
        </section>
      </aside>
    </div>
  )
}

function NeedsYou({ state, root, open }: { state: IncidentState; root: string | null; open: (tab: Tab) => void }) {
  const { tenant, user } = useWorkspace()
  const { investigation, remediations, actions } = state
  const confirm = usePost<{ playbook: string; postmortem: string }>((learned) =>
    toast.success(`Learned ${learned.playbook}; ${learned.postmortem} written back as a source.`),
  )
  const drafts = actions.filter((action) => action.status === "proposed" && action.kind !== "revert_pr")
  const reverts = actions.filter((action) => action.status === "proposed" && action.kind === "revert_pr")
  const openFixes = remediations.filter((remediation) => remediation.status === "proposed")
  const awaiting = investigation.status === "awaiting_approval" && root !== null
  const resolve = usePost(() => toast.success("Incident resolved."))
  const closable = state.incident.status === "open" && investigation.status === "confirmed" && openFixes.length === 0
  const count = Number(awaiting) + openFixes.length + reverts.length + Number(drafts.length > 0) + Number(closable)
  if (count === 0) return null
  return (
    <section>
      <p className="flex items-center gap-2 border-b pb-2 text-sm font-medium">
        <Circle className="size-3.5" />
        Needs you
        <span className="text-xs font-normal text-muted-foreground">{count}</span>
      </p>
      {awaiting && (
        <Row title={`Confirm ${investigation.root_id} as the root cause`} detail="Confirming teaches Ripple a playbook and files the postmortem as a source." status="Ready to confirm">
          <Button size="sm" disabled={confirm.isPending} onClick={() => confirm.mutate({ path: `/${tenant}/investigations/${investigation.id}/confirm`, body: { user: user.id } })}>
            {confirm.isPending && <Spinner />}
            {confirm.isPending ? "Confirming…" : "Confirm"}
          </Button>
        </Row>
      )}
      {openFixes.map((remediation) => (
        <Row
          key={remediation.id}
          title={remediation.title}
          detail={remediation.kind === "rollback" ? remediation.warning || remediation.summary : remediation.summary}
          status={remediation.tests_passed && remediation.load_passed ? "Checks pass" : "Checks failing"}
        >
          <Button size="sm" variant="outline" onClick={() => open("fixes")}>
            Review change
          </Button>
        </Row>
      ))}
      {reverts.map((revert) => (
        <Row key={revert.id} title={revert.subject} detail={`Opens a pull request on ${revert.to} that undoes the change.`} status="Draft ready">
          <Button size="sm" variant="outline" onClick={() => open("fixes")}>
            Review change
          </Button>
        </Row>
      ))}
      {closable && (
        <Row title="Mark the incident resolved" detail="No code change is waiting. Close it once the service has recovered." status="Still open">
          <Button size="sm" disabled={resolve.isPending} onClick={() => resolve.mutate({ path: `/${tenant}/investigations/${investigation.id}/resolve`, body: { user: user.id } })}>
            {resolve.isPending && <Spinner />}
            {resolve.isPending ? "Resolving…" : "Resolve"}
          </Button>
        </Row>
      )}
      {drafts.length > 0 && (
        <Row title={`${drafts.length} messages drafted`} detail={drafts.map((draft) => draft.to).join(", ")} status="Drafts ready">
          <Button size="sm" variant="outline" onClick={() => open("messages")}>
            Review drafts
          </Button>
        </Row>
      )}
    </section>
  )
}

function Row({ title, detail, status, children }: { title: string; detail: string; status: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-4 border-b py-3">
      <Circle className="size-4 shrink-0 text-brand" />
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{title}</p>
        <p className="truncate text-xs text-muted-foreground">{detail}</p>
      </div>
      <span className="shrink-0 text-xs text-brand">{status}</span>
      {children}
    </div>
  )
}

function Legend({ kinds }: { kinds: string[] }) {
  return (
    <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {kinds.map((kind) => (
        <span key={kind} className="flex items-center gap-1.5">
          <span className="h-3 w-1 rounded-sm" style={{ background: KIND_COLOR[kind] ?? "#7b766b" }} />
          {kind}
        </span>
      ))}
    </p>
  )
}

interface Stage {
  kind: string
  tasks: Task[]
  findings: Finding[]
  steps: Step[]
}

function stages(state: IncidentState): Stage[] {
  const kinds = [...new Set(state.tasks.map((task) => task.kind))]
  const owner = (agent: string) => kinds.find((kind) => (STAGES[kind]?.agents ?? [kind]).includes(agent)) ?? kinds[0]
  return kinds.map((kind) => ({
    kind,
    tasks: state.tasks.filter((task) => task.kind === kind),
    findings: state.findings.filter((finding) => owner(finding.agent) === kind),
    steps: state.steps.filter((step) => owner(step.agent) === kind),
  }))
}

function Thread({ state }: { state: IncidentState }) {
  return (
    <ol className="relative space-y-7 before:absolute before:top-2 before:bottom-2 before:left-[13px] before:w-px before:bg-border">
      <StageItem icon={BellRing} title="Alert fired" state="done">
        <p className="text-sm text-muted-foreground">{`${state.investigation.symptom} on ${state.investigation.service}. ${state.incident.title}.`}</p>
      </StageItem>
      {stages(state).map((stage) => {
        const working = stage.tasks.some((task) => task.status === "claimed")
        const done = stage.tasks.every((task) => task.status === "done")
        const failed = stage.tasks.some((task) => task.status === "failed")
        const meta = STAGES[stage.kind]
        return (
          <StageItem key={stage.kind} icon={meta?.icon ?? Circle} title={meta?.title ?? stage.kind} state={failed ? "failed" : done ? "done" : working ? "working" : "waiting"}>
            {[...new Set(stage.tasks.map((task) => task.summary).filter(Boolean))].map((summary) => (
              <p key={summary} className="text-sm text-muted-foreground">
                {summary}
              </p>
            ))}
            {stage.findings.map((finding) => (
              <div key={finding.id} className="space-y-1.5">
                <p className="leading-relaxed">{finding.claim}</p>
                <RefList refs={finding.refs} />
              </div>
            ))}
            {working && stage.findings.length === 0 && <SkeletonLines label={`${meta?.title ?? stage.kind} is working`} count={2} className="max-w-md" />}
            {stage.steps.length > 0 && <Queries steps={stage.steps} />}
          </StageItem>
        )
      })}
    </ol>
  )
}

function StageItem({ icon: Icon, title, state, children }: { icon: LucideIcon; title: string; state: "done" | "working" | "waiting" | "failed"; children: React.ReactNode }) {
  return (
    <li className={cn("relative grid grid-cols-[27px_1fr] gap-4", state === "waiting" && "opacity-50")}>
      <span className={cn("z-10 grid size-[27px] place-items-center rounded-full border bg-background", state === "working" && "border-brand text-brand", state === "failed" && "border-destructive text-destructive")}>
        {state === "working" ? <Spinner className="size-3.5" /> : state === "failed" ? <CircleAlert className="size-3.5" /> : <Icon className="size-3.5" />}
      </span>
      <div className="min-w-0 space-y-3">
        <h3 className="flex items-center gap-2 pt-0.5 font-heading text-base leading-tight">
          {title}
          {state === "done" && <Check className="size-3.5 text-emerald-700" />}
          {state === "working" && <span className="font-sans text-xs font-normal text-brand">working</span>}
          {state === "waiting" && <span className="font-sans text-xs font-normal text-muted-foreground">queued</span>}
          {state === "failed" && <span className="font-sans text-xs font-normal text-destructive">failed</span>}
        </h3>
        {children}
      </div>
    </li>
  )
}

function Queries({ steps }: { steps: Step[] }) {
  return (
    <details className="group text-xs text-muted-foreground">
      <summary className="flex cursor-pointer list-none items-center gap-1 hover:text-foreground">
        <ChevronRight className="size-3 transition-transform group-open:rotate-90" />
        {`${steps.length} graph queries`}
      </summary>
      <ul className="mt-2 space-y-1 border-l pl-3">
        {steps.map((step) => (
          <li key={step.id} className="flex items-baseline gap-2">
            <span className="text-foreground">{step.tool.replaceAll("_", " ")}</span>
            <span className="truncate">{Object.values(step.params).map(String).join(", ")}</span>
            <span className="ml-auto shrink-0">{`${step.rows} rows`}</span>
          </li>
        ))}
      </ul>
    </details>
  )
}

function Suspect({ hypothesis }: { hypothesis: Hypothesis }) {
  const leading = hypothesis.status === "leading"
  return (
    <article className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <RefChip reference={hypothesis.subject} className={cn(leading && "border-brand")} />
        <span className={cn("text-sm font-medium tabular-nums", leading ? "text-brand" : "text-muted-foreground")}>{hypothesis.score.toFixed(2)}</span>
      </div>
      <div className="grid grid-cols-[5.5rem_1fr] items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
        {SCORE_FACTORS.filter((factor) => factor in hypothesis.factors).map((factor) => (
          <div key={factor} className="contents">
            <span>{factor.replace("_", " ")}</span>
            <span className="h-1 rounded bg-muted">
              <span className={cn("block h-1 rounded", leading ? "bg-brand" : "bg-ring")} style={{ width: `${hypothesis.factors[factor] * 100}%` }} />
            </span>
          </div>
        ))}
      </div>
      {hypothesis.factors.deployed === 0 && <p className="text-xs text-muted-foreground">Not deployed when the alert fired, so ruled out.</p>}
    </article>
  )
}
