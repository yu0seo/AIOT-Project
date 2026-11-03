"""Explicit screen-capture preparation and a cancellable, single-window ROI picker."""

import math


def selection_region(display, scale, start, end):
    """Convert a scaled preview drag to physical desktop coordinates."""
    x1, x2 = sorted((start[0], end[0]))
    y1, y2 = sorted((start[1], end[1]))
    left = max(0, min(display["width"], round(x1 / scale)))
    right = max(0, min(display["width"], round(x2 / scale)))
    top = max(0, min(display["height"], round(y1 / scale)))
    bottom = max(0, min(display["height"], round(y2 / scale)))
    if right <= left or bottom <= top:
        return None
    return {"left": display["left"] + left, "top": display["top"] + top,
            "width": right - left, "height": bottom - top}


class ScreenSelector:
    def __init__(self, capture, display, delay_seconds=3):
        import tkinter as tk
        from tkinter import ttk

        self.capture, self.display = capture, display
        self.delay_seconds = delay_seconds
        self.tk = tk
        self.ttk = ttk
        self.root = tk.Tk()
        self.root.title("Road Eye - CCTV 화면 준비")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.cancel)
        self.root.bind("<Escape>", lambda _: self.cancel())
        self.root.bind("<Return>", lambda _: self.confirm())
        self.root.bind("<r>", lambda _: self.prepare_capture())
        self.result = self.error = None
        self.closed = False
        self.pending_capture = None
        self.scale = 1
        self.start = self.end = self.rectangle = None
        self.canvas = None
        self.status = tk.StringVar(master=self.root, value="아직 화면을 캡처하지 않았습니다.")
        self.content = ttk.Frame(self.root, padding=18)
        self.content.pack(fill="both", expand=True)
        ttk.Label(self.content, text="CCTV 화면을 먼저 준비하세요", font=("맑은 고딕", 15)).pack(anchor="w")
        ttk.Label(self.content, text="브라우저에서 CCTV를 재생하고 창을 원하는 위치에 배치하세요.\n"
                  "아래 버튼을 누르면 이 창이 숨겨지고, 잠시 후 화면을 캡처합니다.\n"
                  "그 사이 CCTV 창을 앞으로 전환하세요.", padding=(0, 12)).pack(anchor="w")
        ttk.Label(self.content, textvariable=self.status).pack(anchor="w", pady=(0, 12))
        self.buttons = ttk.Frame(self.content)
        self.buttons.pack(fill="x")
        self.capture_button = ttk.Button(self.buttons, text=f"{delay_seconds:g}초 후 화면 가져오기",
                                         command=self.prepare_capture)
        self.capture_button.pack(side="left")
        ttk.Button(self.buttons, text="종료", command=self.cancel).pack(side="right")

    def prepare_capture(self):
        if self.closed or self.pending_capture is not None:
            return
        self.capture_button.configure(state="disabled")
        self.root.withdraw()
        self.pending_capture = self.root.after(round(self.delay_seconds * 1000), self.show_preview)

    def show_preview(self):
        from PIL import Image, ImageTk
        self.pending_capture = None
        if self.closed:
            return
        try:
            # This is the first grab, performed only after the user's button and delay.
            shot = self.capture.grab(self.display)
            image = Image.frombytes("RGB", shot.size, shot.rgb)
            max_width = max(200, min(1280, self.root.winfo_screenwidth() - 80))
            max_height = max(150, min(760, self.root.winfo_screenheight() - 280))
            self.scale = min(1, max_width / image.width, max_height / image.height)
            image = image.resize((math.floor(image.width * self.scale), math.floor(image.height * self.scale)))
            self.preview = ImageTk.PhotoImage(image, master=self.root)
            if self.canvas is None:
                self.canvas = self.tk.Canvas(self.content, highlightthickness=0)
                self.canvas.pack(before=self.buttons, pady=(0, 12))
                self.canvas.bind("<ButtonPress-1>", self.drag_start)
                self.canvas.bind("<B1-Motion>", self.drag_move)
                self.canvas.bind("<ButtonRelease-1>", self.drag_move)
                self.confirm_button = self.ttk.Button(
                    self.buttons, text="선택 확정 (Enter)", command=self.confirm)
                self.confirm_button.pack(side="left", padx=10)
            self.canvas.configure(width=image.width, height=image.height)
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, anchor="nw", image=self.preview)
            self.start = self.end = self.rectangle = None
            self.status.set("CCTV 영상 부분을 드래그한 뒤 Enter. 다시 찍기는 R, 종료는 Esc 또는 X.")
            self.root.title("Road Eye - CCTV 영상 영역 선택")
            self.capture_button.configure(state="normal", text=f"다시 가져오기 ({self.delay_seconds:g}초)")
            self.root.deiconify()
            self.root.lift()
            self.canvas.focus_set()
        except Exception as exc:
            self.error = exc
            self.cancel()

    def drag_start(self, event):
        self.start = self.end = (event.x, event.y)
        if self.rectangle is not None:
            self.canvas.delete(self.rectangle)
        self.rectangle = self.canvas.create_rectangle(event.x, event.y, event.x, event.y,
                                                      outline="#00ff99", width=2)

    def drag_move(self, event):
        if self.start is None:
            return
        self.end = (event.x, event.y)
        self.canvas.coords(self.rectangle, *self.start, *self.end)

    def confirm(self):
        if self.closed or self.start is None or self.end is None:
            return
        self.result = selection_region(self.display, self.scale, self.start, self.end)
        if self.result is not None:
            self.cancel()

    def cancel(self):
        if self.closed:
            return
        self.closed = True
        if self.pending_capture is not None:
            self.root.after_cancel(self.pending_capture)
            self.pending_capture = None
        self.root.destroy()

    def run(self):
        self.root.mainloop()
        if self.error:
            raise self.error
        return self.result


def select_screen_region(capture, display, delay_seconds=3):
    return ScreenSelector(capture, display, delay_seconds).run()
