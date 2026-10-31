# ADR-3: Pool of 100 ledger connections per payments pod

Status: Superseded by ADR-7
Date: 2026-03-11
Deciders: Ravi Menon

## Context
payments-core opens a new ledger-db connection for every charge. Under load the connection setup dominates latency.

## Decision
Each payments-core pod keeps a pool of 100 ledger-db connections.

## Consequences
Latency drops sharply. Total connections grow with the number of pods, which nobody is tracking yet.
