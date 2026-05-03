#!/usr/bin/env python3
"""One-off backfill: apply XP from rustchain-bounties issue #104 ledger evidence.

Rules:
- Parse markdown ledger table in issue body under Active Entries.
- Parse payout evidence in issue comments (bullet blocks + table rows).
- Skip rows with status=Voided.
- Convert Amount RTC -> tier label:
  <=10 micro, <=50 standard, <=100 major, >100 critical.
- Apply XP using update_xp_tracker_api.py local mode.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class LedgerEntry:
    user: str
    amount: float
    status: str
    pending_id: str
    tx_hash: str
    source: str = "body"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--issue-json", default="/tmp/issue104.json")
    p.add_argument("--comments-json", default="/tmp/issue104_comments.json")
    p.add_argument("--tracker", default="bounties/XP_TRACKER.md")
    p.add_argument("--comments-only", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def parse_amount(value: str) -> float:
    m = re.search(r"\d+(?:\.\d+)?", value)
    return float(m.group(0)) if m else 0.0


def tier_for_amount(amount: float) -> str:
    if amount <= 10:
        return "micro"
    if amount <= 50:
        return "standard"
    if amount <= 100:
        return "major"
    return "critical"


def clean_user(value: str) -> str:
    value = value.strip().strip("`")
    value = value.lstrip("@")
    return value.strip(" \t*_,.;:()[]{}<>")


def parse_ledger_table(body: str, source: str = "body") -> List[LedgerEntry]:
    """Parse issue body active table rows only."""
    lines = body.splitlines()
    out: List[LedgerEntry] = []

    in_table = False
    for line in lines:
        if line.strip().startswith("| Date (UTC) | Bounty Ref | GitHub User"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.strip().startswith("|---"):
            continue
        if not line.strip().startswith("|"):
            if out:
                break
            continue

        cells = [c.strip() for c in line.strip().split("|")[1:-1]]
        if len(cells) < 9:
            continue

        user_cell = cells[2]
        if not user_cell.startswith("@"):
            continue

        out.append(
            LedgerEntry(
                user=clean_user(user_cell),
                amount=parse_amount(cells[4]),
                status=cells[5].strip().lower(),
                pending_id=cells[6].strip().strip("`"),
                tx_hash=cells[7].strip().strip("`"),
                source=source,
            )
        )

    return out


def parse_table_like_rows(text: str, source: str) -> List[LedgerEntry]:
    """Parse inline markdown table rows in comments."""
    out: List[LedgerEntry] = []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().split("|")[1:-1]]
        if len(cells) < 9:
            continue

        status = cells[5].strip().lower()
        if status not in {"pending", "confirmed", "voided"}:
            continue

        user = clean_user(cells[2]) if cells[2].strip().startswith("@") else ""
        amount = parse_amount(cells[4])
        pending_id = cells[6].strip().strip("`")
        tx_hash = cells[7].strip().strip("`")

        if not user or not pending_id or amount <= 0:
            continue

        out.append(
            LedgerEntry(
                user=user,
                amount=amount,
                status=status,
                pending_id=pending_id,
                tx_hash=tx_hash,
                source=source,
            )
        )
    return out


def split_bullet_blocks(text: str) -> List[str]:
    """Collect multiline markdown bullet blocks."""
    blocks: List[str] = []
    cur: List[str] = []

    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("- "):
            if cur:
                blocks.append("\n".join(cur))
            cur = [s[2:].strip()]
            continue
        if cur:
            cur.append(s)

    if cur:
        blocks.append("\n".join(cur))

    return [b for b in blocks if b.strip()]


def parse_pending_ids(block: str) -> List[str]:
    return re.findall(
        r"\bpending(?:_id|\s+id)?\s*(?:#|:)?\s*`?(\d+)`?\b",
        block,
        flags=re.IGNORECASE,
    )


def parse_bullet_entry(block: str, source: str) -> List[LedgerEntry]:
    """Parse a single bullet block if it contains payout evidence."""
    pending_ids = parse_pending_ids(block)
    if not pending_ids:
        return []

    amount_m = re.search(r"(\d+(?:\.\d+)?)\s*RTC", block, flags=re.IGNORECASE)
    amount = float(amount_m.group(1)) if amount_m else 0.0
    if amount <= 0:
        return []

    user = ""
    m = re.search(r"(?:->|to)\s*`?([A-Za-z0-9_.:@-]+)`?", block, flags=re.IGNORECASE)
    if m:
        user = clean_user(m.group(1))
    if not user:
        mention = re.search(r"@([A-Za-z0-9_.-]+)", block)
        if mention:
            user = clean_user(mention.group(1))
    if not user:
        return []

    tx_m = re.search(
        r"\btx(?:_hash| hash)?\b\s*[: ]\s*`?([a-fA-F0-9]{16,64})`?",
        block,
        flags=re.IGNORECASE,
    )
    tx_hash = tx_m.group(1) if tx_m else ""

    status = "voided" if "voided" in block.lower() else "pending"
    if "confirmed" in block.lower() and status != "voided":
        status = "confirmed"

    out: List[LedgerEntry] = []
    for pending_id in pending_ids:
        out.append(
            LedgerEntry(
                user=user,
                amount=amount,
                status=status,
                pending_id=pending_id,
                tx_hash=tx_hash,
                source=source,
            )
        )
    return out


def parse_comment_entries(comment_text: str, source: str) -> List[LedgerEntry]:
    """Parse entries from comment text using both table and bullet approaches."""
    entries: List[LedgerEntry] = []

    # Try table-like rows first
    entries.extend(parse_table_like_rows(comment_text, source))

    # Try bullet blocks
    blocks = split_bullet_blocks(comment_text)
    for block in blocks:
        entries.extend(parse_bullet_entry(block, source))

    return entries


def load_entries(args: argparse.Namespace) -> List[LedgerEntry]:
    """Load all ledger entries from issue and comments."""
    entries: List[LedgerEntry] = []

    # Load from issue body if not comments-only
    if not args.comments_only:
        try:
            with open(args.issue_json) as f:
                issue_data = json.load(f)
            body = issue_data.get("body", "")
            entries.extend(parse_ledger_table(body, "body"))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load issue JSON: {e}")

    # Load from comments
    try:
        with open(args.comments_json) as f:
            comments_data = json.load(f)
        for i, comment in enumerate(comments_data):
            comment_text = comment.get("body", "")
            source = f"comment-{i + 1}"
            entries.extend(parse_comment_entries(comment_text, source))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Warning: Could not load comments JSON: {e}")

    return entries


def apply_xp_updates(
    entries: List[LedgerEntry], tracker_path: str, dry_run: bool
) -> None:
    """Apply XP updates using the tracker API."""
    script_path = Path(__file__).parent / "update_xp_tracker_api.py"

    for entry in entries:
        if entry.status == "voided":
            print(f"Skipping voided entry: {entry.user} {entry.amount} RTC")
            continue

        tier = tier_for_amount(entry.amount)
        cmd = [
            "python3",
            str(script_path),
            "--local",
            tracker_path,
            "--user",
            entry.user,
            "--tier",
            tier,
            "--source",
            f"issue-104-{entry.source}-{entry.pending_id}",
        ]

        if dry_run:
            print(f"DRY RUN: {' '.join(cmd)}")
        else:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                print(f"Applied XP: {entry.user} +{tier} ({entry.amount} RTC)")
            except subprocess.CalledProcessError as e:
                print(f"Error applying XP for {entry.user}: {e}")
                print(f"Stdout: {e.stdout}")
                print(f"Stderr: {e.stderr}")


def main() -> None:
    args = parse_args()
    entries = load_entries(args)

    print(f"Loaded {len(entries)} entries")

    # Show summary
    by_status = {}
    for entry in entries:
        by_status.setdefault(entry.status, []).append(entry)

    for status, status_entries in by_status.items():
        print(f"  {status}: {len(status_entries)} entries")

    # Apply updates
    apply_xp_updates(entries, args.tracker, args.dry_run)


if __name__ == "__main__":
    main()
