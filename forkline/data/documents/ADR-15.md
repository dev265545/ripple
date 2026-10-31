# ADR-15: Vector indexes are built on a replica

Status: Accepted
Date: 2026-08-11
Deciders: Sara Haddad

## Decision
A new vector index is built on a replica and swapped in, so that building it never blocks writes on the primary.

## Risks
A cluster without a replica cannot build a vector index without a short pause in writes.

## Applies to
This decision governs index.
