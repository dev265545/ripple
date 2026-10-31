import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Download, Upload } from "lucide-react"
import { useRef, type ChangeEvent } from "react"

import { Spinner } from "@/components/status"
import { Button } from "@/components/ui/button"
import { get, post, type Connector, type SyncStats } from "@/lib/api"

async function downloadExample(source: string) {
  const example = await get<{ filename: string; text: string }>(`/connectors/${source}/example`)
  const link = document.createElement("a")
  link.href = URL.createObjectURL(new Blob([example.text]))
  link.download = example.filename
  link.click()
  URL.revokeObjectURL(link.href)
}

interface Props {
  tenant: string
  connector: Connector
  example?: boolean
  onRead: (stats: SyncStats) => void
  onError: (message: string) => void
}

export function ExportUpload({ tenant, connector, example, onRead, onError }: Props) {
  const client = useQueryClient()
  const picker = useRef<HTMLInputElement>(null)
  const upload = useMutation({
    mutationFn: async (file: File) => post<SyncStats>(`/${tenant}/sources/${connector.source}/file`, { text: await file.text() }),
    onSuccess: (stats) => {
      void client.invalidateQueries()
      onRead(stats)
    },
    onError: (error: Error) => onError(error.message),
  })

  function pick(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ""
    if (file) upload.mutate(file)
  }

  return (
    <>
      {example && (
        <Button size="sm" variant="ghost" onClick={() => void downloadExample(connector.source!).catch((error: Error) => onError(error.message))}>
          <Download />
          Example
        </Button>
      )}
      <Button size="sm" variant="outline" disabled={upload.isPending} onClick={() => picker.current?.click()}>
        {upload.isPending ? <Spinner /> : <Upload />}
        {upload.isPending ? "Reading…" : connector.status === "connected" ? "Replace" : "Upload"}
      </Button>
      <input ref={picker} type="file" hidden aria-label={`${connector.name} export file, ${connector.file}`} onChange={pick} />
    </>
  )
}
