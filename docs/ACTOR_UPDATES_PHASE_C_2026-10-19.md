# Actor Updates — Phase C (related organisations and hub fit) report, 2026-10-19

Phase C covers spec section 9 (related actors) and section 10 (hub reassessment). Both reuse the existing writers and Review:

- nothing is written around Review;
- no membership is ever removed automatically;
- no hub is ever created.

It was built and tested on the isolated clone `ghus_v2_actor_updates_test`. No migration was needed.

## 1. Related organisations (spec section 9)

When a check finds a value in a box that can name another organisation, one small extra model call lists the organisations named. Those boxes are: partnerships, funding, members, pilots/customers, parent, operator, sponsor.

- **Grounding.** A name is kept only if it appears word for word in a value the update already verified against the page. The model can point at names but never add them; an invented name is dropped.
- **Direction.** Every relation states what the other organisation is to this actor: partner, funder, a grantee it funds, parent, a unit of it, a body it belongs to, its member, operator or investor. Each maps to exactly one edge type and direction.
- **Mapped-first routing,** with the Architecture V2 exact rule (domain, name or alternate name; aggregates excluded):
  - **On the map:** writing raises a link proposal in Review, with the page as its source. The edge is written only if a person confirms it. It is never proposed twice, and never proposed when the link already exists.
  - **Several matches:** listed for a person; nothing is written.
  - **Not on the map:** offered as "Find it with Discovery". That pipeline runs entity resolution and sends every new organisation to Review. Nothing is staged around it.
- **Cost.** The extra call is made only when such a box has a value. In live use it cost about $0.004, and it counts against the same per-actor cap.

## 2. Hub fit (spec section 10)

A read-only check uses the hub contract itself (`hub_assignment`: sector first, then the hub's radius) against the actor's current record:

- **Memberships** show whether they still fit. One that does not ("outside its radius", "sector no longer matches") is reported for a person to look at and **never removed**. GHUS and imported memberships are marked preserved.
- **Unassigned actors stay eligible.** When a hub of the actor's sector now contains it, the nearest such hub is proposed to Review on write. The membership is added only if a person accepts.
- **No hub is created.** New hubs still come only from Phase 7 hub detection.
- **Older databases.** Before migration 520, hubs take their sector from their own topic, which mirrors the sector of the same code.
- **Updates do not change hub fit.** An update writes facts only; it does not change the actor's coordinates or sectors. This check therefore mainly catches actors that a newer hub now fits, and memberships that no longer fit.

## 3. Review

- **Link proposals** read: "CPower is a unit of NRG Energy?", with the source page. The answers are "Confirm the link" or "Not a link".
- **Hub proposals** read: "Add X to Northeast Energy Hub?", with the sector and the distance against the radius. The answers are "Add to the hub" or "Keep it out".
- **Fact conflicts** keep "Use the new value" / "Keep the current value".
- **No rejection reason** is needed for any of these. The safe default is to leave the item in the queue.
- **Older relationship items now have a decision path** (the 42 imported link items in the demo copy, which Review could not decide before):
  - ones with a recorded source page can be confirmed;
  - ones without a source can only be refused or left, because confirming needs a source.
- **Older hub review items** (not membership proposals) and location items still have no decision in Review. That is unchanged and outside this phase.

## 4. Where it is in the UI

Discovery → Actor updates:

- **Request preview:** a "Hubs" line, for example "In Bay Hub (fits) · Newly fits Delta Hub (12 mi) — proposed to Review when written". It is free.
- **Check result:**
  - "Organisations its pages name", each with its status and source, and "Find it with Discovery" for ones not on the map.
  - A "Hubs" line.
- **After writing:** the proposals raised ("Proposed to Review: link with …", "add to …").

## 5. Proven

- **Live, real model:** from Clean Energy Group's own funding statement, it named the "Massachusetts Department of Energy Resources" as a funder (Clean Energy Group funded by it). That organisation is not on the map, so it is offered to Discovery. Cost: $0.004.
- **Live checks:**
  - MIT's site refused the agent (403) and Clean Energy Group's first check hit a model timeout. Both were reported, and nothing was written.
  - The Midwest Alliance for Clean Hydrogen showed two GHUS memberships that still fit, marked preserved.
- **Database tests on the clone,** each run twice in a row to prove reruns are clean:
  - an invented name is dropped;
  - an on-map organisation is proposed and not written;
  - it is not proposed twice;
  - a person confirms it, and only then the edge exists;
  - a membership that no longer fits is reported and not removed;
  - an unassigned actor gets a proposal when a nearer hub is added;
  - acceptance adds a sourced `reviewed_assignment` membership;
  - refusal writes nothing;
  - a legacy hub item cannot be decided as a proposal.

- **End to end through the Review route on the clone** (the admission bridge and the backend writer):
  - "CPower Energy works with Clean Energy Group?" → Confirm the link → an edge sourced to the CPower page.
  - A hub proposal → Keep it out → the item is closed, and no membership is written.

**Test results**

- **Backend:** 869 passed, 24 skipped, 4 failed. The 4 are the documented baseline (the uncommitted smoke-test stub ×2 and two schema checks needing deferred migration 500). The canonical-writer guard passes.
- **Clone:** 33 passed.
- **Platform:** pytest 310 passed. Node UI tests: 26 + 6 + 9 + 57, all passed.

## 6. Not done

- **Adaptive scheduling, notifications, personal ownership and analytics** (P3). Deferred, as the spec says.
- **No Deep Pull reader** (unchanged).
- **Older hub and location review items still need decision paths** in Review.
- **Observation from the live check.** A Light read can replace a stronger recorded fact with a newer but weaker one in the same box. In Clean Energy Group's funding box, "helped communities access $3.6 million" replaced a direct grant to Clean Energy Group. That is the Phase 11 rule (newer and at least as confident supersedes). A finer rule would need GHUS to decide what "stronger evidence" means.
