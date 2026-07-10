#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = ["requests"]
# ///

import json
import sys
import requests
from pathlib import Path
from datetime import datetime

try:
    from macos_notification import send_macos_notification, extract_latest_message
except ImportError:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "macos_notification",
        Path(__file__).parent / "macos_notification.py"
    )
    macos_notification = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(macos_notification)
    send_macos_notification = macos_notification.send_macos_notification
    extract_latest_message = macos_notification.extract_latest_message

try:
    from channel_flags import macos_enabled, slack_enabled
except ImportError:
    import importlib.util
    flags_spec = importlib.util.spec_from_file_location(
        "channel_flags",
        Path(__file__).parent / "channel_flags.py"
    )
    channel_flags = importlib.util.module_from_spec(flags_spec)
    flags_spec.loader.exec_module(channel_flags)
    macos_enabled = channel_flags.macos_enabled
    slack_enabled = channel_flags.slack_enabled

try:
    from attention_hub_bridge import report_state, get_session_name, set_waiting_marker
except ImportError:
    import importlib.util
    bridge_spec = importlib.util.spec_from_file_location(
        "attention_hub_bridge",
        Path(__file__).parent / "attention_hub_bridge.py"
    )
    attention_hub_bridge = importlib.util.module_from_spec(bridge_spec)
    bridge_spec.loader.exec_module(attention_hub_bridge)
    report_state = attention_hub_bridge.report_state
    get_session_name = attention_hub_bridge.get_session_name
    set_waiting_marker = attention_hub_bridge.set_waiting_marker

# Notification types that mean the agent is blocked and needs user action.
ACTIONABLE_NOTIFICATION_TYPES = {"permission_prompt", "idle_prompt", "elicitation_dialog"}


def log_message(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = Path.home() / ".claude" / "logs" / "notification_hook.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")
    print(f"[{timestamp}] {message}", file=sys.stderr)


def send_to_slack_app(session_id, message, hook_type="notification"):
    try:
        payload = {"session_id": session_id, "message": message, "hook_type": hook_type}
        log_message(f"🚀 Sending to Slack: {payload}")
        response = requests.post("http://localhost:8080/claude/hook", json=payload, timeout=10)
        log_message(f"📡 Slack response: {response.status_code}")
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        log_message(f"🔌 Slack connection error: {e}")
        return False


def main():
    try:
        log_message("🔔 NOTIFICATION HOOK TRIGGERED")

        input_data = json.load(sys.stdin)
        log_message(f"📥 Input: {input_data}")

        session_id = input_data.get("session_id", "")
        transcript_path = input_data.get("transcript_path", "")
        notification_type = input_data.get("notification_type", "")

        log_message(f"🔖 notification_type: {notification_type}")

        if notification_type not in ACTIONABLE_NOTIFICATION_TYPES:
            log_message(f"⏭️ Skipping non-actionable notification type: {notification_type!r}")
            sys.exit(0)

        if not session_id:
            log_message("❌ No session ID, exiting")
            sys.exit(0)

        message = extract_latest_message(transcript_path) or input_data.get("message", "")

        # Set the waiting marker even if the hub POST fails: intent matters,
        # and a later redundant "working" report is harmless. No-ops silently
        # when attention-hub isn't installed.
        set_waiting_marker(session_id)

        hub_success = report_state(session_id, input_data.get("cwd", ""), "waiting", message,
                                   session_name=get_session_name(input_data))
        log_message(f"{'✅' if hub_success else '❌'} Hub (waiting)")

        if not message:
            log_message("⚠️ No message to send")
            sys.exit(0)

        log_message(f"📤 Sending notifications for actionable type: {notification_type!r}")

        if slack_enabled():
            slack_success = send_to_slack_app(session_id, message, f"notification_{notification_type}")
            log_message(f"{'✅' if slack_success else '❌'} Slack")
        else:
            log_message("⏭️ Slack disabled via CLAUDE_NOTIFY_SLACK")

        if macos_enabled():
            macos_success = send_macos_notification(message, subtitle="Needs Attention", sound="Glass")
            log_message(f"{'✅' if macos_success else '❌'} macOS")
        else:
            log_message("⏭️ macOS disabled via CLAUDE_NOTIFY_MACOS")

        sys.exit(0)

    except json.JSONDecodeError:
        sys.exit(0)
    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
