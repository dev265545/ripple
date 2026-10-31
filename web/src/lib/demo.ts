type Json = any // eslint-disable-line @typescript-eslint/no-explicit-any

export const DEMO = import.meta.env.VITE_RIPPLE_DEMO === "1"

const cache = new Map<string, Promise<Json>>()

function load(file: string): Promise<Json> {
  if (!cache.has(file)) {
    cache.set(
      file,
      fetch(`/demo/${file}`).then((response) => {
        if (!response.ok) throw new Error("Not captured in this static demo. Run Ripple locally to explore everything.")
        return response.json()
      }),
    )
  }
  return cache.get(file)!
}

const snapshot = (path: string) => load(`${encodeURIComponent(path).replaceAll("%", "~")}.json`)

function readOnly(): never {
  throw new Error("This is a read-only demo. Run Ripple locally to connect sources and take actions.")
}

async function search(tenant: string, query: string) {
  const graph = await snapshot(`/${tenant}/graph`)
  const q = query.toLowerCase()
  return graph.nodes
    .filter((node: Json) => `${node.id} ${node.name}`.toLowerCase().includes(q))
    .slice(0, 20)
    .map((node: Json) => ({ kind: node.kind, id: node.id, name: node.name }))
}

async function login(tenant: string, email: string) {
  const [people, personas] = await Promise.all([snapshot(`/${tenant}/people`), load("personas.json")])
  const persona = people.find((person: Json) => person.id === personas[tenant])
  if (persona?.email !== email) throw new Error(`In the demo, sign in as ${persona?.name} (${persona?.email}).`)
  return persona
}

async function chat(tenant: string, text: string) {
  const answer = (await load("chats.json"))[tenant]?.[text]
  if (!answer) throw new Error("The static demo only has saved answers for the suggested questions. Run Ripple locally to ask anything.")
  return answer
}

async function fire(tenant: string, scenario: string) {
  const investigation = (await load("fires.json"))[tenant]?.[scenario]
  if (!investigation) readOnly()
  return { investigation, opened: true }
}

export async function demoRequest<T>(path: string, init?: RequestInit): Promise<T> {
  return route(path, init) as Promise<T>
}

async function route(path: string, init?: RequestInit): Promise<Json> {
  const [endpoint, query = ""] = path.split("?")
  const tenant = endpoint.split("/")[1]
  if (!init?.method || init.method === "GET") {
    if (endpoint.endsWith("/search")) return search(tenant, new URLSearchParams(query).get("q") ?? "")
    return snapshot(path)
  }
  const body = typeof init.body === "string" ? JSON.parse(init.body) : {}
  if (endpoint.endsWith("/login")) return login(tenant, body.email)
  if (endpoint.endsWith("/chat")) return chat(tenant, body.text)
  const fired = endpoint.match(/^\/[^/]+\/scenarios\/([^/]+)\/fire$/)
  if (fired) return fire(tenant, fired[1])
  return readOnly()
}
