# ADR-5: Fraud scoring is synchronous with a 300 ms timeout

Status: Accepted
Date: 2026-04-22
Deciders: Ravi Menon

## Context
Charges must be scored before capture, but fraud-scorer latency is variable.

## Decision
payments-core calls fraud-scorer synchronously and fails open after 300 ms.

## Consequences
A slow fraud-scorer adds at most 300 ms to a charge. Charges are never blocked by it.
