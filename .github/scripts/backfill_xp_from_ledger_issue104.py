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
from typing import Dict, List


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
        if line.strip().startswith("|") and "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 7:
                user = clean_user(parts[3])
                amount = parse_amount(parts[4])
                status = parts[5].strip()
                pending_id = parts[6].strip()
                tx_hash = parts[7].strip() if len(parts) > 7 else ""

                if user and amount > 0 and status.lower() != "voided":
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
        else:
            in_table = False

    return out


def parse_comment_payouts(comments: List[Dict]) -> List[LedgerEntry]:
    """Parse payout evidence from comments."""
    out: List[LedgerEntry] = []

    for comment in comments:
        body = comment.get("body", "")
        lines = body.splitlines()

        for line in lines:
            if line.strip().startswith("- ") and "RTC" in line:
                # Parse bullet format: - user: amount RTC
                match = re.search(r"-\s*([^:]+):\s*(\d+(?:\.\d+)?)\s*RTC", line)
                if match:
                    user = clean_user(match.group(1))
                    amount = float(match.group(2))
                    if user and amount > 0:
                        out.append(
                            LedgerEntry(
                                user=user,
                                amount=amount,
                                status="Paid",
                                pending_id="",
                                tx_hash="",
                                source="comment",
                            )
                        )

    return out


def load_json_file(path: str) -> Dict:
    """Load JSON file safely."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Warning: Could not load {path}: {e}")
        return {}


def apply_xp_entry(
    entry: LedgerEntry, tracker_path: str, dry_run: bool = False
) -> bool:
    """Apply XP for a single ledger entry."""
    tier = tier_for_amount(entry.amount)

    cmd = [
        "python3",
        ".github/scripts/update_xp_tracker_api.py",
        "--local",
        "--user",
        entry.user,
        "--tier",
        tier,
        "--tracker",
        tracker_path,
        "--reason",
        f"Backfill from ledger: {entry.amount} RTC ({entry.source})",
    ]

    if dry_run:
        print(f"DRY RUN: {' '.join(cmd)}")
        return True

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"Applied XP for {entry.user}: {tier} tier ({entry.amount} RTC)")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error applying XP for {entry.user}: {e}")
        print(f"STDOUT: {e.stdout}")
        print(f"STDERR: {e.stderr}")
        return False


def main():
    args = parse_args()

    entries: List[LedgerEntry] = []

    # Parse issue body unless comments-only
    if not args.comments_only:
        issue_data = load_json_file(args.issue_json)
        if issue_data:
            body = issue_data.get("body", "")
            entries.extend(parse_ledger_table(body, "body"))

    # Parse comments
    comments_data = load_json_file(args.comments_json)
    if comments_data and isinstance(comments_data, list):
        entries.extend(parse_comment_payouts(comments_data))

    print(f"Found {len(entries)} ledger entries to process")

    # Deduplicate by user (keep highest amount)
    user_entries: Dict[str, LedgerEntry] = {}
    for entry in entries:
        if (
            entry.user not in user_entries
            or entry.amount > user_entries[entry.user].amount
        ):
            user_entries[entry.user] = entry

    final_entries = list(user_entries.values())
    print(f"After deduplication: {len(final_entries)} unique users")

    # Apply XP for each entry
    success_count = 0
    for entry in final_entries:
        if apply_xp_entry(entry, args.tracker, args.dry_run):
            success_count += 1

    print(f"Successfully processed {success_count}/{len(final_entries)} entries")


if __name__ == "__main__":
    main()
