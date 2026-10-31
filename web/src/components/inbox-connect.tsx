import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Upload } from "lucide-react"
import { useRef, useState } from "react"

import { BrandIcon } from "@/components/brand"
import { Spinner } from "@/components/status"
import { useLive, Watching } from "@/components/watching"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { post, postFile, type Connector, type InboxStats } from "@/lib/api"

function summary(stats: InboxStats): string {
  if (stats.changed === 0) return `Read ${stats.records} ${stats.records === 1 ? "item" : "items"}. All of them were already in the graph.`
  const found = [`${stats.linked} links to things already known`, stats.promises > 0 && `${stats.promises} ${stats.promises === 1 ? "promise" : "promises"}`, stats.decisions > 0 && `${stats.decisions} ${stats.decisions === 1 ? "decision" : "decisions"}`, stats.notes > 0 && `${stats.notes} ${stats.notes === 1 ? "note" : "notes"}`].filter(Boolean)
  const model = stats.model ? "" : " No language model is configured, so promises, decisions and notes were not looked for."
  const skipped = stats.skipped > 0 ? ` ${stats.skipped} more were left out; one read takes 200 items.` : ""
  return `Read ${stats.records} ${stats.records === 1 ? "item" : "items"}, ${stats.changed} new. Found ${found.join(", ")}.${model}${skipped}`
}

export function InboxConnect({ tenant, connector, onBrowse }: { tenant: string; connector: Connector; onBrowse: () => void }) {
  const inbox = connector.inbox!
  const client = useQueryClient()
  const picker = useRef<HTMLInputElement>(null)
  const [fields, setFields] = useState<Record<string, string>>({})
  const base = `/${tenant}/inbox/${connector.source}`
  const watched = useLive(tenant, connector.source!) !== undefined
  const read = useMutation({
    mutationFn: (job: { file?: File; example?: boolean }) =>
      job.file ? postFile<InboxStats>(`${base}/file`, job.file) : post<InboxStats>(job.example ? `${base}/example` : `${base}/pull`, job.example ? {} : { fields }),
    onSuccess: () => void client.invalidateQueries(),
  })
  return (
    <Dialog onOpenChange={() => read.reset()}>
      <DialogTrigger render={<Button size="sm" variant="outline" />}>{watched ? "Watching" : connector.status === "connected" ? "Read more" : "Connect"}</DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <BrandIcon system={connector.systems[0]} className="size-4" />
            {connector.name}
          </DialogTitle>
          <DialogDescription>{inbox.help}</DialogDescription>
        </DialogHeader>
        <Watching tenant={tenant} source={connector.source!} />
        {inbox.pull && (
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault()
              read.mutate({})
            }}
          >
            {inbox.fields.map((field) => (
              <label key={field.name} className="block space-y-1 text-sm">
                <span className="font-medium">{field.label}</span>
                <Input
                  type={field.secret ? "password" : "text"}
                  autoComplete="off"
                  required={!field.optional}
                  placeholder={field.placeholder}
                  value={fields[field.name] ?? ""}
                  onChange={(event) => setFields({ ...fields, [field.name]: event.target.value })}
                />
              </label>
            ))}
            <Button type="submit" disabled={read.isPending} className="rounded-full">
              {read.isPending && !read.variables.file && !read.variables.example && <Spinner />}
              {inbox.pull}
            </Button>
          </form>
        )}
        <div className="flex flex-wrap items-center gap-2 border-t pt-4">
          <Button variant="outline" size="sm" disabled={read.isPending} onClick={() => picker.current?.click()}>
            {read.isPending && read.variables.file ? <Spinner /> : <Upload />}
            {`Upload a file (${inbox.accepts.replaceAll(",", ", ")})`}
          </Button>
          {connector.example && (
            <Button variant="ghost" size="sm" disabled={read.isPending} onClick={() => read.mutate({ example: true })}>
              {read.isPending && read.variables.example && <Spinner />}
              Read the sample
            </Button>
          )}
          <input
            ref={picker}
            type="file"
            hidden
            accept={inbox.accepts}
            aria-label={`${connector.name} file`}
            onChange={(event) => {
              const file = event.target.files?.[0]
              event.target.value = ""
              if (file) read.mutate({ file })
            }}
          />
        </div>
        {read.isPending && <p className="text-sm text-muted-foreground">Reading, matching people and customers, and linking what it names…</p>}
        {read.isError && <p role="alert" className="rounded-xl bg-destructive/10 px-3 py-2 text-sm text-destructive">{read.error.message}</p>}
        {read.data && (
          <div className="space-y-2 rounded-xl bg-muted px-3 py-2.5 text-sm">
            <p>{summary(read.data)}</p>
            <Button variant="outline" size="sm" onClick={onBrowse}>
              Open the records
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
