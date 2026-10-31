import { useQuery } from "@tanstack/react-query"
import { BadgeCheck, Lock } from "lucide-react"
import { useState } from "react"

import { Connections } from "@/components/connections"
import { KIND_COLOR } from "@/components/ref-chip"
import { Problem, SkeletonLines } from "@/components/status"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { RefChip } from "@/components/ref-chip"
import { get, type Entity, type Row } from "@/lib/api"
import { splitRef, usePost, useWorkspace } from "@/lib/workspace"

export function EntityDrawer({ reference, onClose }: { reference: string | null; onClose: () => void }) {
  const { tenant } = useWorkspace()
  const target = reference ? splitRef(reference) : null
  const entity = useQuery({
    queryKey: [tenant, "entity", reference],
    queryFn: () => get<Entity>(`/${tenant}/entities/${target!.kind}/${encodeURIComponent(target!.id)}`),
    enabled: target !== null,
  })
  const title = String(entity.data?.props.name ?? target?.id ?? "")
  return (
    <Sheet open={reference !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="gap-0 overflow-y-auto data-[side=right]:w-[46rem] data-[side=right]:max-w-full data-[side=right]:sm:max-w-none">
        <SheetHeader className="flex-row items-center gap-3">
          <span className="grid size-11 shrink-0 place-items-center rounded-full text-sm font-medium text-white" style={{ background: KIND_COLOR[target?.kind ?? ""] ?? "#7b766b" }}>
            {initials(title)}
          </span>
          <div className="min-w-0">
            <SheetTitle className="truncate text-lg">{title}</SheetTitle>
            <SheetDescription>{[target?.kind, entity.data?.props.role, entity.data?.props.email].filter(Boolean).join(" · ")}</SheetDescription>
          </div>
        </SheetHeader>
        {entity.isError && <Problem error={entity.error} retry={() => void entity.refetch()} className="mx-4" />}
        {entity.isPending && target && <SkeletonLines label={`Loading ${target.id}`} count={8} className="px-4" />}
        {entity.data && <EntityBody entity={entity.data} />}
      </SheetContent>
    </Sheet>
  )
}

const HEADER_PROPS = ["id", "name", "role", "email", "code", "hash", "findings", "owner", "verified_by", "verified_at", "verify_days"]

const initials = (name: string) => name.split(/[\s-]+/).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("")
const readable = (key: string) => key.charAt(0).toUpperCase() + key.slice(1).replaceAll("_", " ")

function EntityBody({ entity }: { entity: Entity }) {
  const details = Object.entries(entity.props).filter(([key]) => !HEADER_PROPS.includes(key))
  return (
    <div className="space-y-6 px-4 pb-6 text-sm">
      <section className="space-y-2">
        <h3 className="text-xs font-medium text-muted-foreground">Connections</h3>
        <Connections key={`${entity.kind}:${entity.id}`} entity={entity} />
      </section>
      <Standing entity={entity} />
      <Verification entity={entity} />
      <History entity={entity} />
      {entity.kind === "PR" && <Reach pr={entity.id} />}
      {typeof entity.props.code === "string" && entity.props.code && (
        <section className="space-y-2">
          <h3 className="text-xs font-medium text-muted-foreground">{`Code, from line ${entity.props.line} of ${entity.props.path}`}</h3>
          <pre className="max-h-72 overflow-auto rounded-xl bg-foreground p-3 font-mono text-xs leading-relaxed text-background">{entity.props.code}</pre>
        </section>
      )}
      {details.length > 0 && (
        <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1.5">
          {details.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="text-muted-foreground">{readable(key)}</dt>
              <dd className="break-words">
                {typeof value === "string" && value.startsWith("https://") ? (
                  <a href={value} target="_blank" rel="noreferrer" className="underline underline-offset-2 hover:text-brand">
                    {value}
                  </a>
                ) : Array.isArray(value) ? (
                  value.join(", ")
                ) : (
                  String(value)
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}
      <section className="space-y-2">
        <h3 className="text-xs font-medium text-muted-foreground">Where this comes from</h3>
        {entity.sources.map((source) => (
          <div key={source.record} className="rounded-md border bg-card p-2.5">
            <div className="flex justify-between gap-2 text-xs text-muted-foreground">
              <span>{source.source}</span>
              <span className="truncate font-mono">{source.uri}</span>
            </div>
            {source.quote && <blockquote className="mt-1.5 border-l-2 border-brand pl-2 text-sm text-muted-foreground">{source.quote}</blockquote>}
            {source.visibility !== "org" && <Readers source={source} />}
          </div>
        ))}
        {entity.sources.length === 0 && <p className="text-muted-foreground">Created by an investigation, not by a source.</p>}
      </section>
    </div>
  )
}

function Readers({ source }: { source: Entity["sources"][number] }) {
  const { tenant, user } = useWorkspace()
  const share = usePost()
  if (source.visibility === "shared") return <p className="mt-2 text-xs text-muted-foreground">Private mail or chat that someone on it shared with everyone.</p>
  return (
    <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <Lock className="size-3.5 shrink-0" />
      {`Only ${source.readers.join(", ")} can read this.`}
      {source.readers.includes(user.name) && (
        <Button size="xs" variant="outline" className="rounded-full" disabled={share.isPending} onClick={() => share.mutate({ path: `/${tenant}/share`, body: { record: source.record, user: user.id } })}>
          Share with everyone
        </Button>
      )}
    </p>
  )
}

const KEEP_FOR = [
  { days: "30", label: "30 days" },
  { days: "90", label: "90 days" },
  { days: "180", label: "6 months" },
  { days: "365", label: "1 year" },
  { days: "", label: "until it changes" },
]

function Verification({ entity }: { entity: Entity }) {
  const { tenant, user } = useWorkspace()
  const verify = usePost()
  const [days, setDays] = useState("90")
  const trust = entity.trust
  if (!trust) return null
  const by = trust.verified_at ? `Verified by ${trust.verified_by} on ${day(trust.verified_at)}` : ""
  const standing = {
    unverified: "Nobody has verified this",
    verified: `${by}, ${trust.due_at ? `good until ${day(trust.due_at)}` : "until its source changes"}`,
    expired: `${by}. That ran out on ${trust.due_at ? day(trust.due_at) : ""}`,
    changed: `${by}, but its source changed after that`,
  }[trust.state]
  return (
    <section className="space-y-3 rounded-2xl bg-muted p-4">
      <p className="flex items-center gap-2 font-medium">
        <BadgeCheck className={`size-4 shrink-0 ${trust.state === "verified" ? "text-water" : "text-muted-foreground"}`} />
        {standing}
      </p>
      {trust.owner && trust.owner !== user.id ? (
        <p className="flex flex-wrap items-center gap-1.5 text-muted-foreground">
          Only its owner can verify it
          <RefChip reference={`Person:${trust.owner}`} />
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-muted-foreground">
            {trust.owner ? "You own this. Still right for" : "Nobody owns this. Verify it and it is yours, for"}
            <select value={days} onChange={(event) => setDays(event.target.value)} className="rounded-full border bg-background px-2.5 py-1 text-foreground">
              {KEEP_FOR.map((option) => (
                <option key={option.days} value={option.days}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <Button size="sm" className="rounded-full" disabled={verify.isPending} onClick={() => verify.mutate({ path: `/${tenant}/verify`, body: { kind: entity.kind, id: entity.id, user: user.id, days: days ? Number(days) : null } })}>
            Verify
          </Button>
        </div>
      )}
    </section>
  )
}

const HISTORY_SHOWN = 12
const day = (moment: string) => moment.slice(0, 10)
const phrase = (relation: string) => relation.toLowerCase().replaceAll("_", " ")

/** Whether a promise or decision still holds, and what replaced it, read from its dates and SUPERSEDES links. */
function Standing({ entity }: { entity: Entity }) {
  if (entity.kind !== "Commitment" && entity.kind !== "Decision") return null
  const replacement = entity.neighbours.find((other) => other.relation === "SUPERSEDES" && !other.outgoing)
  const replaced = entity.neighbours.filter((other) => other.relation === "SUPERSEDES" && other.outgoing)
  const ended = typeof entity.props.valid_to === "string" ? entity.props.valid_to : null
  const over = entity.props.status === "superseded" || (ended !== null && ended < new Date().toISOString())
  return (
    <section className="space-y-2 rounded-2xl bg-muted p-4">
      <p className="flex items-center gap-2 font-medium">
        <span className={`size-2 rounded-full ${over ? "border border-foreground/50" : "bg-water"}`} />
        {over ? `No longer in force${ended ? ` since ${day(ended)}` : ""}` : `In force${ended ? ` until ${day(ended)}` : ""}`}
      </p>
      {replacement && (
        <p className="flex flex-wrap items-center gap-1.5 text-muted-foreground">
          {over ? "Replaced by" : "A newer one may replace it, waiting for a human"}
          <RefChip reference={`${replacement.kind}:${replacement.id}`} label={replacement.name} />
        </p>
      )}
      {replaced.map((older) => (
        <p key={older.id} className="flex flex-wrap items-center gap-1.5 text-muted-foreground">
          It replaces
          <RefChip reference={`${older.kind}:${older.id}`} label={older.name} />
        </p>
      ))}
    </section>
  )
}

function History({ entity }: { entity: Entity }) {
  const dated = entity.neighbours.filter((other) => other.at && other.kind !== "Turn").sort((a, b) => b.at!.localeCompare(a.at!))
  if (dated.length < 2) return null
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-medium text-muted-foreground">{`History, newest first${dated.length > HISTORY_SHOWN ? ` · ${HISTORY_SHOWN} of ${dated.length}` : ""}`}</h3>
      <ol className="space-y-1.5 border-l pl-4">
        {dated.slice(0, HISTORY_SHOWN).map((other) => (
          <li key={`${other.relation}:${other.kind}:${other.id}:${other.at}`} className="relative flex flex-wrap items-center gap-1.5">
            <span className="absolute top-2 -left-[19px] size-1.5 rounded-full bg-foreground/40" />
            <span className="w-20 shrink-0 text-xs text-muted-foreground tabular-nums">{day(other.at!)}</span>
            <span className="text-xs text-muted-foreground">{phrase(other.relation)}</span>
            <RefChip reference={`${other.kind}:${other.id}`} label={other.name} />
          </li>
        ))}
      </ol>
    </section>
  )
}

const count = (rows: Row[], column: string) => new Set(rows.flatMap((row) => row[column] as string[])).size
const some = (amount: number, one: string) => `${amount} ${amount === 1 ? one : `${one}s`}`

function Reach({ pr }: { pr: string }) {
  const { tenant } = useWorkspace()
  const reach = useQuery({ queryKey: [tenant, "reach", pr], queryFn: () => get<Row[]>(`/${tenant}/prs/${pr}/reach`) })
  if (!reach.data || reach.data.length === 0) return null
  const rows = reach.data
  const symbols = rows[0].symbols as string[]
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-medium text-muted-foreground">What this change can reach</h3>
      <div className="rounded-2xl bg-muted p-4">
        <p className="leading-relaxed">
          {`${symbols.length > 0 ? `It touches ${some(symbols.length, "symbol")} in the code. From there one` : "One"} graph query reaches ${some(rows.length, "service")}, ${some(count(rows, "customers"), "customer")}, ${some(count(rows, "slas"), "uptime guarantee")} and ${some(count(rows, "commitments"), "promise")}.`}
        </p>
        <ul className="mt-3 space-y-1.5">
          {rows.map((row) => (
            <li key={String(row.service)} className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              <span className="w-20 shrink-0">{row.hops === 0 ? "changed" : `${some(Number(row.hops), "step")} away`}</span>
              <RefChip reference={`Service:${row.service}`} />
              {(row.customers as string[]).length > 0 && <span>{some((row.customers as string[]).length, "customer")}</span>}
              {(row.commitments as string[]).length > 0 && <span>{`· ${some((row.commitments as string[]).length, "promise")}`}</span>}
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
