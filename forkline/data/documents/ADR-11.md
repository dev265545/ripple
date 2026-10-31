# ADR-11: Every customer gets its own database process

Status: Accepted
Date: 2026-08-11
Deciders: Tomas Reyes

## Decision
Each customer's graphs run in a database process of their own, so that one customer's heavy query cannot slow another's.

## Risks
A customer with many small graphs pays for memory it does not use.

## Applies to
This decision governs module.
