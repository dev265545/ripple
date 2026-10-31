import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createContext, useContext } from "react"
import { toast } from "sonner"

import { get, post, type Person } from "@/lib/api"

export interface Session {
  tenant: string
  user: Person
}

const SESSION_KEY = "ripple.session"

export function readSession(): Session | null {
  try {
    return JSON.parse(localStorage.getItem(SESSION_KEY) ?? "null")
  } catch {
    return null
  }
}

export function writeSession(session: Session | null) {
  if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session))
  else localStorage.removeItem(SESSION_KEY)
}

export interface Workspace {
  tenant: string
  user: Person
  openRecord: (record: string) => void
  investigation: string | null
  incidentsLoaded: boolean
  selectInvestigation: (id: string | null) => void
  openEntity: (ref: string) => void
}

export const WorkspaceContext = createContext<Workspace | null>(null)

export function useWorkspace(): Workspace {
  const workspace = useContext(WorkspaceContext)
  if (!workspace) throw new Error("useWorkspace outside of the app shell")
  return workspace
}

/** Name of the language model the server is configured with, or null when it runs without one. */
export function useModel(): string | null {
  return useQuery({ queryKey: ["model"], queryFn: () => get<{ name: string | null }>("/model"), staleTime: Infinity }).data?.name ?? null
}

export function usePost<T = unknown>(done?: (result: T) => void) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ path, body }: { path: string; body?: object }) => post<T>(path, body),
    onSuccess: (result) => {
      void client.invalidateQueries()
      done?.(result)
    },
    onError: (error: Error) => toast.error(error.message),
  })
}

export function splitRef(ref: string): { kind: string; id: string } {
  const [kind, ...rest] = ref.split(":")
  return { kind, id: rest.join(":") }
}
