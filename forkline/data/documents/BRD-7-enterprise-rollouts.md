# BRD-7: Enterprise rollouts

Owner: Yusuf Demir
Date: 2026-08-31

## Background
Harbor Analytics is moving its fraud graph to Forkline and asked for guarantees before it does.

## Requirements
R1. module must keep 2,000 connections open at once without dropping any.
R2. runtime must answer 99% of two-hop queries within 50 milliseconds.
R3. Enterprise customers must be told about any outage within 15 minutes.
