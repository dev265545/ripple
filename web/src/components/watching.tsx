import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { BrandIcon } from "@/components/brand"
import { Spinner } from "@/components/status"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { get, post, remove, type Connector, type LiveConnection, type SyncStats } from "@/lib/api"

export function useLive(tenant: string, source: string): LiveConnection | undefined {
  return useQuery({ queryKey: [tenant, "live"], queryFn: () => get<Record<string, LiveConnection>>(`/${tenant}/live`), refetchInterval: 30_000 }).data?.[source]
}

export function Watching({ tenant, source }: { tenant: string; source: string }) {
  const client = useQueryClient()
  const connection = useLive(tenant, source)
  const check = useMutation({ mutationFn: () => post<SyncStats>(`/${tenant}/live/${source}/check`), onSettled: () => void client.invalidateQueries() })
  const disconnect = useMutation({ mutationFn: () => remove(`/${tenant}/live/${source}`), onSuccess: () => void client.invalidateQueries() })
  if (!connection) return null
  const minutes = connection.every_seconds / 60
  return (
    <div className="space-y-2 rounded-xl border px-3 py-2.5 text-sm">
      <p className="font-medium">Watching {connection.watching}</p>
      <p className="text-muted-foreground">
        {`Read again every ${minutes === 1 ? "minute" : `${minutes} minutes`}`}
        {connection.checked_at ? `, last at ${new Date(connection.checked_at).toLocaleTimeString()}` : ""}. {connection.sends}
      </p>
      {connection.error && <p role="alert" className="text-destructive">{connection.error}</p>}
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={check.isPending} onClick={() => check.mutate()}>
          {check.isPending && <Spinner />}
          Check now
        </Button>
        <Button size="sm" variant="ghost" disabled={disconnect.isPending} onClick={() => disconnect.mutate()}>
          Disconnect
        </Button>
      </div>
      {check.data && <p>{`Read ${check.data.records} ${check.data.records === 1 ? "record" : "records"}, ${check.data.changed} new or changed.`}</p>}
    </div>
  )
}

export function WatchConnect({ tenant, connector }: { tenant: string; connector: Connector }) {
  const watch = connector.watch!
  const source = connector.source!
  const client = useQueryClient()
  const [fields, setFields] = useState<Record<string, string>>({})
  const connected = useLive(tenant, source) !== undefined
  const connect = useMutation({ mutationFn: () => post<SyncStats>(`/${tenant}/live/${source}`, { fields }), onSuccess: () => void client.invalidateQueries() })
  return (
    <Dialog onOpenChange={() => connect.reset()}>
      <DialogTrigger render={<Button size="sm" variant="outline" />}>
        <BrandIcon system={connector.systems[0]} className="size-3.5" />
        {connected ? "Watching" : watch.pull}
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{watch.pull}</DialogTitle>
          <DialogDescription>{watch.help}</DialogDescription>
        </DialogHeader>
        <Watching tenant={tenant} source={source} />
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault()
            connect.mutate()
          }}
        >
          {watch.fields.map((field) => (
            <label key={field.name} className="block space-y-1 text-sm">
              <span className="font-medium">{field.label}</span>
              <Input required autoComplete="off" placeholder={field.placeholder} value={fields[field.name] ?? ""} onChange={(event) => setFields({ ...fields, [field.name]: event.target.value })} />
            </label>
          ))}
          <Button type="submit" disabled={connect.isPending} className="rounded-full">
            {connect.isPending && <Spinner />}
            {connect.isPending ? "Reading…" : watch.pull}
          </Button>
        </form>
        {connect.isError && <p role="alert" className="rounded-xl bg-destructive/10 px-3 py-2 text-sm text-destructive">{connect.error.message}</p>}
        {connect.data && <p className="rounded-xl bg-muted px-3 py-2.5 text-sm">{`Read ${connect.data.records} incidents, ${connect.data.changed} new or changed in the graph.`}</p>}
      </DialogContent>
    </Dialog>
  )
}
