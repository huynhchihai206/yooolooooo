# -*- coding: utf-8 -*-
import ctypes
from ctypes import wintypes
import threading
import tkinter as tk
from tkinter import messagebox

import tro_ly_plus as app

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.RegisterHotKey.argtypes = [
    wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT
]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
user32.GetMessageW.restype = wintypes.BOOL

user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.UINT,
]

user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.PostThreadMessageW.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

KEYS = {
    "ctrl": 0x11,
    "alt": 0x12,
    "q": 0x51,
    "a": 0x41,
    "h": 0x48,
}


def native_is_pressed(key):
    return bool(user32.GetAsyncKeyState(KEYS[key]) & 0x8000)


app.keyboard.is_pressed = native_is_pressed


class FixedOverlay(app.Overlay):
    def __init__(self, root):
        old_add = app.keyboard.add_hotkey
        app.keyboard.add_hotkey = lambda *args, **kwargs: None

        try:
            super().__init__(root)
        finally:
            app.keyboard.add_hotkey = old_add

        self.hotkeys = []
        self.hotkey_thread_id = None
        self.hotkey_stop = threading.Event()
        self.hotkey_ready = threading.Event()

        self.listener = threading.Thread(
            target=self.listen, daemon=True
        )
        self.listener.start()

    def listen(self):
        registered = []

        try:
            self.hotkey_thread_id = kernel32.GetCurrentThreadId()
            message = wintypes.MSG()

            user32.PeekMessageW(
                ctypes.byref(message), None, 0, 0, 0
            )

            bindings = {
                1: (0x51, "auto", "Ctrl+Alt+Q"),
                2: (0x48, "toggle", "Ctrl+Alt+H"),

            }

            for identifier, (key, action, label) in bindings.items():
                success = user32.RegisterHotKey(
                    None,
                    identifier,
                    0x0001 | 0x0002 | 0x4000,
                    key,
                )

                if not success:
                    code = ctypes.get_last_error()
                    raise RuntimeError(
                        f"Không đăng ký được {label} (lỗi {code}). "
                        "Hãy đóng các bản công cụ cũ rồi mở lại."
                    )

                registered.append(identifier)

            self.hotkey_ready.set()

            while not self.hotkey_stop.is_set():
                result = user32.GetMessageW(
                    ctypes.byref(message), None, 0, 0
                )

                if result == 0:
                    break
                if result == -1:
                    raise RuntimeError(
                        "Windows không nhận được sự kiện phím."
                    )

                if message.message == 0x0312:
                    binding = bindings.get(int(message.wParam))
                    if binding:
                        self.events.put(("request", binding[1]))

        except Exception as error:
            self.events.put(("error", str(error)))

        finally:
            for identifier in registered:
                user32.UnregisterHotKey(None, identifier)
            self.hotkey_ready.set()

    def close(self):
        self.hotkey_stop.set()

        if self.hotkey_thread_id:
            user32.PostThreadMessageW(
                self.hotkey_thread_id, 0x0012, 0, 0
            )

        self.listener.join(timeout=0.5)
        super().close()


if __name__ == "__main__":
    root = tk.Tk()

    try:
        tool = FixedOverlay(root)
        root.mainloop()
    except Exception as error:
        messagebox.showerror("Lỗi công cụ", str(error))
        root.destroy()