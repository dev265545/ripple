import { RefChip } from "@/components/ref-chip"
import type { CheckFinding } from "@/lib/api"
import { useWorkspace } from "@/lib/workspace"

const LABEL: Record<CheckFinding["kind"], string> = { conflict: "Conflict", stale: "Out of date" }

export function NeedsAttention({ findings }: { findings: CheckFinding[] }) {
  const { openRecord } = useWorkspace()
  return (
    <div className="divide-y rounded-2xl border">
      {findings.map((finding) => (
        <div key={finding.text} className="space-y-1.5 px-4 py-3 text-sm">
          <p className="flex flex-wrap items-baseline gap-2">
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium">{LABEL[finding.kind]}</span>
            {finding.text}
          </p>
          {(finding.refs.length > 0 || finding.records.length > 0) && (
            <p className="flex flex-wrap items-center gap-1.5">
              {finding.refs.map((ref) => (
                <RefChip key={ref} reference={ref} />
              ))}
              {finding.records.map((record) => (
                <button key={record} type="button" className="text-xs text-muted-foreground underline-offset-2 hover:underline" onClick={() => openRecord(record)}>
                  {`Where it was written: ${record}`}
                </button>
              ))}
            </p>
          )}
        </div>
      ))}
    </div>
  )
}
