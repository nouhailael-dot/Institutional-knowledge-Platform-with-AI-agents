# GHUS Compass on Render: 10-day private team trial

**Date:** 9 Nov 2026. **Scope:** host the existing platform at a stable HTTPS
URL, behind a login, against the team's Supabase database. Nothing about the
agents, Review or the database changes. Local development continues; validated
updates are released to the host by hand.

---

## 1. What blocked a hosted deployment, and what fixes it

| Blocker | Why it blocked | Fix (this change) |
|---|---|---|
| **Linux startup** | `scripts/run_shared_server.py` reads `.env`, hard-codes a Windows store path and listens on `127.0.0.1` only. | `scripts/run_hosted_server.py`: settings from the host's environment, state on the disk, listens on `0.0.0.0:$PORT`. The local launcher is unchanged. |
| **Dependencies** | Two requirement files disagree (`anthropic>=1.5` vs `==1.0.0`), and the default Linux `torch` wheel pulls several GB of CUDA libraries. | `requirements-deploy.txt` pins the exact versions the local server runs today; the `Dockerfile` installs CPU-only `torch` first and bakes in the entity-resolution model (no download at decision time). |
| **Secrets** | Kept only in the local `.env`. | Entered once in Render's environment settings. `.env` is never in the image (`.dockerignore`). |
| **Access protection** | The app has no login: anyone with the URL could read and decide. | `backend/access.py`: every page and API call asks for a login (`GHUS_ACCESS_USERS`). The launcher refuses to start without accounts. Only `/api/health` is open. Locally nothing changes. |
| **Persistent Review decisions** | Review decisions live in a SQLite file. It is the **only** record of a rejected candidate; a redeploy wipes the container's files (docs/REVIEW_STORE_PERSISTENCE.md). | A Render persistent disk at `/var/data` holds the Review store, Data Feed uploads, Build the Map jobs and the agents' caches. The launcher refuses to start if the disk is missing. |
| **Background agent execution** | "Run now", Review admission and Data Feed staging start `ghus-backend` commands with the app's own Python. | One image holds both; the commands run as child processes of the web service. Recurring requests stay plan-only by policy (live runs only on "Run now"), so no scheduler is needed. |
| **Database compatibility** | Supabase's direct connection is IPv6-only, and Render has no outbound IPv6. | Use the **Session pooler** URI (IPv4, port 5432), which the local server already uses. No code reads tables from a migration Supabase lacks (630 is not applied; nothing reads `event_details` or `person_details`). |

## 2. Cost

| Item | Monthly | For 10 days |
|---|---|---|
| Web service, Standard (2 GB RAM, 1 CPU) | $25 | about $8.30 (billed by the second) |
| Persistent disk, 2 GB | $0.50 | about $0.20 |

Starter (512 MB) is not enough: a Review admission loads the entity-resolution
model (PyTorch) next to the web app. A disk needs a paid instance; the free
plan also sleeps after 15 minutes.

## 3. One-time setup

You do these steps yourself: they create an account, enter secrets and publish
a URL.

1. **Push the code.** Render deploys from GitHub, so the commits must be on
   `main` in `nouhailael-dot/Institutional-knowledge-Platform-with-AI-agents`.
   Render needs access to that repository: its owner (or an admin) installs
   the Render GitHub app on it, or grants you admin.
2. **Create the service.**
   - Sign in at https://dashboard.render.com with GitHub.
   - Choose **New → Blueprint** and pick the repository. Render reads
     `render.yaml`: a web service `ghus-compass` (Docker, Standard, Virginia)
     with a 2 GB disk at `/var/data`.
3. **Enter the five secrets** when the Blueprint asks for them:

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | Supabase → Project Settings → Database → Connection string → **Session pooler** (host `aws-1-us-east-1.pooler.supabase.com`, port **5432**). Same as `DATABASE_URL` in your local `.env`. |
   | `ANTHROPIC_API_KEY` | Same as in your local `.env`. |
   | `VOYAGE_API_KEY` | Same as in your local `.env`. |
   | `GHUS_AGENT_CONTACT_EMAIL` | The address websites see the agents identify with (a team mailbox if you have one). |
   | `GHUS_ACCESS_USERS` | One login per tester: `amina:long-random-pass,ismail:another-pass`. Commas between people, the first colon between the name and the password. |

4. **Check Auto-Deploy is Off:** the service → Settings → Build & Deploy →
   Auto-Deploy = **Off**. Then a push never changes the hosted app by itself.
5. **First deploy.** The first build takes about 8–12 minutes (PyTorch and the
   model). The log ends with `listening on : 0.0.0.0:10000` and
   `Application startup complete`.
6. **Move the Review store to the disk.** This step must come before anyone
   reviews on the hosted app; see section 4.
7. **Open the URL** (`https://ghus-compass.onrender.com`, or the name Render
   gives it), sign in, and run the checks in section 6.

## 4. Moving Review decisions to the host (once)

The local shared server keeps Review decisions in
`C:\Users\Ismail\GHUS-data\review-store\review-shared.sqlite3`. The host needs
that file, or every candidate you rejected locally comes back as new work.

1. **Stop the local shared server** (port 8030), so no decision is written
   during the copy.
2. **Take a safe copy** (not a file copy of a live database):

   ```bash
   .venv/Scripts/python.exe -c "import sqlite3; s=sqlite3.connect(r'C:\Users\Ismail\GHUS-data\review-store\review-shared.sqlite3'); d=sqlite3.connect(r'C:\Users\Ismail\GHUS-data\review-shared-upload.sqlite3'); s.backup(d); d.close(); s.close()"
   ```

   ```bash
   .venv/Scripts/python.exe -m scripts.verify_review_store_backup "C:\Users\Ismail\GHUS-data\review-shared-upload.sqlite3"
   ```

3. **Upload it to the disk.**
   - Add your SSH public key in Render: Account Settings → SSH Public Keys.
   - Copy the service's SSH address from its **Connect → SSH** tab.
   - Then upload with `scp`:

   ```bash
   scp "C:\Users\Ismail\GHUS-data\review-shared-upload.sqlite3" <service-ssh-address>:/var/data/review-store/review-shared.sqlite3
   ```

   Also upload the Data Feed originals folder (`C:\Users\Ismail\GHUS-data\datafeed-originals`)
   with `scp -r` to `/var/data/datafeed-originals` if Import History should
   show past uploads.
4. **Restart the service** (Manual Deploy → Restart service), so it opens the
   uploaded store.

**From then on the hosted store is the one true Review record.** Two stores
over the same database disagree silently: a decision made in one is unknown to
the other. During the trial, make Review decisions only on the hosted app.
Develop locally against the isolated test database (`ghus_v2_*_test` on
127.0.0.1:55432), or open the local shared server only to look.

## 5. Releasing a validated update during the trial

1. Develop and test locally as now (tests for both parts of the repository).
2. Commit, then push to `main`. Nothing deploys yet.
3. In Render: **Manual Deploy → Deploy latest commit.** The disk, and so every
   Review decision, is kept; the app is unavailable for about a minute while
   it restarts.
4. **Rolling back:** the service → Events → choose the previous deploy →
   **Rollback**.

A deploy stops an agent run in progress (it is a child of the old process).
Release when Monitor shows no run going.

## 6. Checks after each deploy

- `https://<url>/api/health` answers `{"ok": true}` without a login.
- `https://<url>/` asks for a login; a wrong password is refused.
- The Render log shows no `Review persistence:` warning (the store is on the disk).
- Review lists the same pending items as before, and an item rejected before
  the move is not back in the queue.
- Explore, Ask and Monitor open; Monitor lists the requests.
- Once, after the first deploy, approve one candidate you would approve anyway.
  This proves the admission path, including the entity-resolution model.

## 7. Limits of this trial set-up

- **Actions are not attributed to a person.** The login only says who may enter.
  Decisions are still recorded as "Not recorded (no sign-in yet)" (src/identity.py).
- **One instance.** Review's store is a SQLite file on one disk, so the service
  cannot scale out. That is fine for a team of testers.
- **A deploy or crash stops a running agent run.** Start it again with "Run now".
- **Disk backups:** Render snapshots disks daily. For an extra copy, run the
  backup command from section 4 in the service shell
  (`sqlite3`'s Python API, to `/var/data/backups/`).
- **Migration 630** (`event_details`, `person_details`) is not on Supabase.
  Nothing in the app reads those tables yet.
