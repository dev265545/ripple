import { useState, type ComponentProps, type PointerEvent } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

interface Press {
  key: number
  x: number
  y: number
  size: number
}

export function RippleButton({ className, children, onPointerDown, ...props }: ComponentProps<typeof Button>) {
  const [presses, setPresses] = useState<Press[]>([])

  function press(event: PointerEvent<HTMLButtonElement>) {
    const box = event.currentTarget.getBoundingClientRect()
    setPresses((current) => [...current, { key: event.timeStamp, x: event.clientX - box.left, y: event.clientY - box.top, size: box.width * 2.2 }])
  }

  return (
    <Button
      className={cn("relative overflow-hidden", className)}
      onPointerDown={(event) => {
        press(event)
        onPointerDown?.(event)
      }}
      {...props}
    >
      {children}
      {presses.map((item) => (
        <span
          key={item.key}
          aria-hidden
          onAnimationEnd={() => setPresses((current) => current.filter((other) => other.key !== item.key))}
          className="pointer-events-none absolute animate-press rounded-full bg-current"
          style={{ left: item.x, top: item.y, width: item.size, height: item.size }}
        />
      ))}
    </Button>
  )
}
