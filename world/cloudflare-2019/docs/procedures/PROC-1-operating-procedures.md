# PROC-1: Operating procedures in force on 2 July 2019

Source: https://blog.cloudflare.com/details-of-the-cloudflare-outage-on-july-2-2019/

Lines starting with ">" are quoted from that page. The ids are ours.

## Testing a rule change
> The standard procedure for a WAF Managed Rules change indicates that Continuous Integration (CI) tests must pass prior to a global deploy.
> What it didn't do was test for runaway CPU utilization by the WAF and examining the log files from previous WAF builds shows that no increase in test suite run time was observed

## Rolling a rule change back
> The rollback plan required running the complete WAF build twice taking too long.

## Staff access
> some members of the team had lost access because of a security feature that disables their credentials if they don't use the internal control panel frequently
> with our Access service down we couldn't authenticate to our internal control panel

## Telling customers
> We didn't update our status page quickly enough.
> Our customers were unable to access the Cloudflare Dashboard or API because they pass through the Cloudflare edge.
