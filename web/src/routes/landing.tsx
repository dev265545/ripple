import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { ArrowRight, Brain, Cable, GitPullRequest, ListFilter, MessagesSquare, Network, Scale, Send, Siren, Stethoscope, Undo2, Wrench, type LucideIcon } from "lucide-react"
import { useEffect, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from "react"

import { BrandIcon, Logo, Mark, Rings } from "@/components/brand"
import { RippleField } from "@/components/ripple-field"
import { ThemeToggle } from "@/components/theme-toggle"
import { SourceGraph } from "@/components/source-graph"
import { AnimatedBeam } from "@/components/ui/animated-beam"
import { BlurFade } from "@/components/ui/blur-fade"
import { Marquee } from "@/components/ui/marquee"
import { NumberTicker } from "@/components/ui/number-ticker"
import { Loading, Skeleton } from "@/components/status"
import { get, type Connector, type Evaluation, type Overview, type SourcedGraph, type Tool } from "@/lib/api"
import { cn } from "@/lib/utils"

const REACH = [
  {
    title: "Systems",
    question: "What broke, and what changed just before it did?",
    found: "checkout-api is failing because payments-core runs out of ledger connections. PR-412 capped that pool.",
    sources: ["catalog", "git", "deploys", "alerts", "vendor_status"],
  },
  {
    title: "People and decisions",
    question: "Who owns this, and why was it built this way?",
    found: "Mei Tanaka is on call. PR-412 implements ADR-7, decided by Tomas Novak after INC-088, with the burst risk written down.",
    sources: ["hr", "oncall", "documents"],
  },
  {
    title: "Customers",
    question: "Who is feeling it right now?",
    found: "Larkspur Retail, Kite Grocers and three more use features served by payments-core. Larkspur is in the middle of its Festive Mega Sale.",
    sources: ["crm", "product_map", "calendar"],
  },
  {
    title: "Promises",
    question: "What did we tell them, and what does it cost?",
    found: "An account manager emailed “zero checkout downtime, 3 to 6 October”. The contract guarantees 99.95% with 4,200 in monthly credit.",
    sources: ["email", "documents", "uploads"],
  },
]

const PIPELINE = [
  { step: "Read", detail: "Each connector turns a system into records: one pull request, one email, one contract." },
  { step: "Hash", detail: "A record that has not changed since the last sync is skipped. Syncing twice writes nothing." },
  { step: "Quote", detail: "A fact taken from prose must carry the sentence it came from, or it is rejected." },
  { step: "Resolve", detail: "An email address, a Git handle and an HR row become one person, not three." },
  { step: "Link", detail: "Every node and relationship points back to its record, so any answer can show its source." },
]

const STAGES: { name: string; icon: LucideIcon; does: string }[] = [
  { name: "Triage", icon: ListFilter, does: "Reads the alert, opens the incident, and checks memory for a playbook that worked before." },
  { name: "Root cause", icon: Stethoscope, does: "Walks dependencies and recent changes, scores each suspect, and names the most likely one." },
  { name: "Who it reaches", icon: Network, does: "Follows the failing service out to features, customers, contracts and live promises." },
  { name: "Why it was built this way", icon: Scale, does: "Finds the decision, requirement or earlier incident behind the suspect change." },
  { name: "Ways out", icon: Wrench, does: "Prepares a rollback and a proper fix as two pull requests, each checked under load." },
  { name: "Who needs to hear", icon: Send, does: "Drafts each message that has to go out, addressed and cited, for a person to approve." },
]

export function Landing() {
  const catalog = useQuery({ queryKey: ["connectors"], queryFn: () => get<Connector[]>("/connectors") })
  const evaluation = useQuery({ queryKey: ["evaluation"], queryFn: () => get<Evaluation>("/evaluation") })
  const questions = useQuery({ queryKey: ["suggestions"], queryFn: () => get<string[]>("/chat/suggestions") })
  return (
    <div className="bg-background">
      <Hero systems={[...new Set((catalog.data ?? []).flatMap((connector) => connector.systems))]} />
      <Reach catalog={catalog.data ?? []} />
      {catalog.data && <Connect catalog={catalog.data} />}
      {catalog.isPending && (
        <Loading label="Loading the connector directory" className="mx-auto grid max-w-6xl gap-4 px-6 py-20 md:grid-cols-3">
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="h-40 rounded-3xl" />
          ))}
        </Loading>
      )}
      <OneGraph catalog={catalog.data ?? []} />
      <Example />
      <Team />
      <WaysOut />
      <Tour />
      {questions.data && <Ask questions={questions.data} />}
      {evaluation.data?.runs && <Evidence evaluation={evaluation.data} />}
      <Closing />
    </div>
  )
}

function Pill({ to, href, dark, children, className }: { to?: "/login" | "/setup"; href?: string; dark?: boolean; children: ReactNode; className?: string }) {
  const look = cn(
    "inline-flex h-11 items-center gap-2 rounded-full px-5 text-[15px] font-medium transition active:translate-y-px",
    dark ? "bg-foreground text-background hover:bg-foreground/85" : "border bg-background hover:bg-muted",
    className,
  )
  return to ? (
    <Link to={to} className={look}>
      {children}
    </Link>
  ) : (
    <a href={href} className={look}>
      {children}
    </a>
  )
}

function Section({ id, title, lead, children }: { id?: string; title: string; lead: string; children: ReactNode }) {
  return (
    <section id={id} className="mx-auto max-w-6xl scroll-mt-24 px-6 py-20">
      <BlurFade inView>
        <h2 className="max-w-2xl font-heading text-4xl leading-[1.08] md:text-5xl">{title}</h2>
        <p className="mt-4 max-w-xl text-lg text-muted-foreground">{lead}</p>
      </BlurFade>
      <div className="mt-10">{children}</div>
    </section>
  )
}

function Hero({ systems }: { systems: string[] }) {
  const [waves, setWaves] = useState<{ key: number; x: number; y: number }[]>([])
  const hero = useRef<HTMLElement>(null)
  const mark = useRef<HTMLButtonElement>(null)
  const ripple = (clientX: number, clientY: number) => {
    const box = hero.current!.getBoundingClientRect()
    setWaves((current) => [...current, { key: performance.now(), x: clientX - box.left, y: clientY - box.top }])
  }
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return
    const box = mark.current!.getBoundingClientRect()
    const first = setTimeout(() => ripple(box.left + box.width / 2, box.top + box.height / 2), 700)
    return () => clearTimeout(first)
  }, [])
  return (
    <header ref={hero} onPointerDown={(event) => ripple(event.clientX, event.clientY)} className="relative overflow-clip px-6 pt-5">
      {waves.map((wave) => (
        <div key={wave.key} aria-hidden className="pointer-events-none absolute size-[90rem] -translate-1/2 text-brand" style={{ left: wave.x, top: wave.y }}>
          <span className="absolute inset-[38%] animate-wave rounded-full bg-[radial-gradient(closest-side,currentColor,transparent)] [--peak:0.14]" />
          {[0, 1, 2, 3, 4].map((ring) => (
            <span
              key={ring}
              onAnimationEnd={ring === 4 ? () => setWaves((current) => current.filter((other) => other.key !== wave.key)) : undefined}
              className="absolute inset-0 animate-wave rounded-full border-2 border-current shadow-[0_0_28px_0_currentColor,inset_0_0_28px_0_currentColor] will-change-transform"
              style={{ animationDelay: `${ring * 0.22}s`, "--peak": 0.42 - ring * 0.08 } as CSSProperties}
            />
          ))}
        </div>
      ))}
      <nav className="sticky top-5 z-20 mx-auto flex max-w-2xl items-center rounded-full bg-muted/90 py-2 pr-2 pl-5 backdrop-blur">
        <Logo />
        <div className="ml-auto flex items-center gap-5 text-[15px] font-medium">
          <a href="#connect" className="hidden hover:opacity-60 sm:block">Connect</a>
          <a href="#graph" className="hidden hover:opacity-60 sm:block">The graph</a>
          <a href="#team" className="hidden hover:opacity-60 sm:block">How it works</a>
          <Link to="/setup" className="hidden hover:opacity-60 sm:block">Set up</Link>
          <ThemeToggle className="-mx-2 rounded-full hover:bg-background" />
          <Link to="/login" className="rounded-full bg-background px-4 py-1.5 shadow-xs hover:bg-background/70">
            Sign in
          </Link>
        </div>
      </nav>
      <div className="mx-auto max-w-4xl pt-20 pb-16 text-center">
        <BlurFade>
          <div className="relative mx-auto size-20 text-foreground/25">
            <Rings count={3} className="-inset-10" />
            <button
              type="button"
              aria-label="Make a ripple"
              title="Make a ripple"
              ref={mark}
              className="relative block rounded-[1.4rem] transition-transform duration-150 active:scale-90"
            >
              <Mark className="size-20 rounded-[1.4rem] shadow-lg" />
            </button>
          </div>
        </BlurFade>
        <BlurFade delay={0.1}>
          <h1 className="mt-10 font-heading text-6xl leading-[1.02] text-balance md:text-7xl">Root cause is only the first ring.</h1>
        </BlurFade>
        <BlurFade delay={0.2}>
          <p className="mx-auto mt-6 max-w-2xl text-xl text-muted-foreground">
            Ripple follows an incident from the failing service to the people, customers and promises it reaches, then hands you the pull request.
          </p>
        </BlurFade>
        <BlurFade delay={0.3}>
          <div className="mt-8 flex justify-center gap-3">
            <Pill to="/login" dark>
              Open the demo company
            </Pill>
            <Pill href={`/login?company=${REPLAY_COMPANY}`}>
              Replay Cloudflare's 2019 outage
              <ArrowRight className="size-4" />
            </Pill>
          </div>
        </BlurFade>
        {systems.length > 0 && (
          <BlurFade delay={0.4}>
            <p className="mt-16 text-sm text-muted-foreground">Reads exports from the tools you already run</p>
            <div className="mt-5 flex flex-wrap justify-center gap-x-8 gap-y-3 text-muted-foreground/70">
              {["GitHub", "PagerDuty", "Datadog", "Backstage", "HubSpot", "Confluence"].filter((system) => systems.includes(system)).map((system) => (
                <span key={system} className="flex items-center gap-2 text-lg font-semibold">
                  <BrandIcon system={system} className="size-5" />
                  {system}
                </span>
              ))}
            </div>
          </BlurFade>
        )}
      </div>
    </header>
  )
}

function Reach({ catalog }: { catalog: Connector[] }) {
  const [ring, setRing] = useState(0)
  const feeds = REACH[ring].sources.flatMap((id) => catalog.filter((connector) => connector.id === id))
  return (
    <section id="reach" className="scroll-mt-24 px-4">
      <div className="mx-auto grid max-w-7xl items-center gap-8 rounded-[2rem] bg-muted px-6 py-12 md:px-12 lg:grid-cols-[1fr_1.1fr]">
        <div>
          <p className="text-sm font-medium text-muted-foreground">One alert, followed outward</p>
          <h2 className="mt-3 font-heading text-4xl leading-[1.08] md:text-5xl">Most tools stop at the first ring.</h2>
          <div role="tablist" className="mt-8 flex flex-wrap gap-2">
            {REACH.map((row, index) => (
              <button
                key={row.title}
                type="button"
                role="tab"
                aria-selected={index === ring}
                onClick={() => setRing(index)}
                className={cn("rounded-full px-4 py-2 text-[15px] font-medium transition", index === ring ? "bg-foreground text-background" : "bg-background hover:bg-background/60")}
              >
                {row.title}
              </button>
            ))}
          </div>
          <BlurFade key={ring} className="mt-6 rounded-2xl bg-background p-6 shadow-xs">
            <p className="text-sm text-muted-foreground">{REACH[ring].question}</p>
            <p className="mt-2 text-xl leading-snug font-medium">{REACH[ring].found}</p>
            {feeds.length > 0 && (
              <div className="mt-5 border-t pt-4">
                <p className="text-sm text-muted-foreground">Ripple knows this from</p>
                <ul className="mt-2.5 flex flex-wrap gap-2">
                  {feeds.map((connector) => (
                    <li key={connector.id} className="flex items-center gap-2 rounded-full bg-muted py-1.5 pr-3.5 pl-2.5 text-sm font-medium">
                      {connector.systems.slice(0, 2).map((system) => (
                        <BrandIcon key={system} system={system} className="size-3.5" />
                      ))}
                      {connector.name}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </BlurFade>
          <p className="mt-4 text-sm text-muted-foreground">From Northwind Pay, the demo company that ships with Ripple.</p>
        </div>
        <RippleField focus={ring} className="w-full" />
      </div>
    </section>
  )
}

function Connect({ catalog }: { catalog: Connector[] }) {
  const systems = [...new Set(catalog.flatMap((connector) => connector.systems))]
  const reading = catalog.filter((connector) => connector.source !== null).length
  const half = Math.ceil(systems.length / 2)
  return (
    <Section
      id="connect"
      title="Any system is a source. So is any document."
      lead={`${reading} connectors read today, from exports in the formats these tools produce. ${catalog.length - reading} more are planned and marked as such in the app.`}
    >
      <div className="-mx-6 space-y-3 mask-[linear-gradient(to_right,transparent,black_12%,black_88%,transparent)]">
        {[systems.slice(0, half), systems.slice(half)].map((row, index) => (
          <Marquee key={index} reverse={index === 1} pauseOnHover className="p-0 [--duration:45s] [--gap:0.75rem]">
            {row.map((system) => (
              <span key={system} className="flex items-center gap-2.5 rounded-full border bg-background px-4 py-2.5 text-[15px] font-medium">
                <BrandIcon system={system} />
                {system}
              </span>
            ))}
          </Marquee>
        ))}
      </div>
      <Directory catalog={catalog} />
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="rounded-3xl bg-muted p-8">
          <h3 className="text-xl font-semibold">Everything lands in one graph</h3>
          <p className="mt-1 text-muted-foreground">Pull requests, on-call shifts, accounts and emails become connected things.</p>
          <Confluence catalog={catalog} />
        </div>
        <div className="rounded-3xl bg-muted p-8">
          <h3 className="text-xl font-semibold">What happens to one record</h3>
          <ol className="mt-5 space-y-2">
            {PIPELINE.map((stage, index) => (
              <BlurFade key={stage.step} inView delay={index * 0.06}>
                <li className="flex gap-4 rounded-2xl bg-background p-4">
                  <span className="grid size-7 shrink-0 place-items-center rounded-full bg-foreground text-xs font-semibold text-background">{index + 1}</span>
                  <p className="text-[15px] leading-snug">
                    <span className="font-semibold">{`${stage.step}. `}</span>
                    <span className="text-muted-foreground">{stage.detail}</span>
                  </p>
                </li>
              </BlurFade>
            ))}
          </ol>
        </div>
      </div>
    </Section>
  )
}

function Directory({ catalog }: { catalog: Connector[] }) {
  const [category, setCategory] = useState("All")
  const categories = ["All", ...new Set(catalog.map((connector) => connector.category))]
  const shown = catalog.filter((connector) => category === "All" || connector.category === category)
  return (
    <div className="mt-12">
      <div className="inline-flex flex-wrap rounded-full bg-muted p-1">
        {categories.map((name) => (
          <button
            key={name}
            type="button"
            aria-pressed={name === category}
            onClick={() => setCategory(name)}
            className={cn("rounded-full px-4 py-1.5 text-[15px] font-medium text-muted-foreground", name === category && "bg-background text-foreground shadow-xs")}
          >
            {name}
          </button>
        ))}
      </div>
      <ul className="mt-5 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {shown.map((connector) => (
          <li key={connector.id} className="flex flex-col rounded-3xl border p-6">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-lg font-semibold">{connector.name}</h3>
              <span className={cn("shrink-0 rounded-full px-2.5 py-1 text-xs font-medium", connector.source ? "bg-emerald-50 text-emerald-700" : "bg-muted text-muted-foreground")}>
                {connector.source ? "Reads today" : "Planned"}
              </span>
            </div>
            <p className="mt-1 text-[15px] text-muted-foreground">{`${connector.source ? "Reads" : "Will read"} ${connector.reads}.`}</p>
            {connector.systems.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-1.5">
                {connector.systems.map((system) => (
                  <span key={system} className="flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-sm font-medium">
                    <BrandIcon system={system} className="size-3.5" />
                    {system}
                  </span>
                ))}
              </div>
            )}
            <p className="mt-auto pt-5 text-sm text-muted-foreground">
              Adds <span className="font-medium text-foreground">{connector.produces.join(", ")}</span>
            </p>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Stop({ innerRef, children, className }: { innerRef: RefObject<HTMLDivElement | null>; children: ReactNode; className?: string }) {
  return (
    <div ref={innerRef} className={cn("relative z-10 flex items-center gap-2 rounded-xl bg-background px-3 py-2 text-sm font-medium shadow-xs", className)}>
      {children}
    </div>
  )
}

function Confluence({ catalog }: { catalog: Connector[] }) {
  const container = useRef<HTMLDivElement>(null)
  const graph = useRef<HTMLDivElement>(null)
  const sources = [useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null)]
  const kinds = [useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null)]
  const shown = ["git", "oncall", "crm", "email"].flatMap((id) => catalog.filter((connector) => connector.id === id))
  const produced = ["Pull request", "Person", "Customer", "Promise"]
  return (
    <div ref={container} className="relative mt-8 flex items-center justify-between gap-4">
      <div className="space-y-6">
        {shown.map((connector, index) => (
          <Stop key={connector.id} innerRef={sources[index]}>
            {connector.systems[0] && <BrandIcon system={connector.systems[0]} />}
            {connector.name}
          </Stop>
        ))}
      </div>
      <div ref={graph} className="relative z-10 text-foreground/30">
        <Rings count={3} className="-inset-8" />
        <Mark className="relative size-16 rounded-2xl shadow-lg" />
      </div>
      <div className="space-y-6">
        {produced.map((kind, index) => (
          <Stop key={kind} innerRef={kinds[index]}>
            {kind}
          </Stop>
        ))}
      </div>
      {sources.map((source, index) => (
        <AnimatedBeam key={`in${index}`} containerRef={container} fromRef={source} toRef={graph} curvature={(1.5 - index) * 12} pathColor="var(--foreground)" pathOpacity={0.12} gradientStartColor="var(--foreground)" gradientStopColor="#f04a23" delay={index * 0.5} duration={4} />
      ))}
      {kinds.map((kind, index) => (
        <AnimatedBeam key={`out${index}`} containerRef={container} fromRef={graph} toRef={kind} curvature={(index - 1.5) * 12} pathColor="var(--foreground)" pathOpacity={0.12} gradientStartColor="#f04a23" gradientStopColor="var(--foreground)" delay={2 + index * 0.5} duration={4} />
      ))}
    </div>
  )
}

const DEMO_COMPANY = "northwind"
const REPLAY_COMPANY = "cloudflare-2019"
const SHOWN_QUERIES = ["commitments_at_risk", "change_reach", "code_history", "suspect_changes", "critical_services"]

function OneGraph({ catalog }: { catalog: Connector[] }) {
  const graph = useQuery({ queryKey: [DEMO_COMPANY, "graph"], queryFn: () => get<SourcedGraph>(`/${DEMO_COMPANY}/graph`), retry: false })
  const overview = useQuery({ queryKey: [DEMO_COMPANY, "overview"], queryFn: () => get<Overview>(`/${DEMO_COMPANY}/overview`), retry: false })
  const tools = useQuery({ queryKey: ["tools"], queryFn: () => get<Tool[]>("/tools") })
  const [picked, setPicked] = useState(SHOWN_QUERIES[0])
  if (!graph.data || graph.data.nodes.length === 0) return null
  const shown = SHOWN_QUERIES.flatMap((name) => (tools.data ?? []).filter((tool) => tool.name === name))
  const query = shown.find((tool) => tool.name === picked) ?? shown[0]
  const stored = overview.data ? overview.data.nodes.reduce((sum, row) => sum + row.count, 0) : null
  return (
    <Section
      id="graph"
      title="Separate systems in, one connected graph out."
      lead="This is the demo company's graph as it sits in FalkorDB right now. The pull request came from Git, the service from the catalog, the customer from the CRM and the promise from an email, and here they are joined to each other."
    >
      <SourceGraph graph={graph.data} catalog={catalog} />
      {query && (
        <div className="mt-4 grid gap-4 lg:grid-cols-[1.25fr_1fr]">
          <div className="flex min-w-0 flex-col rounded-3xl bg-ink p-8 text-background">
            <h3 className="text-xl font-semibold">One question, one path through the graph</h3>
            <p className="mt-1 text-background/65">{`These are the queries the agents run on FalkorDB, word for word. There are ${tools.data?.length} of them, and they are the only way an agent can read.`}</p>
            <div className="mt-5 flex flex-wrap gap-1.5">
              {shown.map((tool) => (
                <button
                  key={tool.name}
                  type="button"
                  aria-pressed={tool.name === query.name}
                  onClick={() => setPicked(tool.name)}
                  className={cn("rounded-full px-3 py-1.5 text-sm font-medium", tool.name === query.name ? "bg-background text-foreground" : "bg-background/10 text-background/80 hover:bg-background/20")}
                >
                  {tool.name.replaceAll("_", " ")}
                </button>
              ))}
            </div>
            <p className="mt-5 text-[15px] text-background/80">{query.doc}</p>
            <pre className="mt-3 rounded-2xl bg-background/[0.07] p-5 font-mono text-[12.5px] leading-relaxed break-words whitespace-pre-wrap text-background/90">{query.cypher.replace(/\n\s{8}/g, "\n")}</pre>
            {stored !== null && overview.data && (
              <dl className="mt-auto grid grid-cols-3 gap-4 pt-8">
                {[
                  [stored, "nodes in the demo company's graph"],
                  [overview.data.edges, "relationships between them"],
                  [new Set(graph.data.nodes.flatMap((node) => node.sources)).size, "sources they were read from"],
                ].map(([value, label]) => (
                  <div key={label}>
                    <dd className="font-heading text-3xl tabular-nums">{value.toLocaleString()}</dd>
                    <dt className="mt-1 text-sm text-background/65">{label}</dt>
                  </div>
                ))}
              </dl>
            )}
          </div>
          <div className="rounded-3xl bg-muted p-8">
            <h3 className="text-xl font-semibold">What FalkorDB does here</h3>
            <ul className="mt-5 space-y-2 text-[15px] leading-snug">
              {[
                ["One graph per company.", "Each company's data lives in its own FalkorDB graph, so nothing crosses between them."],
                ["Paths instead of joins.", "From a failing service to the promise it breaks is a single pattern, however many dependencies sit in between."],
                ["Code and customers on one path.", "Functions, files and what calls what sit in the same graph as contracts and email, so one query runs from a changed line of code to the promise it can break."],
                ["Built-in ranking.", "Betweenness centrality over the dependency edges tells Ripple which services matter most."],
                ["Built-in search.", "The search box in the app runs on FalkorDB's full-text index."],
                ["Evidence as edges.", "Every thing points to the record it was read from, so an answer can always show its source."],
              ].map(([head, detail]) => (
                <li key={head} className="rounded-2xl bg-background p-4">
                  <span className="font-semibold">{`${head} `}</span>
                  <span className="text-muted-foreground">{detail}</span>
                </li>
              ))}
            </ul>
            <p className="mt-4 text-sm text-muted-foreground">The counts include the investigations and conversations Ripple stores in the same graph.</p>
          </div>
        </div>
      )}
    </Section>
  )
}

const FACTS = [
  { from: "Nikhil Shah", relation: "made", to: "the promise" },
  { from: "The promise", relation: "was made to", to: "Larkspur Retail" },
  { from: "The promise", relation: "is about", to: "Hosted Checkout" },
]

function Example() {
  return (
    <Section title="From one sentence to a fact you can act on." lead="This is a real record from the demo company. The highlighted sentences are the quotes Ripple keeps as evidence.">
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-3xl bg-muted p-8">
          <p className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <BrandIcon system="Gmail" />
            Email, 30 September
          </p>
          <div className="mt-4 rounded-2xl bg-background p-6 text-[15px] leading-relaxed shadow-xs">
            <p className="font-semibold">Re: Festive Mega Sale: can you hold up?</p>
            <p className="text-sm text-muted-foreground">Nikhil Shah to Dana Whitfield</p>
            <p className="mt-4">Hi Dana,</p>
            <p className="mt-2">
              I have checked with engineering. <mark className="rounded bg-brand/15 px-0.5 text-foreground">We commit to zero checkout downtime for the whole Festive Mega Sale, 3 to 6 October.</mark>{" "}
              <mark className="rounded bg-brand/15 px-0.5 text-foreground">If anything goes wrong I will call you personally within 10 minutes.</mark>
            </p>
            <p className="mt-2">Nikhil</p>
          </div>
        </div>
        <div className="rounded-3xl bg-muted p-8">
          <p className="text-sm font-medium text-muted-foreground">What Ripple adds to the graph</p>
          <div className="mt-4 space-y-2">
            <div className="rounded-2xl bg-background p-5 shadow-xs">
              <p className="text-sm text-muted-foreground">Two promises, live until 6 October</p>
              <p className="mt-1 font-medium">Zero checkout downtime for the whole Festive Mega Sale.</p>
              <p className="mt-1 font-medium">A personal call within 10 minutes if anything goes wrong.</p>
            </div>
            {FACTS.map((fact, index) => (
              <BlurFade key={fact.relation} inView delay={index * 0.06}>
                <p className="flex flex-wrap items-center gap-2 rounded-2xl bg-background px-5 py-3.5 text-[15px] shadow-xs">
                  <span className="font-medium">{fact.from}</span>
                  <span className="text-muted-foreground">{fact.relation}</span>
                  <span className="font-medium">{fact.to}</span>
                </p>
              </BlurFade>
            ))}
          </div>
          <p className="mt-4 text-sm text-muted-foreground">
            Hosted Checkout depends on checkout-api, so when that service fails, this email shows up in the incident room.
          </p>
        </div>
      </div>
    </Section>
  )
}

const SCREENS: { name: string; icon: LucideIcon; does: string }[] = [
  { name: "Incident room", icon: Siren, does: "The investigation as it happens, what needs your approval, the impact map, the two fixes and the drafted messages." },
  { name: "Connect", icon: Cable, does: "Every connector and its status, a box to paste any document, and every record with the facts taken from it." },
  { name: "Ask Ripple", icon: MessagesSquare, does: "Questions about services, customers, changes and promises, answered with numbered sources and the query behind them." },
  { name: "Memory", icon: Brain, does: "The playbooks and facts Ripple keeps after a person confirms a root cause, so the next incident is shorter." },
]

function Tour() {
  return (
    <Section title="What you get when you sign in." lead="Four screens, all reading from the same graph.">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {SCREENS.map((screen, index) => (
          <BlurFade key={screen.name} inView delay={index * 0.05}>
            <Link to="/login" className="group block h-full rounded-3xl border p-6 transition hover:border-foreground">
              <span className="grid size-11 place-items-center rounded-xl bg-muted">
                <screen.icon className="size-5" />
              </span>
              <h3 className="mt-6 flex items-center gap-1.5 text-lg font-semibold">
                {screen.name}
                <ArrowRight className="size-4 opacity-0 transition group-hover:translate-x-0.5 group-hover:opacity-100" />
              </h3>
              <p className="mt-1.5 text-[15px] leading-relaxed text-muted-foreground">{screen.does}</p>
            </Link>
          </BlurFade>
        ))}
      </div>
    </Section>
  )
}

function Team() {
  return (
    <Section id="team" title="Six jobs, one shared board." lead="Each stage claims its task from the graph, records every query it ran, and may only state a finding that points at things it actually read.">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {STAGES.map((stage, index) => (
          <BlurFade key={stage.name} inView delay={index * 0.05}>
            <div className="h-full rounded-3xl bg-muted p-7">
              <span className="grid size-11 place-items-center rounded-xl bg-background shadow-xs">
                <stage.icon className="size-5" />
              </span>
              <h3 className="mt-6 text-xl font-semibold">{stage.name}</h3>
              <p className="mt-1.5 text-[15px] leading-relaxed text-muted-foreground">{stage.does}</p>
            </div>
          </BlurFade>
        ))}
      </div>
    </Section>
  )
}

function Proposal({ icon: Icon, kind, title, note, children }: { icon: LucideIcon; kind: string; title: string; note: string; children: ReactNode }) {
  return (
    <div className="rounded-3xl bg-muted p-8">
      <h3 className="text-xl font-semibold">{kind}</h3>
      <p className="mt-1 text-muted-foreground">{children}</p>
      <div className="mt-6 rounded-2xl bg-background p-4 shadow-xs">
        <div className="flex items-start gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-muted">
            <Icon className="size-4" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="font-medium">{title}</p>
            <p className="text-sm text-muted-foreground">{note}</p>
          </div>
          <span className="shrink-0 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">Checks pass</span>
        </div>
      </div>
    </div>
  )
}

function WaysOut() {
  return (
    <Section id="ways-out" title="It ends with two pull requests." lead="Nothing merges and no message is sent until a signed-in person approves it.">
      <div className="grid gap-4 lg:grid-cols-2">
        <Proposal icon={Undo2} kind="Roll it back" title="Revert PR-412" note="Undoes ADR-7, the decision that change was made for.">
          Fast, and honest about what you lose: the decision behind the change comes back as a warning on the pull request.
        </Proposal>
        <Proposal icon={GitPullRequest} kind="Fix it properly" title="Queue charges beyond the ledger pool instead of failing them" note="Keeps ADR-5 and ADR-7 in force.">
          Keeps the decision and removes the failure. The patch runs against the service's tests and a load check before it is offered.
        </Proposal>
      </div>
    </Section>
  )
}

function Ask({ questions }: { questions: string[] }) {
  return (
    <Section title="Between incidents, ask it anything." lead="Every answer lists the records it rests on, with the quoted sentence, and shows the graph query that produced it.">
      <div className="flex flex-wrap gap-2.5">
        {questions.map((question, index) => (
          <BlurFade key={question} inView delay={index * 0.04}>
            <Link to="/login" className="inline-flex rounded-full border px-5 py-3 text-[15px] font-medium transition hover:border-foreground">
              {question}
            </Link>
          </BlurFade>
        ))}
      </div>
    </Section>
  )
}

function Figure({ value, suffix, label }: { value: number; suffix?: string; label: string }) {
  return (
    <div className="p-8">
      <p className="font-heading text-6xl">
        <NumberTicker value={value} className="text-foreground" />
        {suffix}
      </p>
      <p className="mt-2 text-[15px] text-muted-foreground">{label}</p>
    </div>
  )
}

function Evidence({ evaluation: { runs = [], accuracy = 0, memory } }: { evaluation: Evaluation }) {
  return (
    <Section title="Measured, not claimed." lead="These numbers are read from the last run of the evaluation harness. Sign in to rerun it yourself.">
      <div className="grid divide-y rounded-3xl border md:grid-cols-3 md:divide-x md:divide-y-0">
        <Figure value={Math.round(accuracy * 100)} suffix="%" label={`root cause correct across ${runs.length} planted scenarios`} />
        {memory && <Figure value={memory.cold_steps} label={`investigator steps on scenario ${memory.scenario}, first time`} />}
        {memory && <Figure value={memory.warm_steps} label="steps on the same scenario after one confirmed cause" />}
      </div>
    </Section>
  )
}

function Closing() {
  return (
    <footer className="px-4 pb-4">
      <div className="relative mx-auto max-w-7xl overflow-hidden rounded-[2rem] bg-ink px-6 py-28 text-center text-background">
        <Rings count={5} className="top-1/2 left-1/2 w-[64rem] -translate-x-1/2 -translate-y-1/2 text-background/25" />
        <div className="relative">
          <h2 className="font-heading text-5xl md:text-6xl">Drop a stone in.</h2>
          <p className="mx-auto mt-4 max-w-md text-lg text-background/70">Sign in as someone at Northwind Pay, fire an alert, and watch how far it travels.</p>
          <Pill to="/login" className="mt-8 border-0 bg-background text-foreground hover:bg-background/85">
            Open the demo company
            <ArrowRight className="size-4" />
          </Pill>
          <p className="mt-5 text-background/70">
            Or{" "}
            <Link to="/setup" className="font-medium text-background underline underline-offset-4">
              set it up for your own company
            </Link>{" "}
            from your tools' export files.
          </p>
        </div>
      </div>
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-6 text-sm text-muted-foreground">
        <Logo className="text-foreground" />
        One graph per company, on FalkorDB
      </div>
    </footer>
  )
}
