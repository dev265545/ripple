# ADR-7: Cap the ledger pool at 20 connections per payments pod

Status: Accepted
Date: 2026-09-28
Deciders: Tomas Novak
Supersedes: ADR-3

## Context
INC-088 took ledger-db down when payouts scaled out and the database ran out of connections. ledger-db accepts 100 connections in total. payments-core runs 4 pods, each holding up to 100 connections under ADR-3.

## Decision
Each payments-core pod holds at most 20 ledger-db connections, so that all pods together stay under the ledger-db limit of 100.

## Risks
Under burst traffic, requests beyond the pool size fail immediately unless a bounded wait queue is added in front of the pool.

## Consequences
ledger-db can no longer be exhausted by payments-core. A wait queue is planned as follow-up work and is not part of this change.
