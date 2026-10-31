import { useIsFetching, useIsMutating } from "@tanstack/react-query"
import { CircleAlert, LoaderCircle } from "lucide-react"
import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export function Spinner({ className }: { className?: string }) {
  return <LoaderCircle aria-hidden className={cn("size-4 shrink-0 animate-spin", className)} />
}

export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden className={cn("block animate-pulse rounded-md bg-foreground/[0.07]", className)} />
}

export function Loading({ label, className, children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <div role="status" aria-busy="true" aria-label={label} className={className}>
      {children}
    </div>
  )
}

export function SkeletonRows({ label, count = 4 }: { label: string; count?: number }) {
  return (
    <Loading label={label} className="divide-y rounded-2xl border">
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="flex items-center gap-4 px-4 py-3.5">
          <Skeleton className="size-10 rounded-xl" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-40" />
            <Skeleton className="h-3 w-2/3" />
          </div>
          <Skeleton className="h-7 w-20 rounded-lg" />
        </div>
      ))}
    </Loading>
  )
}

export function SkeletonLines({ label, count = 3, className }: { label: string; count?: number; className?: string }) {
  return (
    <Loading label={label} className={cn("space-y-2.5", className)}>
      {Array.from({ length: count }, (_, index) => (
        <Skeleton key={index} className={cn("h-3.5", index === count - 1 ? "w-3/5" : "w-full")} />
      ))}
    </Loading>
  )
}

export function Problem({ error, retry, className }: { error: Error; retry?: () => void; className?: string }) {
  return (
    <div role="alert" className={cn("flex items-center gap-3 rounded-2xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm", className)}>
      <CircleAlert className="size-4 shrink-0 text-destructive" />
      <p className="min-w-0 flex-1">{error.message}</p>
      {retry && (
        <Button size="sm" variant="outline" onClick={retry}>
          Try again
        </Button>
      )}
    </div>
  )
}

export function ActivityBar() {
  const firstLoads = useIsFetching({ predicate: (query) => query.state.status === "pending" })
  const saves = useIsMutating()
  if (firstLoads + saves === 0) return null
  return (
    <div role="progressbar" aria-label="Working" className="fixed inset-x-0 top-0 z-[60] h-0.5 overflow-hidden bg-brand/15">
      <span className="block h-full w-1/3 animate-[slide_1.1s_ease-in-out_infinite] bg-brand" />
    </div>
  )
}
