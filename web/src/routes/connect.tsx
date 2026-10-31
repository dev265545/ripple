import { useQuery } from "@tanstack/react-query"
import { FileUp } from "lucide-react"
import { useState, type ChangeEvent } from "react"
import { toast } from "sonner"

import { BrandIcon } from "@/components/brand"
import { ExportUpload } from "@/components/export-upload"
import { LivePull } from "@/components/live-pull"
import { InboxConnect } from "@/components/inbox-connect"
import { WatchConnect } from "@/components/watching"
import { Eyebrow, PageHeader, UnderlineTabs } from "@/components/page"
import { RefChip } from "@/components/ref-chip"
import { RippleButton } from "@/components/ripple-button"
import { Loading, Problem, Skeleton, SkeletonRows, Spinner } from "@/components/status"
import { BlurFade } from "@/components/ui/blur-fade"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { NumberTicker } from "@/components/ui/number-ticker"
import { Textarea } from "@/components/ui/textarea"
import { get, type AddedDocument, type Connector, type Overview, type SourceRecord } from "@/lib/api"
import { cn, when } from "@/lib/utils"
import { useModel, usePost, useWorkspace } from "@/lib/workspace"

type Tab = "connectors" | "add" | "records"

const STATUS: Record<NonNullable<Connector["status"]>, { label: string; dot: string }> = {
  connected: { label: "Connected", dot: "bg-water" },
  listening: { label: "Listening", dot: "bg-brand animate-pulse" },
  ready: { label: "Ready", dot: "border border-foreground/50" },
  planned: { label: "Planned", dot: "border border-dashed border-foreground/40" },
}

export function Connect() {
  const { tenant } = useWorkspace()
  const [tab, setTab] = useState<Tab>("connectors")
  const [source, setSource] = useState<string | null>(null)
  const connectors = useQuery({ queryKey: [tenant, "connectors"], queryFn: () => get<Connector[]>(`/${tenant}/connectors`) })
  const overview = useQuery({ queryKey: [tenant, "overview"], queryFn: () => get<Overview>(`/${tenant}/overview`) })
  const connected = connectors.data?.filter((connector) => connector.status === "connected") ?? []

  function browse(id: string) {
    setSource(id)
    setTab("records")
  }

  return (
    <div className="mx-auto max-w-5xl space-y-8 px-10 py-8">
      <PageHeader eyebrow="Company graph" title="Connect" subtitle="Everything Ripple knows was read from a record you can open. Nothing here is typed in by hand." />
      {overview.data && connectors.data ? (
        <Flow connected={connected} overview={overview.data} />
      ) : (
        !overview.isError && (
          <Loading label="Loading the company graph totals" className="grid grid-cols-4 divide-x rounded-2xl border">
            {Array.from({ length: 4 }, (_, index) => (
              <div key={index} className="space-y-2 px-5 py-4">
                <Skeleton className="h-8 w-16" />
                <Skeleton className="h-3.5 w-28" />
              </div>
            ))}
          </Loading>
        )
      )}
      {overview.isError && <Problem error={overview.error} retry={() => void overview.refetch()} />}
      <UnderlineTabs<Tab>
        tabs={[
          { id: "connectors", label: "Connectors", count: connectors.data?.length },
          { id: "add", label: "Add a document" },
          { id: "records", label: "Records" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "connectors" && connectors.data && <Gallery connectors={connectors.data} onBrowse={browse} />}
      {tab === "connectors" && connectors.isPending && <SkeletonRows label="Loading connectors" count={6} />}
      {tab === "connectors" && connectors.isError && <Problem error={connectors.error} retry={() => void connectors.refetch()} />}
      {tab === "add" && <AddDocument onBrowse={() => browse("uploads")} />}
      {tab === "records" && <Records connected={connected} source={source ?? connected[0]?.source ?? null} onSource={setSource} />}
    </div>
  )
}

function Flow({ connected, overview }: { connected: Connector[]; overview: Overview }) {
  const stages = [
    { value: connected.length, label: "Sources connected" },
    { value: connected.reduce((total, connector) => total + (connector.records ?? 0), 0), label: "Records read" },
    { value: overview.nodes.reduce((total, row) => total + row.count, 0), label: `Things known, ${overview.nodes.length} kinds` },
    { value: overview.edges, label: "Relationships" },
  ]
  return (
    <dl className="grid grid-cols-4 divide-x rounded-2xl border">
      {stages.map((stage) => (
        <div key={stage.label} className="px-5 py-4">
          <dd className="text-3xl font-semibold tracking-tight">
            <NumberTicker value={stage.value} className="text-foreground" />
          </dd>
          <dt className="mt-0.5 text-sm text-muted-foreground">{stage.label}</dt>
        </div>
      ))}
    </dl>
  )
}

function Gallery({ connectors, onBrowse }: { connectors: Connector[]; onBrowse: (source: string) => void }) {
  const { tenant } = useWorkspace()
  const [category, setCategory] = useState("All")
  const sync = usePost<{ records: number; changed: number }>((stats) => toast.success(`Read ${stats.records} records, ${stats.changed} changed`))
  const categories = ["All", ...new Set(connectors.map((connector) => connector.category))]
  const shown = connectors.filter((connector) => category === "All" || connector.category === category)
  return (
    <div className="space-y-4">
      <div className="inline-flex rounded-full bg-muted p-1">
        {categories.map((name) => (
          <button
            key={name}
            type="button"
            aria-pressed={name === category}
            onClick={() => setCategory(name)}
            className={cn("rounded-full px-3.5 py-1 text-sm font-medium text-muted-foreground", name === category && "bg-background text-foreground shadow-xs")}
          >
            {name}
          </button>
        ))}
      </div>
      <div className="divide-y rounded-2xl border">
        {shown.map((connector) => {
          const status = STATUS[connector.status ?? "planned"]
          const live = connector.status === "connected"
          return (
            <div key={connector.id} className={cn("flex items-center gap-4 px-4 py-3.5", connector.status === "planned" && "opacity-55")}>
              <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-muted">
                {connector.systems[0] ? <BrandIcon system={connector.systems[0]} className="size-[18px]" /> : <FileUp className="size-[18px]" />}
              </span>
              <div className="min-w-0 flex-1">
                <p className="flex items-baseline gap-2">
                  <span className="font-medium">{connector.name}</span>
                  <span className="truncate text-sm text-muted-foreground">{connector.systems.join(", ")}</span>
                </p>
                <p className="truncate text-sm text-muted-foreground">
                  {`${connector.status === "planned" ? "Will read" : "Reads"} ${connector.reads} · makes ${connector.produces.join(", ")}`}
                </p>
              </div>
              <div className="w-36 shrink-0 text-right text-xs text-muted-foreground">
                {live && <p>{`${connector.records} records, ${connector.nodes} nodes`}</p>}
                {live && connector.last_sync && <p>{when(connector.last_sync)}</p>}
              </div>
              <span className="flex w-28 shrink-0 items-center gap-1.5 text-sm">
                <span className={cn("size-2 rounded-full", status.dot)} />
                {status.label}
              </span>
              <div className="flex w-60 shrink-0 flex-wrap items-center justify-end gap-1.5">
                {connector.status === "listening" && <code className="truncate rounded-full bg-muted px-2.5 py-1 text-[11px] text-muted-foreground">{`POST /api/${tenant}/hooks/alerts`}</code>}
                {live && (
                  <>
                    <Button size="sm" variant="ghost" onClick={() => onBrowse(connector.source!)}>
                      Records
                    </Button>
                    {!connector.inbox && (
                      <Button size="sm" variant="outline" disabled={sync.isPending} onClick={() => sync.mutate({ path: `/${tenant}/sources/${connector.source}/sync` })}>
                        {sync.isPending && sync.variables.path.includes(`/${connector.source}/`) && <Spinner />}
                        Sync
                      </Button>
                    )}
                  </>
                )}
                {connector.inbox && <InboxConnect tenant={tenant} connector={connector} onBrowse={() => onBrowse(connector.source!)} />}
                {connector.live && <LivePull tenant={tenant} connector={connector} />}
                {connector.watch && <WatchConnect tenant={tenant} connector={connector} />}
                {connector.file && (
                  <ExportUpload
                    tenant={tenant}
                    connector={connector}
                    example={!live}
                    onRead={(stats) => toast.success(`Read ${stats.records} records, ${stats.changed} changed`)}
                    onError={(message) => toast.error(message)}
                  />
                )}
              </div>
            </div>
          )
        })}
      </div>
      <p className="text-xs text-muted-foreground">
A connected GitHub repository is watched: Ripple keeps checking it for new changes and for issues labelled incident. Gmail, Google files and Slack are read once when you connect them and nothing is kept between reads. The other connectors read each system's export file, and uploading a new export replaces the one a connector reads.
      </p>
    </div>
  )
}

function AddDocument({ onBrowse }: { onBrowse: () => void }) {
  const { tenant, openRecord } = useWorkspace()
  const model = useModel()
  const [name, setName] = useState("")
  const [text, setText] = useState("")
  const [added, setAdded] = useState<AddedDocument | null>(null)
  const add = usePost<AddedDocument>(setAdded)

  async function load(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    setName(file.name)
    setText(await file.text())
  }

  return (
    <div className="grid gap-10 lg:grid-cols-2">
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault()
          add.mutate({ path: `/${tenant}/documents`, body: { name, text } })
        }}
      >
        <p className="text-sm text-muted-foreground">
          Paste meeting notes, a customer email, a runbook. Ripple files it as a source and links it to every service, person, customer, change and decision it names.
        </p>
        <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-dashed border-input px-3 py-2.5 text-sm text-muted-foreground hover:border-ring hover:text-foreground">
          <FileUp className="size-4" />
          Choose a text file (.txt, .md, .eml, .csv, .json)
          <input type="file" accept=".txt,.md,.eml,.csv,.json,text/*" className="sr-only" onChange={load} />
        </label>
        <Input required value={name} onChange={(event) => setName(event.target.value)} placeholder="Title, for example: Larkspur call notes" />
        <Textarea required value={text} onChange={(event) => setText(event.target.value)} placeholder="Paste the document here…" className="min-h-64 font-mono text-xs" />
        <RippleButton type="submit" disabled={add.isPending} className="rounded-full px-4">
          {add.isPending && <Spinner />}
          {add.isPending ? "Reading and linking…" : "Add to the graph"}
        </RippleButton>
      </form>
      <div>
        {added ? (
          <BlurFade key={added.record} className="space-y-4">
            <Eyebrow>{added.changed ? "Filed and linked" : "Already filed, nothing changed"}</Eyebrow>
            <h3 className="text-xl font-semibold">{added.title}</h3>
            <p className="text-sm text-muted-foreground">
              {added.linked.length > 0 ? `It names ${added.linked.length} things Ripple already knows:` : "It names nothing Ripple already knows, so it stands alone for now."}
            </p>
            {added.linked.map((entity) => (
              <div key={`${entity.kind}:${entity.id}`} className="space-y-1 border-b pb-3">
                <RefChip reference={`${entity.kind}:${entity.id}`} label={entity.name} />
                <blockquote className="border-l-2 border-brand pl-2 text-sm text-muted-foreground">{entity.quote}</blockquote>
              </div>
            ))}
            {added.promises.length > 0 && <p className="text-sm text-muted-foreground">{`${added.model} found ${added.promises.length === 1 ? "a promise" : `${added.promises.length} promises`} in it, each kept with its exact sentence:`}</p>}
            {added.promises.map((promise) => (
              <div key={promise.id} className="space-y-1 border-b pb-3">
                <p className="text-sm font-medium">{`${promise.made_by_name} promised ${promise.customer_name}: ${promise.text}`}</p>
                <blockquote className="border-l-2 border-brand pl-2 text-sm text-muted-foreground">{promise.quote}</blockquote>
              </div>
            ))}
            {added.links.length > 0 && <p className="text-sm text-muted-foreground">{`${added.model} read ${added.links.length === 1 ? "one link" : `${added.links.length} links`} out of it, each kept with its exact sentence:`}</p>}
            {added.links.map((link) => (
              <div key={`${link.from.join(":")} ${link.type} ${link.to.join(":")}`} className="space-y-1 border-b pb-3">
                <p className="flex flex-wrap items-center gap-1.5 text-sm">
                  <RefChip reference={link.from.join(":")} />
                  <span className="text-muted-foreground">{link.type.toLowerCase().replaceAll("_", " ")}</span>
                  <RefChip reference={link.to.join(":")} />
                </p>
                <blockquote className="border-l-2 border-brand pl-2 text-sm text-muted-foreground">{link.quote}</blockquote>
              </div>
            ))}
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => openRecord(added.record)}>
                Open the record trace
              </Button>
              <Button variant="ghost" size="sm" onClick={onBrowse}>
                All pasted documents
              </Button>
            </div>
          </BlurFade>
        ) : (
          <div className="space-y-3 rounded-2xl bg-muted p-6 text-sm text-muted-foreground">
            <Eyebrow>How linking works here</Eyebrow>
            <p>A name is linked when it appears in the text exactly as the graph knows it: an id such as PR-412, or a name such as Larkspur Retail.</p>
            <p>The line it appears on is kept as the quote behind the link, so you can always see why two things are connected.</p>
            <p>
              {model
                ? `${model} also reads the text for what it defines: a contract and its uptime guarantee, an incident and its cause, a decision, a requirement, a promise to a customer. Each is kept only if its sentence is in the document word for word and what it points at is named in the document.`
                : "Matching is exact. Nicknames, typos and new facts stated in the prose are not picked up without a language model configured."}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

function Records({ connected, source, onSource }: { connected: Connector[]; source: string | null; onSource: (source: string) => void }) {
  const { tenant, openRecord } = useWorkspace()
  const records = useQuery({
    queryKey: [tenant, "records", source],
    queryFn: () => get<SourceRecord[]>(`/${tenant}/sources/${source}/records`),
    enabled: source !== null,
  })
  return (
    <div className="grid grid-cols-[13rem_1fr] gap-8">
      <nav className="space-y-0.5">
        {connected.map((connector) => (
          <button
            key={connector.id}
            type="button"
            onClick={() => onSource(connector.source!)}
            className={cn("flex w-full justify-between rounded-md px-2 py-1.5 text-left text-sm text-muted-foreground hover:text-foreground", connector.source === source && "bg-muted font-medium text-foreground")}
          >
            {connector.name}
            <span className="font-mono text-xs">{connector.records}</span>
          </button>
        ))}
      </nav>
      <div className="h-fit divide-y rounded-2xl border">
        {records.data?.map((record) => (
          <button key={record.id} type="button" onClick={() => openRecord(record.id)} className="flex w-full items-center gap-4 px-4 py-2.5 text-left text-sm hover:bg-muted/60">
            <span className="min-w-0 flex-1 truncate font-mono text-xs">{record.uri}</span>
            <span className="shrink-0 font-mono text-[10px] text-muted-foreground">{record.hash.slice(0, 8)}</span>
            <span className="w-20 shrink-0 text-right text-xs text-muted-foreground">{`${record.nodes} nodes`}</span>
            <span className="w-32 shrink-0 text-right text-xs text-muted-foreground">{when(record.fetched_at)}</span>
          </button>
        ))}
        {records.data?.length === 0 && <p className="p-4 text-sm text-muted-foreground">No records from this source yet.</p>}
        {source === null && <p className="p-4 text-sm text-muted-foreground">No source is connected yet.</p>}
        {source !== null && records.isPending && (
          <Loading label="Loading records" className="divide-y">
            {Array.from({ length: 6 }, (_, index) => (
              <div key={index} className="flex items-center gap-4 px-4 py-3">
                <Skeleton className="h-3.5 flex-1" />
                <Skeleton className="h-3.5 w-32" />
              </div>
            ))}
          </Loading>
        )}
        {records.isError && <Problem error={records.error} retry={() => void records.refetch()} className="m-3" />}
      </div>
    </div>
  )
}
