import { useMutation, useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Check, FileUp } from "lucide-react"
import { useState, type FormEvent, type ReactNode } from "react"

import { BrandIcon, Mark } from "@/components/brand"
import { LivePull } from "@/components/live-pull"
import { ExportUpload } from "@/components/export-upload"
import { RippleButton } from "@/components/ripple-button"
import { Loading, Skeleton, SkeletonRows, Spinner } from "@/components/status"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { get, post, type Connector, type Person, type SyncStats } from "@/lib/api"
import { cn } from "@/lib/utils"

type Outcome = { stats: SyncStats } | { error: string }

export function Setup() {
  const [tenant, setTenant] = useState(() => new URLSearchParams(window.location.search).get("company"))
  const people = useQuery({ queryKey: [tenant, "people"], queryFn: () => get<Person[]>(`/${tenant}/people`), enabled: tenant !== null })
  const canSignIn = (people.data?.length ?? 0) > 0

  function created(name: string) {
    window.history.replaceState(null, "", `/setup?company=${name}`)
    setTenant(name)
  }

  return (
    <div className="min-h-screen bg-muted px-4 py-10">
      <main className="mx-auto w-full max-w-3xl">
        <Link to="/" aria-label="Ripple home" className="mx-auto block w-fit">
          <Mark className="size-12 rounded-2xl shadow-md" />
        </Link>
        <h1 className="mt-6 text-center font-heading text-3xl">Set up a new company</h1>
        <p className="mx-auto mt-2 max-w-lg text-center text-[15px] text-muted-foreground">
          Ripple builds its graph from the export files of the tools you already run. Nothing is typed in by hand, and each company gets its own graph.
        </p>
        <div className="mt-8 space-y-4">
          <Step title="Name the company" done={tenant !== null}>
            {tenant === null ? <NameForm onCreated={created} /> : <p className="text-sm text-muted-foreground">{`Created. Its graph is ripple:${tenant}.`}</p>}
          </Step>
          <Step title="Load your systems" done={canSignIn} waiting={tenant === null}>
            {tenant && <Exports tenant={tenant} />}
          </Step>
          <Step title="Point your alerts at Ripple" waiting={tenant === null}>
            {tenant && <Alerts tenant={tenant} />}
          </Step>
          <Step title="Sign in" waiting={!canSignIn}>
            {tenant && canSignIn ? (
              <div className="flex flex-wrap items-center gap-4">
                <a href={`/login?company=${tenant}`} className="inline-flex h-10 items-center rounded-full bg-foreground px-5 text-sm font-medium text-background hover:bg-foreground/85">
                  {`Sign in to ${tenant}`}
                </a>
                <p className="text-sm text-muted-foreground">
                  {`${people.data!.length} people can sign in with their work email. Emails, wiki pages and contracts are added from Connect once you are in.`}
                </p>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Sign-in checks the HR directory, so upload that export first.</p>
            )}
          </Step>
        </div>
        <p className="mt-6 text-center text-sm text-muted-foreground">
          Already set up?{" "}
          <Link to="/login" className="font-medium text-foreground underline underline-offset-4">
            Sign in
          </Link>
        </p>
      </main>
    </div>
  )
}

function Step({ title, done, waiting, children }: { title: string; done?: boolean; waiting?: boolean; children: ReactNode }) {
  return (
    <section className={cn("rounded-3xl bg-background p-6 shadow-sm", waiting && "opacity-60")}>
      <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
        {title}
        {done && <Check className="size-4 text-water" aria-label="done" />}
      </h2>
      <div className="mt-3">{children}</div>
    </section>
  )
}

function NameForm({ onCreated }: { onCreated: (tenant: string) => void }) {
  const [name, setName] = useState("")
  const create = useMutation({
    mutationFn: () => post<{ tenant: string }>("/tenants", { name }),
    onSuccess: (company) => onCreated(company.tenant),
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate()
  }

  return (
    <form onSubmit={submit} className="space-y-2">
      <div className="flex gap-2">
        <Input required aria-label="Company name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Acme Payments" className="h-10" />
        <RippleButton type="submit" disabled={create.isPending} className="h-10 rounded-full px-5">
          {create.isPending && <Spinner />}
          {create.isPending ? "Creating…" : "Create company"}
        </RippleButton>
      </div>
      {create.isError && <p className="text-sm text-destructive">{create.error.message}</p>}
    </form>
  )
}

function Exports({ tenant }: { tenant: string }) {
  const connectors = useQuery({ queryKey: [tenant, "connectors"], queryFn: () => get<Connector[]>(`/${tenant}/connectors`) })
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({})
  const record = (id: string, outcome: Outcome) => setOutcomes((current) => ({ ...current, [id]: outcome }))
  if (connectors.isError) return <p className="text-sm text-destructive">{connectors.error.message}</p>
  return (
    <>
      <p className="text-sm text-muted-foreground">
        Upload the export each tool gives you; an example shows the exact columns and fields Ripple reads. Git is read straight from a GitHub repository. Start with the HR directory: it decides who can sign in.
      </p>
      {connectors.isPending && (
        <div className="mt-4">
          <SkeletonRows label="Loading connectors" count={5} />
        </div>
      )}
      <ul className={cn("mt-4 divide-y rounded-2xl border", connectors.isPending && "hidden")}>
        {connectors.data
          ?.filter((connector) => connector.file)
          .map((connector) => {
            const outcome = outcomes[connector.id]
            return (
              <li key={connector.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3">
                <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-muted">
                  {connector.systems[0] ? <BrandIcon system={connector.systems[0]} className="size-[18px]" /> : <FileUp className="size-[18px]" />}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{connector.name}</p>
                  <p className="truncate text-sm text-muted-foreground">{`${connector.file} · ${connector.reads}`}</p>
                </div>
                {connector.status === "connected" && <span className="text-sm text-muted-foreground">{`${connector.records} records`}</span>}
                <div className="flex gap-1.5">
                  {connector.live && <LivePull tenant={tenant} connector={connector} />}
                  <ExportUpload
                    tenant={tenant}
                    connector={connector}
                    example
                    onRead={(stats) => record(connector.id, { stats })}
                    onError={(error) => record(connector.id, { error })}
                  />
                </div>
                {outcome && "error" in outcome && <p className="w-full pl-14 text-sm text-destructive">{outcome.error}</p>}
                {outcome && "stats" in outcome && (
                  <p className="w-full pl-14 text-sm text-water">{`Read ${outcome.stats.records} records, ${outcome.stats.changed} new or changed.`}</p>
                )}
              </li>
            )
          })}
      </ul>
      <p className="mt-3 text-xs text-muted-foreground">GitHub is read live here and then watched for new changes and incident issues. Gmail, Slack and Google files are read live from Connect once you are signed in. The other tools are read from their export files.</p>
    </>
  )
}

function Alerts({ tenant }: { tenant: string }) {
  const services = useQuery({ queryKey: [tenant, "services"], queryFn: () => get<string[]>(`/${tenant}/services`) })
  const [service, setService] = useState<string | null>(null)
  const url = `${window.location.origin}/api/${tenant}/hooks/alerts`
  const test = useMutation({
    mutationFn: () =>
      post<{ investigation: string; opened: boolean }[]>(`/${tenant}/hooks/alerts`, {
        receiver: "ripple",
        status: "firing",
        alerts: [
          {
            status: "firing",
            labels: { alertname: "RippleSetupTest", service, severity: "critical" },
            annotations: { summary: `Setup test alert on ${service}` },
            startsAt: new Date().toISOString(),
          },
        ],
      }),
  })
  return (
    <div className="space-y-3 text-sm">
      <p className="text-muted-foreground">Add this URL as a webhook receiver in Alertmanager. Every firing alert opens an investigation on the service named in its labels.</p>
      <div className="flex items-center gap-2 rounded-xl bg-muted py-1.5 pr-1.5 pl-3">
        <code className="min-w-0 flex-1 truncate font-mono text-xs">{`POST ${url}`}</code>
        <Button size="sm" variant="outline" onClick={() => void navigator.clipboard.writeText(url)}>
          Copy
        </Button>
      </div>
      {services.isPending ? (
        <Loading label="Loading services" className="flex gap-1.5">
          <Skeleton className="h-7 w-28 rounded-full" />
          <Skeleton className="h-7 w-24 rounded-full" />
          <Skeleton className="h-7 w-32 rounded-full" />
        </Loading>
      ) : services.data && services.data.length > 0 ? (
        <>
          <p className="pt-1 font-medium">Send a test alert</p>
          <div className="flex flex-wrap gap-1.5">
            {services.data.map((name) => (
              <button
                key={name}
                type="button"
                aria-pressed={name === service}
                onClick={() => setService(name)}
                className={cn("rounded-full border px-3 py-1 text-muted-foreground", name === service && "border-foreground bg-foreground text-background")}
              >
                {name}
              </button>
            ))}
          </div>
          <Button variant="outline" disabled={service === null || test.isPending} onClick={() => test.mutate()}>
            {test.isPending && <Spinner />}
            {test.isPending ? "Sending…" : "Send test alert"}
          </Button>
          {test.isError && <p className="text-destructive">{test.error.message}</p>}
          {test.data?.map((result) => (
            <p key={result.investigation} className="text-water">
              {`${result.investigation} ${result.opened ? "opened" : "already covers this alert"}. It is in the incident room when you sign in.`}
            </p>
          ))}
        </>
      ) : (
        <p className="text-muted-foreground">Upload the service catalog to send a test alert from here.</p>
      )}
    </div>
  )
}
