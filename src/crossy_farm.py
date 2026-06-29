#!/usr/bin/env python3
"""Crossy Road Farm — the auto-farming engine for free rewards.

Two ways to run it:
  - visual panel:  crossy_gui.py   (button + counters)  <- the normal way
  - from terminal: python3 crossy_farm.py               (logs in the window, Ctrl+C to stop)

Loop: Play -> dump the run backwards -> death screen -> collect FREE reward (when blue)
      -> wait for the next run (once per cooldown) -> repeat.
"""
from __future__ import annotations

import atexit
import logging
import os
import signal
import sys
import threading
import time

import crossy_lib as cl

LOG_DIR = cl.LOG_DIR
PID_FILE = LOG_DIR / ".crossy-farm.pid"

# Timings, seconds.
IDLE_SECONDS = 61      # stand still in the game between runs (reward cooldown, 1 min 1 s)
RACE_LOAD = 1.0        # pause after pressing Play (run is loading)
BACK_TAPS = 5          # how many backward hops to dump the run
BACK_INTERVAL = 0.3
DEATH_WAIT = 2.5       # pause after dumping (death screen loads, FREE button appears)
REWARD_WAIT = 1.5      # pause after clicking FREE
COINS_PER_REWARD = 40  # coins granted per collected reward

# Screen / button text markers. Vision OCR reads the game's on-screen text, which
# depends on the GAME'S language. We match several languages so the farm works
# regardless of the in-game locale. If your language is missing, add its word here:
#   - DEATH_MARKERS: the rank label shown on the death screen (e.g. "BEST")
#   - FREE_MARKERS:  the label on the free-reward button (e.g. "FREE")
DEATH_MARKERS = (
    "TOP", "BEST",                                  # EN (game shows "TOP <n>")
    "ЛУЧШ", "ПУЧШ",                                  # RU "ЛУЧШИЕ" (OCR may read Л as П)
    "MEILLEUR", "MEJOR", "MIGLIOR", "MELHOR", "BESTE", "TERBAIK",  # FR/ES/IT/PT/DE/ID
    "トップ", "ベスト", "最高", "최고", "最佳", "أفضل",      # JA/KO/ZH/AR
)
FREE_MARKERS = (
    "FREE",                                         # EN
    "БЕСП",                                         # RU "БЕСПЛАТНО"
    "GRATUIT", "GRATIS", "GRÁTIS", "GRATUITO", "KOSTENLOS",  # FR/ES·IT·ID/PT/IT/DE
    "無料", "무료", "免费", "免費", "مجان",                # JA/KO/ZH-s/ZH-t/AR
)
# The big "CROSSY ROAD" logo is shown ONLY on the main menu, never on the death
# screen. The Latin letters are identical in every language, so OCR catches it even
# when garbled ("CROASY"). This is the language-proof way to tell the two apart.
MENU_MARKERS = ("CROSS", "CROAS", "ROAD", "ROAL", "ROAO")


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    logger = logging.getLogger("crossy-farm")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    fh = logging.FileHandler(LOG_DIR / "crossy-farm.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


def _sleep(seconds: float, stop_check) -> None:
    """Interruptible pause — reacts to a stop request almost instantly."""
    waited = 0.0
    while waited < seconds and not stop_check():
        time.sleep(0.1)
        waited += 0.1


def _find_free(blocks: list) -> tuple[float, float] | None:
    """Locate the free-reward button by any of the known language markers."""
    for marker in FREE_MARKERS:
        hit = cl.find_text(blocks, marker)
        if hit is not None:
            return hit
    return None


def _press_orange(win: dict, log: logging.Logger, what: str) -> bool:
    """Find the orange button and click it. In menu => start a run; on death => to menu."""
    w = cl.find_game_window() or win
    img = cl.capture_cgimage(w["id"])
    play = cl.find_orange_button(img) if img is not None else None
    if play is not None:
        cl.click_rel(w, *play)
        log.info(what)
        return True
    return False


def _slide_back(stop_check, win: dict) -> None:
    """Dump the run: hop backwards until death."""
    for _ in range(BACK_TAPS):
        if stop_check():
            return
        cl.move_back_key(cl.find_game_window() or win)
        _sleep(BACK_INTERVAL, stop_check)


def _is_main_menu(blocks: list) -> bool:
    """Main menu shows the big CROSSY ROAD logo in the center; the death screen does
    not. Matching the (Latin) logo separates 'play again' from 'collect the reward'
    in EVERY language — no reliance on localized words."""
    return any(any(m in b["text"].upper() for m in MENU_MARKERS) for b in blocks)


def _find_reward(img, blocks) -> tuple[float, float] | None:
    """Find the once-a-minute reward button. Primary: the FREE text marker (works in
    many languages) — only if active (blue, not gray). Fallback: detect the blue
    reward banner by color, which is language-proof. Return click point or None."""
    free = _find_free(blocks)
    if free is not None and cl.is_free_active(img, *free):
        return free
    return cl.find_reward_button(img)


def farm_loop(stop_check, on_reward, log: logging.Logger) -> None:
    """Main state-driven loop. stop_check()->bool; on_reward(total)->None.

    The two screens are told apart by the CROSSY ROAD logo (menu only), NOT by
    localized text, so it works in every game language:
      - main menu              -> start a run and dump it;
      - orange button, no logo -> death screen: grab the reward, go to menu, wait;
      - no orange button       -> a run is in progress: keep hopping back."""
    rewards = 0
    while not stop_check():
        win = cl.find_game_window()
        if win is None:
            log.info("game window not found — bringing the game up")
            win = cl.activate_game()
            if win is None:
                _sleep(2.0, stop_check)
                continue

        img = cl.capture_cgimage(win["id"])
        if img is None:
            _sleep(0.5, stop_check)
            continue
        blocks = cl.ocr_blocks(img)

        if _is_main_menu(blocks):
            # Main menu (CROSSY ROAD logo): start a run and dump it backwards.
            _press_orange(win, log, "Play — starting a run")
            _sleep(RACE_LOAD, stop_check)
            _slide_back(stop_check, win)
            _sleep(DEATH_WAIT, stop_check)
        elif cl.find_orange_button(img) is not None:
            # Orange button without the logo => death screen. Grab reward if ready.
            reward = _find_reward(img, blocks)
            if reward is not None:
                cl.click_rel(win, *reward)
                rewards += 1
                log.info("reward collected (total: %s, coins: %s)",
                         rewards, rewards * COINS_PER_REWARD)
                on_reward(rewards)
                _sleep(REWARD_WAIT, stop_check)
            _press_orange(win, log, "orange button — back to main menu")
            log.info("waiting %s s in menu (reward cooldown)", IDLE_SECONDS)
            _sleep(IDLE_SECONDS, stop_check)
        else:
            # A run is in progress (no orange button) — keep hopping back.
            _slide_back(stop_check, win)
            _sleep(DEATH_WAIT, stop_check)


def main() -> int:
    if sys.platform != "darwin":
        print("This tool runs on macOS only.")
        return 1

    log = setup_logging()
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            log.error("Already running (PID %s).", pid)
            return 1
        except (ValueError, OSError):
            pass

    PID_FILE.write_text(str(os.getpid()))
    atexit.register(lambda: PID_FILE.unlink(missing_ok=True))

    stop_event = threading.Event()
    signal.signal(signal.SIGINT, lambda *a: stop_event.set())
    signal.signal(signal.SIGTERM, lambda *a: stop_event.set())

    log.info("=== Crossy Farm started (PID %s) ===", os.getpid())
    log.info("Stop: Ctrl+C or close the panel window.")

    if cl.activate_game() is None:
        log.error("Could not open the game.")
        return 1

    try:
        farm_loop(stop_event.is_set, lambda r: None, log)
    finally:
        log.info("=== Crossy Farm stopped. The game was left open. ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
