import { motion } from "motion/react"
import { useState } from "react"

import { KIND_COLOR } from "@/components/ref-chip"
import type { Entity } from "@/lib/api"
import { cn } from "@/lib/utils"
import { useWorkspace } from "@/lib/workspace"

type Neighbour = Entity["neighbours"][number]
type Row = { label: string } | { neighbour: Neighbour } | { more: number; group: string }

const ROW = 30
const GROUP_SHOWN = 4
const SIDE = 31
const CENTRE_FROM = 37.5
const CENTRE_TO = 62.5
// Ripple's own working notes about a thing, counted under the graph instead of drawn in it.
const WORKING_KINDS: Record<string, string> = { Turn: "chat turns", Finding: "investigation findings", Hypothesis: "hypotheses" }

const words = (relation: string) => relation.toLowerCase().replaceAll("_", " ")
const keyOf = (neighbour: Neighbour) => `${neighbour.outgoing}:${neighbour.relation}:${neighbour.kind}:${neighbour.id}`

function rows(neighbours: Neighbour[], open: Set<string>): Row[] {
  const relations = [...new Set(neighbours.map((neighbour) => neighbour.relation))]
  return relations.flatMap((relation): Row[] => {
    const members = neighbours.filter((neighbour) => neighbour.relation === relation)
    const group = `${members[0].outgoing}:${relation}`
    const shown = open.has(group) || members.length <= GROUP_SHOWN + 1 ? members : members.slice(0, GROUP_SHOWN)
    return [{ label: words(relation) }, ...shown.map((neighbour) => ({ neighbour })), ...(shown.length < members.length ? [{ more: members.length - shown.length, group }] : [])]
  })
}

export function Connections({ entity }: { entity: Entity }) {
  const { openEntity } = useWorkspace()
  const [hover, setHover] = useState<Neighbour | null>(null)
  const [open, setOpen] = useState<Set<string>>(new Set())
  const name = String(entity.props.name ?? entity.id)
  const drawn = entity.neighbours.filter((neighbour) => !(neighbour.kind in WORKING_KINDS))
  const sides = [rows(drawn.filter((neighbour) => !neighbour.outgoing), open), rows(drawn.filter((neighbour) => neighbour.outgoing), open)]
  const height = Math.max(sides[0].length, sides[1].length, 3) * ROW
  const notes = Object.entries(WORKING_KINDS).flatMap(([kind, label]) => {
    const count = entity.neighbours.filter((neighbour) => neighbour.kind === kind).length
    return count ? [`${count} ${label}`] : []
  })
  if (drawn.length === 0) return <p className="text-muted-foreground">Nothing else in the graph is connected to this yet.</p>
  return (
    <div>
      <div className="relative rounded-2xl bg-muted/60 px-3" style={{ height: height + 24 }}>
        <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" aria-hidden className="absolute inset-x-3 top-3" style={{ height, width: "calc(100% - 1.5rem)" }}>
          {sides.flatMap((side, right) =>
            side.map((row, index) => {
              if (!("neighbour" in row)) return null
              const y = (height - side.length * ROW) / 2 + index * ROW + ROW / 2
              const [from, to] = right ? [100 - SIDE, CENTRE_TO] : [SIDE, CENTRE_FROM]
              const bend = (from + to) / 2
              const lit = hover !== null && keyOf(hover) === keyOf(row.neighbour)
              return (
                <motion.path
                  key={keyOf(row.neighbour)}
                  d={`M ${from} ${y} C ${bend} ${y}, ${bend} ${height / 2}, ${to} ${height / 2}`}
                  fill="none"
                  stroke={lit ? "var(--brand)" : (KIND_COLOR[row.neighbour.kind] ?? "#7b766b")}
                  strokeWidth={lit ? 2 : 1.25}
                  vectorEffect="non-scaling-stroke"
                  initial={{ pathLength: 0, opacity: 0 }}
                  animate={{ pathLength: 1, opacity: lit ? 1 : hover ? 0.12 : 0.45 }}
                  transition={{ pathLength: { duration: 0.6, delay: index * 0.02 }, opacity: { duration: 0.15 } }}
                />
              )
            }),
          )}
        </svg>
        {sides.map((side, right) => (
          <div key={right} className={cn("absolute top-3 flex flex-col justify-center", right ? "right-3" : "left-3")} style={{ height, width: `calc((100% - 1.5rem) * ${SIDE / 100})` }}>
            {side.map((row, index) =>
              "label" in row ? (
                <p key={`label:${row.label}`} className={cn("flex shrink-0 items-end truncate pb-1 text-[11px] text-muted-foreground", !right && "justify-end")} style={{ height: ROW }}>
                  {row.label}
                </p>
              ) : "more" in row ? (
                <div key={`more:${row.group}`} className={cn("flex shrink-0 items-center", !right && "justify-end")} style={{ height: ROW }}>
                  <button type="button" onClick={() => setOpen((current) => new Set(current).add(row.group))} className="rounded-full px-2 py-0.5 text-xs text-muted-foreground hover:bg-background hover:text-foreground">
                    {`+${row.more} more`}
                  </button>
                </div>
              ) : (
                <div key={keyOf(row.neighbour)} className={cn("flex shrink-0 items-center", !right && "justify-end")} style={{ height: ROW }}>
                  <motion.button
                    type="button"
                    initial={{ opacity: 0, x: right ? 8 : -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: index * 0.02 }}
                    onClick={() => openEntity(`${row.neighbour.kind}:${row.neighbour.id}`)}
                    onMouseEnter={() => setHover(row.neighbour)}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover(row.neighbour)}
                    onBlur={() => setHover(null)}
                    className="flex max-w-full items-center gap-1.5 rounded-full border bg-background px-2.5 py-1 text-xs hover:border-foreground"
                  >
                    <span className="size-2 shrink-0 rounded-full" style={{ background: KIND_COLOR[row.neighbour.kind] ?? "#7b766b" }} />
                    <span className="truncate font-medium">{row.neighbour.name}</span>
                  </motion.button>
                </div>
              ),
            )}
          </div>
        ))}
        <div className="absolute top-1/2 -translate-y-1/2 rounded-2xl bg-ink px-3 py-2.5 text-center text-background" style={{ left: `calc(0.75rem + (100% - 1.5rem) * ${CENTRE_FROM / 100})`, width: `calc((100% - 1.5rem) * ${(CENTRE_TO - CENTRE_FROM) / 100})` }}>
          <p className="text-[11px] opacity-60">{entity.kind}</p>
          <p className="line-clamp-3 text-sm font-medium break-words">{name}</p>
        </div>
      </div>
      <p className="mt-2.5 min-h-10 text-sm text-muted-foreground">
        {hover ? (
          <>
            <span className="font-medium text-foreground">{hover.outgoing ? name : hover.name}</span>
            {` ${words(hover.relation)} `}
            <span className="font-medium text-foreground">{hover.outgoing ? hover.name : name}</span>
            {` · ${hover.kind}`}
            {hover.quote && <span className="mt-1 line-clamp-2 block border-l-2 border-brand pl-2">{hover.quote}</span>}
          </>
        ) : (
          `${drawn.length} ${drawn.length === 1 ? "connection" : "connections"}. Left: what points to ${name}. Right: what ${name} points to. Point at one to read the link, click to open it.${notes.length ? ` Also referenced by ${notes.join(", ")}.` : ""}`
        )}
      </p>
    </div>
  )
}
