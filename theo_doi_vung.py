# -*- coding: utf-8 -*-
"""Refresh a selected screen region locally; only F8 submits a question."""
import ctypes
import json
from pathlib import Path
import time
import tkinter as tk
from tkinter import messagebox
from PIL import ImageGrab

SETTINGS = Path(__file__).with_name('vung_theo_doi.json')


def enable_dpi_awareness():
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass


class RegionWatchMixin:
    def init_region_watch(self):
        self.watch_enabled = False
        self.watch_region = None
        self.watch_latest = None
        self.watch_captured_at = None
        self.watch_selector = None
        self.watch_timer = None
        self.watch_menu_open = False
        try:
            region = json.loads(SETTINGS.read_text(encoding='utf-8'))['region']
            if (isinstance(region, list) and len(region) == 4
                    and all(type(n) is int for n in region)
                    and region[2] > region[0] and region[3] > region[1]):
                self.watch_region = tuple(region)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        # Require an explicit start each run, avoiding accidental capture on launch.
        self.show('F8: tra vùng đã chọn' if self.watch_region else 'Chuột phải → Khoanh vùng câu hỏi')
        self.watch_timer = self.root.after(500, self.watch_tick)

    def toggle_watch(self):
        if self.watch_enabled:
            self.watch_enabled = False
            self.show('Đã dừng đọc liên tục · F8 vẫn tra được')
        elif self.watch_region is None:
            self.select_region()
        else:
            self.watch_enabled = True
            self.show('Sẵn sàng · F8 để tra')

    def select_region(self):
        if self.watch_selector is not None:
            return
        was_enabled = self.watch_enabled
        self.watch_enabled = False
        window = tk.Toplevel(self.root)
        self.watch_selector = window
        window.overrideredirect(True)
        window.attributes('-topmost', True)
        window.attributes('-alpha', 0.3)
        u = ctypes.windll.user32
        left, top = u.GetSystemMetrics(76), u.GetSystemMetrics(77)
        width, height = u.GetSystemMetrics(78), u.GetSystemMetrics(79)
        window.geometry(f'{width}x{height}{left:+d}{top:+d}')
        canvas = tk.Canvas(window, bg='black', cursor='crosshair', highlightthickness=0)
        canvas.pack(fill='both', expand=True)
        canvas.create_text(30, 30, anchor='nw', fill='white', font=('Arial', 18),
                           text='Kéo chuột khoanh câu hỏi và các lựa chọn. Esc: hủy.')
        origin = []
        rectangle = [None]

        def finish(region=None):
            window.grab_release()
            window.destroy()
            self.watch_selector = None
            if region is None:
                self.watch_enabled = was_enabled
                return
            self.watch_region = region
            self.watch_latest = None
            self.watch_captured_at = None
            try:
                SETTINGS.write_text(json.dumps({'region': region}), encoding='utf-8')
            except OSError:
                messagebox.showwarning('Vùng theo dõi', 'Không lưu được vùng; vẫn dùng được trong phiên này.', parent=self.root)
            self.watch_enabled = True
            self.show('Sẵn sàng · F8 để tra')

        def press(event):
            origin[:] = [event.x, event.y]
            if rectangle[0] is not None:
                canvas.delete(rectangle[0])
            rectangle[0] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline='#00ffff', width=3)

        def move(event):
            if origin:
                canvas.coords(rectangle[0], origin[0], origin[1], event.x, event.y)

        def release(event):
            if not origin:
                return
            x1, x2 = sorted((origin[0], max(0, min(width, event.x))))
            y1, y2 = sorted((origin[1], max(0, min(height, event.y))))
            if x2 - x1 >= 80 and y2 - y1 >= 40:
                finish((x1 + left, y1 + top, x2 + left, y2 + top))

        canvas.bind('<ButtonPress-1>', press)
        canvas.bind('<B1-Motion>', move)
        canvas.bind('<ButtonRelease-1>', release)
        window.bind('<Escape>', lambda event: finish())
        window.grab_set()
        window.focus_force()

    def capture_region(self):
        if self.watch_region is None:
            raise RuntimeError("Hãy khoanh vùng câu hỏi trước.")
        if self.watch_selector is not None:
            raise RuntimeError("Hãy khoanh xong vùng trước khi bấm F8.")
        picture = ImageGrab.grab(bbox=self.watch_region, all_screens=True)
        self.watch_latest = picture
        self.watch_captured_at = time.monotonic()
        return picture.copy()

    def watch_tick(self):
        if self.closing:
            return
        try:
            if (self.watch_enabled and self.watch_region
                    and self.watch_selector is None and not self.watch_menu_open):
                # Local refresh only. Never enqueue, OCR or send from this timer.
                self.capture_region()
        except Exception as error:
            self.watch_enabled = False
            self.show('Đã tạm dừng đọc vùng: ' + str(error))
        finally:
            if not self.closing:
                self.watch_timer = self.root.after(500, self.watch_tick)

    def menu(self):
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label='Tạm dừng đọc vùng' if self.watch_enabled else 'Đọc vùng liên tục (không tự tra)', command=self.toggle_watch)
        menu.add_command(label='Khoanh / chọn lại vùng câu hỏi', command=self.select_region)
        menu.add_separator()
        menu.add_command(label='Tra vùng đang chọn (F8)', command=lambda: self.ask('auto'))
        menu.add_command(label='Tra chữ bôi đen / ảnh clipboard', command=lambda: self.ask('clipboard'))
        menu.add_command(label='Chọn tài liệu', command=self.choose_documents)
        menu.add_command(label='Bỏ tài liệu', command=self.clear_documents)
        menu.add_command(label='Sao chép đáp án', command=lambda: self.root.clipboard_clear() or self.root.clipboard_append(self.answer))
        menu.add_command(label='Dừng tất cả', command=self.stop)
        menu.add_command(label='Ẩn / hiện (F9)', command=self.toggle)
        menu.add_command(label='Thoát', command=self.close)
        self.watch_menu_open = True
        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()
            self.watch_menu_open = False

    def shutdown_region_watch(self):
        self.watch_enabled = False
        if self.watch_timer is not None:
            self.root.after_cancel(self.watch_timer)
        if self.watch_selector is not None:
            self.watch_selector.destroy()
            self.watch_selector = None
