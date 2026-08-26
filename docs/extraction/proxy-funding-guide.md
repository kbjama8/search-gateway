# Proxy Funding Guide

How to fund, provision, and operate the optional residential/ISP proxy tier
for kortex-search (Phase 3.5 of Project Gatekeeper). The subsystem ships
**disabled** (`KORTEX_SEARCH_PROXY_ENABLED=0`); this guide is what you read
before flipping it on.

All prices are 2026 market figures (verified 2026-08-22 — LESSONS.md §2).

## Do you even need proxies?

The gateway's doctrine is zero-cost-by-default: direct IP + pacing + persona
hygiene covers most research loads. Proxies earn their money in exactly
three situations:

1. **Chinese-ecosystem sources** (zhihu/weibo/bilibili/XHS) — CN risk
   control correlates aggressively on IP reputation; a single datacenter IP
   is throttled fast.
2. **Hosted-netblock IPs** — Reddit's Data API *requires* OAuth from
   cloud/hosted netblocks; residential egress sidesteps the class-wide ban.
3. **Account-level monitoring** (Instagram/Facebook-class) — one sticky
   residential IP per persona mirrors the real-user model and stabilizes
   cookie sessions.

If none of these apply to your load, keep the tier off.

## Market landscape (2026)

| Tier | Providers | Price/GB | Fit for us |
|------|-----------|----------|-----------|
| Enterprise | Bright Data (72M+ IPs), Oxylabs (100M+, sub-0.6s) | $8.50–12 | no — we're not at 1TB scale |
| Mid-market | **SOAX** (city/ASN targeting, aggressively cleaned pool), Decodo (ex-Smartproxy), NetNut | $3.50–6 | **yes — SOAX primary** |
| Budget | **IPRoyal** ($1.75 PAYG), Webshare (dev API), ProxyHat | $1.75–3.50 | **yes — pilot** |
| Mobile | CGNAT tiers (IG/TikTok-class) | $10–30 | no (unless account-level IG work begins) |
| Datacenter | any | cheap | **never** — instantly blocked on CF/Akamai targets |

The market split is the story: enterprise pricing buys pools and compliance
we don't need; mid-market buys geo-precision and pool cleanliness (what
actually defeats risk control at our volume); budget buys entry.

## Cost model for our actual load

- Daily budget: `KORTEX_SEARCH_DAILY_QUERY_LIMIT=300` source-queries/day.
- Browser-tier pages ≈ 1–3 MB; API-tier (CN signed) ≈ 10–50 KB.
- Worst case (every query through proxies): ≈ 18 GB/mo → $32–90/mo.
- **Realistic: $10–30/mo** — only browser-tier + CN sources route through
  the tier; the API tier stays direct.

| Provider | Pilot (pay-as-you-go) | Farm (sticky, geo-targeted) |
|----------|----------------------|-----------------------------|
| IPRoyal | $1.75–3.50/GB, no commitment | — |
| SOAX | $3.50–5/GB | $3.50–5/GB, city/ASN targeting, clean pool |
| Decodo | $8.50/GB | $5/GB at 40 GB/mo |

**Recommendation (D6):** IPRoyal PAYG for the pilot (prove the tier works,
measure block-rate delta) → SOAX once the farm is live (geo-precision +
pool cleanliness matter more than raw IP count at our volume). Budget
envelope: $30/mo worst-case pilot, $60/mo farm.

## Procurement checklist

1. Create the provider account with the **burner email/persona**, not the
   personal one (the persona model extends to vendors).
2. Generate API credentials → store in `~/.agent-reach/proxy.env` (0600):
   ```
   KORTEX_SEARCH_PROXY_GATEWAY=gate.provider.com:8080
   KORTEX_SEARCH_PROXY_USERNAME=<targeting-grammar username>
   KORTEX_SEARCH_PROXY_PASSWORD=<password>
   ```
   Never commit; `.gitignore` already blocks `*.env`.
3. Confirm the provider supports the **username-targeting grammar** (sticky
   `sid` + `ttl` tokens — LESSONS.md §2.2). ProxyHat documents the canonical
   form: `-country-us-sid-<id>-ttl-30m`. If the provider's grammar differs,
   set `KORTEX_SEARCH_PROXY_USERNAME` verbatim and skip the auto-grammar.
4. Set `KORTEX_SEARCH_PROXY_COUNTRY` to the persona's home region, and keep
   `KORTEX_SEARCH_PROXY_GEO_ALIGN=1` — the fingerprint bundle derives
   timezone/locale/languages from the egress country (the coherence
   doctrine, LESSONS.md §1.2).
5. Smoke-test with `kortex-search doctor` (proxy health section) and one
   live CN query.

## Setup walkthrough (SOAX-style, representative)

```
# 1. create proxy env file
touch ~/.agent-reach/proxy.env && chmod 600 ~/.agent-reach/proxy.env

# 2. enable the tier
export KORTEX_SEARCH_PROXY_ENABLED=1
export KORTEX_SEARCH_PROXY_PROTOCOL=http

# 3. point the gateway at the env file (values load from it)
export KORTEX_SEARCH_PROXY_AUTH_FILE=~/.agent-reach/proxy.env

# 4. verify
kortex-search doctor | jq .proxy          # health + geo alignment status
kortex-search serve                       # stdio as usual; browser tier
                                           # picks up sticky proxies per profile
```

The proxy engine (`extract/proxies.py`) assigns **one pinned residential IP
per profile** for the sticky TTL — never per-request rotation on the browser
tier. Rotation happens on the health ladder (block → rotate profile → rotate
IP → quarantine), never opportunistically.

## Operations notes

- **Per-IP health** is tracked in Redis (`sg:px:*`): a sticky IP with falling
  reliability gets rotated before it burns the persona.
- **Geo drift**: if the provider's egress country differs from
  `KORTEX_SEARCH_PROXY_COUNTRY`, the coherence lint (`doctor`) will flag it.
- **Overage**: committed plans bill overage at higher rates; prefer PAYG
  while the load is sub-10 GB/mo.
- **Never** mix the personal account's egress with the burner personas —
  that is the one mistake that unmasks the whole operation.

## Gotchas

- Smartproxy rebranded to **Decodo** in 2026 — searches for the old name
  surface stale pricing.
- Some providers charge geographic surcharges (US/UK/CAN premium) — factor
  into the cost model if the persona's home region is premium.
- Free proxies are a honeypot for credential theft and are instantly
  reputation-burned — never.
- Residential IP pools have variable latency (2–10 Mbps typical) — the
  adaptive-timeout machinery (`KORTEX_SEARCH_ADAPTIVE_TIMEOUT_*`) already
  absorbs this; raise `ADAPTIVE_TIMEOUT_MAX` if the proxy tier feels slow.
