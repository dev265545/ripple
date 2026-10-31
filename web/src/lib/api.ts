import { DEMO, demoRequest } from "@/lib/demo"

export type Row = Record<string, unknown>

export interface Investigation {
  id: string
  status: string
  service: string
  symptom: string
  incident: string
  steps: number
  root_kind?: string | null
  root_id?: string | null
  root_service?: string | null
  root_title?: string | null
  playbook?: string | null
}

export interface Incident {
  id: string
  title: string
  status: string
  started_at: string
}

export interface Task {
  id: string
  kind: string
  stage: number
  status: string
  summary?: string | null
  claimed_by?: string | null
}

export interface Step {
  id: string
  seq: number
  agent: string
  tool: string
  params: Row
  rows: number
  refs: string[]
  result: Row[]
}

export interface Hypothesis {
  id: string
  subject: string
  status: string
  statement: string
  score: number
  factors: Record<string, number>
}

export interface Finding {
  id: string
  kind: string
  agent: string
  claim: string
  refs: string[]
}

export interface Action {
  id: string
  kind: string
  to: string
  channel: string
  subject: string
  body: string
  status: string
  approved_by?: string | null
  delivered?: string | null
  url?: string | null
}

export interface Remediation {
  id: string
  kind: "rollback" | "fix"
  title: string
  summary: string
  warning: string
  diff: string
  status: string
  branch: string
  repo: string
  tests_passed: boolean
  load_passed: boolean
  load_output: string
  refs: string[]
  pr?: string | null
  merged_by?: string | null
  written_by?: string | null
}

export interface CanvasData {
  nodes: { kind: string; id: string; name: string; first_seq?: number | null }[]
  edges: { source: string; relation: string; target: string }[]
}

export interface Scenario {
  id: string
  title: string
  story: string | null
  basis: string | null
  service: string
  symptom: string
  summary: string
  at: string
}

export interface SourcedGraph {
  sources: { id: string; name: string }[]
  nodes: { kind: string; id: string; name: string; sources: string[]; area?: string | null }[]
  edges: CanvasData["edges"]
  withheld?: number
}

export interface Area {
  id: string
  title: string
  summary: string
  findings: { text: string; refs: string[] }[]
  size: number
  members: string[]
  built_at: string
  written_by: string | null
  open_incidents: string[]
}

export interface CheckFinding {
  kind: "conflict" | "stale"
  text: string
  refs: string[]
  records: string[]
}

export interface Trust {
  kind: string
  id: string
  name: string
  owner: string | null
  verified_by: string | null
  verified_at: string | null
  days: number | null
  due_at: string | null
  state: "unverified" | "verified" | "expired" | "changed"
}

export interface IncidentState {
  investigation: Investigation
  incident: Incident
  tasks: Task[]
  steps: Step[]
  hypotheses: Hypothesis[]
  findings: Finding[]
  actions: Action[]
  remediations: Remediation[]
  canvas: CanvasData
}

export interface InvestigationSummary {
  id: string
  incident: string
  title: string
  incident_status: string
  status: string
  steps: number
  root: string | null
  playbook: string | null
}

export interface Memory {
  playbooks: { id: string; symptom: string; service: string; tools: string[]; risk: string[]; wins: number; losses: number }[]
  facts: { id: string; text: string; services: string[] }[]
  notes: { id: string; text: string; written_by: string; written_at: string; origin: string; origin_name: string; about: string[] }[]
  investigations: InvestigationSummary[]
}

export interface ReviewPair {
  kind: string
  customer: string | null
  customer_name: string | null
  newer: string
  newer_text: string
  newer_quote: string | null
  newer_record: string | null
  newer_at: string | null
  older: string
  older_text: string
  older_quote: string | null
  older_record: string | null
  older_at: string | null
  found_by: string | null
  reason: string | null
}

export interface Brief {
  promises: { id: string; text: string; customer: string; customer_name: string; made_at: string; valid_to: string | null }[]
  projects: { id: string; name: string; status: string; due_at: string | null; goal: string; open_incidents: string[] }[]
  on_call: { service: string; until: string }[]
  only_expert: { service: string }[]
  recent: { kind: string; id: string; title: string; at: string | null; note: string | null }[]
  review: ReviewPair[]
  to_check: Trust[]
}

export interface Source {
  id: string
  name: string
  uri: string
  last_sync: string
  records: number
  nodes: number
}

export interface Overview {
  nodes: { kind: string; count: number }[]
  edges: number
}

export interface Entity {
  kind: string
  id: string
  props: Row
  neighbours: { relation: string; outgoing: boolean; kind: string; id: string; name: string; quote: string | null; src: string | null; at: string | null }[]
  sources: { source: string; record: string; uri: string; quote: string | null; fetched_at: string; visibility: "org" | "restricted" | "shared"; readers: string[] }[]
  trust: Trust | null
}

export interface SearchHit {
  kind: string
  id: string
  name: string
}

export interface Tool {
  name: string
  doc: string
  params: string[]
  cypher: string
}

export interface ToolResult {
  rows: Row[]
  refs: string[]
}

export interface Turn {
  session: string
  seq: number
  role: string
  text: string
  at: string
  refs: string[]
}

export interface Evaluation {
  runs?: { scenario: string; title: string; truth: string; root: string | null; investigator_steps: number; correct: boolean }[]
  accuracy?: number
  memory?: { scenario: string; cold_steps: number; warm_steps: number; cold_correct: boolean; warm_correct: boolean; playbook: string | null }
  reading?: { model: string; expected: number; found: number; matched: number; documents: { document: string }[] }
}

export interface LoadResult {
  claimed: number
  double_claims: number
  claims_per_second: number
  p95_claim_ms: number
}

/** Who is asking, so the server can leave out what this person may not read. */
function viewer(): Record<string, string> {
  try {
    const id = JSON.parse(localStorage.getItem("ripple.session") ?? "null")?.user?.id
    return id ? { "X-Ripple-User": id } : {}
  } catch {
    return {}
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (DEMO) return demoRequest<T>(path, init)
  const response = await fetch(`/api${path}`, { ...init, headers: { ...viewer(), ...init?.headers } })
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}))
    throw new Error(typeof problem.detail === "string" ? problem.detail : response.statusText)
  }
  return response.json()
}

export const get = <T,>(path: string) => request<T>(path)

export const postFile = <T,>(path: string, file: File) =>
  request<T>(`${path}?name=${encodeURIComponent(file.name)}`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file })

export const post = <T,>(path: string, body: object = {}) =>
  request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })

export interface Person {
  id: string
  name: string
  email: string
  role: string
  team: string
}

export interface GithubConnection {
  connected: boolean
  repo?: string
  has_token?: boolean
  checked_at?: string | null
  error?: string
  every_seconds?: number
  label?: string
  hook?: string
  secret?: string
}

export interface LiveConnection {
  watching: string
  sends: string
  checked_at: string | null
  error: string
  every_seconds: number
}

export interface PublicStatus {
  company: string
  updates: { title: string; body: string; at: string; incident_status: string; resolved_at: string | null }[]
}

export interface SyncStats {
  records: number
  changed: number
}

export interface Connector {
  id: string
  name: string
  category: string
  systems: string[]
  reads: string
  produces: string[]
  source: string | null
  file: string | null
  status?: "connected" | "ready" | "listening" | "planned"
  records?: number
  nodes?: number
  last_sync?: string
  uri?: string
  example?: boolean
  live?: {
    pull: string
    fields: { name: string; label: string; placeholder: string; secret?: boolean; optional?: boolean }[]
    help: string
  }
  watch?: {
    pull: string
    fields: { name: string; label: string; placeholder: string }[]
    help: string
  }
  inbox?: {
    accepts: string
    pull: string | null
    fields: { name: string; label: string; placeholder: string; secret?: boolean; optional?: boolean }[]
    help: string
  }
}

export interface InboxStats extends SyncStats {
  linked: number
  promises: number
  decisions: number
  notes: number
  skipped: number
  model: string | null
}

export interface LinkedEntity {
  kind: string
  id: string
  name: string
  quote: string
}

export interface AddedDocument {
  doc: string
  record: string
  title: string
  linked: LinkedEntity[]
  promises: { id: string; text: string; quote: string; customer: string; customer_name: string; made_by: string; made_by_name: string }[]
  links: { from: [string, string]; type: string; to: [string, string]; quote: string }[]
  model: string | null
  changed: number
}

export interface SourceRecord {
  id: string
  uri: string
  hash: string
  fetched_at: string
  nodes: number
}

export interface RecordTrace {
  id: string
  uri: string
  hash: string
  fetched_at: string
  source: string
  text: string | null
  nodes: { kind: string; id: string; name: string; quote: string | null; inferred: boolean }[]
  edges: { source: string; relation: string; target: string; quote: string | null; inferred: boolean }[]
}

export interface Citation {
  ref: string
  name: string
  source: string
  record: string
  uri: string
  quote: string | null
  verified_by: string | null
}

export interface ChatAnswer {
  answer: string
  lines: string[]
  tool: string | null
  cypher: string | null
  params: Row
  rows: Row[]
  refs: string[]
  citations: Citation[]
  carried: string | null
  withheld: number
  model: string | null
  steps?: QueryStep[]
}

export type QueryStep = Pick<ChatAnswer, "tool" | "cypher" | "params" | "rows">

export const remove = <T,>(path: string) => request<T>(path, { method: "DELETE" })
