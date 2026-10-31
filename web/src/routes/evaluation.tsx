import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { PageHeader } from "@/components/page"
import { Loading, Problem, Skeleton, Spinner } from "@/components/status"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { get, type Evaluation as EvaluationResult, type LoadResult } from "@/lib/api"
import { usePost } from "@/lib/workspace"

function Stat({ value, label }: { value: string | number; label: string }) {
  return (
    <div className="min-w-48 flex-1 bg-background px-5 py-4">
      <p className="font-heading text-3xl tabular-nums">{value}</p>
      <p className="mt-1 text-sm text-muted-foreground">{label}</p>
    </div>
  )
}

function Cause({ reference }: { reference: string | null }) {
  if (!reference) return <span className="text-muted-foreground">Inconclusive</span>
  const [kind, id] = reference.split(":")
  return (
    <span className="whitespace-nowrap">
      <span className="text-muted-foreground">{kind}</span> {id}
    </span>
  )
}

export function Evaluation() {
  const evaluation = useQuery({ queryKey: ["evaluation"], queryFn: () => get<EvaluationResult>("/evaluation") })
  const [load, setLoad] = useState<LoadResult | null>(null)
  const evaluate = usePost()
  const race = usePost<LoadResult>(setLoad)
  const { runs, accuracy, memory, reading } = evaluation.data ?? {}
  return (
    <div className="mx-auto max-w-4xl space-y-8 px-10 py-8">
      <PageHeader eyebrow="Does it work" title="Evaluation" subtitle="Each scenario plants a cause and red herrings on a fresh copy of the company, then checks what the agents conclude." />
      <div className="flex items-center gap-2">
        <Button disabled={evaluate.isPending} onClick={() => evaluate.mutate({ path: "/evaluation/run" })}>
          {evaluate.isPending && <Spinner />}
          {evaluate.isPending ? "Running every scenario…" : "Run evaluation"}
        </Button>
        <Button variant="outline" disabled={race.isPending} onClick={() => race.mutate({ path: "/load/run" })}>
          {race.isPending && <Spinner />}
          {race.isPending ? "Racing workers…" : "Run task-claim race"}
        </Button>
      </div>
      {evaluate.isPending && (
        <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner className="size-3.5 text-brand" />
          Seeding a fresh copy of the company for each scenario and running the agents on it. This takes about ten seconds.
        </p>
      )}
      {evaluation.isError && <Problem error={evaluation.error} retry={() => void evaluation.refetch()} />}
      {evaluation.isPending && (
        <Loading label="Loading evaluation results" className="space-y-8">
          <div className="flex gap-10">
            <Skeleton className="h-14 w-40" />
            <Skeleton className="h-14 w-40" />
          </div>
          <div className="space-y-3">
            {Array.from({ length: 6 }, (_, index) => (
              <Skeleton key={index} className="h-8 w-full" />
            ))}
          </div>
        </Loading>
      )}
      <section className="flex flex-wrap gap-px overflow-hidden rounded-2xl border bg-border empty:hidden">
        {accuracy !== undefined && <Stat value={`${Math.round(accuracy * 100)}%`} label={`root cause correct over ${runs?.length} scenarios`} />}
        {memory && <Stat value={`${memory.cold_steps} → ${memory.warm_steps}`} label={`investigator steps on scenario ${memory.scenario}, before and after learning ${memory.playbook}`} />}
        {reading && <Stat value={`${reading.matched} of ${reading.expected}`} label={`links a person wrote down for ${reading.documents.length} sample documents that ${reading.model} found by reading them; it added ${reading.found - reading.matched} others`} />}
        {load && <Stat value={load.double_claims} label={`double claims in ${load.claimed} task claims`} />}
        {load && <Stat value={load.claims_per_second} label={`claims per second, p95 ${load.p95_claim_ms} ms`} />}
      </section>
      {runs && (
        <Table className={evaluate.isPending ? "opacity-50" : undefined}>
          <TableHeader>
            <TableRow>
              <TableHead>Scenario</TableHead>
              <TableHead>Planted cause</TableHead>
              <TableHead>Found</TableHead>
              <TableHead>Steps</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {runs.map((run) => (
              <TableRow key={run.scenario}>
                <TableCell className="whitespace-normal">
                  <span className="mr-2 text-muted-foreground">{run.scenario}</span>
                  {run.title}
                </TableCell>
                <TableCell>
                  <Cause reference={run.truth} />
                </TableCell>
                <TableCell>
                  <Cause reference={run.root} />
                </TableCell>
                <TableCell className="tabular-nums">{run.investigator_steps}</TableCell>
                <TableCell className="text-right">
                  <Badge variant={run.correct ? "secondary" : "destructive"}>{run.correct ? "correct" : "missed"}</Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {evaluation.data && !runs && <p className="text-sm text-muted-foreground">No evaluation has been run yet.</p>}
    </div>
  )
}
