import { Controls, Handle, NodeToolbar, Position, ReactFlow, ReactFlowProvider, useNodesInitialized, useReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react"
import { useDark } from "@/lib/theme"
import "@xyflow/react/dist/style.css"
import { useEffect, useMemo, useState } from "react"

import { KIND_COLOR, KIND_MEANING } from "@/components/ref-chip"
import type { CanvasData } from "@/lib/api"
import { cn } from "@/lib/utils"
import { useWorkspace } from "@/lib/workspace"

const CARD_WIDTH = 186
const CARD_HEIGHT = 32
const COLUMN = 226
const ROW = 37
export const HIDDEN_KINDS = ["Investigation"]
const PROPOSED_KINDS = ["Fix", "Message"]
// The route worth following by default ends at one of these: who is hit and what they were promised.
const STAKES = ["Customer", "Commitment", "SLA", "Contract"]
const NAMES_SHOWN = 4

interface CanvasProps {
  canvas: CanvasData
  centre: string
  onProposal: (kind: string) => void
  /** When given, only these nodes are drawn; the layout still makes room for all of them. */
  shown?: Set<string>
  fresh?: Set<string>
  /** A fixed height, for a graph that grows; without it the box takes the shape of the whole graph. */
  height?: string
}

interface Placed {
  key: string
  kind: string
  name: string
  depth: number
  row: number
  parent: string | null
}

type Link = CanvasData["edges"][number]

function neighbours(links: Link[]): Map<string, string[]> {
  const near = new Map<string, string[]>()
  for (const link of links) {
    near.set(link.source, [...(near.get(link.source) ?? []), link.target])
    near.set(link.target, [...(near.get(link.target) ?? []), link.source])
  }
  return near
}

/** Tidy tree: a column per hop from the cause, a row per leaf, each parent level with the middle of its children. */
function place(canvas: CanvasData, centre: string): Placed[] {
  const known = new Map(canvas.nodes.filter((node) => !HIDDEN_KINDS.includes(node.kind)).map((node) => [`${node.kind}:${node.id}`, node]))
  const near = neighbours(canvas.edges.filter((edge) => known.has(edge.source) && known.has(edge.target)))
  const start = known.has(centre) ? centre : [...known.keys()][0]
  const parent = new Map<string, string | null>([[start, null]])
  const depth = new Map<string, number>([[start, 0]])
  const queue = [start]
  for (const key of queue) {
    for (const next of near.get(key) ?? []) {
      if (parent.has(next)) continue
      parent.set(next, key)
      depth.set(next, depth.get(key)! + 1)
      queue.push(next)
    }
  }
  const outer = Math.max(1, ...depth.values())
  for (const key of known.keys()) {
    if (parent.has(key)) continue
    parent.set(key, start)
    depth.set(key, outer)
    queue.push(key)
  }
  const children = new Map<string, string[]>()
  for (const key of queue.slice(1)) children.set(parent.get(key)!, [...(children.get(parent.get(key)!) ?? []), key])
  for (const list of children.values()) list.sort((a, b) => known.get(a)!.kind.localeCompare(known.get(b)!.kind) || a.localeCompare(b))
  const row = new Map<string, number>()
  let next = 0
  const settle = (key: string): number => {
    const rows = (children.get(key) ?? []).map(settle)
    const mine = rows.length > 0 ? (rows[0] + rows[rows.length - 1]) / 2 : next++
    row.set(key, mine)
    return mine
  }
  settle(start)
  return queue.map((key) => ({ key, kind: known.get(key)!.kind, name: known.get(key)!.name ?? known.get(key)!.id, depth: depth.get(key)!, row: row.get(key)!, parent: parent.get(key) ?? null }))
}

interface CardData extends Record<string, unknown> {
  name: string
  kind: string
  cause: boolean
  relation: string | null
  focused: boolean
  fresh: boolean
  faded: boolean
  about: About | null
}

interface About {
  route: string[]
  reaches: { kind: string; names: string[] }[]
  side: Position
}

const HANDLE = "!size-px !min-h-0 !min-w-0 !border-0 !opacity-0"

function Card({ data }: NodeProps<Node<CardData>>) {
  const color = KIND_COLOR[data.kind] ?? "#7b766b"
  return (
    <div
      title={`${data.kind} · ${data.name}`}
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-full border bg-background px-3 text-sm leading-none shadow-xs transition-[opacity,border-color,box-shadow] hover:border-foreground/40",
        data.cause && "border-transparent bg-foreground text-background",
        data.focused && "border-foreground/60 shadow-sm",
        data.fresh && "animate-in ring-2 ring-brand zoom-in-90 fade-in",
        data.faded && "opacity-25",
      )}
      style={{ width: CARD_WIDTH, height: CARD_HEIGHT }}
    >
      <Handle type="target" position={Position.Left} className={HANDLE} />
      <span className="size-2 shrink-0 rounded-full" style={{ background: color, boxShadow: data.cause ? "0 0 0 2px var(--background)" : undefined }} />
      <span className="truncate font-medium">{data.name}</span>
      {data.relation && <span className="ml-auto shrink-0 text-[11px] text-brand">{data.relation}</span>}
      <Handle type="source" position={Position.Right} className={HANDLE} />
      <Handle id="side" type="target" position={Position.Right} className={HANDLE} />
      {data.about && <Explainer name={data.name} kind={data.kind} cause={data.cause} about={data.about} />}
    </div>
  )
}

function Explainer({ name, kind, cause, about }: { name: string; kind: string; cause: boolean; about: About }) {
  return (
    <NodeToolbar isVisible position={about.side} offset={12} className="pointer-events-none w-80 space-y-3 rounded-2xl border bg-background p-4 text-left text-sm shadow-lg">
      <div>
        <p className="leading-snug font-semibold">{name}</p>
        <p className="mt-1 text-muted-foreground">{cause ? `${kind}. The likely cause of this incident.` : `${kind}. ${KIND_MEANING[kind] ?? ""}`}</p>
      </div>
      {about.route.length > 1 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground">How the incident gets here</p>
          <p className="mt-1 leading-snug">{about.route.join("  →  ")}</p>
        </div>
      )}
      <div>
        <p className="text-xs font-medium text-muted-foreground">{about.reaches.length > 0 ? "Reached through this" : "Nothing in this incident is reached through this."}</p>
        {about.reaches.map((group) => (
          <p key={group.kind} className="mt-1 flex gap-2 leading-snug">
            <span className="mt-1.5 size-2 shrink-0 rounded-full" style={{ background: KIND_COLOR[group.kind] ?? "#7b766b" }} />
            <span>
              <span className="font-medium">{`${group.kind} · ${group.names.length}`}</span>
              <span className="text-muted-foreground">{`  ${group.names.slice(0, NAMES_SHOWN).join(", ")}${group.names.length > NAMES_SHOWN ? ` and ${group.names.length - NAMES_SHOWN} more` : ""}`}</span>
            </span>
          </p>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">{PROPOSED_KINDS.includes(kind) ? "Click to review it." : "Click for its records and connections."}</p>
    </NodeToolbar>
  )
}

function ColumnTitle({ data }: NodeProps<Node<{ title: string; count: number }>>) {
  return (
    <div className="flex items-baseline gap-1.5 px-3 text-[13px] whitespace-nowrap text-muted-foreground" style={{ width: CARD_WIDTH }}>
      <span className="font-medium text-foreground">{data.title}</span>
      {data.count > 1 && <span className="tabular-nums">{data.count}</span>}
    </div>
  )
}

const NODE_TYPES = { card: Card, title: ColumnTitle }

function build(canvas: CanvasData, centre: string, focus: string | null, shown?: Set<string>, fresh?: Set<string>): { nodes: Node[]; edges: Edge[]; ratio: number } {
  const placed = place(canvas, centre)
  const at = new Map(placed.map((node) => [node.key, node]))
  const links = canvas.edges.filter((edge) => at.has(edge.source) && at.has(edge.target))
  const onPath = new Set(placed.flatMap((node) => (node.parent ? [`${node.key}|${node.parent}`, `${node.parent}|${node.key}`] : [])))
  const lit = new Map<string, string>()
  for (const edge of focus ? links : []) {
    if (edge.source !== focus && edge.target !== focus) continue
    const other = edge.source === focus ? edge.target : edge.source
    if (!lit.has(other)) lit.set(other, edge.relation.toLowerCase().replaceAll("_", " "))
  }
  const columns = Math.max(...placed.map((node) => node.depth)) + 1
  const route = (key: string): string[] => (at.get(key)!.parent ? [...route(at.get(key)!.parent!), key] : [key])
  const stakes = new Set(placed.filter((node) => STAKES.includes(node.kind)).flatMap((node) => route(node.key)))
  const trail = new Set(focus ? route(focus) : [])
  const about = (key: string): About => {
    const below = placed.filter((node) => node.key !== key && route(node.key).includes(key))
    const kinds = [...new Set(below.map((node) => node.kind))].sort((a, b) => Number(STAKES.includes(b)) - Number(STAKES.includes(a)))
    return {
      route: route(key).map((step) => at.get(step)!.name),
      reaches: kinds.map((kind) => ({ kind, names: below.filter((node) => node.kind === kind).map((node) => node.name) })),
      side: at.get(key)!.depth >= columns - 2 ? Position.Left : Position.Right,
    }
  }
  const nodes: Node[] = [
    ...Array.from({ length: columns }, (_, column) => ({
      id: `title${column}`,
      type: "title",
      position: { x: column * COLUMN, y: -ROW },
      data: { title: column === 0 ? "Likely cause" : column === 1 ? "1 step away" : `${column} steps away`, count: placed.filter((node) => node.depth === column && (!shown || shown.has(node.key))).length },
      hidden: shown && !placed.some((node) => node.depth === column && shown.has(node.key)),
      width: CARD_WIDTH,
      height: 20,
      selectable: false,
      draggable: false,
    })),
    ...placed.map((node) => ({
      id: node.key,
      type: "card",
      width: CARD_WIDTH,
      height: CARD_HEIGHT,
      position: { x: node.depth * COLUMN, y: node.row * ROW },
      hidden: shown && !shown.has(node.key),
      data: { name: node.name, kind: node.kind, cause: node.depth === 0, relation: lit.get(node.key) ?? null, focused: node.key === focus, fresh: fresh?.has(node.key) ?? false, faded: focus !== null && !trail.has(node.key) && !lit.has(node.key), about: node.key === focus ? about(node.key) : null },
      zIndex: node.key === focus ? 10 : 0,
    })),
  ]
  const seen = new Set<string>()
  const edges = links.flatMap((edge): Edge[] => {
    const pair = [edge.source, edge.target].sort().join("|")
    const touching = focus !== null && (edge.source === focus || edge.target === focus)
    if (seen.has(pair) || (!touching && !onPath.has(`${edge.source}|${edge.target}`))) return []
    seen.add(pair)
    const spine = onPath.has(`${edge.source}|${edge.target}`)
    const followed = spine && trail.has(edge.source) && trail.has(edge.target)
    const marked = focus ? followed || touching : spine && stakes.has(edge.source) && stakes.has(edge.target)
    // Drawn from the nearer column to the further one so every line runs left to right.
    const [from, to] = at.get(edge.source)!.depth <= at.get(edge.target)!.depth ? [edge.source, edge.target] : [edge.target, edge.source]
    return [
      {
        id: pair,
        hidden: shown && !(shown.has(from) && shown.has(to)),
        source: from,
        target: to,
        targetHandle: at.get(from)!.depth === at.get(to)!.depth ? "side" : undefined,
        zIndex: followed ? 3 : touching ? 2 : 0,
        style: { stroke: marked ? "var(--brand)" : "var(--foreground)", strokeWidth: followed ? 2.5 : marked ? 1.75 : 1.25, opacity: marked ? 1 : focus ? 0.08 : 0.22 },
      },
    ]
  })
  return { nodes, edges, ratio: (columns * COLUMN) / ((Math.max(...placed.map((node) => node.row)) + 2.5) * ROW) }
}

function Flow({ canvas, centre, onProposal, shown, fresh, height }: CanvasProps) {
  const dark = useDark()
  const { openEntity } = useWorkspace()
  const { fitView } = useReactFlow()
  const [focus, setFocus] = useState<string | null>(null)
  const { nodes, edges, ratio } = useMemo(() => build(canvas, centre, focus, shown, fresh), [canvas, centre, focus, shown, fresh])
  const measured = useNodesInitialized()
  useEffect(() => {
    if (!measured && !shown) return
    const followed = [...(fresh ?? [])].filter((key) => shown?.has(key)).map((id) => ({ id }))
    // Nodes revealed this render are not measured yet, so the fit waits a frame for them.
    const timer = setTimeout(() => void fitView(followed.length > 0 ? { nodes: followed, duration: 600, padding: 0.35, minZoom: 0.6, maxZoom: 1 } : { duration: 600, padding: 0.03 }), shown ? 80 : 0)
    return () => clearTimeout(timer)
  }, [measured, canvas.nodes.length, fresh, shown, fitView])
  return (
    <div className="min-h-80 w-full" style={height ? { height } : { aspectRatio: ratio }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        colorMode={dark ? "dark" : "light"}
        fitView
        minZoom={0.2}
        maxZoom={1.1}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => node.type === "card" && (PROPOSED_KINDS.includes(node.data.kind as string) ? onProposal(node.data.kind as string) : openEntity(node.id))}
        onNodeMouseEnter={(_, node) => node.type === "card" && setFocus(node.id)}
        onNodeMouseLeave={() => setFocus(null)}
      >
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
    </div>
  )
}

export function Canvas(props: CanvasProps) {
  return (
    <ReactFlowProvider>
      <Flow {...props} />
    </ReactFlowProvider>
  )
}
