import {
  siArgo,
  siBackstage,
  siBamboo,
  siConfluence,
  siDatadog,
  siGithub,
  siGithubactions,
  siGitlab,
  siGmail,
  siGoogledocs,
  siGooglecalendar,
  siGoogledrive,
  siGrafana,
  siHubspot,
  siJira,
  siKubernetes,
  siLinear,
  siNotion,
  siOkta,
  siOpentelemetry,
  siOpsgenie,
  siPagerduty,
  siPrometheus,
  siSentry,
  siStatuspage,
  siWhatsapp,
  siZendesk,
  type SimpleIcon,
} from "simple-icons"

import { cn } from "@/lib/utils"

const ICONS: Record<string, SimpleIcon> = {
  "Argo CD": siArgo,
  Backstage: siBackstage,
  BambooHR: siBamboo,
  Confluence: siConfluence,
  Datadog: siDatadog,
  GitHub: siGithub,
  "GitHub Actions": siGithubactions,
  GitLab: siGitlab,
  Gmail: siGmail,
  "Google Calendar": siGooglecalendar,
  "Google Docs": siGoogledocs,
  "Google Drive": siGoogledrive,
  Grafana: siGrafana,
  HubSpot: siHubspot,
  Jira: siJira,
  Kubernetes: siKubernetes,
  Linear: siLinear,
  Notion: siNotion,
  Okta: siOkta,
  OpenTelemetry: siOpentelemetry,
  Opsgenie: siOpsgenie,
  PagerDuty: siPagerduty,
  Prometheus: siPrometheus,
  Sentry: siSentry,
  Statuspage: siStatuspage,
  WhatsApp: siWhatsapp,
  Zendesk: siZendesk,
}

export function BrandIcon({ system, className }: { system: string; className?: string }) {
  const icon = ICONS[system]
  if (!icon) {
    return <span className={cn("grid size-4 place-items-center rounded-sm border font-mono text-[9px] leading-none uppercase", className)}>{system[0]}</span>
  }
  return (
    <svg viewBox="0 0 24 24" role="img" aria-label={system} className={cn("size-4 fill-current", className)}>
      <path d={icon.path} />
    </svg>
  )
}

export function Mark({ className }: { className?: string }) {
  return (
    <span className={cn("grid size-7 place-items-center rounded-lg bg-foreground text-background", className)}>
      <svg viewBox="0 0 24 24" className="size-[70%]" fill="none" stroke="currentColor" aria-hidden>
        <circle cx="12" cy="12" r="2.2" fill="var(--brand)" stroke="none" />
        <circle cx="12" cy="12" r="6" strokeWidth="1.6" />
        <circle cx="12" cy="12" r="10.2" strokeWidth="1.2" opacity="0.5" />
      </svg>
    </span>
  )
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-[17px] font-semibold tracking-tight", className)}>
      <Mark />
      Ripple
    </span>
  )
}

export function Rings({ count = 4, className }: { count?: number; className?: string }) {
  return (
    <div aria-hidden className={cn("pointer-events-none absolute aspect-square", className)}>
      {Array.from({ length: count }, (_, index) => (
        <span key={index} className="absolute inset-0 animate-swell rounded-full border border-current" style={{ animationDelay: `${(-index * 5) / count}s` }} />
      ))}
    </div>
  )
}
