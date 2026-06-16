#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

WIKILINK_RE = re.compile(r"!\[\[([^\]]+)\]\]|\[\[([^\]]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")


@dataclass
class Note:
    path: Path
    rel_path: str
    stem: str
    title: str
    content: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit an Obsidian-style markdown vault for broken links and note hygiene.")
    parser.add_argument("--root", type=Path, required=True, help="Vault or markdown folder root.")
    parser.add_argument("--json-out", type=Path, help="Optional JSON path for the full report.")
    parser.add_argument("--hide-orphans", action="store_true", help="Skip orphan-note reporting.")
    parser.add_argument(
        "--exclude-glob",
        action="append",
        default=[],
        help="Repeatable glob relative to the root for notes or folders to exclude.",
    )
    parser.add_argument("--report-limit", type=int, default=12, help="Max rows to print per issue section.")
    return parser.parse_args()


def normalize_note_key(raw: str) -> str:
    return raw.strip().replace("\\", "/").removesuffix(".md").lower()


def extract_title(path: Path, content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return path.stem.replace("-", " ").replace("_", " ").strip()


def should_exclude(path: Path, root: Path, exclude_globs: list[str]) -> bool:
    relative = path.relative_to(root).as_posix()
    return any(path.match(pattern) or relative == pattern or relative.startswith(pattern.rstrip("/") + "/") for pattern in exclude_globs)


def load_notes(root: Path, exclude_globs: list[str]) -> list[Note]:
    notes: list[Note] = []
    for path in sorted(root.rglob("*.md")):
        if should_exclude(path, root, exclude_globs):
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        notes.append(
            Note(
                path=path,
                rel_path=path.relative_to(root).as_posix(),
                stem=path.stem,
                title=extract_title(path, content),
                content=content,
            )
        )
    if not notes:
        raise ValueError(f"No markdown files found under {root}")
    return notes


def build_lookup(notes: list[Note]) -> dict[str, list[Note]]:
    lookup: dict[str, list[Note]] = defaultdict(list)
    for note in notes:
        lookup[normalize_note_key(note.rel_path)].append(note)
        lookup[normalize_note_key(note.stem)].append(note)
        lookup[normalize_note_key(note.title)].append(note)
    return lookup


def build_suggestion_index(notes: list[Note]) -> dict[str, str]:
    suggestions: dict[str, str] = {}
    for note in notes:
        for candidate in (note.rel_path, note.stem, note.title):
            normalized = normalize_note_key(candidate)
            suggestions.setdefault(normalized, note.rel_path)
    return suggestions


def parse_link_target(raw: str) -> str:
    base = raw.split("|", 1)[0].split("#", 1)[0].strip()
    return normalize_note_key(base)


def resolve_markdown_target(source: Note, root: Path, target: str) -> str | None:
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    candidate = (source.path.parent / target).resolve()
    try:
        rel = candidate.relative_to(root.resolve())
    except ValueError:
        return normalize_note_key(candidate.name)
    return normalize_note_key(rel.as_posix())


def audit(root: Path, hide_orphans: bool, exclude_globs: list[str]) -> dict[str, object]:
    notes = load_notes(root, exclude_globs)
    lookup = build_lookup(notes)
    suggestion_index = build_suggestion_index(notes)
    inbound_counts: dict[str, int] = defaultdict(int)
    broken_links: list[dict[str, str]] = []
    ambiguous_links: list[dict[str, object]] = []

    for note in notes:
        for match in WIKILINK_RE.finditer(note.content):
            raw_target = match.group(1) or match.group(2) or ""
            target_key = parse_link_target(raw_target)
            if not target_key:
                continue
            matches = lookup.get(target_key, [])
            if not matches:
                candidates = difflib.get_close_matches(target_key, suggestion_index.keys(), n=3, cutoff=0.55)
                broken_links.append(
                    {
                        "source": note.rel_path,
                        "target": raw_target,
                        "kind": "wikilink",
                        "suggestions": [suggestion_index[candidate] for candidate in candidates],
                    }
                )
            elif len({item.rel_path for item in matches}) > 1:
                ambiguous_links.append(
                    {
                        "source": note.rel_path,
                        "target": raw_target,
                        "matches": sorted({item.rel_path for item in matches}),
                        "kind": "wikilink",
                    }
                )
            else:
                inbound_counts[matches[0].rel_path] += 1

        for match in MARKDOWN_LINK_RE.finditer(note.content):
            raw_target = match.group(2).strip()
            target_key = resolve_markdown_target(note, root, raw_target)
            if not target_key:
                continue
            matches = lookup.get(target_key, [])
            if not matches:
                candidates = difflib.get_close_matches(target_key, suggestion_index.keys(), n=3, cutoff=0.55)
                broken_links.append(
                    {
                        "source": note.rel_path,
                        "target": raw_target,
                        "kind": "markdown",
                        "suggestions": [suggestion_index[candidate] for candidate in candidates],
                    }
                )
            elif len({item.rel_path for item in matches}) > 1:
                ambiguous_links.append(
                    {
                        "source": note.rel_path,
                        "target": raw_target,
                        "matches": sorted({item.rel_path for item in matches}),
                        "kind": "markdown",
                    }
                )
            else:
                inbound_counts[matches[0].rel_path] += 1

    duplicate_titles = []
    title_buckets: dict[str, list[str]] = defaultdict(list)
    for note in notes:
        title_buckets[normalize_note_key(note.title)].append(note.rel_path)
    for normalized_title, rel_paths in sorted(title_buckets.items()):
        if len(rel_paths) > 1:
            duplicate_titles.append({"title": normalized_title, "paths": rel_paths})

    orphans = []
    if not hide_orphans:
        for note in notes:
            if inbound_counts[note.rel_path] == 0:
                orphans.append(note.rel_path)

    return {
        "root": str(root.resolve()),
        "excluded_globs": exclude_globs,
        "note_count": len(notes),
        "broken_links": broken_links,
        "ambiguous_links": ambiguous_links,
        "duplicate_titles": duplicate_titles,
        "orphans": sorted(orphans),
    }


def print_report(report: dict[str, object], hide_orphans: bool, report_limit: int) -> None:
    broken_links = report["broken_links"]
    ambiguous_links = report["ambiguous_links"]
    duplicate_titles = report["duplicate_titles"]
    orphans = report["orphans"]

    print("Vault Link Auditor")
    print("==================")
    print(f"Root:              {report['root']}")
    print(f"Markdown notes:    {report['note_count']}")
    print(f"Broken links:      {len(broken_links)}")
    print(f"Ambiguous links:   {len(ambiguous_links)}")
    print(f"Duplicate titles:  {len(duplicate_titles)}")
    if not hide_orphans:
        print(f"Orphan notes:      {len(orphans)}")

    if broken_links:
        print("\nBroken links:")
        for row in broken_links[:report_limit]:
            suggestion_text = ""
            suggestions = row.get("suggestions") or []
            if suggestions:
                suggestion_text = f" | try {', '.join(suggestions)}"
            print(f"  {row['source']} -> {row['target']} ({row['kind']}){suggestion_text}")

    if ambiguous_links:
        print("\nAmbiguous links:")
        for row in ambiguous_links[:report_limit]:
            matches = ", ".join(row["matches"])
            print(f"  {row['source']} -> {row['target']} maps to {matches}")

    if duplicate_titles:
        print("\nDuplicate titles:")
        for row in duplicate_titles[:report_limit]:
            print(f"  {row['title']}: {', '.join(row['paths'])}")

    if not hide_orphans and orphans:
        print("\nSample orphans:")
        for rel_path in orphans[:report_limit]:
            print(f"  {rel_path}")


def main() -> None:
    args = parse_args()
    report = audit(args.root, hide_orphans=args.hide_orphans, exclude_globs=args.exclude_glob)
    print_report(report, hide_orphans=args.hide_orphans, report_limit=max(1, args.report_limit))

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nWrote JSON report: {args.json_out}")


if __name__ == "__main__":
    main()
