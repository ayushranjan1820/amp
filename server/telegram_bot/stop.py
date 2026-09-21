"""
Stop all running Telegram bot instances.

Cross-platform: works on Windows (tasklist/taskkill) and Unix (pgrep/pkill).

Usage:
  python stop.py          (from server/telegram_bot/)
  python -c "from telegram_bot.stop import main; main()"
"""

import os
import platform
import signal
import subprocess
import sys

import httpx

# Resolve paths
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(BOT_DIR)

# Load token from server/.env
TOKEN = ""
env_path = os.path.join(SERVER_DIR, ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                TOKEN = line.split("=", 1)[1].strip()


def _kill_windows() -> int:
    """Find and kill telegram_bot Python processes on Windows."""
    killed = 0
    try:
        # Use tasklist + WMIC alternative (PowerShell) since wmic is deprecated on Win11.
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Process -Filter "
                "\"Name='python.exe' or Name='python3.exe' or Name='pythonw.exe'\" "
                "| Select-Object ProcessId, CommandLine | Format-List",
            ],
            capture_output=True, text=True, timeout=15,
        )
        current_pid = os.getpid()
        # Parse output: ProcessId : 12345  /  CommandLine : ...
        pid = None
        cmdline = ""
        for raw_line in result.stdout.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("ProcessId"):
                val = stripped.split(":", 1)[-1].strip()
                pid = int(val) if val.isdigit() else None
            elif stripped.startswith("CommandLine"):
                cmdline = stripped.split(":", 1)[-1].strip().lower()
            elif not stripped and pid is not None:
                # End of record — decide whether to kill.
                if (
                    pid != current_pid
                    and "telegram_bot" in cmdline
                    and "stop" not in cmdline
                ):
                    try:
                        os.kill(pid, signal.SIGTERM)
                        print(f"  Killed PID {pid}")
                        killed += 1
                    except OSError:
                        pass
                pid = None
                cmdline = ""
    except FileNotFoundError:
        # PowerShell not available — fall back to taskkill by window title guess.
        try:
            subprocess.run(
                ["taskkill", "/F", "/FI", "WINDOWTITLE eq telegram_bot*"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            pass
    except Exception as exc:
        print(f"  Windows process scan failed: {exc}")
    return killed


def _kill_unix() -> int:
    """Find and kill telegram_bot Python processes on Linux/macOS."""
    killed = 0
    try:
        result = subprocess.run(
            ["pgrep", "-f", "telegram_bot"],
            capture_output=True, text=True, timeout=10,
        )
        current_pid = os.getpid()
        for pid_str in result.stdout.strip().split():
            if not pid_str.isdigit():
                continue
            pid = int(pid_str)
            if pid == current_pid:
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"  Killed PID {pid}")
                killed += 1
            except OSError:
                pass
    except FileNotFoundError:
        print("  pgrep not found; cannot scan for running bots on this system")
    except Exception as exc:
        print(f"  Unix process scan failed: {exc}")
    return killed


def kill_python_processes() -> int:
    """Kill all Python processes running the telegram bot (cross-platform)."""
    if platform.system() == "Windows":
        return _kill_windows()
    return _kill_unix()


def delete_webhook():
    """Delete webhook and drop pending updates to clear remote conflicts."""
    if not TOKEN:
        print("  No TELEGRAM_BOT_TOKEN found in .env, skipping webhook cleanup")
        return
    try:
        r = httpx.get(
            f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true",
            timeout=10,
        )
        data = r.json()
        if data.get("ok"):
            print("  Webhook cleared & pending updates dropped")
        else:
            print(f"  Webhook response: {data}")
    except Exception as e:
        print(f"  Failed to clear webhook: {e}")


def main():
    print("=" * 50)
    print("  STOP ALL TELEGRAM BOT INSTANCES")
    print("=" * 50)

    print("\n[1/2] Killing local bot processes...")
    killed = kill_python_processes()
    if killed == 0:
        print("  No local bot processes found")
    else:
        print(f"  Killed {killed} process(es)")

    print("\n[2/2] Clearing Telegram webhook...")
    delete_webhook()

    print("\n Done! You can now start a fresh instance:")
    print("   python telegram_bot/bot.py")
    print("   python -m telegram_bot")
    print("=" * 50)


if __name__ == "__main__":
    main()
