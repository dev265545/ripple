import { useQuery } from "@tanstack/react-query"
import { Link, Navigate, Outlet, useNavigate } from "@tanstack/react-router"
import { Brain, Cable, CircleHelp, Compass, FlaskConical, LogOut, MessagesSquare, Search, Siren, CirclePlay, Waypoints, Newspaper } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { Logo } from "@/components/brand"
import { EntityDrawer } from "@/components/entity-drawer"
import { Hint } from "@/components/hint"
import { Tour, tourSeen } from "@/components/tour"
import { RecordTraceDrawer } from "@/components/record-trace"
import { Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { toast } from "sonner"
import { Skeleton, Spinner } from "@/components/status"
import { ThemeToggle } from "@/components/theme-toggle"
import { Toaster } from "@/components/ui/sonner"
import { useDark } from "@/lib/theme"
import { get, type InvestigationSummary } from "@/lib/api"
import { cn } from "@/lib/utils"
import { readSession, usePost, WorkspaceContext, writeSession, type Session, type Workspace } from "@/lib/workspace"

const PAGES = [
  { to: "/app", label: "Incident room", icon: Siren, hint: "One incident as a report: the cause, who it reaches, and the fixes and messages waiting for you." },
  { to: "/app/simulator", label: "Simulator", icon: CirclePlay, hint: "Fire an incident and watch the agents work through it, one step at a time." },
  { to: "/app/brief", label: "My brief", icon: Newspaper, hint: "Your promises, projects, on-call shifts and anything waiting for your call, read from the graph." },
  { to: "/app/graph", label: "Graph", icon: Waypoints, hint: "The whole company graph on one page: every thing Ripple read and how they join." },
  { to: "/app/connect", label: "Connect", icon: Cable, hint: "The systems that feed the graph and what each one added." },
  { to: "/app/chat", label: "Ask Ripple", icon: MessagesSquare, hint: "Ask the company graph a question in plain words." },
  { to: "/app/memory", label: "Memory", icon: Brain, hint: "What Ripple learned from incidents you confirmed." },
  { to: "/app/evaluation", label: "Evaluation", icon: FlaskConical, hint: "How often Ripple finds the planted cause in generated incidents." },
  { to: "/app/guide", label: "Guide", icon: CircleHelp, hint: "What each agent does and what the words mean." },
] as const

export function Shell() {
  const session = readSession()
  return session ? <Workbench session={session} /> : <Navigate to="/login" />
}

function Workbench({ session: { tenant, user } }: { session: Session }) {
  const dark = useDark()
  const [investigation, selectInvestigation] = useState<string | null>(null)
  const [entity, openEntity] = useState<string | null>(null)
  const [record, openRecord] = useState<string | null>(null)
  const [palette, setPalette] = useState(false)
  const [tourStop, setTourStop] = useState<number | null>(() => (tourSeen() ? null : 0))
  const [query, setQuery] = useState("")
  const matches = useQuery({
    queryKey: [tenant, "search", query],
    queryFn: () => get<{ kind: string; id: string; name: string }[]>(`/${tenant}/search?q=${encodeURIComponent(query)}`),
    enabled: palette && query.trim().length > 1,
  })
  const navigate = useNavigate()
  const scenarios = useQuery({
    queryKey: [tenant, "scenarios"],
    queryFn: () => get<{ id: string; title: string }[]>(`/${tenant}/scenarios`),
  })
  const incidents = useQuery({
    queryKey: [tenant, "investigations"],
    queryFn: () => get<InvestigationSummary[]>(`/${tenant}/investigations`),
    refetchInterval: 3000,
  })
  const fire = usePost<{ investigation: string; opened: boolean }>((started) => {
    if (!started.opened) toast.info(`This alert joined ${started.investigation}, which is already open on the same dependency chain.`)
    selectInvestigation(started.investigation)
    void navigate({ to: "/app" })
  })
  const seed = usePost(() => selectInvestigation(null))
  const current = investigation ?? (incidents.data?.find((item) => item.incident_status === "open") ?? incidents.data?.[0])?.id ?? null
  const workspace = useMemo<Workspace>(
    () => ({
      tenant,
      user,
      investigation: current,
      incidentsLoaded: incidents.isSuccess,
      selectInvestigation,
      openEntity,
      openRecord,
    }),
    [tenant, user, current, incidents.isSuccess],
  )

  useEffect(() => {
    if (investigation === null && current !== null) selectInvestigation(current)
  }, [investigation, current])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault()
        setPalette((open) => !open)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  function run(action: () => void) {
    setPalette(false)
    setQuery("")
    action()
  }

  return (
    <WorkspaceContext.Provider value={workspace}>
      <div className="grid h-screen grid-cols-[15.5rem_1fr]">
        <aside className="flex min-h-0 flex-col gap-5 border-r bg-sidebar px-3 py-4">
          <Logo className="px-2" />
          <button type="button" onClick={() => setPalette(true)} className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-sidebar-accent hover:text-foreground">
            <Search className="size-4" />
            Search or jump
            <kbd className="ml-auto font-mono text-[10px]">Ctrl K</kbd>
          </button>
          <nav className="space-y-0.5">
            {PAGES.map((page) => (
              <Hint key={page.to} text={page.hint} side="right" className="flex">
                <Link
                  to={page.to}
                  className="flex flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:text-foreground"
                  activeOptions={{ exact: page.to === "/app" }}
                  activeProps={{
                    className: "bg-sidebar-accent font-medium text-foreground",
                  }}
                >
                  <page.icon className="size-4" />
                  {page.label}
                </Link>
              </Hint>
            ))}
            <button type="button" onClick={() => setTourStop(0)} className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:text-foreground">
              <Compass className="size-4" />
              Take the tour
            </button>
          </nav>
          <section className="min-h-0 flex-1 space-y-0.5 overflow-y-auto">
            <p className="px-2 pb-1 text-xs text-muted-foreground">Incidents</p>
            {incidents.data?.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  selectInvestigation(item.id)
                  void navigate({ to: "/app" })
                }}
                className={cn("flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-sidebar-accent", item.id === current && "bg-sidebar-accent/60")}
              >
                {item.status === "running" ? (
                  <Spinner className="mt-1 size-3 text-brand" />
                ) : (
                  <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", item.incident_status === "resolved" ? "bg-emerald-600" : "bg-brand")} title={item.incident_status} />
                )}
                <span className="min-w-0">
                  <span className="line-clamp-2 leading-snug">{item.title}</span>
                  <span className="font-mono text-[10px] text-muted-foreground">{item.incident}</span>
                </span>
              </button>
            ))}
            {incidents.data?.length === 0 && <p className="px-2 text-xs text-muted-foreground">None yet.</p>}
            {incidents.isPending && (
              <div role="status" aria-label="Loading incidents" className="space-y-3 px-2 pt-1">
                <Skeleton className="h-8" />
                <Skeleton className="h-8" />
              </div>
            )}
            {incidents.isError && <p className="px-2 text-xs text-destructive">Cannot reach the server. Retrying…</p>}
          </section>
          <div className="flex items-center gap-2 border-t px-2 pt-3">
            <span className="grid size-7 shrink-0 place-items-center rounded-full bg-foreground text-xs font-medium text-background">{user.name[0]}</span>
            <span className="min-w-0 flex-1 leading-tight">
              <span className="block truncate text-sm font-medium">{user.name}</span>
              <span className="block truncate text-[11px] text-muted-foreground">{`${user.role} · ${tenant}`}</span>
            </span>
            <ThemeToggle />
            <button
              type="button"
              title="Sign out"
              aria-label="Sign out"
              onClick={() => {
                writeSession(null)
                void navigate({ to: "/" })
              }}
              className="rounded-md p-1.5 text-muted-foreground hover:bg-sidebar-accent hover:text-foreground"
            >
              <LogOut className="size-4" />
            </button>
          </div>
        </aside>
        <main className="min-h-0 overflow-y-auto">
          <Outlet />
        </main>
      </div>
      <CommandDialog open={palette} onOpenChange={setPalette} title="Search and commands" description="Find anything in the company graph, fire a scenario or move around">
        <Command>
          <CommandInput value={query} onValueChange={setQuery} placeholder="Search people, services, customers, changes…" />
          <CommandList>
          {matches.isFetching && (
            <p role="status" className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
              <Spinner className="size-3" />
              Searching the graph…
            </p>
          )}
            <CommandEmpty>Nothing matches.</CommandEmpty>
            {matches.data && matches.data.length > 0 && (
              <CommandGroup heading="In the graph">
                {matches.data.slice(0, 8).map((match) => (
                  <CommandItem key={`${match.kind}:${match.id}`} value={`${query} ${match.kind}:${match.id}`} onSelect={() => run(() => openEntity(`${match.kind}:${match.id}`))}>
                    <span className="w-24 shrink-0 text-xs text-muted-foreground">{match.kind}</span>
                    <span className="truncate">{match.name}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
            {scenarios.data && scenarios.data.length > 0 && (
              <>
                <CommandGroup heading="Fire an alert">
                  {scenarios.data.map((scenario) => (
                    <CommandItem
                      key={scenario.id}
                      onSelect={() =>
                        run(() =>
                          fire.mutate({
                            path: `/${tenant}/scenarios/${scenario.id}/fire`,
                          }),
                        )
                      }
                    >
                      {`Scenario ${scenario.id}: ${scenario.title}`}
                    </CommandItem>
                  ))}
                </CommandGroup>
                <CommandGroup heading="Demo company">
                  <CommandItem onSelect={() => run(() => seed.mutate({ path: `/tenants/${tenant}/seed` }))}>{`Reset ${tenant} to its starting state`}</CommandItem>
                </CommandGroup>
              </>
            )}
            <CommandGroup heading="Go to">
              {PAGES.map((page) => (
                <CommandItem key={page.to} onSelect={() => run(() => void navigate({ to: page.to }))}>
                  {page.label}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </CommandDialog>
      <EntityDrawer reference={entity} onClose={() => openEntity(null)} />
      <RecordTraceDrawer record={record} onClose={() => openRecord(null)} />
      <Tour stop={tourStop} onStop={setTourStop} />
      <Toaster theme={dark ? "dark" : "light"} position="bottom-left" />
    </WorkspaceContext.Provider>
  )
}
