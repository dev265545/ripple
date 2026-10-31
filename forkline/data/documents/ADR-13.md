# ADR-13: Queries on shared plans stop after thirty seconds

Status: Accepted
Date: 2026-08-11
Deciders: Hana Kobayashi

## Decision
runtime stops any query on a shared plan that has run for thirty seconds.

## Risks
A legitimate analytical query on a shared plan is cut off and has to be moved to a dedicated plan.

## Applies to
This decision governs runtime.
