from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path

from .monitor import close_monitor, load_monitor, monitor_path, sync_monitor_from_root


COLORS = {
    "green": "#1f9d55",
    "yellow": "#c68612",
    "red": "#c2410c",
}


class HulunWidget:
    def __init__(self, monitor_id: str, x: int | None, y: int | None, once: bool = False) -> None:
        self.monitor_id = monitor_id
        self.once = once
        self.root = tk.Tk()
        self.root.title(f"HulunGauge {monitor_id}")
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(True)
        self.root.configure(bg="#171717")
        self.root.geometry(f"220x46+{x if x is not None else 60}+{y if y is not None else 60}")
        try:
            self.root.attributes("-alpha", 0.92)
        except tk.TclError:
            pass

        self.drag_x = 0
        self.drag_y = 0
        self.label = tk.Label(self.root, text="", fg="#f7f7f4", bg="#171717", font=("Segoe UI", 9), anchor="w")
        self.label.place(x=8, y=5, width=206, height=16)
        self.canvas = tk.Canvas(self.root, width=206, height=14, highlightthickness=0, bg="#2a2a2a")
        self.canvas.place(x=8, y=26)
        self.root.bind("<ButtonPress-1>", self.start_drag)
        self.root.bind("<B1-Motion>", self.drag)
        self.root.bind("<Double-Button-1>", self.close)
        self.label.bind("<ButtonPress-1>", self.start_drag)
        self.label.bind("<B1-Motion>", self.drag)
        self.label.bind("<Double-Button-1>", self.close)
        self.canvas.bind("<ButtonPress-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<Double-Button-1>", self.close)

    def start_drag(self, event: tk.Event) -> None:
        self.drag_x = event.x
        self.drag_y = event.y

    def drag(self, event: tk.Event) -> None:
        x = self.root.winfo_x() + event.x - self.drag_x
        y = self.root.winfo_y() + event.y - self.drag_y
        self.root.geometry(f"+{x}+{y}")

    def close(self, _event: tk.Event | None = None) -> None:
        try:
            close_monitor(self.monitor_id)
        except Exception:
            pass
        self.root.destroy()

    def render(self) -> None:
        try:
            sync_monitor_from_root(self.monitor_id)
            data = load_monitor(self.monitor_id)
        except SystemExit:
            self.root.destroy()
            return
        if data.get("status") == "closed" or not monitor_path(self.monitor_id).exists():
            self.root.destroy()
            return
        score = int(data.get("score", 0))
        band = data.get("band", "green")
        color = COLORS.get(band, "#737373")
        name = data.get("conversation", self.monitor_id)
        self.label.configure(text=f"{name}  {score}/100  {band}")
        self.canvas.delete("all")
        self.canvas.create_rectangle(0, 0, 206, 14, fill="#3b3b3b", width=0)
        self.canvas.create_rectangle(0, 0, int(206 * score / 100), 14, fill=color, width=0)
        self.canvas.create_line(72, 0, 72, 14, fill="#f5f5f5")
        self.canvas.create_line(136, 0, 136, 14, fill="#f5f5f5")
        if self.once:
            self.root.after(400, self.root.destroy)
        else:
            self.root.after(1000, self.render)

    def run(self) -> None:
        self.render()
        self.root.mainloop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HulunGauge desktop widget.")
    parser.add_argument("--id", required=True)
    parser.add_argument("--x", type=int)
    parser.add_argument("--y", type=int)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    HulunWidget(args.id, args.x, args.y, once=args.once).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
