# Changelog

## 1.2.1

- Restored automatic `written_note` reading so in-game notes are spoken again by screen readers.

## 1.2

- Fixed repeated speech on `{nw}` / `extend` dialogue chains by buffering partial lines and only speaking the completed line once.
- Added flush handling before menus, prompts, and label transitions so pending dialogue is not cut off or replayed during scene changes.
- Added an explicit spoken announcement for `scene_deleted` so the Steam build clearly reports when adult scenes are omitted or disabled.
- Audited the Steam scripts and confirmed the repeated Misha school-tour line comes from the accessibility hook interacting with the base game's `extend` flow, not from duplicated script text.
