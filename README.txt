Katawa Shoujo Accessibility Mod
================================

Adds full screen reader and TTS support for blind players on the Steam version.
All dialogue, menus, choices, settings, save/load slots, and extras screens are
spoken automatically. No changes to original game files required.


INSTALLATION
------------
Copy ks_accessibility.rpy into:
  C:\Program Files (x86)\Steam\steamapps\common\Katawa Shoujo\game\

Launch the game normally. On first launch you will hear
"Accessibility speech is active." confirming the mod loaded.

To uninstall, delete ks_accessibility.rpy from that folder.


REQUIREMENTS
------------
One of the following:

  NVDA (recommended)
    NVDA must be running. The mod finds the NVDA controller DLL automatically.

  JAWS
    Place Tolk.dll in the game folder.

  Neither
    Falls back to SAPI (Windows built-in voice). No setup needed.


KEYS
----
  V           Toggle speech on/off
  R           Repeat the last spoken line
  Shift+C     Copy the last spoken text to the clipboard


CREDITS
-------
Mod by Shaysters, developed with Claude (Anthropic).
