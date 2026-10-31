import { splitRef, useWorkspace } from "@/lib/workspace"
import { cn } from "@/lib/utils"

export const KIND_COLOR: Record<string, string> = {
  Service: "#2f6f9f",
  Vendor: "#a8487a",
  PR: "#c2571b",
  Event: "#a37b10",
  Decision: "#6b55a8",
  Incident: "#b8392f",
  Requirement: "#8a4fa3",
  Feature: "#22807a",
  Customer: "#3f7d3a",
  Contract: "#5d7a2c",
  SLA: "#7a7a1f",
  Commitment: "#a3691a",
  Person: "#8a8477",
  Team: "#7b766b",
  File: "#4a6fa5",
  Symbol: "#2d8a9e",
  Email: "#22807a",
  Doc: "#6f6a8f",
  Conversation: "#1f8f6a",
  Channel: "#4f7f73",
  Contact: "#9a8f7c",
  Note: "#b0832a",
  Project: "#c2571b",
  Area: "#2f6f9f",
  Fix: "#71717a",
  Message: "#f04a23",
}

export const KIND_MEANING: Record<string, string> = {
  Service: "A running system, such as checkout-api.",
  PR: "A merged pull request: a change to a service.",
  Decision: "A recorded choice, such as an ADR, and the risk it accepted.",
  Incident: "Something that went wrong, now or in the past.",
  Customer: "A company that uses your product.",
  Feature: "A part of the product that customers use and services serve.",
  Contract: "A signed agreement with a customer.",
  SLA: "An uptime guarantee inside a contract, with the credit owed if it is missed.",
  Commitment: "A promise someone made to a customer, usually in an email.",
  Requirement: "Something a document says a service must do.",
  Person: "Someone in the HR directory.",
  Team: "A group of people that owns services.",
  Vendor: "An outside provider a service depends on.",
  Event: "A customer's sale or launch on the calendar.",
  File: "A source file in a service's repository.",
  Symbol: "A function, class or constant in the code, with what uses it.",
  Email: "A message read from a mailbox.",
  Doc: "A document or file Ripple read.",
  Conversation: "One day of a chat channel or group, kept as it was written.",
  Channel: "A chat channel or group.",
  Contact: "Someone who wrote or was written to and is not in the HR directory.",
  Note: "One line a language model wrote about what a message or file means. Not a quote.",
  Project: "A piece of planned work, with its lead, services, changes and customers.",
  Area: "A part of the company found by clustering the graph: things more connected to each other than to the rest.",
  Fix: "A change Ripple proposes, waiting for your approval.",
  Message: "A message Ripple drafted, waiting for your approval.",
}

export function RefChip({ reference, label, className }: { reference: string; label?: string; className?: string }) {
  const { openEntity } = useWorkspace()
  const { kind, id } = splitRef(reference)
  return (
    <button
      type="button"
      onClick={() => openEntity(reference)}
      title={KIND_MEANING[kind]}
      className={cn("inline-flex max-w-full items-center gap-1.5 rounded-full border bg-card px-2 py-0.5 text-xs hover:border-ring", className)}
    >
      <span className="size-1.5 shrink-0 rounded-full" style={{ background: KIND_COLOR[kind] ?? "#7b766b" }} />
      <span className="text-muted-foreground">{kind}</span>
      <span className="truncate font-medium">{label ?? id}</span>
    </button>
  )
}

export function RefList({ refs }: { refs: string[] }) {
  if (refs.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1">
      {refs.map((reference) => (
        <RefChip key={reference} reference={reference} />
      ))}
    </div>
  )
}
