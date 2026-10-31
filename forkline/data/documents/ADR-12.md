# ADR-12: Snapshots go to object storage every fifteen minutes

Status: Accepted
Date: 2026-08-11
Deciders: Tomas Reyes

## Decision
persistence writes a snapshot of every cluster to object storage every fifteen minutes.

## Risks
A failure between two snapshots can lose up to fifteen minutes of writes on a cluster without a replica.

## Applies to
This decision governs persistence.
