# -*- coding: utf-8 -*-
from collections import deque
import ctypes
from ctypes import wintypes
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox

import chay_tool as native
import tro_ly_plus as app
from theo_doi_vung import RegionWatchMixin, enable_dpi_awareness

local_input = threading.local()
original_capture = app.smart_capture


def stored_capture():
    if hasattr(local_input, "payload"):
        return local_input.payload
    return original_capture()


app.smart_capture = stored_capture


def capture_now():
    # Chờ nhả phím trước khi gửi Ctrl+C để ứng dụng nhận đúng tổ hợp.
    release_deadline = time.monotonic() + 1.5
    while native.user32.GetAsyncKeyState(0x77) & 0x8000:
        if time.monotonic() >= release_deadline:
            raise RuntimeError("Hãy nhả F8 rồi thử lại.")
        time.sleep(0.01)

    # Lưu dữ liệu trước khi đưa vào hàng chờ.
    try:
        picture = app.ImageGrab.grabclipboard()
        picture = (
            picture.copy()
            if isinstance(picture, app.Image.Image)
            else None
        )
    except OSError:
        picture = None

    sequence = native.user32.GetClipboardSequenceNumber()
    app.keyboard.send("ctrl+c")
    deadline = time.monotonic() + 1.0

    while time.monotonic() < deadline:
        if native.user32.GetClipboardSequenceNumber() != sequence:
            try:
                text = app.pyperclip.paste().strip()
            except Exception:
                text = ""

            if text:
                if len(text) > 20000:
                    raise RuntimeError("Câu hỏi vượt 20.000 ký tự.")
                return text, None

        time.sleep(0.025)

    # Ảnh chụp có thể tới clipboard sau thời điểm bấm F8.
    try:
        latest_picture = app.ImageGrab.grabclipboard()
        if isinstance(latest_picture, app.Image.Image):
            picture = latest_picture.copy()
    except OSError:
        pass

    if picture is not None:
        return "Trả lời câu hỏi trong ảnh.", picture

    raise RuntimeError(
        "Hãy bôi đen câu hỏi hoặc chụp ảnh trước khi bấm F8."
    )


class QueueOverlay(RegionWatchMixin, native.FixedOverlay):
    def __init__(self, root):
        self.pending = deque()
        self.batch_results = []
        self.batch_count = 0
        self.active_job = None
        self.display_text = ""
        self.last_result = ""
        self.starting = False
        self.closing = False
        super().__init__(root)
        self.init_region_watch()

    def listen(self):
        registered = []

        try:
            self.hotkey_thread_id = native.kernel32.GetCurrentThreadId()
            message = wintypes.MSG()

            native.user32.PeekMessageW(
                ctypes.byref(message), None, 0, 0, 0
            )

            bindings = {
                1: (0x77, "auto", "F8"),
                2: (0x78, "toggle", "F9"),
            }

            for identifier, (key, action, label) in bindings.items():
                success = native.user32.RegisterHotKey(
                    None, identifier, 0x4000, key
                )
                if not success:
                    raise RuntimeError(
                        f"{label} đang bị chiếm hoặc không đăng ký được "
                        f"(lỗi {ctypes.get_last_error()}). "
                        "Hãy đóng công cụ cũ."
                    )
                registered.append(identifier)

            self.hotkey_ready.set()

            while not self.hotkey_stop.is_set():
                result = native.user32.GetMessageW(
                    ctypes.byref(message), None, 0, 0
                )

                if result == 0:
                    break
                if result == -1:
                    raise RuntimeError("Lỗi nhận phím tắt Windows.")

                if message.message == 0x0312:
                    binding = bindings.get(int(message.wParam))
                    if binding:
                        self.events.put(("request", binding[1]))

        except Exception as error:
            self.events.put(("hotkey_error", str(error)))

        finally:
            for identifier in registered:
                native.user32.UnregisterHotKey(None, identifier)
            self.hotkey_ready.set()

    def show(self, text):
        self.display_text = text
        self.render()

    def render(self):
        lines = []
        for number, answer in self.batch_results:
            lines.append(f"{number}: {answer}" if self.batch_count > 1 else answer)
        if self.display_text:
            lines.append(self.display_text)
        text = "\n".join(lines)

        if self.pending:
            text += f"\n({len(self.pending)}) chờ"

        super().show(text)

    def ask(self, mode="auto"):
        if self.closing:
            return

        try:
            if mode != "clipboard" and self.watch_selector is not None:
                return
            if mode != "clipboard" and self.watch_region is not None:
                # Capture at the explicit request, never use a stale buffered frame.
                picture = self.capture_region()
                question = "Trả lời câu hỏi trong vùng ảnh. Giữ nguyên ngôn ngữ đáp án."
            else:
                question, picture = capture_now()
        except Exception as error:
            messagebox.showerror(
                "Chưa nhận được câu hỏi",
                str(error),
                parent=self.root,
            )
            return

        self.enqueue_capture(question, picture)

    def enqueue_capture(self, question, picture):
        if self.closing:
            return
        # Một đợt mới bắt đầu khi không còn câu đang xử lý hoặc chờ.
        if not self.busy and not self.pending:
            self.batch_results.clear()
            self.batch_count = 0
        self.batch_count += 1
        self.pending.append(
            (question, picture, self.documents, self.batch_count)
        )

        self.start_next()
        self.render()
        

    def start_next(self):
        if self.closing or self.busy or not self.pending:
            return

        self.active_job = self.pending.popleft()
        current_documents = self.documents
        self.documents = self.active_job[2]
        self.starting = True

        try:
            super().ask("auto")
        finally:
            self.documents = current_documents
            self.starting = False

    def launch(self, task):
        if self.busy:
            return

        self.busy = True
        self.cancelled.clear()
        captured = self.active_job

        def work():
            try:
                if captured is not None:
                    local_input.payload = captured[:2]

                self.events.put(("done", task()))

            except Exception as error:
                self.events.put(("error", str(error)))

            finally:
                if hasattr(local_input, "payload"):
                    del local_input.payload

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        if self.closing:
            return

        try:
            for _ in range(30):
                kind, data = self.events.get_nowait()

                if kind == "request":
                    if data == "toggle":
                        self.toggle()
                    else:
                        self.ask()

                elif kind == "hotkey_error":
                    messagebox.showerror(
                        "Phím tắt", data, parent=self.root
                    )

                elif kind == "done":
                    self.busy = False
                    finished_job = self.active_job
                    self.active_job = None
                    result_type, value = data

                    if result_type == "documents":
                        self.documents = value
                        self.show("Đã nạp tài liệu.")
                    else:
                        self.last_result = value
                        if finished_job is not None:
                            self.batch_results.append((finished_job[3], value))
                            self.show("")
                        else:
                            self.show(value)

                    self.start_next()

                elif kind == "error":
                    self.busy = False
                    finished_job = self.active_job
                    self.active_job = None
                    self.last_result = "Lỗi: " + data
                    if finished_job is not None:
                        self.batch_results.append((finished_job[3], self.last_result))
                        self.show("")
                    else:
                        self.show(self.last_result)
                    self.start_next()

        except queue.Empty:
            pass

        self.root.after(60, self.poll)

    def stop(self):
        self.watch_enabled = False
        # Menu Dừng hủy lượt hiện tại và xóa hàng chờ.
        self.pending.clear()
        self.render()
        super().stop()

    def close(self):
        self.shutdown_region_watch()
        self.closing = True
        super().close()


if __name__ == "__main__":
    enable_dpi_awareness()
    root = tk.Tk()

    try:
        tool = QueueOverlay(root)
        root.mainloop()
    except Exception as error:
        messagebox.showerror("Lỗi công cụ", str(error))
        root.destroy()