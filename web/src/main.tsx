import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from "@tanstack/react-router"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import { Shell } from "@/components/shell"
import "@/index.css"
import { BriefPage } from "@/routes/brief"
import { Chat } from "@/routes/chat"
import { Connect } from "@/routes/connect"
import { Evaluation } from "@/routes/evaluation"
import { GraphView } from "@/routes/graph"
import { Guide } from "@/routes/guide"
import { IncidentRoom } from "@/routes/incident"
import { Landing } from "@/routes/landing"
import { ActivityBar } from "@/components/status"
import { Login } from "@/routes/login"
import { Setup } from "@/routes/setup"
import { Simulator } from "@/routes/simulator"
import { StatusPage } from "@/routes/status"
import { MemoryPanel } from "@/routes/memory"
import { DEMO } from "@/lib/demo"

function DemoBanner() {
  return (
    <div className="bg-foreground px-4 py-1.5 text-center text-xs text-background">
      Static demo with recorded data: sign in as Elena Voss (Northwind) or John Graham-Cumming (Cloudflare 2019). Actions are read-only.
    </div>
  )
}

function Root() {
  return (
    <>
      {DEMO && <DemoBanner />}
      <ActivityBar />
      <Outlet />
    </>
  )
}

const rootRoute = createRootRoute({ component: Root })
const appRoute = createRoute({ getParentRoute: () => rootRoute, path: "/app", component: Shell })
const routeTree = rootRoute.addChildren([
  createRoute({ getParentRoute: () => rootRoute, path: "/", component: Landing }),
  createRoute({ getParentRoute: () => rootRoute, path: "/login", component: Login }),
  createRoute({ getParentRoute: () => rootRoute, path: "/setup", component: Setup }),
  createRoute({ getParentRoute: () => rootRoute, path: "/status/$tenant", component: StatusPage }),
  appRoute.addChildren([
    createRoute({ getParentRoute: () => appRoute, path: "/", component: IncidentRoom }),
    createRoute({ getParentRoute: () => appRoute, path: "/simulator", component: Simulator }),
    createRoute({ getParentRoute: () => appRoute, path: "/brief", component: BriefPage }),
    createRoute({ getParentRoute: () => appRoute, path: "/graph", component: GraphView }),
    createRoute({ getParentRoute: () => appRoute, path: "/connect", component: Connect }),
    createRoute({ getParentRoute: () => appRoute, path: "/chat", component: Chat }),
    createRoute({ getParentRoute: () => appRoute, path: "/memory", component: MemoryPanel }),
    createRoute({ getParentRoute: () => appRoute, path: "/evaluation", component: Evaluation }),
    createRoute({ getParentRoute: () => appRoute, path: "/guide", component: Guide }),
  ]),
])
const router = createRouter({ routeTree, scrollRestoration: true })

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
