import { Moon, Sun } from "lucide-react"

import { toggleTheme, useDark } from "@/lib/theme"
import { cn } from "@/lib/utils"

export function ThemeToggle({ className }: { className?: string }) {
  const dark = useDark()
  const label = dark ? "Switch to light mode" : "Switch to dark mode"
  return (
    <button type="button" title={label} aria-label={label} onClick={toggleTheme} className={cn("rounded-md p-1.5 text-muted-foreground hover:bg-sidebar-accent hover:text-foreground", className)}>
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  )
}
