import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { Areas } from "@/components/areas"
import { PageHeader } from "@/components/page"
import { SourceGraph, type Grouping } from "@/components/source-graph"
import { Loading, Problem, Skeleton } from "@/components/status"
import { get, type Connector, type SourcedGraph } from "@/lib/api"
import { cn } from "@/lib/utils"
import { useWorkspace } from "@/lib/workspace"

const SIZE = { width: 1400, height: 760 }
const GROUPINGS: { id: Grouping; label: string }[] = [
  { id: "kind", label: "By kind of thing" },
  { id: "source", label: "By source system" },
  { id: "area", label: "By area" },
]

export function GraphView() {
  const { tenant, openEntity } = useWorkspace()
  const [by, setBy] = useState<Grouping>("kind")
  const graph = useQuery({ queryKey: [tenant, "graph"], queryFn: () => get<SourcedGraph>(`/${tenant}/graph`) })
  const catalog = useQuery({ queryKey: ["connectors"], queryFn: () => get<Connector[]>("/connectors") })
  return (
    <div className="flex flex-col gap-6 px-10 py-8">
      <PageHeader
        eyebrow="Everything Ripple knows"
        title="Graph"
        subtitle={graph.data ? `${graph.data.nodes.length} things and ${graph.data.edges.length} relationships, read from FalkorDB as they are stored right now.${graph.data.withheld ? ` ${graph.data.withheld} more are left out: they come only from mail or chats you are not on.` : ""}` : "The whole company graph, as it is stored in FalkorDB."}
      >
        <div className="flex shrink-0 gap-1 rounded-full bg-muted p-1">
          {GROUPINGS.map((grouping) => (
            <button
              key={grouping.id}
              type="button"
              aria-pressed={by === grouping.id}
              onClick={() => setBy(grouping.id)}
              className={cn("rounded-full px-3 py-1.5 text-sm font-medium text-muted-foreground", by === grouping.id && "bg-background text-foreground shadow-xs")}
            >
              {grouping.label}
            </button>
          ))}
        </div>
      </PageHeader>
      {graph.data ? (
        <SourceGraph key={by} graph={graph.data} catalog={catalog.data ?? []} by={by} subject="this company's graph" size={SIZE} onOpen={openEntity} className="flex h-[calc(100vh-13rem)] min-h-[560px] shrink-0 flex-col" />
      ) : graph.isError ? (
        <Problem error={graph.error} retry={() => void graph.refetch()} />
      ) : (
        <Loading label="Loading the graph" className="h-[calc(100vh-13rem)] min-h-[560px]">
          <Skeleton className="h-full w-full rounded-3xl" />
        </Loading>
      )}
      <Areas />
    </div>
  )
}
