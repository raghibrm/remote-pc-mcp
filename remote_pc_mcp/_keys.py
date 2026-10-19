"""Keyboard input on Windows through SendInput, one batch per call.

pyautogui sends each key event on its own, so input arriving at the same moment
from elsewhere (a remote-desktop host, a virtual gamepad driver) can land
between a Shift press and the letter it was meant to shift. On a real host that
turned "Line 2" into "LINE @", dropped Shift from ")_+{}" and lost whole runs
of text. pyautogui also skips every character outside ASCII without a word.

SendInput takes the whole sequence in one call, and Windows does not interleave
it with other input. Text goes in as KEYEVENTF_UNICODE events, one character at
a time as itself, so no Shift is involved and é, — or an emoji come through.

Building the event list is pure and testable anywhere; only send() touches
Windows.
"""

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_TAB = 0x09
VK_RETURN = 0x0D

# One key event: (virtual-key code, scan code or UTF-16 unit, flags).
Event = tuple[int, int, int]

_NAMED = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12,
    "shiftleft": 0xA0, "shiftright": 0xA1, "ctrlleft": 0xA2, "ctrlright": 0xA3,
    "altleft": 0xA4, "altright": 0xA5,
    "win": 0x5B, "winleft": 0x5B, "winright": 0x5C, "super": 0x5B, "cmd": 0x5B,
    "apps": 0x5D, "menu": 0x5D, "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,
    "printscreen": 0x2C, "prtsc": 0x2C, "prtscr": 0x2C, "pause": 0x13,
    "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF,
    "nexttrack": 0xB0, "prevtrack": 0xB1, "playpause": 0xB3,
    # US-layout punctuation, for combos like ctrl+= or ctrl+/.
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0,
    "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}
_NAMED.update({chr(c): c - 0x20 for c in range(ord("a"), ord("z") + 1)})  # a-z -> 0x41-0x5A
_NAMED.update({str(d): 0x30 + d for d in range(10)})
_NAMED.update({f"f{n}": 0x6F + n for n in range(1, 25)})  # f1 -> 0x70

# Keys that need KEYEVENTF_EXTENDEDKEY, or Windows reads them as their numpad twins
# (shift+up then selects nothing when Num Lock is on).
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E,
             0x5B, 0x5C, 0x5D, 0x6F, 0x90, 0xA3, 0xA5}


def text_events(text: str) -> list[Event]:
    """Events that type text exactly. Newlines press Enter and tabs press Tab,
    because many apps ignore them sent as characters."""
    events: list[Event] = []
    for ch in text.replace("\r\n", "\n"):
        if ch in "\r\n":
            events += [(VK_RETURN, 0, 0), (VK_RETURN, 0, KEYEVENTF_KEYUP)]
        elif ch == "\t":
            events += [(VK_TAB, 0, 0), (VK_TAB, 0, KEYEVENTF_KEYUP)]
        else:
            data = ch.encode("utf-16-le")  # two units (a surrogate pair) above U+FFFF
            for i in range(0, len(data), 2):
                unit = int.from_bytes(data[i:i + 2], "little")
                events += [(0, unit, KEYEVENTF_UNICODE), (0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
    return events


def combo_events(key: str) -> list[Event]:
    """Events for one key or a combo like 'ctrl+shift+s': every key down in
    order, then up in reverse. Raises ValueError for a key it does not know."""
    names = [k.strip().lower() for k in key.split("+")]
    if not names or any(not n for n in names):
        raise ValueError(f"cannot parse key {key!r}")
    vks = []
    for name in names:
        if name not in _NAMED:
            raise ValueError(f"unknown key {name!r} in {key!r}")
        vks.append(_NAMED[name])
    flags = [KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0 for vk in vks]
    downs = [(vk, 0, f) for vk, f in zip(vks, flags)]
    ups = [(vk, 0, f | KEYEVENTF_KEYUP) for vk, f in reversed(list(zip(vks, flags)))]
    return downs + ups


def send(events: list[Event]) -> None:
    """Send events as one SendInput batch. Windows only."""
    import ctypes
    from ctypes import wintypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class MOUSEINPUT(ctypes.Structure):  # only here so the union has the real INPUT size
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    user32 = ctypes.windll.user32
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    user32.MapVirtualKeyW.restype = wintypes.UINT

    INPUT_KEYBOARD, MAPVK_VK_TO_VSC = 1, 0
    batch = (INPUT * len(events))()
    for slot, (vk, scan, flags) in zip(batch, events):
        if not flags & KEYEVENTF_UNICODE:
            scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
        slot.type = INPUT_KEYBOARD
        slot.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    sent = user32.SendInput(len(events), batch, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise OSError(
            f"SendInput inserted {sent} of {len(events)} key events; input was blocked, "
            "for example because the focused window runs as administrator and this server does not"
        )
