#!/usr/bin/env python3
"""Low-level automation primitives for Crossy Road (iOS-on-Mac, Unity).

Empirically established facts about this game:
  - window capture:  CGWindowListCreateImage by window id (needs Screen Recording)
  - clicking:        ONLY a global CGEventPost works (CGEventPostToPid is ignored)
  - window:          floats freely; we re-read its real bounds before every action
  - coordinates:     we work in window-relative fractions (0..1), not raw pixels
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import Quartz
import Vision

PROJECT_DIR = Path(__file__).resolve().parent

# Logs and the pid file live STRICTLY outside the .app bundle. Writing inside the
# bundle would mutate its contents, break the app's code signature, and make macOS
# re-prompt for permissions on every launch. So we keep them in Application Support.
LOG_DIR = Path.home() / "Library" / "Application Support" / "CrossyFarm"
LOG_DIR.mkdir(parents=True, exist_ok=True)
GAME_APP = "Crossy Road"
OWNER_HINTS = ("crossy",)


def find_game_window() -> dict | None:
    """Return live bounds of the game's main window (the largest window it owns)."""
    options = (
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListExcludeDesktopElements
    )
    windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
    cands = []
    for w in windows or []:
        owner = (w.get("kCGWindowOwnerName") or "").lower()
        if any(h in owner for h in OWNER_HINTS):
            b = w.get("kCGWindowBounds", {}) or {}
            cands.append(
                {
                    "id": int(w.get("kCGWindowNumber", 0)),
                    "pid": int(w.get("kCGWindowOwnerPID", 0)),
                    "x": float(b.get("X", 0)),
                    "y": float(b.get("Y", 0)),
                    "w": float(b.get("Width", 0)),
                    "h": float(b.get("Height", 0)),
                }
            )
    if not cands:
        return None
    return max(cands, key=lambda c: c["w"] * c["h"])


def activate_game() -> dict | None:
    """Bring the game to the foreground (Unity requires focus) and wait for its window."""
    subprocess.run(["open", "-a", GAME_APP], check=False)
    for _ in range(20):
        time.sleep(1.0)
        win = find_game_window()
        if win:
            return win
    return None


def click_abs(x: float, y: float) -> None:
    """Global click (the only method this game actually accepts)."""
    pos = Quartz.CGPointMake(float(x), float(y))
    for kind in (
        Quartz.kCGEventMouseMoved,
        Quartz.kCGEventLeftMouseDown,
        Quartz.kCGEventLeftMouseUp,
    ):
        e = Quartz.CGEventCreateMouseEvent(None, kind, pos, Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)
        time.sleep(0.02)


def click_rel(win: dict, rx: float, ry: float) -> tuple[float, float]:
    """Click at a fraction of the window (rx, ry in 0..1). Return the absolute point."""
    x = win["x"] + rx * win["w"]
    y = win["y"] + ry * win["h"]
    click_abs(x, y)
    return (x, y)


def key_press(keycode: int) -> None:
    """Global key tap (down + up)."""
    down = Quartz.CGEventCreateKeyboardEvent(None, keycode, True)
    up = Quartz.CGEventCreateKeyboardEvent(None, keycode, False)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    time.sleep(0.03)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
    time.sleep(0.03)


def move_back_key(win: dict) -> None:
    """Hop backwards via the Down arrow key (keyboard) — used to end the run."""
    key_press(125)  # kVK_DownArrow


def capture_cgimage(win_id: int):
    """Grab a frame of the window into memory (CGImage), without touching disk."""
    return Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull,
        Quartz.kCGWindowListOptionIncludingWindow,
        win_id,
        Quartz.kCGWindowImageBoundsIgnoreFraming,
    )


def _pixels(img) -> tuple[bytes, int, int, int]:
    w = Quartz.CGImageGetWidth(img)
    h = Quartz.CGImageGetHeight(img)
    bpr = Quartz.CGImageGetBytesPerRow(img)
    provider = Quartz.CGImageGetDataProvider(img)
    data = Quartz.CGDataProviderCopyData(provider)
    return bytes(data), w, h, bpr


def find_orange_button(img) -> tuple[float, float] | None:
    """Center of the orange Play button as window fractions. Searched in the lower band."""
    buf, w, h, bpr = _pixels(img)
    sx = sy = n = 0
    step = 4
    for y in range(int(0.76 * h), int(0.98 * h), step):
        base = y * bpr
        for x in range(0, w, step):
            i = base + x * 4
            b, g, r = buf[i], buf[i + 1], buf[i + 2]  # BGRA order
            if r > 200 and 145 < g < 220 and b < 140:  # golden-orange
                sx += x
                sy += y
                n += 1
    if n < 40:
        return None
    return (sx / n / w, sy / n / h)


# Two language groups. A single big set hurts Latin recognition (the "FREE" button
# stops being read), so we OCR in two passes and merge: Latin/Cyrillic, then CJK/Arabic.
_LANGS_LATIN = ["en", "ru"]                              # EN/FR/DE/IT/ES/PT/ID + RU
_LANGS_CJK = ["zh-Hans", "zh-Hant", "ja", "ko", "ar"]    # Chinese/Japanese/Korean/Arabic


def _ocr_pass(img, langs) -> list:
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(0)  # Accurate
    req.setUsesLanguageCorrection_(False)
    try:
        req.setRecognitionLanguages_(langs)
    except Exception:
        pass
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, {})
    handler.performRequests_error_([req], None)
    out = []
    for r in req.results() or []:
        c = r.topCandidates_(1)
        if not c:
            continue
        b = r.boundingBox()
        out.append(
            {
                "text": c[0].string(),
                "cx": b.origin.x + b.size.width / 2.0,
                "cy": 1.0 - (b.origin.y + b.size.height / 2.0),
                "conf": c[0].confidence(),
            }
        )
    return out


def ocr_blocks(img) -> list:
    """Recognized text lines from two OCR passes (Latin/Cyrillic + CJK/Arabic),
    merged. This reads the game's buttons in all 13 of its languages without the
    large-language-set penalty that breaks Latin recognition."""
    return _ocr_pass(img, _LANGS_LATIN) + _ocr_pass(img, _LANGS_CJK)


def find_text(blocks: list, needle: str) -> tuple[float, float] | None:
    """Center of the right-most block containing needle (right occurrence = the button)."""
    needle = needle.upper()
    matches = [b for b in blocks if needle in b["text"].upper()]
    if not matches:
        return None
    best = max(matches, key=lambda b: b["cx"])
    return (best["cx"], best["cy"])


def _avg_color(img, rx: float, ry: float, rw: float = 0.045, rh: float = 0.022):
    """Average color (R, G, B) of an area around the fraction (rx, ry)."""
    buf, w, h, bpr = _pixels(img)
    x, y = int(rx * w), int(ry * h)
    dxr, dyr = int(rw * w), int(rh * h)
    rs = gs = bs = n = 0
    for dy in range(-dyr, dyr + 1, 3):
        for dx in range(-dxr, dxr + 1, 4):
            xx = min(max(x + dx, 0), w - 1)
            yy = min(max(y + dy, 0), h - 1)
            i = yy * bpr + xx * 4
            bs += buf[i]
            gs += buf[i + 1]
            rs += buf[i + 2]
            n += 1
    return rs / n, gs / n, bs / n


def is_free_active(img, rx: float, ry: float) -> bool:
    """Is the FREE reward button active (blue)? A gray one (used/cooldown) -> False."""
    r, _g, b = _avg_color(img, rx, ry)
    return (b - r) > 20


def find_reward_button(img) -> tuple[float, float] | None:
    """Find the once-a-minute reward by COLOR (language-proof, no text needed): the
    reward banner is a wide horizontal BLUE strip across the middle of the death
    screen. Returns the RIGHT button (the one with the character) as window
    fractions, or None when there's no banner (reward not ready yet)."""
    buf, w, h, bpr = _pixels(img)
    best_y, best_frac = None, 0.0
    step = 4
    for y in range(int(0.40 * h), int(0.60 * h), step):
        base = y * bpr
        blue = total = 0
        for x in range(0, w, step):
            i = base + x * 4
            b, g, r = buf[i], buf[i + 1], buf[i + 2]  # BGRA
            total += 1
            # specific cyan-blue of the banner: high blue, low red (not sky/purple)
            if (b - r) > 45 and b > 140 and r < 130:
                blue += 1
        frac = blue / total if total else 0.0
        if frac > best_frac:
            best_frac, best_y = frac, y
    if best_frac < 0.45:  # no wide blue banner -> reward not ready
        return None
    return (0.56, best_y / h)  # right (character) button of the banner
