import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export function PageHeader({ eyebrow, title, subtitle, children }: { eyebrow: ReactNode; title: string; subtitle?: string; children?: ReactNode }) {
  return (
    <header className="flex items-end justify-between gap-6">
      <div className="min-w-0">
        <p className="flex items-center gap-2 text-xs font-medium text-muted-foreground">{eyebrow}</p>
        <h1 className="mt-1 font-heading text-2xl leading-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {children}
    </header>
  )
}

export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <h3 className={cn("text-xs font-medium text-muted-foreground", className)}>{children}</h3>
}

export interface TabOption<T extends string> {
  id: T
  label: string
  count?: number
}

export function UnderlineTabs<T extends string>({ tabs, value, onChange }: { tabs: TabOption<T>[]; value: T; onChange: (tab: T) => void }) {
  return (
    <div role="tablist" className="flex gap-6 border-b">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={tab.id === value}
          onClick={() => onChange(tab.id)}
          className={cn(
            "-mb-px flex items-center gap-1.5 border-b-2 border-transparent pb-2 text-sm text-muted-foreground hover:text-foreground",
            tab.id === value && "border-foreground font-medium text-foreground",
          )}
        >
          {tab.label}
          {tab.count !== undefined && <span className="text-xs text-muted-foreground">{tab.count}</span>}
        </button>
      ))}
    </div>
  )
}
