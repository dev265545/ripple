# SOP-1: WAF Managed Rules changes deploy globally in one step

Status: Accepted
Source: https://blog.cloudflare.com/details-of-the-cloudflare-outage-on-july-2-2019/

Lines starting with ">" are quoted from that page. The id SOP-1 is ours.

## How other software ships
> Once approved deployment to what we call the "animal PoPs" occurs: DOG, PIG, and the Canaries.
> The entire DOG, PIG, Canary, Global process can take hours or days

## What the WAF does instead
> But, by design, the WAF doesn't use this process because of the need to respond rapidly to threats.
> The SOP for a rule change specifically allows it to be pushed globally.
> deployed using our Quicksilver distributed key-value (KV) store that can push changes globally in seconds

## Risk
> The SOP allowed a non-emergency rule change to go globally into production without a staged rollout.

## Volume
> In the last 60 days, 476 change requests have been handled for the WAF Managed Rules (averaging one every 3 hours).
