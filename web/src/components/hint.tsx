import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

const SIDE = {
  below: "top-full left-1/2 mt-1.5 -translate-x-1/2",
  right: "top-1/2 left-full ml-2 -translate-y-1/2",
}

export function Hint({ text, side = "below", className, children }: { text: string; side?: keyof typeof SIDE; className?: string; children: ReactNode }) {
  return (
    <span className={cn("group/hint relative inline-flex", className)}>
      {children}
      <span
        role="tooltip"
        className={cn(
          "pointer-events-none absolute z-50 w-max max-w-64 rounded-lg bg-foreground px-2.5 py-1.5 text-left text-xs leading-snug font-normal text-background opacity-0 shadow-md transition-opacity delay-200 group-focus-within/hint:opacity-100 group-hover/hint:opacity-100",
          SIDE[side],
        )}
      >
        {text}
      </span>
    </span>
  )
}
