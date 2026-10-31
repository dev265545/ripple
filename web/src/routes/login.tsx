import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { useState, type FormEvent } from "react"

import { Mark } from "@/components/brand"
import { RippleButton } from "@/components/ripple-button"
import { Loading, Skeleton, Spinner } from "@/components/status"
import { Input } from "@/components/ui/input"
import { get, post, type Person } from "@/lib/api"
import { cn } from "@/lib/utils"
import { writeSession } from "@/lib/workspace"

export function Login() {
  const navigate = useNavigate()
  const client = useQueryClient()
  const tenants = useQuery({ queryKey: ["tenants"], queryFn: () => get<string[]>("/tenants") })
  const [chosen, setTenant] = useState(() => new URLSearchParams(window.location.search).get("company"))
  const tenant = chosen ?? tenants.data?.[0] ?? null
  const [email, setEmail] = useState("")
  const people = useQuery({ queryKey: [tenant, "people"], queryFn: () => get<Person[]>(`/${tenant}/people`), enabled: tenant !== null })
  const signIn = useMutation({
    mutationFn: (address: string) => post<Person>(`/${tenant}/login`, { email: address }),
    onSuccess: (user) => {
      writeSession({ tenant: tenant!, user })
      client.clear()
      void navigate({ to: "/app" })
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    signIn.mutate(email)
  }

  return (
    <div className="grid min-h-screen place-items-center bg-muted px-4 py-10">
      <main className="w-full max-w-md">
        <Link to="/" aria-label="Ripple home" className="mx-auto block w-fit">
          <Mark className="size-12 rounded-2xl shadow-md" />
        </Link>
        <h1 className="mt-6 text-center font-heading text-3xl">Sign in to Ripple</h1>
        <p className="mt-2 text-center text-[15px] text-muted-foreground">Use a work email from the company's HR directory. This build has no password.</p>
        <form onSubmit={submit} className="mt-8 space-y-4 rounded-3xl bg-background p-6 shadow-sm">
          <fieldset className="space-y-1.5 text-sm font-medium">
            <legend className="mb-1.5">Company</legend>
            <div className="flex flex-wrap gap-1.5">
              {tenants.isPending && (
                <Loading label="Loading companies" className="flex gap-1.5">
                  <Skeleton className="h-8 w-24 rounded-full" />
                  <Skeleton className="h-8 w-20 rounded-full" />
                </Loading>
              )}
              {tenants.data?.map((name) => (
                <button
                  key={name}
                  type="button"
                  aria-pressed={name === tenant}
                  onClick={() => setTenant(name)}
                  className={cn("rounded-full border px-3.5 py-1.5 font-medium text-muted-foreground", name === tenant && "border-foreground bg-foreground text-background")}
                >
                  {name}
                </button>
              ))}
            </div>
          </fieldset>
          <label className="block space-y-1.5 text-sm font-medium">
            Work email
            <Input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.example" className="h-10 font-normal" />
          </label>
          {signIn.isError && <p className="text-sm text-destructive">{signIn.error.message}</p>}
          {tenants.isError && <p className="text-sm text-destructive">Cannot reach the Ripple server. Start FalkorDB and the API, then reload.</p>}
          {tenants.data?.length === 0 && <p className="text-sm text-destructive">No company is loaded yet. Set one up below.</p>}
          <RippleButton type="submit" size="lg" disabled={!tenant || signIn.isPending} className="h-11 w-full rounded-full text-[15px]">
            {signIn.isPending && <Spinner />}
            {signIn.isPending ? "Checking the directory…" : "Continue"}
          </RippleButton>
          {tenant && people.isPending && (
            <Loading label="Loading the directory" className="space-y-3 pt-4">
              {Array.from({ length: 4 }, (_, index) => (
                <div key={index} className="flex items-center gap-3 px-2">
                  <Skeleton className="size-8 rounded-full" />
                  <div className="flex-1 space-y-1.5">
                    <Skeleton className="h-3.5 w-32" />
                    <Skeleton className="h-3 w-44" />
                  </div>
                </div>
              ))}
            </Loading>
          )}
          {people.data?.length === 0 && (
            <p className="rounded-xl bg-muted px-3 py-2.5 text-sm text-muted-foreground">
              {`Nobody can sign in to ${tenant} yet, because its HR directory has not been uploaded. `}
              <a href={`/setup?company=${tenant}`} className="font-medium text-foreground underline underline-offset-4">
                Finish its setup
              </a>
            </p>
          )}
          {people.data && people.data.length > 0 && (
            <div className="pt-2">
              <p className="flex items-center gap-3 text-xs text-muted-foreground before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border">
                {`or sign in as one of ${people.data.length} people`}
              </p>
              <ul className="mt-3 max-h-56 space-y-0.5 overflow-y-auto">
                {people.data.map((person) => (
                  <li key={person.id}>
                    <button
                      type="button"
                      disabled={signIn.isPending}
                      onClick={() => {
                        setEmail(person.email)
                        signIn.mutate(person.email)
                      }}
                      className={cn("flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left text-sm hover:bg-muted", person.email === email && "bg-muted")}
                    >
                      <span className="grid size-8 shrink-0 place-items-center rounded-full bg-foreground text-xs font-medium text-background">{person.name[0]}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block font-medium">{person.name}</span>
                        <span className="block truncate text-xs text-muted-foreground">{`${person.role} · ${person.team}`}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </form>
        <p className="mt-6 text-center text-sm text-muted-foreground">
          New here?{" "}
          <Link to="/setup" className="font-medium text-foreground underline underline-offset-4">
            Set up your company
          </Link>
        </p>
      </main>
    </div>
  )
}
