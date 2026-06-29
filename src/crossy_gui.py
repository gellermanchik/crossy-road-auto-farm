#!/usr/bin/env python3
"""Visual control panel for Crossy Farm (native, Cocoa/PyObjC).

ON/OFF button, counters (coins = rewards x40, reward count, elapsed time).
On first launch it asks for permissions (Screen Recording + Accessibility).
Closing the window stops the farm completely.
"""
from __future__ import annotations

import os
import threading
import time

import objc
import Quartz
from AppKit import (
    NSApp, NSApplication, NSApplicationActivationPolicyRegular, NSBackingStoreBuffered,
    NSButton, NSColor, NSFont, NSMakeRect, NSMakeSize, NSScreen, NSTextField, NSTimer,
    NSWindow, NSWindowStyleMaskClosable, NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable, NSWindowStyleMaskTitled, NSFloatingWindowLevel,
    NSFontAttributeName, NSForegroundColorAttributeName,
)
from Foundation import NSObject, NSAttributedString

import crossy_farm as cf

_CENTER = 1  # NSTextAlignmentCenter (verified: Center=1, Right=2)

BG     = (0.09, 0.10, 0.16)
ORANGE = (0.96, 0.65, 0.14)
RED    = (0.84, 0.22, 0.22)
GOLD   = (1.00, 0.84, 0.31)
GREEN  = (0.34, 0.82, 0.46)
GRAY   = (0.62, 0.64, 0.72)
WHITE  = (0.96, 0.97, 1.00)


@objc.python_method
def _c(rgb, a=1.0):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(rgb[0], rgb[1], rgb[2], a)


@objc.python_method
def _label(text, size, rgb, bold=False):
    lbl = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
    lbl.setStringValue_(text)
    lbl.setBezeled_(False)
    lbl.setDrawsBackground_(False)
    lbl.setEditable_(False)
    lbl.setSelectable_(False)
    lbl.setTextColor_(_c(rgb))
    lbl.setAlignment_(_CENTER)
    lbl.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    return lbl


class FarmController(NSObject):
    def init(self):
        self = objc.super(FarmController, self).init()
        if self is None:
            return None
        self.log = cf.setup_logging()
        self.thread = None
        self.stop_event = threading.Event()
        self.rewards = 0
        self._shown = 0
        self.start_time = None
        self._build()
        self._request_permissions()
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.5, self, b"tick:", None, True)
        threading.Thread(target=self._watch_parent, daemon=True).start()
        return self

    @objc.python_method
    def _request_permissions(self):
        # Ask for access once at launch; if already granted, no dialogs appear.
        try:
            Quartz.CGRequestScreenCaptureAccess()
        except Exception:
            pass
        try:
            from ApplicationServices import AXIsProcessTrustedWithOptions
            AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True})
        except Exception:
            pass

    @objc.python_method
    def _build(self):
        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                 | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 290, 348), style, NSBackingStoreBuffered, False)
        win.setTitle_("Crossy Farm")
        win.setLevel_(NSFloatingWindowLevel)
        win.setReleasedWhenClosed_(False)
        win.setDelegate_(self)
        win.setContentMinSize_(NSMakeSize(270, 320))
        win.setBackgroundColor_(_c(BG))
        scr = NSScreen.mainScreen().frame()
        win.setFrameOrigin_((scr.size.width - 312, scr.size.height - 392))

        content = win.contentView()
        content.setWantsLayer_(True)

        self.chicken = _label("🐔", 36, WHITE)
        self.title = _label("CROSSY FARM", 15, WHITE, bold=True)
        self.status = _label("Stopped", 12, GRAY)
        self.status.setWantsLayer_(True)

        self.btn = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.btn.setBordered_(False)
        self.btn.setWantsLayer_(True)
        self.btn.layer().setCornerRadius_(13.0)
        self.btn.layer().setBackgroundColor_(_c(ORANGE).CGColor())
        self.btn.setTarget_(self)
        self.btn.setAction_(b"toggle:")
        self._btn_title("START")

        self.coins = _label("0", 32, GOLD, bold=True)
        self.coins.setWantsLayer_(True)
        self.coins_sub = _label("coins farmed", 11, GRAY)
        self.time_lbl = _label("⏱ 00:00", 12, WHITE)
        self.rew_lbl = _label("🎁 0", 12, WHITE)

        for v in (self.chicken, self.title, self.status, self.btn,
                  self.coins, self.coins_sub, self.time_lbl, self.rew_lbl):
            content.addSubview_(v)

        self.window = win
        self._relayout()
        win.makeKeyAndOrderFront_(None)

    @objc.python_method
    def _btn_title(self, text):
        attrs = {
            NSFontAttributeName: NSFont.boldSystemFontOfSize_(19),
            NSForegroundColorAttributeName: _c(WHITE),
        }
        self.btn.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(text, attrs))

    @objc.python_method
    def _relayout(self):
        b = self.window.contentView().bounds()
        W, H = b.size.width, b.size.height
        cx = W / 2.0
        self.chicken.setFrame_(NSMakeRect(0, H - 58, W, 40))
        self.title.setFrame_(NSMakeRect(0, H - 86, W, 24))
        self.status.setFrame_(NSMakeRect(0, H - 110, W, 18))
        self.time_lbl.setFrame_(NSMakeRect(14, 20, W / 2.0 - 18, 18))
        self.rew_lbl.setFrame_(NSMakeRect(cx + 4, 20, W / 2.0 - 18, 18))
        self.coins_sub.setFrame_(NSMakeRect(0, 56, W, 16))
        self.coins.setFrame_(NSMakeRect(0, 74, W, 42))
        top = H - 122.0
        bottom = 126.0
        bh = 50.0
        by = (top + bottom) / 2.0 - bh / 2.0
        bw = min(228.0, W - 42)
        self.btn.setFrame_(NSMakeRect(cx - bw / 2.0, by, bw, bh))

    def windowDidResize_(self, notification):
        self._relayout()

    @objc.python_method
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def toggle_(self, sender):
        if self.running():
            self.stop_event.set()
            self.status.setStringValue_("Stopping…")
            self.btn.setEnabled_(False)
            return
        # Verify both permissions are actually ACTIVE before farming. Without this
        # the bot would silently spin — seeing nothing or landing no clicks — which
        # is exactly what a revoked/again-granted permission looks like.
        screen, ax = self._check_permissions()
        if not (screen and ax):
            missing = []
            if not screen:
                missing.append("Screen Recording")
            if not ax:
                missing.append("Accessibility")
            self.status.setStringValue_("⚠ Allow " + " + ".join(missing) + ", reopen app")
            self.status.setTextColor_(_c(RED))
            self._request_permissions()
            self._open_privacy_settings(screen)
            return
        self.stop_event.clear()
        self.rewards = 0
        self._shown = 0
        self.start_time = time.monotonic()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.status.setStringValue_("Running")
        self.status.setTextColor_(_c(GREEN))
        self.btn.layer().setBackgroundColor_(_c(RED).CGColor())
        self._btn_title("STOP")
        self._pulse(True)

    @objc.python_method
    def _check_permissions(self):
        """Return (screen_recording_ok, accessibility_ok) for THIS app — the real
        live state, so we never start farming when a permission was revoked."""
        try:
            screen = bool(Quartz.CGPreflightScreenCaptureAccess())
        except Exception:
            screen = True  # older macOS without the API: assume ok
        try:
            from ApplicationServices import AXIsProcessTrusted
            ax = bool(AXIsProcessTrusted())
        except Exception:
            ax = True
        return screen, ax

    @objc.python_method
    def _open_privacy_settings(self, screen_ok):
        """Open the exact Privacy pane the user still needs to enable."""
        import subprocess
        pane = "Privacy_Accessibility" if screen_ok else "Privacy_ScreenCapture"
        subprocess.run(
            ["open", f"x-apple.systempreferences:com.apple.preference.security?{pane}"],
            check=False)

    @objc.python_method
    def _run(self):
        cf.farm_loop(self.stop_event.is_set, self._on_reward, self.log)

    @objc.python_method
    def _watch_parent(self):
        # If the launcher (the parent app) dies on Force Quit, our parent changes
        # (reparent). We exit immediately so the python farm thread is not left
        # behind as an orphan.
        initial = os.getppid()
        while True:
            if os.getppid() != initial:
                os._exit(0)
            time.sleep(0.5)

    @objc.python_method
    def _on_reward(self, total):
        self.rewards = total

    @objc.python_method
    def _pulse(self, on):
        try:
            if on:
                a = Quartz.CABasicAnimation.animationWithKeyPath_("opacity")
                a.setFromValue_(1.0)
                a.setToValue_(0.35)
                a.setDuration_(0.8)
                a.setAutoreverses_(True)
                a.setRepeatCount_(1e9)
                self.status.layer().addAnimation_forKey_(a, "pulse")
            else:
                self.status.layer().removeAnimationForKey_("pulse")
        except Exception:
            pass

    @objc.python_method
    def _bump(self):
        try:
            a = Quartz.CABasicAnimation.animationWithKeyPath_("transform.scale")
            a.setFromValue_(1.0)
            a.setToValue_(1.2)
            a.setDuration_(0.18)
            a.setAutoreverses_(True)
            self.coins.layer().addAnimation_forKey_(a, "bump")
        except Exception:
            pass

    def tick_(self, timer):
        self.coins.setStringValue_(f"{self.rewards * cf.COINS_PER_REWARD}")
        self.rew_lbl.setStringValue_(f"🎁 {self.rewards}")
        if self.rewards != self._shown:
            self._shown = self.rewards
            self._bump()
        if self.running():
            if self.start_time is not None:
                e = int(time.monotonic() - self.start_time)
                self.time_lbl.setStringValue_(f"⏱ {e // 60:02d}:{e % 60:02d}")
        elif self.stop_event.is_set():
            self.status.setStringValue_("Stopped")
            self.status.setTextColor_(_c(GRAY))
            self.btn.layer().setBackgroundColor_(_c(ORANGE).CGColor())
            self._btn_title("START")
            self.btn.setEnabled_(True)
            self._pulse(False)

    def windowWillClose_(self, notification):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
        NSApp().terminate_(self)


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    FarmController.alloc().init()
    app.activateIgnoringOtherApps_(True)
    app.run()


if __name__ == "__main__":
    main()
