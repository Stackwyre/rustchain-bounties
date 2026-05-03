#!/usr/bin/env python3
"""Update XP_TRACKER.md with new bounty completions.

This script processes bounty claims and updates the XP tracker markdown file.
"""

import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update XP tracker with bounty claims")
    parser.add_argument(
        "--tracker-file",
        default="bounties/XP_TRACKER.md",
        help="Path to XP tracker file",
    )
    parser.add_argument("--user", required=True, help="GitHub username")
    parser.add_argument("--wallet", required=True, help="RTC wallet address")
    parser.add_argument("--amount", type=float, required=True, help="RTC amount")
    parser.add_argument("--description", required=True, help="Bounty description")
    parser.add_argument("--issue-number", help="Related issue number")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show changes without writing"
    )
    return parser.parse_args()


def get_tier_for_amount(amount: float) -> str:
    """Convert RTC amount to tier label."""
    if amount <= 10:
        return "micro"
    elif amount <= 50:
        return "standard"
    elif amount <= 100:
        return "major"
    else:
        return "critical"


def get_xp_for_tier(tier: str) -> int:
    """Get XP points for tier."""
    tier_xp = {"micro": 5, "standard": 25, "major": 100, "critical": 500}
    return tier_xp.get(tier, 0)


def update_xp_tracker(
    tracker_file: Path,
    user: str,
    wallet: str,
    amount: float,
    description: str,
    issue_number: Optional[str] = None,
    dry_run: bool = False,
) -> None:
    """Update the XP tracker with a new bounty claim."""
    tier = get_tier_for_amount(amount)
    xp = get_xp_for_tier(tier)

    # Create new entry
    date_str = datetime.now().strftime("%Y-%m-%d")
    issue_ref = f"#{issue_number}" if issue_number else "PR Review"

    new_entry = f"| {date_str} | {issue_ref} | @{user} | {description} | {amount} RTC | {tier} | {xp} XP | {wallet} |"

    if dry_run:
        print(f"Would add entry: {new_entry}")
        return

    # Read existing tracker file or create new one
    if tracker_file.exists():
        content = tracker_file.read_text()
    else:
        content = """# XP Tracker

## Active Entries

| Date | Bounty Ref | User | Description | Amount | Tier | XP | Wallet |
|------|------------|------|-------------|--------|------|----|---------|
"""

    # Add new entry to the table
    lines = content.splitlines()
    table_end_idx = -1

    # Find the end of the Active Entries table
    in_active_table = False
    for i, line in enumerate(lines):
        if "## Active Entries" in line:
            in_active_table = True
            continue
        if in_active_table and line.startswith("|"):
            table_end_idx = i
        elif (
            in_active_table
            and line.strip()
            and not line.startswith("|")
            and not line.startswith("|---")
        ):
            break

    # Insert new entry
    if table_end_idx >= 0:
        lines.insert(table_end_idx + 1, new_entry)
    else:
        # Append to end if table structure not found
        lines.append(new_entry)

    # Write back to file
    tracker_file.write_text("\n".join(lines) + "\n")
    print(f"Added XP entry for {user}: {xp} XP ({tier} tier)")


def main():
    args = parse_args()
    tracker_file = Path(args.tracker_file)

    update_xp_tracker(
        tracker_file=tracker_file,
        user=args.user,
        wallet=args.wallet,
        amount=args.amount,
        description=args.description,
        issue_number=args.issue_number,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
