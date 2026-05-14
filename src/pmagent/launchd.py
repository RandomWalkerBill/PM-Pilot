from __future__ import annotations

import argparse
import shutil
from pathlib import Path


DAILY_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.pmagnet.daily-digest</string>
    <key>ProgramArguments</key>
    <array>
      <string>{pmagent}</string>
      <string>digest</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
      <key>Hour</key>
      <integer>{hour}</integer>
      <key>Minute</key>
      <integer>{minute}</integer>
    </dict>
    <key>RunAtLoad</key>
    <true/>
  </dict>
</plist>
"""

WEEKLY_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.pmagnet.weekly-routine</string>
    <key>ProgramArguments</key>
    <array>
      <string>{pmagent}</string>
      <string>weekly</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
      <key>Weekday</key>
      <integer>{weekday}</integer>
      <key>Hour</key>
      <integer>{hour}</integer>
      <key>Minute</key>
      <integer>{minute}</integer>
    </dict>
    <key>RunAtLoad</key>
    <false/>
  </dict>
</plist>
"""


def _pmagent_executable() -> str:
    return shutil.which("pmagent") or "pmagent"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install launchd plist files")
    parser.add_argument("job", choices=["daily-digest", "weekly-routine"])
    parser.add_argument("--weekday", type=int, default=1)
    parser.add_argument("--hour", type=int, default=None)
    parser.add_argument("--minute", type=int, default=None)
    args = parser.parse_args(argv)

    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)

    if args.job == "daily-digest":
        target = launch_agents / "com.pmagnet.daily-digest.plist"
        target.write_text(
            DAILY_TEMPLATE.format(pmagent=_pmagent_executable(), hour=args.hour or 9, minute=args.minute or 0),
            encoding="utf-8",
        )
    else:
        target = launch_agents / "com.pmagnet.weekly-routine.plist"
        target.write_text(
            WEEKLY_TEMPLATE.format(
                pmagent=_pmagent_executable(),
                weekday=args.weekday,
                hour=args.hour or 9,
                minute=args.minute or 30,
            ),
            encoding="utf-8",
        )

    print(str(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
