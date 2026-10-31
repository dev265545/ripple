import { Link } from "@tanstack/react-router"
import { ArrowRight, BadgeCheck, BellRing, Brain, Cable, CirclePlay, FlaskConical, ListChecks, MessagesSquare, Newspaper, ScanSearch, Siren, Waypoints, type LucideIcon } from "lucide-react"

import { Eyebrow, PageHeader } from "@/components/page"
import { KIND_COLOR, KIND_MEANING } from "@/components/ref-chip"

const STEPS = [
  { icon: BellRing, title: "Fire an alert", detail: "Press Ctrl K and pick a scenario. Each one plants a real cause and a few red herrings in the demo company." },
  { icon: ScanSearch, title: "Watch the investigation", detail: "The incident room fills in stage by stage: triage, root cause, who it reaches, why it was built that way, ways out, who needs to hear." },
  { icon: ListChecks, title: "Review what needs you", detail: "Open the two fixes and the drafted messages. Nothing merges or sends until you approve it." },
  { icon: BadgeCheck, title: "Confirm the root cause", detail: "Confirming saves a playbook to memory, so the same kind of incident takes fewer steps next time." },
]

const SCREENS: { to: "/app" | "/app/simulator" | "/app/brief" | "/app/graph" | "/app/connect" | "/app/chat" | "/app/memory" | "/app/evaluation"; name: string; icon: LucideIcon; what: string; parts: string[] }[] = [
  {
    to: "/app",
    name: "Incident room",
    icon: Siren,
    what: "One incident from alert to resolution.",
    parts: [
      "Needs you: the decisions waiting on a person.",
      "Investigation: every stage, its findings and the graph queries behind them.",
      "Incident graph: the cause, the services, customers, contracts and promises it reaches, and the proposed fixes and messages.",
      "Fixes: a rollback and a proper fix, each with its diff and check results.",
      "Messages: drafts you can edit before approving.",
      "Right side: the likely cause and how each suspect scored.",
    ],
  },
  {
    to: "/app/simulator",
    name: "Simulator",
    icon: CirclePlay,
    what: "An incident replayed one step at a time.",
    parts: [
      "Run this incident: the agents investigate for real, then you step through what each one asked and found.",
      "Code walk: the Fixer follows the changed function through the code graph, writes a fix, and keeps it only if the repository's own checks pass.",
    ],
  },
  {
    to: "/app/brief",
    name: "My brief",
    icon: Newspaper,
    what: "What the graph holds about your own work today.",
    parts: [
      "Waiting for a human: two promises or decisions that look like they disagree. Both stay in force until someone chooses.",
      "Promises you made: every live promise to a customer with your name on it.",
      "Projects, on call, only expert: what you lead, what you are on call for, and services nobody else has worked on.",
      "Yours to keep current: promises and decisions you own that nobody has verified, or whose verification ran out or whose source changed since.",
      "Latest mail and chats: the conversations you were part of, with the model's note where it wrote one.",
    ],
  },
  {
    to: "/app/graph",
    name: "Graph",
    icon: Waypoints,
    what: "The whole company graph on one page.",
    parts: [
      "By kind of thing, by source system or by area: three ways to group the same dots.",
      "Areas: clusters FalkorDB finds in the graph, each with a summary. Ask Ripple uses them for questions about the company as a whole.",
      "Point at a dot to light up what it connects to. Click it for its records.",
    ],
  },
  {
    to: "/app/connect",
    name: "Connect",
    icon: Cable,
    what: "Where the company graph comes from.",
    parts: [
      "Connectors: each system Ripple reads, with its status.",
      "Gmail, Google Drive and Word, Slack, WhatsApp: connect one, upload a file, or read the sample. Senders are matched to people and customers, and what each item names is linked.",
      "Promises, decisions and notes: found by the language model. A promise or decision is kept only if its sentence is in the text word for word.",
      "Add a document: paste any text and see which known things it names.",
      "Who can read what: a mail or WhatsApp chat is visible only to the people on it until one of them shares it. Channels and files are for everyone.",
      "Records: every record read, and the facts and quotes taken from it. A record that changes takes back what it no longer says.",
    ],
  },
  {
    to: "/app/chat",
    name: "Ask Ripple",
    icon: MessagesSquare,
    what: "Questions about the company, answered from the graph.",
    parts: [
      "Sources: numbered cards. Click one to open the record with the quote highlighted.",
      "In this answer: the things mentioned. Click one for its details and connections.",
      "How I got this: the exact query and rows behind the answer.",
      "Left out: when part of an answer comes only from mail or chats you are not on, Ripple leaves it out and says how many results it left out.",
    ],
  },
  {
    to: "/app/memory",
    name: "Memory",
    icon: Brain,
    what: "What Ripple keeps between incidents.",
    parts: [
      "Waiting for a human: the same review queue as My brief.",
      "Found by rules: conflicts and out-of-date knowledge that plain graph queries catch, such as a service with two owners or a project past its due date.",
      "Playbooks: the steps that found the cause last time. Kept only after a person confirms a root cause.",
      "Facts: short lessons tied to the services they are about.",
      "Notes: one line the model wrote about each mail, chat or file it read. A summary, not a quote.",
    ],
  },
  {
    to: "/app/evaluation",
    name: "Evaluation",
    icon: FlaskConical,
    what: "Proof that it works, rerun on demand.",
    parts: ["Run evaluation: every scenario on a fresh copy of the company.", "Task-claim race: many workers claiming tasks at once, counting double claims."],
  },
]

export function Guide() {
  return (
    <div className="mx-auto max-w-4xl space-y-10 px-10 py-8">
      <PageHeader eyebrow="Help" title="Guide" subtitle="What each screen is for, and what the words mean." />
      <section className="space-y-3">
        <Eyebrow>Start here</Eyebrow>
        <ul className="grid gap-3 sm:grid-cols-2">
          {STEPS.map((step) => (
            <li key={step.title} className="flex gap-3 rounded-2xl border p-4">
              <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-foreground text-background">
                <step.icon className="size-4" />
              </span>
              <div>
                <p className="font-medium">{step.title}</p>
                <p className="mt-0.5 text-sm text-muted-foreground">{step.detail}</p>
              </div>
            </li>
          ))}
        </ul>
      </section>
      <section className="space-y-3">
        <Eyebrow>Screens</Eyebrow>
        <div className="divide-y rounded-2xl border">
          {SCREENS.map((screen) => (
            <div key={screen.to} className="grid gap-x-6 gap-y-2 p-5 sm:grid-cols-[14rem_1fr]">
              <div>
                <Link to={screen.to} className="group flex items-center gap-2 font-medium">
                  <span className="grid size-8 place-items-center rounded-lg bg-muted">
                    <screen.icon className="size-4" />
                  </span>
                  {screen.name}
                  <ArrowRight className="size-3.5 opacity-0 transition group-hover:opacity-100" />
                </Link>
                <p className="mt-2 text-sm text-muted-foreground">{screen.what}</p>
              </div>
              <ul className="space-y-1.5 text-sm">
                {screen.parts.map((part) => {
                  const [name, ...rest] = part.split(": ")
                  return (
                    <li key={part}>
                      <span className="font-medium">{name}</span>
                      <span className="text-muted-foreground">{`: ${rest.join(": ")}`}</span>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))}
        </div>
      </section>
      <section className="space-y-3">
        <Eyebrow>The coloured chips</Eyebrow>
        <p className="text-sm text-muted-foreground">Every chip is one thing in the graph. The dot colour tells you what kind it is. Click any chip to see where it came from and what it connects to.</p>
        <dl className="grid gap-x-8 gap-y-2.5 sm:grid-cols-2">
          {Object.entries(KIND_MEANING).map(([kind, meaning]) => (
            <div key={kind} className="flex items-baseline gap-2 text-sm">
              <span className="size-2 shrink-0 translate-y-[-1px] rounded-full" style={{ background: KIND_COLOR[kind] }} />
              <dt className="w-24 shrink-0 font-medium">{kind}</dt>
              <dd className="text-muted-foreground">{meaning}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  )
}
