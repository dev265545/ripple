import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { ArrowLeft, ArrowRight, BellRing, Check, ListFilter, Network, Pause, Play, RotateCcw, Scale, Send, SkipBack, SkipForward, Stethoscope, UserCheck, Wrench, type LucideIcon } from "lucide-react"
import { motion } from "motion/react"
import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"

import { Rings } from "@/components/brand"
import { Canvas } from "@/components/canvas"
import { Hint } from "@/components/hint"
import { PageHeader } from "@/components/page"
import { KIND_COLOR, RefList } from "@/components/ref-chip"
import { RippleButton } from "@/components/ripple-button"
import { Problem, SkeletonRows } from "@/components/status"
import { get, type IncidentState, type InvestigationSummary, type Row, type Scenario, type Step } from "@/lib/api"
import { cn, when } from "@/lib/utils"
import { usePost, useWorkspace } from "@/lib/workspace"

const BEAT_MS = 1700
const SPEEDS = [1, 2, 4]
const REFS_SHOWN = 8

const AGENTS: Record<string, { name: string; asks: string; icon: LucideIcon; does: string }> = {
  alert: { name: "Alert", asks: "Something is failing", icon: BellRing, does: "A monitoring alert arrives. Ripple opens an incident and puts the first task on a board the agents share, stored in the graph." },
  triage: { name: "Triage", asks: "Has this happened before?", icon: ListFilter, does: "Checks memory first: past incidents on the same dependency chain, and the order of checks that worked last time." },
  investigator: { name: "Investigator", asks: "What changed, and which change did it?", icon: Stethoscope, does: "Walks the dependency graph for recent changes and vendor outages, then scores each suspect and shows the score." },
  impact: { name: "Impact", asks: "Who is hit, and what were they promised?", icon: Network, does: "Follows the graph outward from the failing service: features, customers, uptime guarantees, promises made in email." },
  context: { name: "Context", asks: "Why was it built this way?", icon: Scale, does: "Finds the decision behind the change, the rules any fix has to keep, and who knows this code best." },
  fixer: { name: "Fixer", asks: "What are the ways out?", icon: Wrench, does: "Walks the code graph from the bad change, writes a rollback and a fix on their own branches, and runs the repository's tests on both." },
  scribe: { name: "Scribe", asks: "Who needs to hear?", icon: Send, does: "Drafts the page, the status update and each customer notice from the findings above. Drafts only." },
  you: { name: "You", asks: "Approve, edit or reject", icon: UserCheck, does: "A person reads the evidence and decides. Nothing is merged or sent before that." },
}

const TOOL_SAYS: Record<string, (params: Step["params"]) => string> = {
  similar_incidents: ({ service }) => `Looked for past incidents on the same dependency chain as ${service}`,
  recall_playbooks: () => "Checked memory for an investigation order that worked on this symptom before",
  recall_facts: ({ service }) => `Recalled what earlier investigations learned about ${service}`,
  vendor_outages: ({ service }) => `Checked whether an outside vendor behind ${service} was down`,
  blast_radius: ({ service }) => `Traced which services depend on ${service}`,
  customer_events: () => "Checked whether a customer has a sale or launch running right now",
  suspect_changes: ({ service }) => `Pulled every change deployed in the 48 hours before the alert, on ${service} or anything it depends on`,
  change_detail: ({ pr }) => `Read ${pr}: the files it changed, who reviewed it and when it went live`,
  affected_customers: ({ service }) => `Found the customers who use something served by ${service}`,
  sla_exposure: ({ service }) => `Worked out which uptime guarantees ${service} puts at risk, and the credit owed`,
  commitments_at_risk: () => "Looked for promises people made to those customers that are still live",
  decision_trace: ({ pr }) => `Traced why ${pr} was made: the decision behind it and what that decision replaced`,
  governing_decisions: ({ service }) => `Listed the decisions any fix to ${service} has to respect`,
  requirements_at_risk: ({ service }) => `Checked which written requirements ${service} has to meet`,
  expertise: ({ service }) => `Found who knows ${service} best, to review the fix`,
  who_to_page: ({ service }) => `Found who is on call for ${service}`,
  code_impact: ({ pr }) => `Walked the code graph from ${pr}: what it changed, what calls that, and which tests cover it`,
  code_context: () => "Collected the code that runs alongside the change, so the fix is written against the real call path",
  code_history: ({ pr }) => `Looked for earlier changes to the code ${pr} runs through`,
  write_fix: ({ written_by }) => `Wrote the fix on its own branch (${written_by})`,
  run_checks: ({ branch }) => `Ran the repository's own tests and load check on ${branch}`,
}

const short = (id: unknown) => String(id).split(":").at(-1)
const TOOL_DETAIL: Record<string, (rows: Row[]) => string> = {
  code_impact: (rows) => rows.map((row) => `${row.name} in ${short(row.file)} is used in ${[...(row.used_in as string[]), ...(row.tests as string[])].map(short).join(", ") || "nothing else"}.`).join(" "),
  code_context: (rows) => `Read ${rows.map((row) => row.path).join(", ")}.`,
  code_history: (rows) => rows.map((row) => `${row.pr} (${row.title}) changed ${(row.symbols as string[]).map(short).join(", ")}.`).join(" ") || "No earlier change touched that code.",
  write_fix: (rows) => rows.map((row) => `${row.written_by}: ${row.title ? `"${row.title}", ` : ""}${row.outcome}.`).join(" "),
  run_checks: (rows) => rows.map((row) => `${row.check} ${row.passed ? "pass" : "fail"}${row.output ? ` (${row.output})` : ""}.`).join(" "),
}

const MESSAGE_KIND: Record<string, string> = { page: "a page to the on-call engineer", status_page: "a status page update", customer_notice: "a customer notice", issue_comment: "a comment on the GitHub issue" }
const TALLY = [
  { kind: "Customer", label: "customers reached" },
  { kind: "Commitment", label: "promises at risk" },
  { kind: "SLA", label: "uptime guarantees exposed" },
  { kind: "Fix", label: "fixes proposed" },
  { kind: "Message", label: "messages drafted" },
]

interface Beat {
  agent: string
  say: string
  detail: string | null
  refs: string[]
  seq: number
  reveal: string[]
}

/** The recorded investigation as a script: one beat per graph query, finding, proposed fix and drafted message. */
function script({ investigation, incident, steps, findings, remediations, actions, tasks }: IncidentState): Beat[] {
  const beats: Beat[] = [{ agent: "alert", say: `${investigation.symptom} fires on ${investigation.service}: ${incident.title}.`, detail: `Alert received ${when(incident.started_at)}. Ripple opens ${incident.id} and puts the first task on the board.`, refs: [], seq: 0, reveal: [`Service:${investigation.service}`] }]
  const ordered = [...steps].sort((a, b) => a.seq - b.seq)
  const lastOf = new Map(ordered.map((step) => [step.agent, step.seq]))
  const unfixed = tasks.filter((task) => task.kind === "remediate" && task.summary).map((task) => task.summary)
  const proposed = (seq: number): Beat[] =>
    remediations.length === 0
      ? unfixed.map((summary) => ({ agent: "fixer", say: "Could not write a fix for this one.", detail: `${summary}.`, refs: [], seq, reveal: [] }))
      : remediations.map((fix) => ({ agent: "fixer", say: `${fix.kind === "rollback" ? "Wrote a rollback" : "Wrote a proper fix"}: ${fix.title}.`, detail: [fix.summary, fix.warning].filter(Boolean).join(" ") || null, refs: [], seq, reveal: [`Fix:${fix.id}`] }))
  let fixed = remediations.length + unfixed.length === 0
  for (const step of ordered) {
    if (step.agent === "scribe" && !fixed) {
      beats.push(...proposed(step.seq - 1))
      fixed = true
    }
    beats.push({ agent: step.agent, say: `${TOOL_SAYS[step.tool]?.(step.params) ?? step.tool.replaceAll("_", " ")}.`, detail: TOOL_DETAIL[step.tool]?.(step.result) ?? `Graph query ${step.tool.replaceAll("_", " ")} returned ${step.rows} ${step.rows === 1 ? "row" : "rows"}.`, refs: step.refs, seq: step.seq, reveal: [] })
    if (lastOf.get(step.agent) !== step.seq) continue
    beats.push(...findings.filter((finding) => finding.agent === step.agent).map((finding) => ({ agent: step.agent, say: finding.claim, detail: "Written down as a finding, with the records it rests on.", refs: finding.refs, seq: step.seq, reveal: [] })))
  }
  const end = ordered.at(-1)?.seq ?? 0
  if (!fixed) beats.push(...proposed(end))
  beats.push(...actions.map((action) => ({ agent: "scribe", say: `Drafted ${MESSAGE_KIND[action.kind] ?? "a message"}: ${action.subject}`, detail: `To ${action.to} by ${action.channel}. Not sent.`, refs: [], seq: end, reveal: [`Message:${action.id}`] })))
  beats.push({ agent: "you", say: "Ripple stops here.", detail: `${remediations.length} fixes and ${actions.length} messages are waiting for a person. Nothing is merged or sent until someone approves it.`, refs: [], seq: end, reveal: [] })
  return beats
}

export function Simulator() {
  const [picked, setPicked] = useState<string | null>(null)
  return picked ? <Run investigation={picked} back={() => setPicked(null)} /> : <Launcher pick={setPicked} />
}

function Launcher({ pick }: { pick: (investigation: string) => void }) {
  const { tenant } = useWorkspace()
  const scenarios = useQuery({ queryKey: [tenant, "scenarios"], queryFn: () => get<Scenario[]>(`/${tenant}/scenarios`) })
  const past = useQuery({ queryKey: [tenant, "investigations"], queryFn: () => get<InvestigationSummary[]>(`/${tenant}/investigations`) })
  const fire = usePost<{ investigation: string; opened: boolean }>((started) => {
    if (!started.opened) toast.info(`That alert joined ${started.investigation}, which is already open on the same dependency chain, so you are watching that one.`)
    pick(started.investigation)
  })
  return (
    <div className="mx-auto max-w-5xl space-y-10 px-10 py-8">
      <PageHeader eyebrow="Simulator" title="Break something and watch Ripple work" subtitle="Each incident below feeds real records into the company graph and fires an alert. The agents then investigate for real, and you watch what they did one step at a time." />
      {scenarios.isError && <Problem error={scenarios.error} retry={() => void scenarios.refetch()} />}
      {scenarios.isPending && <SkeletonRows label="Loading incidents" count={3} />}
      {scenarios.data?.length === 0 && <p className="text-muted-foreground">This company has no prepared incidents. They come with the demo company.</p>}
      <ul className={cn("grid gap-4", (scenarios.data?.length ?? 0) > 1 && "md:grid-cols-3")}>
        {scenarios.data?.map((scenario, index) => (
          <motion.li key={scenario.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.07 }} className="flex flex-col rounded-3xl bg-muted p-6">
            <h2 className="text-lg leading-snug font-medium">{scenario.title}</h2>
            {scenario.story && <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{scenario.story}</p>}
            {scenario.basis && <p className="mt-3 rounded-xl bg-background p-3 text-xs leading-relaxed text-muted-foreground">{scenario.basis}</p>}
            <p className="mt-4 flex items-center gap-2 text-sm">
              <BellRing className="size-4 shrink-0 text-brand" />
              <span className="min-w-0 truncate">{scenario.summary}</span>
            </p>
            <RippleButton className="mt-6 self-start rounded-full" disabled={fire.isPending} onClick={() => fire.mutate({ path: `/${tenant}/scenarios/${scenario.id}/fire` })}>
              <Play className="size-4" />
              Run this incident
            </RippleButton>
          </motion.li>
        ))}
      </ul>
      {past.data && past.data.length > 0 && (
        <section className="space-y-3">
          <h2 className="font-medium">Or replay one that already happened</h2>
          <ul className="divide-y rounded-2xl border">
            {past.data.map((item) => (
              <li key={item.id}>
                <button type="button" onClick={() => pick(item.id)} className="flex w-full items-center gap-4 px-4 py-3 text-left hover:bg-muted/60">
                  <RotateCcw className="size-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{item.title}</span>
                    <span className="text-sm text-muted-foreground">{`${item.incident} · ${item.incident_status} · ${item.steps} graph queries`}</span>
                  </span>
                  <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function Run({ investigation, back }: { investigation: string; back: () => void }) {
  const { tenant } = useWorkspace()
  const room = useQuery({
    queryKey: [tenant, "investigation", investigation],
    queryFn: () => get<IncidentState>(`/${tenant}/investigations/${investigation}`),
    refetchInterval: (query) => (query.state.data?.investigation.status === "running" ? 700 : false),
  })
  if (room.isError) return <Problem error={room.error} retry={() => void room.refetch()} className="m-10" />
  if (!room.data || room.data.investigation.status === "running") {
    return (
      <div className="grid min-h-full place-items-center px-10 py-24">
        <div role="status" className="max-w-md space-y-4 text-center">
          <span className="relative mx-auto block size-12 text-brand">
            <Rings count={3} className="inset-0" />
          </span>
          <p className="shimmer-text text-lg font-medium">The agents are investigating</p>
          <p className="text-sm text-muted-foreground">{room.data ? `${room.data.steps.length} graph queries so far. The replay starts when they finish.` : "Opening the incident."}</p>
        </div>
      </div>
    )
  }
  return <Player key={investigation} state={room.data} back={back} />
}

function Player({ state, back }: { state: IncidentState; back: () => void }) {
  const { selectInvestigation } = useWorkspace()
  const navigate = useNavigate()
  const beats = useMemo(() => script(state), [state])
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(1)
  const last = beats.length - 1
  const beat = beats[index]
  const BeatIcon = AGENTS[beat.agent]?.icon ?? BellRing
  const { investigation, incident, canvas } = state
  const root = investigation.root_id ? `${investigation.root_kind}:${investigation.root_id}` : null

  useEffect(() => {
    if (!playing || index >= last) return
    const timer = setTimeout(() => setIndex((current) => current + 1), BEAT_MS / speed)
    return () => clearTimeout(timer)
  }, [playing, index, last, speed])

  const shown = useMemo(() => new Set([...canvas.nodes.filter((node) => node.first_seq != null && node.first_seq <= beat.seq).map((node) => `${node.kind}:${node.id}`), ...beats.slice(0, index + 1).flatMap((earlier) => earlier.reveal)]), [canvas, beats, index, beat.seq])
  const fresh = useMemo(() => new Set([...beat.refs, ...beat.reveal]), [beat])
  const reached = new Set(beats.slice(0, index + 1).map((earlier) => earlier.agent))
  const jump = (to: number) => {
    setPlaying(false)
    setIndex(Math.min(last, Math.max(0, to)))
  }

  return (
    <div className="space-y-6 px-10 py-8">
      <PageHeader
        eyebrow={
          <button type="button" onClick={back} className="flex items-center gap-1.5 hover:text-foreground">
            <ArrowLeft className="size-3.5" />
            Simulator
          </button>
        }
        title={incident.title}
        subtitle={`${incident.id} on ${investigation.service}. A replay of what the agents actually did, slowed down: ${state.steps.length} graph queries, ${state.findings.length} findings.`}
      >
        <RippleButton
          variant="outline"
          className="shrink-0 rounded-full"
          onClick={() => {
            selectInvestigation(investigation.id)
            void navigate({ to: "/app" })
          }}
        >
          Open in the incident room
          <ArrowRight className="size-4" />
        </RippleButton>
      </PageHeader>

      <ol className="grid grid-cols-4 gap-2 xl:grid-cols-8">
        {Object.entries(AGENTS).map(([id, agent]) => {
          const active = beat.agent === id
          const done = !active && reached.has(id)
          return (
            <li key={id} className={cn("rounded-2xl border transition-colors", active ? "border-foreground bg-foreground text-background" : done ? "bg-muted" : "text-foreground/45")}>
              <Hint text={agent.does} className="block p-3">
                <p className="flex items-center gap-1.5 text-sm font-medium">
                  <agent.icon className="size-3.5 shrink-0" />
                  {agent.name}
                  {done && <Check className="ml-auto size-3.5 text-emerald-700" />}
                </p>
                <p className={cn("mt-1 text-xs leading-snug", active ? "text-background/70" : done ? "text-muted-foreground" : "")}>{agent.asks}</p>
              </Hint>
            </li>
          )
        })}
      </ol>

      <div className="grid gap-6 lg:grid-cols-[24rem_minmax(0,1fr)]">
        <div className="space-y-4">
          <motion.article key={index} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }} className="min-h-44 space-y-3 rounded-3xl bg-muted p-5">
            <p className="flex items-center gap-2 text-sm font-medium">
              <span className="grid size-7 place-items-center rounded-full bg-foreground text-background"><BeatIcon className="size-3.5" /></span>
              {AGENTS[beat.agent]?.name ?? beat.agent}
              <span className="ml-auto text-xs font-normal text-muted-foreground tabular-nums">{`${index + 1} of ${beats.length}`}</span>
            </p>
            <p className="text-[17px] leading-snug font-medium">{beat.say}</p>
            {beat.detail && <p className="text-sm leading-relaxed text-muted-foreground">{beat.detail}</p>}
            {beat.refs.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-xs text-muted-foreground">{`Touched in the graph${beat.refs.length > REFS_SHOWN ? ` · ${REFS_SHOWN} of ${beat.refs.length}` : ""}`}</p>
                <RefList refs={beat.refs.slice(0, REFS_SHOWN)} />
              </div>
            )}
          </motion.article>
          <div className="flex items-center gap-1.5">
            <RippleButton size="icon" variant="outline" className="rounded-full" aria-label="Back to the start" onClick={() => jump(0)}>
              <RotateCcw className="size-4" />
            </RippleButton>
            <RippleButton size="icon" variant="outline" className="rounded-full" aria-label="Previous step" disabled={index === 0} onClick={() => jump(index - 1)}>
              <SkipBack className="size-4" />
            </RippleButton>
            <RippleButton size="icon" className="rounded-full" aria-label={playing ? "Pause" : "Play"} onClick={() => (index >= last ? (setIndex(0), setPlaying(true)) : setPlaying(!playing))}>
              {playing && index < last ? <Pause className="size-4" /> : <Play className="size-4" />}
            </RippleButton>
            <RippleButton size="icon" variant="outline" className="rounded-full" aria-label="Next step" disabled={index >= last} onClick={() => jump(index + 1)}>
              <SkipForward className="size-4" />
            </RippleButton>
            <div role="group" aria-label="Speed" className="ml-auto flex rounded-full bg-muted p-0.5 text-xs">
              {SPEEDS.map((option) => (
                <button key={option} type="button" aria-pressed={speed === option} onClick={() => setSpeed(option)} className={cn("rounded-full px-2.5 py-1 tabular-nums", speed === option ? "bg-background font-medium shadow-xs" : "text-muted-foreground")}>
                  {`${option}×`}
                </button>
              ))}
            </div>
          </div>
          <input type="range" aria-label="Step" min={0} max={last} value={index} onChange={(event) => jump(Number(event.target.value))} className="w-full accent-[var(--brand)]" />
          <ol className="max-h-56 space-y-px overflow-y-auto rounded-2xl border p-1.5 text-sm">
            {beats.slice(0, index).map((earlier, at) => ({ earlier, at })).reverse().map(({ earlier, at }) => (
              <li key={at}>
                <button type="button" onClick={() => jump(at)} className="flex w-full gap-2 rounded-xl px-2.5 py-1.5 text-left hover:bg-muted">
                  <span className="w-20 shrink-0 text-xs leading-5 text-muted-foreground">{AGENTS[earlier.agent]?.name ?? earlier.agent}</span>
                  <span className="line-clamp-2 min-w-0 leading-5">{earlier.say}</span>
                </button>
              </li>
            ))}
            {index === 0 && <li className="px-2.5 py-1.5 text-muted-foreground">Each step the agents take will be listed here.</li>}
          </ol>
        </div>
        <div className="min-w-0 space-y-3">
          <ul className="flex flex-wrap gap-2">
            {TALLY.map(({ kind, label }) => {
              const count = [...shown].filter((key) => key.startsWith(`${kind}:`)).length
              return (
                <li key={kind} className={cn("flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-opacity", count === 0 && "opacity-40")}>
                  <span className="size-2 rounded-full" style={{ background: KIND_COLOR[kind] }} />
                  <span className="font-medium tabular-nums">{count}</span>
                  <span className="text-muted-foreground">{label}</span>
                </li>
              )
            })}
          </ul>
          <div className="overflow-hidden rounded-2xl border bg-muted/40">
            <Canvas canvas={canvas} centre={root ?? `Service:${investigation.service}`} onProposal={() => undefined} shown={shown} fresh={fresh} height="max(26rem, calc(100vh - 23rem))" />
          </div>
          <p className="text-sm text-muted-foreground">The graph fills in as the agents reach things, and the view follows what the current step touched, ringed in orange. Columns count hops from the likely cause.</p>
        </div>
      </div>
    </div>
  )
}
