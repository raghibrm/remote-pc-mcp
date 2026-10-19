import pytest

from remote_pc_mcp._keys import (
    KEYEVENTF_EXTENDEDKEY,
    KEYEVENTF_KEYUP,
    KEYEVENTF_UNICODE,
    VK_RETURN,
    combo_events,
    text_events,
)

DOWN, UP = KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP


def test_each_character_is_typed_as_itself_with_no_shift():
    # The characters pyautogui mangled on a real host, typed as themselves.
    events = text_events("L@)_+:")
    assert events == [e for ch in "L@)_+:" for e in ((0, ord(ch), DOWN), (0, ord(ch), UP))]
    assert all(vk == 0 for vk, _, _ in events), "no virtual keys, so no Shift"


def test_non_ascii_comes_through():
    assert text_events("é—") == [(0, 0xE9, DOWN), (0, 0xE9, UP), (0, 0x2014, DOWN), (0, 0x2014, UP)]


def test_emoji_is_sent_as_its_surrogate_pair():
    assert text_events("🙂") == [(0, 0xD83D, DOWN), (0, 0xD83D, UP), (0, 0xDE42, DOWN), (0, 0xDE42, UP)]


def test_newlines_press_enter_once_each():
    assert text_events("a\r\nb\n") == [
        (0, ord("a"), DOWN), (0, ord("a"), UP),
        (VK_RETURN, 0, 0), (VK_RETURN, 0, KEYEVENTF_KEYUP),
        (0, ord("b"), DOWN), (0, ord("b"), UP),
        (VK_RETURN, 0, 0), (VK_RETURN, 0, KEYEVENTF_KEYUP),
    ]


def test_combo_presses_in_order_and_releases_in_reverse():
    assert combo_events("ctrl+shift+s") == [
        (0x11, 0, 0), (0x10, 0, 0), (0x53, 0, 0),
        (0x53, 0, KEYEVENTF_KEYUP), (0x10, 0, KEYEVENTF_KEYUP), (0x11, 0, KEYEVENTF_KEYUP),
    ]


def test_arrows_are_extended_keys():
    # Without the flag Windows reads them as numpad keys, and shift+up selects nothing.
    assert combo_events("shift+up") == [
        (0x10, 0, 0), (0x26, 0, KEYEVENTF_EXTENDEDKEY),
        (0x26, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP), (0x10, 0, KEYEVENTF_KEYUP),
    ]


def test_names_are_case_and_space_insensitive():
    assert combo_events(" Ctrl + C ") == combo_events("ctrl+c")
    assert combo_events("F11") == [(0x7A, 0, 0), (0x7A, 0, KEYEVENTF_KEYUP)]


@pytest.mark.parametrize("bad", ["", "ctrl+", "ctrl+nosuchkey", "hyper+a"])
def test_unknown_or_malformed_keys_are_rejected(bad):
    with pytest.raises(ValueError):
        combo_events(bad)
