import { motion } from "motion/react"

const CENTRE = 320
const REACH = 312
const CYCLE = 7
const RINGS = [
  { radius: 74, label: "Systems" },
  { radius: 146, label: "People and decisions" },
  { radius: 220, label: "Customers" },
  { radius: 292, label: "Promises" },
]
const STONES = [
  { ring: 0, angle: -28, text: "payments-core" },
  { ring: 0, angle: 96, text: "ledger-db" },
  { ring: 0, angle: 205, text: "PR-412" },
  { ring: 1, angle: -72, text: "Mei Tanaka · on call" },
  { ring: 1, angle: 38, text: "ADR-7 · pool capped at 20" },
  { ring: 1, angle: 158, text: "Tomas Novak · decided" },
  { ring: 2, angle: -40, text: "Larkspur Retail" },
  { ring: 2, angle: 72, text: "Kite Grocers" },
  { ring: 2, angle: 188, text: "Bluepeak Travel" },
  { ring: 3, angle: -58, text: "“Zero checkout downtime, 3 to 6 October”" },
  { ring: 3, angle: 52, text: "99.95% uptime · 4,200 credit" },
  { ring: 3, angle: 128, text: "“Notify within 15 minutes”" },
]

function place(radius: number, angle: number) {
  const radians = (angle * Math.PI) / 180
  return { x: CENTRE + radius * Math.cos(radians), y: CENTRE + radius * Math.sin(radians) }
}

export function RippleField({ className, focus }: { className?: string; focus?: number }) {
  return (
    <svg viewBox="0 0 640 640" className={className} role="img" aria-label="An alert on checkout-api spreading outward to systems, people, customers and promises">
      {RINGS.map((ring, index) => (
        <g key={ring.label}>
          <circle cx={CENTRE} cy={CENTRE} r={ring.radius} fill="none" stroke={index === focus ? "var(--brand)" : "currentColor"} strokeOpacity={index === focus ? 0.7 : 0.16} strokeDasharray={index === focus ? undefined : "2 5"} />
          <text x={CENTRE} y={CENTRE - ring.radius - 6} textAnchor="middle" className="fill-current text-[10px] font-medium opacity-45">
            {ring.label}
          </text>
        </g>
      ))}
      {[0, 0.5].map((offset) => (
        <motion.circle
          key={offset}
          cx={CENTRE}
          cy={CENTRE}
          fill="none"
          stroke="var(--brand)"
          strokeWidth={offset ? 1 : 1.6}
          initial={{ r: 0, opacity: 0 }}
          animate={{ r: [0, REACH], opacity: [offset ? 0.5 : 0.95, 0] }}
          transition={{ duration: CYCLE, delay: offset, repeat: Infinity, ease: "linear" }}
        />
      ))}
      {STONES.map((stone) => {
        const { radius } = RINGS[stone.ring]
        const { x, y } = place(radius, stone.angle)
        const reached = radius / REACH
        const outermost = stone.ring === RINGS.length - 1
        const anchor = outermost ? "middle" : x < CENTRE ? "end" : "start"
        const shift = { middle: 0, end: -10, start: 10 }[anchor]
        return (
          <motion.g
            key={stone.text}
            initial={{ opacity: 0.28 }}
            animate={{ opacity: [0.28, 0.28, 1, 1, 0.28] }}
            transition={{ duration: CYCLE, times: [0, reached, Math.min(reached + 0.03, 0.97), 0.97, 1], repeat: Infinity, ease: "linear" }}
          >
            <circle cx={x} cy={y} r="4" fill="var(--background)" stroke="currentColor" strokeWidth="1.2" />
            <text x={x + shift} y={outermost ? y + (y < CENTRE ? -12 : 20) : y + 4} textAnchor={anchor} className={stone.ring === focus ? "fill-current text-[12.5px] font-semibold" : "fill-current text-[12.5px]"}>
              {stone.text}
            </text>
          </motion.g>
        )
      })}
      <circle cx={CENTRE} cy={CENTRE} r="6" fill="var(--brand)" />
      <motion.circle cx={CENTRE} cy={CENTRE} r="6" fill="none" stroke="var(--brand)" animate={{ r: [6, 18], opacity: [0.8, 0] }} transition={{ duration: 1.6, repeat: Infinity, ease: "easeOut" }} />
      <text x={CENTRE} y={CENTRE + 26} textAnchor="middle" className="fill-current text-[11px] font-semibold">
        Alert · checkout-api 5xx
      </text>
    </svg>
  )
}
