"""
NebulaVoice.py
──────────────
Voice management for Project Nebula.
Can be imported by other scripts or run standalone for testing.

Usage from another script:
    from NebulaVoice import play, VOICES
    play("greeting")
    play("daily_goal_locked")
"""

import os
import subprocess
import time
import sys

# ── voice file paths ──────────────────────────────────────
VOICE_DIR = "/home/aman/.config/nebula/voice"

VOICES = {
    # played when nebula boots with NO goal set
    "no_goal":      os.path.join(VOICE_DIR, "NEBULA_Initialized.mp3"),

    # played when nebula boots WITH goal already set
    "initialized":  os.path.join(VOICE_DIR, "Initialized.mp3"),

    # time-based greetings
    "morning":      os.path.join(VOICE_DIR, "morning.mp3"),
    "afternoon":    os.path.join(VOICE_DIR, "afternoon.mp3"),
    "evening":      os.path.join(VOICE_DIR, "evening.mp3"),

    # played when user tries to edit a locked daily goal
    "goal_locked":  os.path.join(VOICE_DIR, "dailyGoal.mp3"),
}

# ── durations (seconds) ───────────────────────────────────
# used by the voice viz to know how long to animate
DURATIONS = {
    "no_goal":      5.2,
    "initialized":  2.2,
    "morning":      1.2,
    "afternoon":    1.2,
    "evening":      1.2,
    "goal_locked":  6.2,
}

# ── voice viz script path ─────────────────────────────────
VOICE_VIZ = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "NebulaVoiceViz.py")

# ── state file — tells CoreBlob when audio is active ─────
VOICE_STATE_FILE = "/tmp/nebula_voice_active"

def _set_voice_state(active: bool):
    try:
        with open(VOICE_STATE_FILE, "w") as f:
            f.write("1" if active else "0")
    except OSError:
        pass

# ── playback lock ─────────────────────────────────────────
# tracks the current mpv process so we never overlap
_current_proc: subprocess.Popen | None = None

def is_playing() -> bool:
    """Return True if a voice is currently playing."""
    global _current_proc
    if _current_proc is None:
        return False
    if _current_proc.poll() is None:
        return True   # still running
    _current_proc = None
    return False


def _greeting_key():
    """Return 'morning', 'afternoon', or 'evening' based on current hour."""
    h = int(time.strftime("%H"))
    if 5 <= h < 12:
        return "morning"
    elif 12 <= h < 18:
        return "afternoon"
    else:
        return "evening"


def play(key, with_viz=False, force=False) -> bool:
    """
    Play a voice clip by key.

    key:      one of VOICES keys
    with_viz: if True, also launch NebulaVoiceViz for the duration
    force:    if True, stop any current playback and play immediately
    Returns:  True if playback started, False if blocked by ongoing audio
    """
    global _current_proc

    if is_playing():
        if not force:
            return False          # previous audio still running — skip
        _current_proc.terminate()  # force=True — kill previous first
        _current_proc = None

    path = VOICES.get(key)
    if not path or not os.path.exists(path):
        return False

    _current_proc = subprocess.Popen(
        ["mpv", "--no-video", "--really-quiet", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # signal CoreBlob to enter voice mode
    _set_voice_state(True)

    # background thread clears state when mpv finishes
    import threading
    def _clear_when_done(proc):
        proc.wait()
        _set_voice_state(False)
        global _current_proc
        _current_proc = None
    threading.Thread(target=_clear_when_done,
                     args=(_current_proc,), daemon=True).start()

    return True


def play_startup(goal_set):
    """
    Called at nebula boot.
    goal_set: bool — whether user already has a goal for today
    """
    if not goal_set:
        # no goal — play the long initialization voice + viz
        play("no_goal", with_viz=True)
    else:
        # goal exists — play short initialized + greeting
        play("initialized")
        # stagger greeting 2.5s so it plays after "initialized" finishes
        import threading
        def _delayed_greeting():
            time.sleep(2.5)
            play(_greeting_key())
        threading.Thread(target=_delayed_greeting, daemon=True).start()


def play_goal_locked():
    """Called when user clicks a locked daily goal."""
    play("goal_locked", with_viz=True)


# ── standalone test ───────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test Nebula voices")
    parser.add_argument("key", nargs="?", default="greeting",
                        choices=list(VOICES.keys()) + ["greeting", "startup_with", "startup_without"],
                        help="Voice key to test")
    args = parser.parse_args()

    if args.key == "greeting":
        play(_greeting_key(), with_viz=False)
        print(f"Playing: {_greeting_key()}")
    elif args.key == "startup_with":
        play_startup(goal_set=True)
        print("Playing startup sequence (goal set)")
    elif args.key == "startup_without":
        play_startup(goal_set=False)
        print("Playing startup sequence (no goal)")
    else:
        play(args.key, with_viz=(args.key in ("no_goal", "goal_locked")))
        print(f"Playing: {args.key}")
