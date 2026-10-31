import { useNavigate } from "@tanstack/react-router"
import { X } from "lucide-react"
import { motion } from "motion/react"

import { RippleButton } from "@/components/ripple-button"
import { cn } from "@/lib/utils"

const STOPS = [
  { to: null, title: "A one-minute tour", says: "Ripple is a team of agents that works an incident on one graph of the company: its code, services, customers, contracts and promises. A few short stops show you where everything is." },
  { to: "/app/simulator", title: "Start by breaking something", says: "Pick an incident and press Run. The agents investigate for real, then you watch it back one step at a time: the question each agent asked, the graph query it ran, and what lit up." },
  { to: "/app", title: "Read what they found", says: "The incident room is the same investigation as a report. The likely cause, who it reaches, what was promised to them, and two ways out, each with its diff and test results." },
  { to: "/app", title: "You decide, not Ripple", says: "Fixes and messages wait under Proposed. You can edit, approve or reject each one. Nothing is merged or sent before that." },
  { to: "/app", title: "Click anything", says: "Every coloured chip is a real thing in the graph: a person, a pull request, a function, a customer. Click one to see what it connects to and the record it was read from." },
  { to: "/app/chat", title: "Ask in plain words", says: "Ripple picks the graph queries your question needs, answers from their rows, and shows you the Cypher it ran. Try asking what a pull request can reach." },
  { to: "/app/connect", title: "See where it all comes from", says: "Git, the service catalog, the CRM, contracts, Gmail, Drive, Slack and WhatsApp each feed the same graph. Open one of the inboxes and read its sample to watch a message turn into people, links and promises." },
  { to: "/app/brief", title: "Your own page", says: "My brief is the graph from where you stand: promises you made, projects you lead, and any two promises that look like they disagree and need your call." },
  { to: "/app/graph", title: "All of it at once", says: "Every dot is one thing Ripple read. Group them by kind, by source or by the areas FalkorDB finds in the graph, and point at one to see what it joins. Mail you are not on stays out of your view." },
  { to: "/app/memory", title: "It gets faster", says: "When you confirm a cause, Ripple keeps the order of checks that found it. The next incident with the same symptom starts from that playbook." },
] as const

const SEEN_KEY = "ripple.tour.seen"

export const tourSeen = () => localStorage.getItem(SEEN_KEY) !== null

export function Tour({ stop, onStop }: { stop: number | null; onStop: (stop: number | null) => void }) {
  const navigate = useNavigate()
  if (stop === null) return null
  const current = STOPS[stop]
  const last = stop === STOPS.length - 1

  function go(next: number | null) {
    localStorage.setItem(SEEN_KEY, "1")
    onStop(next)
    const to = next === null ? null : STOPS[next].to
    if (to) void navigate({ to })
  }

  return (
    <motion.aside
      key={stop}
      aria-label="Guided tour"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="fixed right-6 bottom-6 z-40 w-[22rem] rounded-3xl bg-foreground p-5 text-background shadow-2xl"
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-[17px] leading-snug font-medium">{current.title}</h2>
        <button type="button" aria-label="Close the tour" onClick={() => go(null)} className="rounded-full p-1 text-background/60 hover:bg-background/10 hover:text-background">
          <X className="size-4" />
        </button>
      </div>
      <p className="mt-2 text-sm leading-relaxed text-background/75">{current.says}</p>
      <div className="mt-4 flex items-center gap-2">
        <div className="flex gap-1" aria-label={`Stop ${stop + 1} of ${STOPS.length}`}>
          {STOPS.map((item, index) => (
            <span key={item.title} className={cn("h-1.5 rounded-full transition-all", index === stop ? "w-5 bg-brand" : "w-1.5 bg-background/30")} />
          ))}
        </div>
        {stop > 0 && (
          <button type="button" onClick={() => go(stop - 1)} className="ml-auto rounded-full px-3 py-1.5 text-sm text-background/70 hover:text-background">
            Back
          </button>
        )}
        <RippleButton size="sm" className={cn("rounded-full bg-background text-foreground hover:bg-background/85", stop === 0 && "ml-auto")} onClick={() => go(last ? null : stop + 1)}>
          {last ? "Done" : "Next"}
        </RippleButton>
      </div>
    </motion.aside>
  )
}
