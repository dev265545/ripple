import { useSyncExternalStore } from "react"

const listeners = new Set<() => void>()
const isDark = () => document.documentElement.classList.contains("dark")

export function toggleTheme() {
  localStorage.setItem("ripple.theme", document.documentElement.classList.toggle("dark") ? "dark" : "light")
  listeners.forEach((listener) => listener())
}

export function useDark() {
  return useSyncExternalStore((listener) => {
    listeners.add(listener)
    return () => listeners.delete(listener)
  }, isDark)
}
