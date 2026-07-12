---
doc_type: Solution design
title: Central Print Module
subtitle: Solution design for the Acme Labs labeling estate
prepared_for: Acme Labs AG
date: July 2026
doc_number: 261910
cover: true
watermark: true
---

# 1. Context

This document sets out the proposed architecture for a central print module that
consolidates label output across the three Acme Labs sites. Today each site runs
its own print stack, which multiplies the operational surface and makes version
drift the norm rather than the exception. The goal is a single, observable
service that every site calls the same way, so that a label produced in Basel is
byte for byte the label produced in Vienna.

The current estate has grown organically over several acquisitions. Each addition
brought its own designer version, its own printer firmware baseline, and its own
idea of where the truth about a label template lives. The result is a system that
works, most days, but resists change and hides its failure modes until a
production line stops. A central module does not remove that complexity; it moves
it into one place where it can be measured, tested, and reasoned about.

## What we are solving

The three problems below recur in every incident review and every audit finding,
and they are the reason a central module is worth building now rather than later.

- Version drift : each site pins a different designer and firmware baseline, so a template that passes validation on one site can fail silently on another.
- Opaque failures : when a print job fails there is no shared log, so the first signal is usually a stalled line and a phone call rather than an alert.
- Duplicated effort : every template change is applied by hand three times, which triples the work and triples the chance of a transcription error.

## Why now

The modernisation programme has already delivered a shared network path and a
common identity provider across the three sites. Those were the hard
prerequisites. With them in place the incremental cost of centralising print is
low, and the window before the next acquisition closes is the cheapest it will
ever be.

# 2. Proposed architecture

The central print module sits between the application layer and the physical
printers. It exposes one HTTP contract, renders every label from a single
template store, and streams a structured event for every job so that operations
can see the whole estate on one board.

## Components

Each component below is independently deployable and independently observable.
The labels in the left column are referenced throughout the rest of this
document.

1. C1: Template store : a versioned, git-backed repository that holds every label template and is the single source of truth for label geometry.
2. C2: Render service : takes a template plus a data payload and produces a print-ready stream; stateless, horizontally scalable, and the only component that speaks the printer dialect.
3. C3: Event bus : carries one structured event per job so that success, failure, and latency are visible without touching the printers themselves.
4. C4: Site agent : a thin process at each site that proxies the local printers to the render service and buffers jobs across a network blip.

## Server inventory

The initial deployment targets the existing modernised hosts. No new hardware is
required for the pilot; the render service runs alongside the existing runtime
nodes.

| Environment | Host | Role |
|---|---|---|
| Dev | PRT-DEV-01 | Designer |
| Test | PRT-TST-07 | Runtime |
| Prod Basel | PRT-PRD-09 | Runtime |
| Prod Vienna | PRT-PRD-11 | Runtime |
| Prod Milan | PRT-PRD-13 | Runtime |

# 3. Effort and commercial estimate

The estimate below covers the pilot through to a production cutover on the first
site. The two remaining sites reuse the same artifacts and are quoted separately
once the pilot has proven the contract in production.

| Workstream | Days | Amount |
|---|---:|---:|
| Discovery and contract design | 8.0 | CHF 12'800.- |
| Template store and migration tooling | 12.0 | CHF 19'200.- |
| Render service and printer dialect | 15.0 | CHF 24'000.- |
| Event bus and operations board | 7.0 | CHF 11'200.- |
| Pilot cutover and hypercare | 6.0 | CHF 9'600.- |
| =BASE ENGAGEMENT TOTAL | 48.0 | CHF 76'800.- |

> Billing is for time actually worked. The amounts above are a planning estimate;
> any scope added during delivery joins through a purchase-order amendment rather
> than silently expanding the fixed figure.

## Illustrative line items

The following worked example shows how a downstream purchase order derived from
this design would itemise, including Swiss VAT. It is illustrative only and not
part of the fixed estimate above.

:::items
{
  "currency": "CHF",
  "tax_rate": 0.081,
  "tax_label": "VAT 8.1%",
  "items": [
    {"description": "Central print module license, annual", "qty": 1, "unit_price": 18000},
    {"description": "Render service compute, per node per month", "qty": 12, "unit_price": 320},
    {"description": "Onboarding and template migration, per site", "qty": 3, "unit_price": 4200},
    {"description": "Standard support, per month", "qty": 12, "unit_price": 650}
  ]
}
:::

# 4. Risks and assumptions

The design assumes the modernisation prerequisites hold and that the printer
fleet stays on its current supported firmware for the duration of the pilot. The
risks below are the ones that would change the estimate materially rather than at
the margin.

- Firmware divergence : if a site upgrades printer firmware mid-pilot the render dialect may need a branch, which adds test surface.
- Template debt : templates that encode site-specific hacks must be normalised before migration, and the volume of such hacks is not yet fully known.
- Network posture : the site agent buffers across short outages, but a sustained partition still stalls print, so the network SLA remains load-bearing.

:::note
This solution design is a planning artifact. Figures, host names, and firmware
baselines are indicative and must be confirmed against the live estate before any
commitment is made.
:::

:::appendix
# Appendix A. Glossary and fine print

The render dialect is the printer-specific command language emitted by the render
service; on the current fleet this is ZPL, but the contract deliberately hides
the dialect from callers so that a future fleet change does not ripple upstream.

The template store is git-backed so that every change to label geometry carries
an author, a timestamp, and a reviewable diff. This is the mechanism by which
version drift is eliminated: there is exactly one main branch, and a template is
in production if and only if it is on that branch. Nothing is applied by hand at
a site, and nothing reaches a printer that did not pass through a reviewed merge.

All amounts are in Swiss francs and exclusive of value added tax unless a line
explicitly states otherwise. This document does not constitute an offer; a
binding quotation is issued separately through the numaco-report quotation flow
once the design is approved.
:::
