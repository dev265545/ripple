# ADR-9: Webhooks are delivered at least once

Status: Accepted
Date: 2026-07-15
Deciders: Priya Nair

## Decision
webhooks-service retries every payment event until the merchant acknowledges it, for up to 72 hours.

## Consequences
Merchants may receive duplicates and must deduplicate on the event id.
