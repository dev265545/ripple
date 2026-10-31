# BRD-12: Festive season readiness

Owner: Sofia Marin
Date: 2026-09-15

## Background
Larkspur Retail runs its Festive Mega Sale in early October and expects three times its normal checkout volume.

## Requirements
R1. checkout-api must sustain 500 charges per second for the duration of a customer sale event.
R2. payments-core must answer 99% of charges within 800 ms during sale events.
R3. Merchants on enterprise plans must be told about any payments incident within 15 minutes.
