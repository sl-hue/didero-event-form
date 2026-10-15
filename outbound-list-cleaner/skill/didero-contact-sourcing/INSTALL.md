# Installing didero-contact-sourcing

This folder is the whole skill — nothing else is needed. Unzip
`didero-contact-sourcing-skill.zip` into your skills folder; you should end up with
`.../skills/didero-contact-sourcing/SKILL.md` (not `.../skills/didero-contact-sourcing/didero-contact-sourcing/SKILL.md`).

## Claude Code (terminal, desktop app, IDE)

Mac / Linux:

    mkdir -p ~/.claude/skills && unzip -o ~/Downloads/didero-contact-sourcing-skill.zip -d ~/.claude/skills

Windows (PowerShell):

    Expand-Archive -Force $HOME\Downloads\didero-contact-sourcing-skill.zip $HOME\.claude\skills

Then start a **new** Claude Code session and type `/didero-contact-sourcing` (it's in the `/`
menu), or just say "Find the contacts at these companies" with the file attached.

Or let Claude do it: in Claude Code, say "install the skill in
~/Downloads/didero-contact-sourcing-skill.zip into ~/.claude/skills".

## Claude app / Cowork

In the skills settings, choose **Upload a skill** and pick the zip (don't
unzip it). Delete any older copy with the same name first, then start a new
chat and type `/didero-contact-sourcing` or name the skill in your message.

## Updating

Same steps with the new zip (`-o` / `-Force` overwrites the old copy). Check
the version with: "which version of didero-contact-sourcing do you have?" — it's in `VERSION`.

## Needs

- The **HubSpot** and **ZoomInfo** connectors. Connect them in the Claude app
  (Settings → Connectors); Claude Code signed in with the same account picks
  them up — check with `/mcp`. The skill checks them first and tells you if one
  is missing.
- Python 3 (comes with macOS and Claude's environments). No packages to install.
