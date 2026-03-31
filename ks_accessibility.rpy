# ks_accessibility.rpy
# Katawa Shoujo Accessibility Mod
# Adds TTS speech for blind players. Requires no changes to original game files.
# Backends: Tolk (Windows, primary) -> NVDA controller DLL -> SAPI/PowerShell -> say/espeak
# Bootstrap: speech fires at first interaction (main menu) without any key press.
# V = toggle speech. R = repeat last line. Shift+C = copy last spoken text to clipboard.


# ---- Phase 1: set persistent defaults before game scripts ----

init -999 python:
    if not hasattr(persistent, 'ks_tts_enabled') or persistent.ks_tts_enabled is None:
        persistent.ks_tts_enabled = True


# ---- Phase 2: define all functions, resolve backend, register hooks ----

init python:
    import sys
    import os
    import ctypes
    import subprocess
    import traceback
    import re as _ks_re
    import time as _ks_time

    # ---- Debug log ----
    # All events are logged with timestamps and category prefixes.
    # Set _ks_debug = False to suppress verbose interaction/hover/speak entries
    # while keeping errors.

    _ks_log_path = os.path.join(renpy.config.gamedir, "ks_accessibility_debug.log")
    _ks_debug = True  # verbose logging; set False to reduce output

    def ks_log(msg):
        try:
            ts = _ks_time.strftime("%H:%M:%S", _ks_time.localtime())
            with open(_ks_log_path, "a") as _f:
                _f.write("[" + ts + "] " + msg + "\n")
        except:
            pass

    def _ks_dlog(msg):
        """Verbose-only log entry. Suppressed when _ks_debug is False."""
        if _ks_debug:
            ks_log(msg)

    # Write session separator at init time so multiple runs are distinguishable
    ks_log("=" * 60)
    ks_log("SESSION START  " + _ks_time.strftime("%Y-%m-%d %H:%M:%S", _ks_time.localtime()))

    # ---- Strip Ren'Py text tags ----

    def _ks_strip_tags(text):
        if not text:
            return u""
        try:
            return _ks_re.sub(r'\{[^}]*\}', u'', unicode(text)).strip()
        except:
            try:
                return unicode(text).strip()
            except:
                return u""

    # ---- TTS backend: Tolk (Windows, primary) ----

    class _KSTolkBackend(object):
        def __init__(self):
            self._lib = None

        def init(self):
            try:
                search_dirs = [
                    renpy.config.gamedir,
                    os.path.dirname(renpy.config.gamedir),
                    os.getcwd(),
                    r"C:\Program Files (x86)\NVDA",
                    r"C:\Program Files\NVDA",
                    os.path.join(r"C:\Program Files (x86)\NVDA", "lib"),
                    os.path.join(r"C:\Program Files (x86)\NVDA", "lib64"),
                    r"C:\Program Files (x86)\Tolk",
                ]
                dll_path = None
                for d in search_dirs:
                    p = os.path.join(d, "Tolk.dll")
                    if os.path.isfile(p):
                        dll_path = p
                        break
                if dll_path is None:
                    ks_log("Tolk: DLL not found. To use Tolk, place Tolk.dll in: " +
                           renpy.config.gamedir)
                    return False
                ks_log("Tolk: found DLL at " + dll_path)
                lib = ctypes.CDLL(dll_path)
                lib.Tolk_IsLoaded.restype = ctypes.c_bool
                lib.Tolk_HasSpeech.restype = ctypes.c_bool
                lib.Tolk_Speak.argtypes = [ctypes.c_wchar_p, ctypes.c_bool]
                lib.Tolk_Speak.restype = ctypes.c_bool
                try:
                    lib.Tolk_Silence.restype = None
                except:
                    pass
                lib.Tolk_Load()
                if not lib.Tolk_IsLoaded():
                    ks_log("Tolk: Tolk_IsLoaded returned False after load.")
                    lib.Tolk_Unload()
                    return False
                # Do NOT call Tolk_TrySAPI here. If we allow Tolk to claim SAPI
                # it becomes the selected backend and blocks the NVDA controller client
                # from ever being reached. Tolk without TrySAPI will detect JAWS fine
                # (JAWS COM interface works). If it can't detect any screen reader
                # (e.g. NVDA 2025.x which this Tolk version cannot see), HasSpeech
                # returns False and we fall through to the NVDA controller client.
                if not lib.Tolk_HasSpeech():
                    ks_log("Tolk: no screen reader detected (HasSpeech=False). Falling through to NVDA controller.")
                    lib.Tolk_Unload()
                    return False
                # Log which screen reader Tolk selected.
                try:
                    lib.Tolk_GetActiveScreenReader.restype = ctypes.c_wchar_p
                    active_sr = lib.Tolk_GetActiveScreenReader()
                    ks_log("Tolk: active screen reader = " + repr(active_sr))
                except:
                    ks_log("Tolk: could not query active screen reader (non-fatal)")
                ks_log("Tolk: HasSpeech=True, ready.")
                self._lib = lib
                return True
            except:
                ks_log("Tolk init error: " + traceback.format_exc())
                return False

        def speak(self, text, interrupt=True):
            try:
                if interrupt:
                    try:
                        self._lib.Tolk_Silence()
                    except:
                        pass
                self._lib.Tolk_Speak(ctypes.c_wchar_p(text), ctypes.c_bool(False))
            except:
                ks_log("Tolk speak error: " + traceback.format_exc())

    # ---- TTS backend: NVDA controller client DLL (Windows, fallback 1) ----

    class _KSNVDABackend(object):
        def __init__(self):
            self._lib = None

        def init(self):
            try:
                if ctypes.sizeof(ctypes.c_voidp) == 8:
                    dll_name = "nvdaControllerClient64.dll"
                else:
                    dll_name = "nvdaControllerClient32.dll"
                search_dirs = [
                    renpy.config.gamedir,
                    os.path.dirname(renpy.config.gamedir),
                    os.getcwd(),
                    r"C:\Program Files (x86)\NVDA",
                    r"C:\Program Files\NVDA",
                    os.path.join(r"C:\Program Files (x86)\NVDA", "lib"),
                    os.path.join(r"C:\Program Files (x86)\NVDA", "lib64"),
                ]
                dll_path = None
                for d in search_dirs:
                    p = os.path.join(d, dll_name)
                    if os.path.isfile(p):
                        dll_path = p
                        break
                if dll_path is None:
                    ks_log("NVDA controller: DLL (" + dll_name + ") not found in any search path.")
                    return False
                ks_log("NVDA controller: found DLL at " + dll_path)
                lib = ctypes.WinDLL(dll_path)
                lib.nvdaController_testIfRunning.restype = ctypes.c_int
                if lib.nvdaController_testIfRunning() != 0:
                    return False
                lib.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
                lib.nvdaController_speakText.restype = ctypes.c_int
                lib.nvdaController_cancelSpeech.restype = ctypes.c_int
                self._lib = lib
                return True
            except:
                ks_log("NVDA DLL init error: " + traceback.format_exc())
                return False

        def speak(self, text, interrupt=True):
            try:
                if interrupt:
                    try:
                        self._lib.nvdaController_cancelSpeech()
                    except:
                        pass
                self._lib.nvdaController_speakText(ctypes.c_wchar_p(text))
            except:
                ks_log("NVDA DLL speak error: " + traceback.format_exc())

    # ---- TTS backend: SAPI via PowerShell subprocess (Windows, fallback 2) ----

    class _KSSAPIBackend(object):
        def __init__(self):
            self._proc = None
            # CREATE_NO_WINDOW: prevents PowerShell from creating a visible console window.
            # Without this, NVDA announces every spawned window as "terminal" or similar.
            self._NO_WINDOW = 0x08000000

        def init(self):
            try:
                devnull = open(os.devnull, 'w')
                result = subprocess.call(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     "Add-Type -AssemblyName System.Speech"],
                    stdout=devnull, stderr=devnull,
                    creationflags=self._NO_WINDOW
                )
                devnull.close()
                return result == 0
            except:
                ks_log("SAPI init error: " + traceback.format_exc())
                return False

        def speak(self, text, interrupt=True):
            try:
                if interrupt and self._proc is not None:
                    try:
                        self._proc.terminate()
                    except:
                        pass
                    self._proc = None
                # Flatten newlines (would break the single-line PowerShell command),
                # then escape single quotes for the PowerShell string literal.
                safe = text.replace(u"\r\n", u" ").replace(u"\r", u" ").replace(u"\n", u" ")
                safe = safe.replace("'", "''")
                cmd = ("Add-Type -AssemblyName System.Speech; "
                       "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                       "$s.Speak('" + safe + "')")
                devnull = open(os.devnull, 'w')
                self._proc = subprocess.Popen(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                    stdout=devnull, stderr=devnull,
                    creationflags=self._NO_WINDOW
                )
            except:
                ks_log("SAPI speak error: " + traceback.format_exc())

    # ---- TTS backend: say command (macOS) ----

    class _KSSayBackend(object):
        def __init__(self):
            self._proc = None

        def init(self):
            try:
                devnull = open(os.devnull, 'w')
                result = subprocess.call(["which", "say"], stdout=devnull, stderr=devnull)
                devnull.close()
                return result == 0
            except:
                return False

        def speak(self, text, interrupt=True):
            try:
                if interrupt and self._proc is not None:
                    try:
                        self._proc.terminate()
                    except:
                        pass
                    self._proc = None
                devnull = open(os.devnull, 'w')
                self._proc = subprocess.Popen(
                    ["say", text.encode("utf-8")],
                    stdout=devnull, stderr=devnull
                )
            except:
                ks_log("say speak error: " + traceback.format_exc())

    # ---- TTS backend: espeak / spd-say (Linux) ----

    class _KSEspeakBackend(object):
        def __init__(self, cmd):
            self._cmd = cmd
            self._proc = None

        def init(self):
            try:
                devnull = open(os.devnull, 'w')
                result = subprocess.call(["which", self._cmd],
                                         stdout=devnull, stderr=devnull)
                devnull.close()
                return result == 0
            except:
                return False

        def speak(self, text, interrupt=True):
            try:
                if interrupt and self._proc is not None:
                    try:
                        self._proc.terminate()
                    except:
                        pass
                    self._proc = None
                devnull = open(os.devnull, 'w')
                self._proc = subprocess.Popen(
                    [self._cmd, text.encode("utf-8")],
                    stdout=devnull, stderr=devnull
                )
            except:
                ks_log("espeak speak error: " + traceback.format_exc())

    # ---- Module-level state ----

    _ks_backend = None
    _ks_backend_name = u"none"
    _ks_last_spoken = u""        # last spoken text — used by R (repeat) and Shift+C (clipboard)
    _ks_last_dialogue = u""      # last dialogue spoken — used only by extend detection in display_say hook
    _ks_bootstrap_done = False
    _ks_last_focus_spoken = u""

    # ---- Backend resolution ----

    def _ks_resolve_backend():
        global _ks_backend, _ks_backend_name
        platform = sys.platform

        if platform == "win32":
            candidates = [
                (_KSTolkBackend(),    "Tolk"),
                (_KSNVDABackend(),    "NVDA controller"),
                (_KSSAPIBackend(),    "SAPI/PowerShell"),
            ]
            for backend, name in candidates:
                try:
                    if backend.init():
                        _ks_backend = backend
                        _ks_backend_name = name
                        ks_log("TTS backend selected: " + name)
                        return
                except:
                    ks_log("Backend probe failed (" + name + "): " + traceback.format_exc())

        elif platform == "darwin":
            b = _KSSayBackend()
            try:
                if b.init():
                    _ks_backend = b
                    _ks_backend_name = u"say"
                    ks_log("TTS backend selected: say")
                    return
            except:
                ks_log("say backend probe failed: " + traceback.format_exc())

        else:
            for cmd in ["espeak", "spd-say"]:
                b = _KSEspeakBackend(cmd)
                try:
                    if b.init():
                        _ks_backend = b
                        _ks_backend_name = cmd
                        ks_log("TTS backend selected: " + cmd)
                        return
                except:
                    ks_log("espeak backend probe failed (" + cmd + "): " + traceback.format_exc())

        ks_log("TTS: no backend available. Clipboard mode still active via Shift+C.")

    _ks_resolve_backend()

    # ---- Core speech interface ----

    def ks_speak(text, interrupt=True):
        global _ks_last_spoken
        try:
            clean = _ks_strip_tags(text)
            if not clean:
                _ks_dlog("SPEAK-SKIP (empty after strip): " + repr((text or u"")[:60]))
                return
            _ks_last_spoken = clean
            if not persistent.ks_tts_enabled:
                _ks_dlog("SPEAK-MUTED: " + repr(clean[:80]))
                return
            if _ks_backend is not None:
                _ks_dlog("SPEAK [" + ("INTERRUPT" if interrupt else "QUEUE") + "] via " +
                         _ks_backend_name + ": " + repr(clean[:80]))
                _ks_backend.speak(clean, interrupt=interrupt)
            else:
                _ks_dlog("SPEAK-NOBACKEND: " + repr(clean[:80]))
        except:
            ks_log("ERROR ks_speak: " + traceback.format_exc())

    def ks_toggle():
        global _ks_last_spoken
        try:
            persistent.ks_tts_enabled = not persistent.ks_tts_enabled
            if persistent.ks_tts_enabled:
                msg = u"Accessibility speech on."
            else:
                msg = u"Accessibility speech off."
            ks_log("KEY-V: TTS toggled -> " + ("ON" if persistent.ks_tts_enabled else "OFF"))
            _ks_last_spoken = msg
            if _ks_backend is not None:
                _ks_backend.speak(msg, interrupt=True)
        except:
            ks_log("ERROR ks_toggle: " + traceback.format_exc())

    def ks_repeat_last():
        try:
            ks_log("KEY-R: repeat last -> " + repr(_ks_last_spoken[:80] if _ks_last_spoken else u"(empty)"))
            if _ks_last_spoken:
                ks_speak(_ks_last_spoken, interrupt=True)
        except:
            ks_log("ERROR ks_repeat_last: " + traceback.format_exc())

    def ks_copy_to_clipboard():
        try:
            ks_log("KEY-C: clipboard copy -> " + repr(_ks_last_spoken[:80] if _ks_last_spoken else u"(empty)"))
            if not _ks_last_spoken:
                return
            text = _ks_last_spoken
            if sys.platform == "win32":
                _ks_win32_copy(text)
            elif sys.platform == "darwin":
                p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                p.communicate(text.encode("utf-8"))
            else:
                for cmd in [["xclip", "-selection", "clipboard"],
                             ["xsel", "--clipboard", "--input"]]:
                    try:
                        p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                        p.communicate(text.encode("utf-8"))
                        break
                    except:
                        pass
        except:
            ks_log("ks_copy_to_clipboard error: " + traceback.format_exc())

    def _ks_win32_copy(text):
        try:
            text_u = (text + u"\x00").encode("utf-16-le")
            kernel32 = ctypes.windll.kernel32
            user32 = ctypes.windll.user32
            GMEM_MOVEABLE = 0x0002
            CF_UNICODETEXT = 13
            h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(text_u))
            if not h:
                return
            ptr = kernel32.GlobalLock(h)
            ctypes.memmove(ptr, text_u, len(text_u))
            kernel32.GlobalUnlock(h)
            if user32.OpenClipboard(None):
                user32.EmptyClipboard()
                user32.SetClipboardData(CF_UNICODETEXT, h)
                user32.CloseClipboard()
                # SetClipboardData transfers ownership of h to the clipboard;
                # do NOT free it here.
            else:
                # OpenClipboard failed — free h ourselves to avoid a handle leak.
                kernel32.GlobalFree(h)
        except:
            ks_log("clipboard win32 error: " + traceback.format_exc())

    # ---- Key overlay: V toggle, Shift+C clipboard, R repeat ----

    def _ks_overlay_keys():
        try:
            ui.keymap(v=ks_toggle)
            ui.keymap(C=ks_copy_to_clipboard)   # 'C' = Shift+C (ev.unicode == 'C')
            ui.keymap(r=ks_repeat_last)          # 'r' = R without shift (safe: 'R' = reload_game)
        except:
            pass

    config.overlay_functions.append(_ks_overlay_keys)

    # ---- Bootstrap: speak welcome message at first interaction ----

    def _ks_bootstrap_callback():
        global _ks_bootstrap_done
        if _ks_bootstrap_done:
            return
        _ks_bootstrap_done = True
        ks_log("BOOTSTRAP: firing (backend=" + _ks_backend_name + " tts_enabled=" +
               str(persistent.ks_tts_enabled) + ")")
        msg = u"Accessibility speech is active."
        ks_speak(msg, interrupt=True)

    config.start_interact_callbacks.append(_ks_bootstrap_callback)

    # ---- Mode change logging ----

    def _ks_mode_callback(new_mode, old_modes):
        try:
            _ks_dlog("MODE: " + str(new_mode) +
                     " (was: " + (str(old_modes[0]) if old_modes else "none") + ")")
        except:
            pass

    config.mode_callbacks.append(_ks_mode_callback)

    # ---- Dialogue hook: patch renpy.character.display_say ----
    # display_say(who, what, ...) is the universal entry point for all character speech.
    # who is None for narrator (adv/n), a name string for named characters.

    _ks_orig_display_say = renpy.character.display_say

    def _ks_display_say_hook(who, what, *args, **kwargs):
        try:
            who_clean = _ks_strip_tags(who).strip() if who else u""
            what_clean = _ks_strip_tags(what).strip() if what else u""
            # Skip empty lines — they are pause/transition markers, not real dialogue.
            if not what_clean:
                pass
            else:
                # Treat '#' as narrator indicator (NARRATOR_NAME strips to '#').
                # Only prepend speaker name for real named characters.
                if who_clean and who_clean != u"#":
                    speech = who_clean + u": " + what_clean
                else:
                    speech = what_clean
                # Detect {nw}+extend pattern: display_say is called twice —
                # first with the partial text (ending at {nw}), then again with
                # the full extended text that starts with the previous call's text.
                # Speak only the appended portion to avoid re-reading the same prefix.
                # Uses _ks_last_dialogue (not _ks_last_spoken) so that hover/focus
                # events between two display_say calls cannot poison the detection.
                global _ks_last_dialogue
                if _ks_last_dialogue and speech.startswith(_ks_last_dialogue):
                    tail = speech[len(_ks_last_dialogue):].strip()
                    if tail:
                        _ks_dlog("DIALOGUE [extend]: " + repr(tail[:100]))
                        _ks_last_dialogue = speech
                        ks_speak(tail, interrupt=False)
                    # else pure duplicate — skip entirely
                else:
                    _ks_last_dialogue = speech
                    _ks_dlog("DIALOGUE: " + repr(speech[:100]))
                    ks_speak(speech, interrupt=True)
        except:
            ks_log("ERROR dialogue hook: " + traceback.format_exc())
        return _ks_orig_display_say(who, what, *args, **kwargs)

    # Patch both references:
    # - renpy.character.display_say: used by ADVCharacter.do_display (module-level call)
    # - renpy.display_say: used by NVLCharacter.do_display (renpy.display_say import in 00nvl_mode.rpy)
    renpy.character.display_say = _ks_display_say_hook
    renpy.display_say = _ks_display_say_hook


# ---- Phase 3: patch store functions defined by game's init blocks ----
# init 1 runs after game's compiled init code, so store.ingamebutton exists here.

init 1 python:

    # ---- Screen state dump: fires at each ui.interact() start ----
    # Logs the current label, scene name, last spoken text, and recent readback_buffer.
    # This is the "screen mirror" — shows what a blind player last heard.

    def _ks_screen_state_callback():
        try:
            if not _ks_debug:
                return
            ctx = renpy.game.context()
            cur_label = getattr(ctx, 'current', u'?')
            scene = getattr(store, 'save_name', None) or u'(no scene)'
            last = repr(_ks_last_spoken[:60]) if _ks_last_spoken else u'(none)'
            ks_log("--- SCREEN STATE ---")
            ks_log("  label=" + str(cur_label) + "  scene=" + str(scene))
            ks_log("  last_spoken=" + last)
            try:
                buf = list(readback_buffer)
                buf_preview = buf[-3:] if buf else []
                for who, what in buf_preview:
                    who_s = (str(who) + ": ") if who else ""
                    ks_log("  [buf] " + who_s + str(what)[:70])
                if not buf_preview:
                    ks_log("  [buf] (empty)")
            except:
                ks_log("  [buf] (unavailable)")
        except:
            pass

    config.start_interact_callbacks.append(_ks_screen_state_callback)

    # ---- Choice menu announcement: speak all options when menu appears ----
    # custom_menu receives the filtered item list (only selectable choices).
    # We announce all choices upfront because Button.focus(default=True) skips
    # the hovered callback — the first item is focused silently on menu open.

    if hasattr(store, 'custom_menu'):
        _ks_orig_custom_menu = store.custom_menu

        def _ks_custom_menu_patched(items, is_narrator, **kwargs):
            try:
                has_choices = any(val is not None and label for label, val in items)
                if has_choices:
                    ks_log("CHOICE MENU: prompting")
                    ks_speak(u"Make a choice.", interrupt=True)
            except:
                ks_log("ERROR custom_menu announcement: " + traceback.format_exc())
            return _ks_orig_custom_menu(items, is_narrator, **kwargs)

        store.custom_menu = _ks_custom_menu_patched
        ks_log("INIT: custom_menu hook installed.")
    else:
        ks_log("WARNING: store.custom_menu not found. Choice menu announcement disabled.")

    # ---- Choice focus hook: patch ingamebutton to speak on hover ----
    # ingamebutton uses ui.imagebutton(idle, hover, clicked=...) with no hovered= callback.
    # We temporarily replace ui.imagebutton while ingamebutton runs to inject one.
    # Also wraps the clicked callback to log the choice that was made.

    if hasattr(store, 'ingamebutton'):
        _ks_orig_ingamebutton = store.ingamebutton

        def _ks_ingamebutton_patched(text, clicked, previously=None):
            # Wrap clicked to log which choice was selected
            _orig_clicked = clicked
            if _orig_clicked is not None:
                def _logged_click(t=text, c=_orig_clicked):
                    ks_log("CLICK-CHOICE: " + repr(t))
                    return c() if callable(c) else c
                clicked = _logged_click

            _orig_ib = ui.imagebutton

            def _ib_with_hover(*args, **kwargs):
                if 'hovered' not in kwargs:
                    def _on_hover(t=text):
                        global _ks_last_focus_spoken
                        if t != _ks_last_focus_spoken:
                            _ks_last_focus_spoken = t
                            _ks_dlog("HOVER [choice]: " + repr(t))
                            ks_speak(t, interrupt=True)
                    kwargs['hovered'] = _on_hover
                return _orig_ib(*args, **kwargs)

            ui.imagebutton = _ib_with_hover
            try:
                _ks_orig_ingamebutton(text, clicked, previously)
            finally:
                ui.imagebutton = _orig_ib

        store.ingamebutton = _ks_ingamebutton_patched
        ks_log("INIT: ingamebutton hook installed.")
    else:
        ks_log("WARNING: store.ingamebutton not found. Choice focus speech disabled.")

    # ---- layout.button hook: menus, nav sidebar, yes/no dialogs ----
    # layout.button(label, type, hovered=None, ...) is the universal Ren'Py button builder.
    # It covers: game menu navigation sidebar, yes/no prompts, file picker tabs,
    # and (via 'mm' type) the main menu items.
    # layout is renpy.store.layout; its .button method is defined in 00layout.rpy.

    _ks_orig_layout_button = layout.button

    def _ks_layout_button_patched(label, type=None, selected=False, enabled=True,
                                   clicked=None, hovered=None, unhovered=None,
                                   index=None, **properties):
        if enabled:
            # Always inject speech even if game already supplied a hovered callback
            # (main menu items use ss_button which passes hovered=myhovered).
            # Chain: speak first, then call the original hover action if any.
            _orig_hovered = hovered
            def _on_hover(lbl=label, tp=type, oh=_orig_hovered):
                global _ks_last_focus_spoken
                clean = _ks_strip_tags(_(lbl))
                if clean and clean != _ks_last_focus_spoken:
                    _ks_last_focus_spoken = clean
                    _ks_dlog("HOVER [layout.button type=" + str(tp) + "]: " + repr(clean))
                    ks_speak(clean, interrupt=True)
                if oh is not None:
                    try:
                        oh() if callable(oh) else None
                    except:
                        pass
            hovered = _on_hover

        # Wrap clicked to log button presses
        _orig_clicked = clicked
        if _orig_clicked is not None:
            def _logged_click(lbl=label, tp=type, c=_orig_clicked):
                ks_log("CLICK [layout.button type=" + str(tp) + "]: " + repr(str(lbl)))
                return c() if callable(c) else c
            clicked = _logged_click

        return _ks_orig_layout_button(label, type=type, selected=selected,
                                       enabled=enabled, clicked=clicked,
                                       hovered=hovered, unhovered=unhovered,
                                       index=index, **properties)

    layout.button = _ks_layout_button_patched
    ks_log("INIT: layout.button hook installed.")

    # widget_button and custom_render_savefile are defined at init 2 in ui_code.rpy.
    # They are patched in the init 3 python: block below.

    # ---- Label-entry announcements and history trigger ----
    # The game sets config.label_callback = fallthrough_catcher in its init python: block.
    # We wrap it here (init 1, runs after) to intercept known UI labels.

    _ks_game_label_callback = config.label_callback

    _ks_label_announcements = {
        "main_menu":       u"Main menu.",
        "gm_bare":         u"Game menu.",
        "save_screen":     u"Save game.",
        "load_screen":     u"Load game.",
        "prefs_screen":    u"Settings.",
        "text_history":    u"Text history.",
        "language_screen": u"Language selection.",
        "extra_menu":      u"Extras.",
        "scene_select":    u"Scene select.",
        "music_menu":      u"Music room.",
        "cg_gallery":      u"Gallery.",
        "video_menu":      u"Videos.",
        "joystick_screen": u"Gamepad settings.",
    }

    def _ks_label_callback_wrapper(label, not_ft):
        try:
            ks_log("LABEL: " + str(label) + " (not_ft=" + str(not_ft) + ")")
            announcement = _ks_label_announcements.get(label)
            if announcement:
                global _ks_last_focus_spoken
                _ks_last_focus_spoken = u""
                if label == "text_history":
                    # Combine announcement + history entries into one speak call
                    # to avoid two sequential interrupt=True calls stepping on each other.
                    entries = list(readback_buffer)
                    ks_log("HISTORY: buffer has " + str(len(entries)) + " entries at label entry")
                    if not entries:
                        ks_speak(u"Text history. No entries yet.", interrupt=True)
                    else:
                        recent = entries[-3:]
                        parts = []
                        for who, what in recent:
                            who_stripped = _ks_strip_tags(unicode(who)) if who else u""
                            what_stripped = _ks_strip_tags(unicode(what)) if what else u""
                            if who_stripped:
                                parts.append(who_stripped + u": " + what_stripped)
                            else:
                                parts.append(what_stripped)
                        full = (u"Text history. Last " + str(len(recent)) +
                                u" lines: " + u" | ".join(parts))
                        ks_log("HISTORY: speaking -> " + repr(full[:120]))
                        ks_speak(full, interrupt=True)
                else:
                    ks_speak(announcement, interrupt=True)
        except:
            ks_log("ERROR label_callback wrapper: " + traceback.format_exc())
        if _ks_game_label_callback:
            return _ks_game_label_callback(label, not_ft)

    config.label_callback = _ks_label_callback_wrapper
    ks_log("label_callback wrapper installed.")


# ---- Phase 4: patch init-2 functions (widget_button, custom_render_savefile) ----
# widget_button and custom_render_savefile are both defined at init 2 in ui_code.rpy.
# This block runs at init 3, after them.

init 3 python:

    # ---- widget_button hook: preferences screen toggle buttons ----

    _ks_orig_widget_button = store.widget_button

    def _ks_widget_button_patched(text, displayable, clicked=None,
                                  style='prefs_label', xsize=220, ysize=30,
                                  widgetyoffset=3, textxoffset=30,
                                  state="button", xpos=0, ypos=0):
        _orig_ib = ui.imagebutton

        def _ib_with_hover(*args, **kwargs):
            if 'hovered' not in kwargs and clicked is not None:
                def _on_hover(t=text):
                    global _ks_last_focus_spoken
                    clean = _ks_strip_tags(t)
                    if clean and clean != _ks_last_focus_spoken:
                        _ks_last_focus_spoken = clean
                        _ks_dlog("HOVER [widget_button]: " + repr(clean))
                        ks_speak(clean, interrupt=True)
                kwargs['hovered'] = _on_hover
            return _orig_ib(*args, **kwargs)

        ui.imagebutton = _ib_with_hover
        try:
            _ks_orig_widget_button(text, displayable, clicked=clicked,
                                   style=style, xsize=xsize, ysize=ysize,
                                   widgetyoffset=widgetyoffset,
                                   textxoffset=textxoffset,
                                   state=state, xpos=xpos, ypos=ypos)
        finally:
            ui.imagebutton = _orig_ib

    store.widget_button = _ks_widget_button_patched
    ks_log("INIT: widget_button hook installed.")

    # ---- custom_render_savefile hook: save/load slot focus speech ----

    _ks_orig_render_savefile = store.custom_render_savefile

    def _ks_render_savefile_patched(index, name, filename, extra_info,
                                    screenshot, mtime, newest, clickable,
                                    has_delete, **positions):
        _orig_btn = ui.button

        try:
            info_split = extra_info.split("#")
            scene_name = name_from_label(info_split[0])
            if len(info_split) > 1:
                playtime = time_from_seconds(info_split[1])
            else:
                playtime = u""
            slot_label = u"Slot " + unicode(name) + u": " + unicode(scene_name or u"empty")
            if playtime:
                slot_label += u", playtime " + playtime
        except:
            slot_label = unicode(name)

        def _btn_with_hover(*args, **kwargs):
            if 'hovered' not in kwargs and clickable:
                def _on_hover(lbl=slot_label):
                    global _ks_last_focus_spoken
                    if lbl != _ks_last_focus_spoken:
                        _ks_last_focus_spoken = lbl
                        _ks_dlog("HOVER [save_slot]: " + repr(lbl))
                        ks_speak(lbl, interrupt=True)
                kwargs['hovered'] = _on_hover
            return _orig_btn(*args, **kwargs)

        ui.button = _btn_with_hover
        try:
            _ks_orig_render_savefile(index, name, filename, extra_info,
                                     screenshot, mtime, newest, clickable,
                                     has_delete, **positions)
        finally:
            ui.button = _orig_btn

    store.custom_render_savefile = _ks_render_savefile_patched
    ks_log("INIT: custom_render_savefile hook installed.")

    # ---- Slider preference hooks: speak name + value on focus and on change ----
    # customSliderPreference and customVolumePreference both call ui.bar(..., changed=fn).
    # ui.bar accepts hovered= which fires when the bar receives focus.
    # We patch render_preference on both classes to inject hovered= and wrap changed=.

    def _ks_make_bar_hover(name):
        def _on_hover(n=name):
            global _ks_last_focus_spoken
            clean = _ks_strip_tags(unicode(n))
            if clean and clean != _ks_last_focus_spoken:
                _ks_last_focus_spoken = clean
                _ks_dlog("HOVER [slider]: " + repr(clean))
                ks_speak(clean, interrupt=True)
        return _on_hover

    def _ks_make_bar_changed(name, orig_changed, range_val):
        def _on_change(v, n=name, oc=orig_changed, r=range_val):
            try:
                pct = int(round(float(v) / float(r) * 100)) if r else 0
                msg = _ks_strip_tags(unicode(n)) + u" " + unicode(pct) + u"%"
                _ks_dlog("SLIDER CHANGE: " + repr(msg))
                ks_speak(msg, interrupt=True)
            except:
                pass
            if oc:
                oc(v)
        return _on_change

    if hasattr(store, 'customSliderPreference'):
        _ks_orig_slider_render = store.customSliderPreference.render_preference

        def _ks_slider_render(self, thisxpos=0, thisypos=0):
            _orig_bar = ui.bar
            _name = self.name
            _range = self.range

            def _bar_with_hover(*args, **kwargs):
                if 'hovered' not in kwargs:
                    kwargs['hovered'] = _ks_make_bar_hover(_name)
                if 'changed' in kwargs and kwargs['changed'] is not None:
                    kwargs['changed'] = _ks_make_bar_changed(_name, kwargs['changed'], _range)
                elif len(args) >= 1:
                    # positional changed not expected here but guard anyway
                    pass
                return _orig_bar(*args, **kwargs)

            ui.bar = _bar_with_hover
            try:
                _ks_orig_slider_render(self, thisxpos, thisypos)
            finally:
                ui.bar = _orig_bar

        store.customSliderPreference.render_preference = _ks_slider_render
        ks_log("INIT: customSliderPreference hook installed.")
    else:
        ks_log("WARNING: customSliderPreference not found.")

    if hasattr(store, 'customVolumePreference'):
        _ks_orig_volume_render = store.customVolumePreference.render_preference

        def _ks_volume_render(self, thisxpos=0, thisypos=0):
            _orig_bar = ui.bar
            _name = self.name
            _steps = self.steps

            def _bar_with_hover(*args, **kwargs):
                if 'hovered' not in kwargs:
                    kwargs['hovered'] = _ks_make_bar_hover(_name)
                if 'changed' in kwargs and kwargs['changed'] is not None:
                    kwargs['changed'] = _ks_make_bar_changed(_name, kwargs['changed'], _steps)
                return _orig_bar(*args, **kwargs)

            ui.bar = _bar_with_hover
            try:
                _ks_orig_volume_render(self, thisxpos, thisypos)
            finally:
                ui.bar = _orig_bar

        store.customVolumePreference.render_preference = _ks_volume_render
        ks_log("INIT: customVolumePreference hook installed.")
    else:
        ks_log("WARNING: customVolumePreference not found.")

    # ---- extra_button hook: extras menu buttons (Music, Gallery, Scene select, etc.) ----
    # extra_button uses ui.imagebutton directly with no hovered= — same pattern as ingamebutton.

    if hasattr(store, 'extra_button'):
        _ks_orig_extra_button = store.extra_button

        def _ks_extra_button_patched(text, in_displayable, clicked=None,
                                     style='prefs_label', state="button"):
            _orig_ib = ui.imagebutton

            def _ib_with_hover(*args, **kwargs):
                if 'hovered' not in kwargs and clicked is not None:
                    def _on_hover(t=text):
                        global _ks_last_focus_spoken
                        clean = _ks_strip_tags(t)
                        if clean and clean != _ks_last_focus_spoken:
                            _ks_last_focus_spoken = clean
                            _ks_dlog("HOVER [extra_button]: " + repr(clean))
                            ks_speak(clean, interrupt=True)
                    kwargs['hovered'] = _on_hover
                return _orig_ib(*args, **kwargs)

            ui.imagebutton = _ib_with_hover
            try:
                _ks_orig_extra_button(text, in_displayable, clicked=clicked,
                                      style=style, state=state)
            finally:
                ui.imagebutton = _orig_ib

        store.extra_button = _ks_extra_button_patched
        ks_log("INIT: extra_button hook installed.")
    else:
        ks_log("WARNING: store.extra_button not found.")

    # ---- _prompt hook: speak question text for all yes/no and info dialogs ----
    # _prompt(screen, message, ...) is called for confirm_quit, confirm_mm,
    # delete/load save confirmations, and any other modal prompt in the game.
    # The message text is displayed visually but never passed through display_say,
    # so it must be spoken here.

    if hasattr(store, '_prompt'):
        _ks_orig_prompt = store._prompt

        def _ks_prompt_patched(screen, message, image=None, isyesno=False,
                               background=None, transition=None, interact=True):
            try:
                msg_clean = _ks_strip_tags(unicode(message)).strip() if message else u""
                if msg_clean:
                    ks_log("PROMPT: " + repr(msg_clean[:80]))
                    ks_speak(msg_clean, interrupt=True)
            except:
                ks_log("ERROR _prompt hook: " + traceback.format_exc())
            if transition is not None:
                return _ks_orig_prompt(screen, message, image=image, isyesno=isyesno,
                                       background=background, transition=transition,
                                       interact=interact)
            else:
                return _ks_orig_prompt(screen, message, image=image, isyesno=isyesno,
                                       background=background, interact=interact)

        store._prompt = _ks_prompt_patched
        ks_log("INIT: _prompt hook installed.")
    else:
        ks_log("WARNING: store._prompt not found. Confirm dialog questions will be silent.")
