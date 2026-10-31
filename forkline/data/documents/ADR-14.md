# ADR-14: Engine upgrades go one minor version at a time

Status: Accepted
Date: 2026-08-11
Deciders: Ines Duarte

## Decision
packaging upgrades a cluster by one minor engine version at a time and waits a day between steps.

## Risks
A fix that only exists two versions ahead takes at least two days to reach a customer.

## Applies to
This decision governs packaging.
