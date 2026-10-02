# Team log of the requirements check

Every run starts with `scripts/preflight.py`. It checks what the skill needs
(Python, openpyxl, scripts, page templates, config, run folder; and, as
reported by Claude, the model and the HubSpot / ZoomInfo / web search / Clay
connectors). It saves the result in three places:

1. `<run_dir>/preflight.json`: with that run's files.
2. `~/.didero-outbound-lists/preflight.jsonl`: on the device that ran it.
3. **The team log**: one row per run in a Supabase table, from every device.
   You open it in the Supabase dashboard. This part needs the one-time setup below.

## One-time setup

1. **Project.** Use the Supabase project "sl@didero.ai's Project"
   (`ddumfpvfxngbpjlchorv`). It is currently **paused (inactive)**, so
   restore it first. Supabase dashboard → the project → "Restore", or ask
   Claude to restore it. A new project works just as well.
2. **Table.** Run `setup/preflight_log.sql` in the project's SQL editor (or
   ask Claude to run it). It creates `preflight_runs`, where the skill can
   only **add** rows. It can't read, change or delete them. It also creates
   the `preflight_summary` view: one line per run, newest first.
3. **Key.** In Supabase → Project Settings → API, copy the **Project URL**
   and the **publishable (anon) key**. Never use the `service_role` / secret
   key. Create `skill/didero-outbound-lists/backend.json`:

   ```json
   {"url": "https://ddumfpvfxngbpjlchorv.supabase.co", "key": "<publishable key>"}
   ```

   The file is git-ignored, so it never goes to the public repo. The zip
   build includes it, so every copy of the skill reports to the same log.
   The key can only add rows, so the worst anyone holding the zip could do is
   add junk rows.
4. **Cowork network access.** Cowork only lets the skill reach allowed
   domains. Add `*.supabase.co` (or `ddumfpvfxngbpjlchorv.supabase.co`) to
   the allowed domains in Claude's settings (Settings → Capabilities, under
   network / domain allowlist). An org admin may need to do this for
   everyone. Without it, the "log:" line says **NOT sent** and the run goes
   on. The local copies still have the result.
5. **Rebuild and re-upload the zip**, then test: start a run in Cowork. The
   requirements check should print `log: sent to the team log (HTTP 201)`,
   and a row appears in `preflight_summary`.

## Reading the log

Supabase → Table Editor → `preflight_summary` (or `preflight_runs` for every
check's detail). `user_label` is the name or email Claude passed, or the
device's user name. `device` is a short code of the computer's name: the same
computer always gets the same code, and the name itself isn't stored.
`passed = false` rows name what was missing.
