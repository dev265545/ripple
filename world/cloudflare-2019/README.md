# Cloudflare, 2 July 2019

A replay of a real, public outage, built from what Cloudflare and the press published about it.

## Real, with the page it comes from
- Timeline, the regular expression, the deploy process, the causes and the follow-up work: https://blog.cloudflare.com/details-of-the-cloudflare-outage-on-july-2-2019/
- Same-day statement: https://blog.cloudflare.com/cloudflare-outage/
- Business plan SLA clauses, as archived on 21 July 2019: https://web.archive.org/web/20190721090147/https://www.cloudflare.com/business-sla/
- Which sites went down: The Verge, BBC, The Register and Data Center Dynamics, linked on each customer record.
- John Graham-Cumming and Matthew Prince are named because they are named in those pages.

## Reconstructed, because it was never published
- The code. The real WAF is Lua on PCRE and its source is not public. `code/waf` is a small Python stand-in that carries the real regular expression and loses its CPU protection in a refactor, as the postmortem describes.
- Pull request numbers, rule ids, the date of the refactor ("weeks prior" is all the postmortem says) and the on-call rota.
- Which team owns which system, beyond the teams the postmortem names.
- Everyone except the two people above appears as a role, not a person. Their addresses are placeholders.
- No customer's plan or spend is public, so none is recorded. The Business plan price is the public list price.
