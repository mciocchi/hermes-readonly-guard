---
schema: milestone/1
architecture: 1
mvp: true
satisfies: [I1, I2, I3, I4, I5, I6, I9]
---

# 01: The guard as shipped

**Goal.** A user can put one session into read-only, plan or writable and watch the guard hold that session to it, with `writable` ending on its own lease.

**Exit.** `python -m unittest discover -s tests -t tests` — 199 tests, `OK`.

**Out of scope.** Keybinds, catalog listing, Windows CI (all delivered before this document existed; the suite is what ratifies them).

## Features

F1: a user can stop an agent from writing anything in the current chat
F2: a user can let an agent plan, with only the plan markdown writable
F3: a user can grant full access for a bounded time, and it expires on its own
F4: a user can keep two chats in different modes at once
F5: a user can find out which mode is enforced, from the chip, `/readonly status`, or the API

## Tickets
