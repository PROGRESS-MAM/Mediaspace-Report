#!/usr/bin/env python3
"""Launcher for mediaspace_report/mediaspace_report.py (Flow Automation or --standalone)."""

# IMPORTS
import sys
import traceback
from pathlib import Path

# CONFIG
app_name = "mediaspace_report_launcher"
app_version = "1.0.0"
script_path = Path(__file__).resolve().parent
target_path = script_path / "mediaspace_report"

# INIT
if not target_path.is_dir():
    print(f"Unterordner nicht gefunden: {target_path}", file=sys.stderr)
    sys.exit(1)
if str(target_path) not in sys.path:
    sys.path.insert(0, str(target_path))

import mediaspace_report

try:
    from editshare_helpers.automation import AutomationScript, main as automation_main
    flow_helpers_available = True
except ImportError:
    AutomationScript = object
    automation_main = None
    flow_helpers_available = False

# FUNC
class MediaspaceReportScript(AutomationScript):
    def process_asset(self, asset_info):
        try:
            exit_code = mediaspace_report.update_mediaspace_report(message_handler=self.add_message, extra_args=self.extra_args())
        except Exception as exc:
            self.add_message("error", traceback.format_exc())
            self.error_and_exit(f"{mediaspace_report.app_name} fehlgeschlagen: {exc}")
            return
        if exit_code != 0:
            self.error_and_exit(f"{mediaspace_report.app_name} fehlgeschlagen (Exit-Code {exit_code}), Details in {mediaspace_report.log_path}")
            return
        self.add_message("info", f"Bericht aktualisiert in {mediaspace_report.report_dir}")

# MAIN
def main(args: list[str]) -> int:
    if "--standalone" in args:
        return mediaspace_report.main([arg for arg in args if arg != "--standalone"])
    if flow_helpers_available:
        automation_main(MediaspaceReportScript)
        return 0
    print("editshare_helpers nicht verfügbar - Standalone-Modus", file=sys.stderr)
    return mediaspace_report.main(args)

# EXEC
if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
