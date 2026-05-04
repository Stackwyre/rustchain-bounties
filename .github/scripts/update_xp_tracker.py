#!/usr/bin/env python3
"""Update XP_TRACKER.md with new bounty completion."""

import argparse
from datetime import datetime
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Update XP tracker")
    parser.add_argument("--user", required=True, help="GitHub username")
    parser.add_argument(
        "--tier",
        required=True,
        choices=["micro", "standard", "major", "critical"],
        help="Bounty tier",
    )
    parser.add_argument("--issue", required=True, help="Issue number")
    parser.add_argument("--description", required=True, help="Bounty description")
    parser.add_argument(
        "--tracker-file",
        default="bounties/XP_TRACKER.md",
        help="Path to XP tracker file",
    )
    return parser.parse_args()


def get_xp_for_tier(tier):
    """Get XP points for bounty tier."""
    xp_map = {"micro": 5, "standard": 25, "major": 50, "critical": 100}
    return xp_map.get(tier, 0)


def update_tracker(user, tier, issue, description, tracker_file):
    """Update the XP tracker with new entry."""
    tracker_path = Path(tracker_file)

    if not tracker_path.exists():
        # Create new tracker file
        content = "# XP Tracker\n\n## Leaderboard\n\n| User | Total XP |\n|------|----------|\n\n## Activity Log\n\n| Date | User | Tier | XP | Issue | Description |\n|------|------|------|----|----|-------------|\n"
    else:
        content = tracker_path.read_text()

    xp = get_xp_for_tier(tier)
    date = datetime.now().strftime("%Y-%m-%d")

    # Add new entry to activity log
    new_entry = f"| {date} | {user} | {tier} | {xp} | #{issue} | {description} |\n"

    # Find activity log section and add entry
    if "## Activity Log" in content:
        # Insert after the header row
        lines = content.split("\n")
        insert_idx = -1
        for i, line in enumerate(lines):
            if line.startswith("|------|------|------|----|----|-------------|"):
                insert_idx = i + 1
                break

        if insert_idx > 0:
            lines.insert(insert_idx, new_entry.rstrip())
            content = "\n".join(lines)

    # Update leaderboard
    content = update_leaderboard(content)

    tracker_path.write_text(content)
    print(f"Updated XP tracker: {user} +{xp} XP for {tier} bounty #{issue}")


def update_leaderboard(content):
    """Recalculate and update leaderboard from activity log."""
    user_xp = {}

    # Parse activity log to calculate totals
    lines = content.split("\n")
    in_activity = False

    for line in lines:
        if line.startswith("## Activity Log"):
            in_activity = True
            continue
        if in_activity and line.startswith("|") and not line.startswith("|---"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 6 and parts[2] and parts[3]:
                try:
                    user = parts[2]
                    xp = int(parts[4])
                    if user != "User":  # Skip header
                        user_xp[user] = user_xp.get(user, 0) + xp
                except ValueError, IndexError:
                    continue

    # Rebuild leaderboard section
    leaderboard_lines = []
    leaderboard_lines.append("## Leaderboard")
    leaderboard_lines.append("")
    leaderboard_lines.append("| User | Total XP |")
    leaderboard_lines.append("|------|----------|")

    # Sort by XP descending
    for user, xp in sorted(user_xp.items(), key=lambda x: x[1], reverse=True):
        leaderboard_lines.append(f"| {user} | {xp} |")

    leaderboard_lines.append("")

    # Replace leaderboard section
    new_content_lines = []
    lines = content.split("\n")
    i = 0

    # Copy everything before leaderboard
    while i < len(lines) and not lines[i].startswith("## Leaderboard"):
        new_content_lines.append(lines[i])
        i += 1

    # Add new leaderboard
    new_content_lines.extend(leaderboard_lines)

    # Skip old leaderboard, find activity log
    while i < len(lines) and not lines[i].startswith("## Activity Log"):
        i += 1

    # Add rest of content
    while i < len(lines):
        new_content_lines.append(lines[i])
        i += 1

    return "\n".join(new_content_lines)


if __name__ == "__main__":
    args = parse_args()
    update_tracker(
        args.user, args.tier, args.issue, args.description, args.tracker_file
    )
