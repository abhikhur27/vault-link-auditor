# Vault Link Auditor

Practical Python CLI for auditing an Obsidian-style markdown vault before broken links, duplicate note names, and orphan pages quietly erode the graph.

## Why this exists

Large note vaults drift over time:

- renamed notes leave stale wikilinks behind
- duplicate titles create ambiguous references
- orphan notes pile up and become hard to rediscover

This tool turns that sprawl into a clean report you can fix in one pass.

## What it checks

- broken `[[wikilinks]]`
- broken relative markdown links like `[doc](folder/file.md)`
- ambiguous links that could resolve to multiple notes
- duplicate note titles
- orphan notes with zero inbound links
- optional JSON export for dashboards or scripted cleanup

## Usage

```bash
python auditor.py --root example_vault
```

Write the full report to JSON:

```bash
python auditor.py --root example_vault --json-out reports/audit.json
```

Skip orphan-note reporting when you only care about link breakage:

```bash
python auditor.py --root example_vault --hide-orphans
```

## Example output

```text
Vault Link Auditor
==================
Root:              ...\example_vault
Markdown notes:    5
Broken links:      2
Ambiguous links:   1
Duplicate titles:  1
Orphan notes:      1
```

## Repository layout

- `auditor.py`: CLI entrypoint and audit logic
- `example_vault/`: small reproducible markdown sample
- `reports/`: optional exported JSON output

## Portfolio positioning

- Project type: Python CLI utility
- Target workflow: markdown / Obsidian vault maintenance
- Verification path: run the CLI on `example_vault` or your real vault root
