import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { BrandIcon } from "@/components/brand"
import { Spinner } from "@/components/status"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { get, post, remove, type Connector, type GithubConnection, type SyncStats } from "@/lib/api"

export function LivePull({ tenant, connector }: { tenant: string; connector: Connector }) {
  const live = connector.live!
  const client = useQueryClient()
  const [fields, setFields] = useState<Record<string, string>>({})
  type Read = SyncStats & { read: number; incidents: number }
  const watched = useQuery({ queryKey: [tenant, "github"], queryFn: () => get<GithubConnection>(`/${tenant}/github`), refetchInterval: 30_000 })
  const read = useMutation({
    mutationFn: () => post<Read>(`/${tenant}/sources/${connector.source}/pull`, { fields }),
    onSuccess: () => void client.invalidateQueries(),
  })
  const check = useMutation({ mutationFn: () => post<Read>(`/${tenant}/github/check`, {}), onSettled: () => void client.invalidateQueries() })
  const disconnect = useMutation({ mutationFn: () => remove(`/${tenant}/github`), onSuccess: () => void client.invalidateQueries() })
  const connection = watched.data?.connected ? watched.data : null
  return (
    <Dialog onOpenChange={() => read.reset()}>
      <DialogTrigger render={<Button size="sm" variant="outline" />}>
        <BrandIcon system={connector.systems[0]} className="size-3.5" />
        {connection ? `Watching ${connection.repo}` : live.pull}
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{live.pull}</DialogTitle>
          <DialogDescription>{live.help}</DialogDescription>
        </DialogHeader>
        {connection && (
          <div className="space-y-2 rounded-xl border px-3 py-2.5 text-sm">
            <p className="font-medium">Watching {connection.repo}</p>
            <p className="text-muted-foreground">
              Checked every {connection.every_seconds! / 60} {connection.every_seconds === 60 ? "minute" : "minutes"}
              {connection.checked_at ? `, last at ${new Date(connection.checked_at).toLocaleTimeString()}` : ""}. A new issue labelled {connection.label} opens an investigation.
              {connection.has_token ? " Approved findings are posted on the issue." : " Add a token to post approved findings on the issue."}
            </p>
            {connection.error && <p role="alert" className="text-destructive">{connection.error}</p>}
            <p className="text-muted-foreground">
              To be told at once instead of on the next check, add a GitHub webhook for issues and pushes to{" "}
              <code className="break-all text-foreground">{`${location.origin}${connection.hook}`}</code> with content type application/json and secret{" "}
              <code className="break-all text-foreground">{connection.secret}</code>. GitHub must be able to reach this address.
            </p>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" disabled={check.isPending} onClick={() => check.mutate()}>
                {check.isPending && <Spinner />}
                Check now
              </Button>
              <Button size="sm" variant="ghost" disabled={disconnect.isPending} onClick={() => disconnect.mutate()}>
                Disconnect and forget the token
              </Button>
            </div>
            {check.data && <p>{`${check.data.read} new ${check.data.read === 1 ? "change" : "changes"}, ${check.data.incidents} new ${check.data.incidents === 1 ? "incident" : "incidents"}.`}</p>}
          </div>
        )}
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault()
            read.mutate()
          }}
        >
          {live.fields.map((field) => (
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
            {read.isPending && <Spinner />}
            {read.isPending ? "Reading…" : live.pull}
          </Button>
        </form>
        {read.isError && <p role="alert" className="rounded-xl bg-destructive/10 px-3 py-2 text-sm text-destructive">{read.error.message}</p>}
        {read.data && (
          <p className="rounded-xl bg-muted px-3 py-2.5 text-sm">
            {`Read ${read.data.read} ${read.data.read === 1 ? "change" : "changes"} from GitHub, ${read.data.changed} new or changed in the graph. Now watching the repository.`}
          </p>
        )}
      </DialogContent>
    </Dialog>
  )
}
