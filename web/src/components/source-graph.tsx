import { motion } from "motion/react"
import { useMemo, useState } from "react"

import { BrandIcon } from "@/components/brand"
import { KIND_COLOR } from "@/components/ref-chip"
import type { Connector, SourcedGraph } from "@/lib/api"
import { cn } from "@/lib/utils"

const LANDING = { width: 1000, height: 620 }
const SPREAD = 11.5
const GOLDEN_ANGLE = 2.39996
const STAGGER = 0.22
const COLORS = ["#2f6f9f", "#c2571b", "#3f7d3a", "#6b55a8", "#a37b10", "#a8487a", "#22807a", "#b8392f", "#5d7a2c", "#7b766b", "#8a4fa3", "#5f5a50"]

export type Grouping = "source" | "kind" | "area"

const NO_AREA = "Outside any area"

const WORDS: Record<Grouping, { one: string; a: string; many: string; colour: string }> = {
  source: { one: "source", a: "a source", many: "sources", colour: "the system it was read from" },
  kind: { one: "kind", a: "a kind", many: "kinds", colour: "the kind of thing it is" },
  area: { one: "area", a: "an area", many: "areas", colour: "the area FalkorDB's label propagation put it in" },
}

interface Dot {
  key: string
  label: string
  source: string
  sources: string[]
  x: number
  y: number
}

interface Cluster {
  id: string
  name: string
  color: string
  x: number
  y: number
  radius: number
  dots: Dot[]
}

/** One cluster per group: the group that joins the most others sits in the middle, the rest around it, each with room for its size. */
function arrange(graph: SourcedGraph, by: Grouping, { width, height }: { width: number; height: number }): { clusters: Cluster[]; at: Map<string, Dot> } {
  const groupOf = (node: SourcedGraph["nodes"][number]) => (by === "source" ? node.sources[0] : by === "area" ? (node.area ?? NO_AREA) : node.kind)
  const groups = by === "source" ? graph.sources : [...new Set(graph.nodes.map(groupOf))].map((id) => ({ id, name: id }))
  const home = new Map(graph.nodes.map((node) => [`${node.kind}:${node.id}`, groupOf(node)]))
  const joins = new Map<string, number>()
  for (const edge of graph.edges) {
    const [from, to] = [home.get(edge.source)!, home.get(edge.target)!]
    if (from === to) continue
    joins.set(from, (joins.get(from) ?? 0) + 1)
    joins.set(to, (joins.get(to) ?? 0) + 1)
  }
  const used = groups
    .map((group) => ({ ...group, members: graph.nodes.filter((node) => groupOf(node) === group.id) }))
    .filter((group) => group.members.length > 0)
    .sort((a, b) => (joins.get(b.id) ?? 0) - (joins.get(a.id) ?? 0))
    .map((group) => ({ ...group, radius: SPREAD * Math.sqrt(group.members.length) + 8 }))
  const around = used.slice(1).reduce((sum, group) => sum + group.radius, 0)
  const at = new Map<string, Dot>()
  let passed = 0
  const clusters = used.map((group, index) => {
    const angle = -Math.PI / 2 + ((passed + (group.radius - (used[1]?.radius ?? 0)) / 2) * 2 * Math.PI) / Math.max(1, around)
    if (index > 0) passed += group.radius
    const x = index === 0 ? width / 2 : width / 2 + Math.cos(angle) * (width / 2 - 135)
    const y = index === 0 ? height / 2 + 10 : height / 2 + 10 + Math.sin(angle) * (height / 2 - 95)
    const dots = group.members.map((node, order) => {
      const reach = SPREAD * Math.sqrt(order + 0.5)
      return { key: `${node.kind}:${node.id}`, label: `${node.kind} · ${node.name}`, source: group.id, sources: node.sources, x: x + Math.cos(order * GOLDEN_ANGLE) * reach, y: y + Math.sin(order * GOLDEN_ANGLE) * reach }
    })
    for (const dot of dots) at.set(dot.key, dot)
    return { id: group.id, name: group.name, color: (by === "kind" && KIND_COLOR[group.id]) || COLORS[index % COLORS.length], x, y, radius: group.radius, dots }
  })
  return { clusters, at }
}

interface SourceGraphProps {
  graph: SourcedGraph
  catalog: Connector[]
  by?: Grouping
  subject?: string
  size?: { width: number; height: number }
  onOpen?: (key: string) => void
  className?: string
}

export function SourceGraph({ graph, catalog, by = "source", subject = "the demo company's graph", size = LANDING, onOpen, className }: SourceGraphProps) {
  const [source, setSource] = useState<string | null>(null)
  const [hover, setHover] = useState<string | null>(null)
  const { clusters, at } = useMemo(() => arrange(graph, by, size), [graph, by, size])
  const words = WORDS[by]
  const sourceName = new Map(graph.sources.map((item) => [item.id, item.name]))
  const color = new Map(clusters.map((cluster) => [cluster.id, cluster.color]))
  const name = new Map(clusters.map((cluster) => [cluster.id, cluster.name]))
  const order = new Map(clusters.map((cluster, index) => [cluster.id, index]))
  const crossing = graph.edges.filter((edge) => at.get(edge.source)!.source !== at.get(edge.target)!.source)
  const lit = (edge: SourcedGraph["edges"][number]) => (hover ? edge.source === hover || edge.target === hover : source ? at.get(edge.source)!.source === source || at.get(edge.target)!.source === source : false)
  const near = new Set(graph.edges.filter(lit).flatMap((edge) => [edge.source, edge.target]))
  const focused = hover !== null || source !== null
  const pointed = hover ? at.get(hover)! : null
  const reached = source ? new Set(crossing.filter(lit).flatMap((edge) => [at.get(edge.source)!.source, at.get(edge.target)!.source])).size - 1 : 0
  return (
    <div className={cn("rounded-3xl bg-muted p-4 md:p-6", className)}>
      <div className="flex flex-wrap gap-1.5">
        {clusters.map((cluster) => {
          const system = by === "source" ? catalog.find((connector) => connector.source === cluster.id)?.systems[0] : undefined
          return (
            <button
              key={cluster.id}
              type="button"
              aria-pressed={source === cluster.id}
              onMouseEnter={() => setSource(cluster.id)}
              onMouseLeave={() => setSource(null)}
              onFocus={() => setSource(cluster.id)}
              onBlur={() => setSource(null)}
              className={cn("flex items-center gap-2 rounded-full border bg-background px-3 py-1.5 text-sm font-medium transition-opacity", source && source !== cluster.id && "opacity-50")}
            >
              <span className="size-2.5 rounded-full" style={{ background: cluster.color }} />
              {system && <BrandIcon system={system} className="size-3.5" />}
              {cluster.name}
              <span className="font-normal text-muted-foreground tabular-nums">{cluster.dots.length}</span>
            </button>
          )
        })}
      </div>
      <svg viewBox={`0 0 ${size.width} ${size.height}`} role="img" aria-label={`${subject}, grouped by ${words.one}`} className="mt-3 min-h-0 w-full flex-1 rounded-2xl bg-background">
        {clusters.map((cluster, index) => (
          <motion.g key={cluster.id} initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} viewport={{ once: true, amount: 0.3 }} transition={{ delay: index * STAGGER, duration: 0.5 }}>
            <circle cx={cluster.x} cy={cluster.y} r={cluster.radius} fill={cluster.color} opacity={source === cluster.id ? 0.12 : 0.06} />
            <text x={cluster.x} y={cluster.y - cluster.radius - 9} textAnchor="middle" className="fill-foreground text-[13px] font-medium">
              {cluster.name}
            </text>
          </motion.g>
        ))}
        {graph.edges.map((edge) => {
          const [from, to] = [at.get(edge.source)!, at.get(edge.target)!]
          const on = lit(edge)
          const joins = from.source !== to.source
          return (
            <motion.line
              key={`${edge.source}|${edge.relation}|${edge.target}`}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke={on ? "var(--brand)" : joins ? "var(--foreground)" : color.get(from.source)}
              strokeWidth={on ? 1.4 : 1}
              initial={{ opacity: 0 }}
              whileInView={{ opacity: on ? 0.85 : focused ? 0.04 : joins ? 0.13 : 0.3 }}
              viewport={{ once: true, amount: 0 }}
              transition={{ delay: focused ? 0 : (Math.max(order.get(from.source)!, order.get(to.source)!) + 1) * STAGGER, duration: focused ? 0.15 : 0.6 }}
            />
          )
        })}
        {clusters.flatMap((cluster, index) =>
          cluster.dots.map((dot) => (
            <motion.circle
              key={dot.key}
              cx={dot.x}
              cy={dot.y}
              r={dot.key === hover ? 7 : 4.5}
              fill={cluster.color}
              stroke="var(--background)"
              strokeWidth={1.5}
              className="cursor-pointer"
              initial={{ opacity: 0 }}
              whileInView={{ opacity: !focused || near.has(dot.key) || dot.key === hover || dot.source === source ? 1 : 0.2 }}
              viewport={{ once: true, amount: 0 }}
              transition={{ delay: focused ? 0 : index * STAGGER, duration: focused ? 0.15 : 0.4 }}
              onMouseEnter={() => setHover(dot.key)}
              onMouseLeave={() => setHover(null)}
              onClick={() => onOpen?.(dot.key)}
            />
          )),
        )}
        {pointed && (
          <text x={pointed.x} y={pointed.y - 13} textAnchor="middle" stroke="var(--background)" strokeWidth={5} paintOrder="stroke" className="pointer-events-none fill-foreground text-[13px] font-medium">
            {pointed.label.length > 60 ? `${pointed.label.slice(0, 59)}…` : pointed.label}
          </text>
        )}
      </svg>
      <p className="mt-3 min-h-10 px-2 text-sm text-muted-foreground md:min-h-5">
        {pointed
          ? `${pointed.label}. Read from ${pointed.sources.map((id) => sourceName.get(id)).join(" and ")}, connected to ${near.size - 1} other things.${onOpen ? " Click for its records." : ""}`
          : source
            ? `${name.get(source)}: ${clusters[order.get(source)!].dots.length} things, joined to ${reached} other ${words.many} by ${crossing.filter(lit).length} relationships.`
            : `Each dot is one thing in ${subject} and each colour is ${words.colour}. Grey lines are relationships that join two ${words.many}: ${crossing.length} of ${graph.edges.length}. Point at ${words.a} or a dot.`}
      </p>
    </div>
  )
}
