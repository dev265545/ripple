import { useState } from "react"
import { toast } from "sonner"

import { RefChip } from "@/components/ref-chip"
import { Badge } from "@/components/ui/badge"
import { RippleButton } from "@/components/ripple-button"
import { Spinner } from "@/components/status"
import { Textarea } from "@/components/ui/textarea"
import { Button } from "@/components/ui/button"
import type { Action, Remediation } from "@/lib/api"
import { cn } from "@/lib/utils"
import { useModel, usePost, useWorkspace } from "@/lib/workspace"

function Check({ passed, label }: { passed: boolean; label: string }) {
  return <Badge variant={passed ? "secondary" : "destructive"}>{`${label} ${passed ? "pass" : "fail"}`}</Badge>
}

function Diff({ text }: { text: string }) {
  return (
    <pre className="max-h-80 overflow-auto rounded-md border bg-muted/60 p-3 font-mono text-[11px] leading-relaxed">
      {text.split("\n").map((line, index) => (
        <div
          key={index}
          className={cn(
            line.startsWith("+") && !line.startsWith("+++") && "bg-emerald-600/10 text-emerald-800",
            line.startsWith("-") && !line.startsWith("---") && "bg-red-600/10 text-red-800",
            line.startsWith("@@") && "text-sky-700",
            (line.startsWith("diff ") || line.startsWith("index ")) && "text-muted-foreground",
          )}
        >
          {line || " "}
        </div>
      ))}
    </pre>
  )
}

export function RemediationCard({ remediation }: { remediation: Remediation }) {
  const { tenant, user } = useWorkspace()
  const merge = usePost<{ pr: string; load_passed: boolean }>((result) =>
    toast.success(`Merged as ${result.pr}. Load check ${result.load_passed ? "passes" : "still fails"} on main.`),
  )
  return (
    <article className="space-y-3 rounded-2xl border bg-card p-5">
      <header className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs font-medium text-muted-foreground">{remediation.kind === "rollback" ? "Option A · Roll back" : "Option B · Proper fix"}</p>
          <h4 className="font-heading text-lg">{remediation.title}</h4>
        </div>
        <Badge variant={remediation.status === "merged" ? "default" : "outline"}>
          {remediation.status === "merged" ? `merged as ${remediation.pr}` : remediation.status}
        </Badge>
      </header>
      <p className="text-sm text-muted-foreground">{remediation.summary}</p>
      {remediation.warning && <p className="flex gap-2 rounded-md border border-amber-600/30 bg-amber-500/10 p-2.5 text-sm text-amber-900">{remediation.warning}</p>}
      <div className="flex flex-wrap items-center gap-1.5">
        <Check passed={remediation.tests_passed} label="tests" />
        <Check passed={remediation.load_passed} label="load check" />
        <span className="text-xs text-muted-foreground">{`${remediation.repo} · branch ${remediation.branch}`}</span>
      </div>
      <p className="text-xs text-muted-foreground">{`Load check: ${remediation.load_output}`}</p>
      {remediation.written_by && <p className="text-xs text-muted-foreground">{`Written by ${remediation.written_by}. Kept only because the repository's own tests and load check pass on it.`}</p>}
      <div className="flex flex-wrap gap-1">
        {remediation.refs.map((reference) => {
          const [relation, ...target] = reference.split(":")
          return (
            <span key={reference} className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              {relation.toLowerCase().replaceAll("_", " ")}
              <RefChip reference={target.join(":")} />
            </span>
          )
        })}
      </div>
      <Diff text={remediation.diff} />
      {remediation.status === "proposed" && (
        <RippleButton
          size="sm"
          disabled={merge.isPending}
          onClick={() => merge.mutate({ path: `/${tenant}/remediations/${remediation.id}/merge`, body: { user: user.id } })}
        >
          {merge.isPending && <Spinner />}
          {merge.isPending ? "Merging and re-running checks…" : "Approve and merge"}
        </RippleButton>
      )}
    </article>
  )
}

export function ActionCard({ action }: { action: Action }) {
  const { tenant, user } = useWorkspace()
  const [body, setBody] = useState(action.body)
  const approve = usePost<Action>((approved) => toast.success(approved.delivered ?? "Approved"))
  const model = useModel()
  const rewrite = usePost<{ body: string }>((result) => {
    setBody(result.body)
    toast.success("Reworded. Nothing is sent until you approve it.")
  })
  const sent = action.status === "sent"
  return (
    <article className="space-y-2.5 rounded-lg border bg-card p-4">
      <header className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs text-muted-foreground">{`${action.kind.replace("_", " ")} · ${action.to} · ${action.channel}`}</p>
          <h4 className="font-medium">{action.subject}</h4>
        </div>
        <Badge variant={sent ? "default" : "outline"}>{sent ? `approved by ${action.approved_by}` : "draft"}</Badge>
      </header>
      {sent ? (
        <>
          <p className="text-sm whitespace-pre-wrap text-muted-foreground">{action.body}</p>
          {action.delivered && (
            <p className="text-sm">
              {action.delivered}{" "}
              {action.url && (
                <a href={action.url} target="_blank" rel="noreferrer" className="font-medium underline underline-offset-2">
                  Open it
                </a>
              )}
            </p>
          )}
        </>
      ) : (
        <>
          <Textarea value={body} onChange={(event) => setBody(event.target.value)} className="min-h-32 text-sm" />
          <RippleButton
            size="sm"
            variant="secondary"
            disabled={approve.isPending}
            onClick={() => approve.mutate({ path: `/${tenant}/actions/${action.id}/approve`, body: { user: user.id, body } })}
          >
            {approve.isPending && <Spinner />}
            {approve.isPending ? "Sending…" : action.kind === "revert_pr" ? "Approve and open the pull request" : "Approve and send"}
          </RippleButton>
          {model && (
            <Button size="sm" variant="ghost" className="ml-1.5" disabled={rewrite.isPending} onClick={() => rewrite.mutate({ path: `/${tenant}/actions/${action.id}/rewrite` })}>
              {rewrite.isPending && <Spinner />}
              {rewrite.isPending ? "Rewording…" : `Reword with ${model}`}
            </Button>
          )}
        </>
      )}
    </article>
  )
}
