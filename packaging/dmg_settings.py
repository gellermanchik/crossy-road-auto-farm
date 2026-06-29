# dmgbuild settings for the Crossy Farm installer DMG.
# Used by package-dmg.sh. Run: dmgbuild -s packaging/dmg_settings.py "Crossy Farm" out.dmg
# Run from the repo root so the relative paths below resolve.
application = "dist/Crossy Farm.app"
appname = "Crossy Farm.app"

format = "UDZO"                       # compressed
files = [application]
symlinks = {"Applications": "/Applications"}
# No custom volume icon on purpose: the installer should look like a standard
# disk image so it's visually distinct from the chicken app icon inside it.

background = "docs/dmg-background.png"  # 1280x800 = @2x of 640x400 (HiDPI)
window_rect = ((200, 120), (640, 400))
default_view = "icon-view"
icon_size = 140
text_size = 13

icon_locations = {
    appname: (160, 185),          # app on the left
    "Applications": (480, 185),   # Applications on the right (drag left -> right)
}
