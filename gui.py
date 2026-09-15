"""A small desktop front end for heic2jpg.

This is a second entry point, not a replacement. All of the conversion logic
lives in heic2jpg.py and is shared with the command line tool, so the two can
never drift apart.

Run it with:

    python gui.py
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import heic2jpg

PAD = 8


class ConverterWindow(ttk.Frame):
    """The whole interface. One window, no dialogs beyond the folder pickers."""

    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=PAD)
        self.master.title(f"heic2jpg {heic2jpg.__version__}")
        self.master.minsize(720, 560)
        self.grid(sticky="nsew")

        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        # Results arrive from a worker thread and are drained on the main
        # thread, because Tk widgets must only be touched from the main thread.
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None

        self._build_folders()
        self._build_naming()
        self._build_output()
        self._build_actions()
        self._build_log()

        self.rowconfigure(4, weight=1)
        self.after(80, self._drain_messages)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_folders(self) -> None:
        box = ttk.LabelFrame(self, text="Folders", padding=PAD)
        box.grid(row=0, column=0, sticky="ew", pady=(0, PAD))
        box.columnconfigure(1, weight=1)

        self.source_var = tk.StringVar(value=str(Path(heic2jpg.DEFAULTS["source"]).resolve()))
        self.target_var = tk.StringVar(value=str(Path(heic2jpg.DEFAULTS["target"]).resolve()))

        for row, (label, var) in enumerate(
            (("Source", self.source_var), ("Target", self.target_var))
        ):
            ttk.Label(box, text=label).grid(row=row, column=0, sticky="w", padx=(0, PAD))
            ttk.Entry(box, textvariable=var).grid(row=row, column=1, sticky="ew")
            ttk.Button(
                box, text="Browse...", command=lambda v=var: self._browse(v)
            ).grid(row=row, column=2, padx=(PAD, 0), pady=2)

        self.recursive_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Include sub-folders", variable=self.recursive_var) \
            .grid(row=2, column=1, sticky="w", pady=(PAD, 0))

    def _build_naming(self) -> None:
        box = ttk.LabelFrame(self, text="Naming", padding=PAD)
        box.grid(row=1, column=0, sticky="ew", pady=(0, PAD))
        box.columnconfigure(1, weight=1)

        self.pattern_var = tk.StringVar(value=heic2jpg.DEFAULTS["pattern"])
        self.prefix_var = tk.StringVar(value="")
        self.suffix_var = tk.StringVar(value="")

        fields = (
            ("Pattern", self.pattern_var),
            ("Prefix", self.prefix_var),
            ("Suffix", self.suffix_var),
        )
        for row, (label, var) in enumerate(fields):
            ttk.Label(box, text=label).grid(row=row, column=0, sticky="w", padx=(0, PAD))
            entry = ttk.Entry(box, textvariable=var)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            var.trace_add("write", lambda *_: self._update_example())

        placeholders = ", ".join("{%s}" % name for name in heic2jpg.PLACEHOLDERS)
        ttk.Label(box, text=f"Placeholders: {placeholders}", foreground="#555") \
            .grid(row=3, column=1, sticky="w", pady=(PAD, 0))

        self.example_var = tk.StringVar()
        ttk.Label(box, textvariable=self.example_var, foreground="#555") \
            .grid(row=4, column=1, sticky="w")

        self.subseconds_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Include fractional seconds in {datetime}",
                        variable=self.subseconds_var,
                        command=self._update_example) \
            .grid(row=5, column=1, sticky="w", pady=(PAD, 0))

        self._update_example()

    def _build_output(self) -> None:
        box = ttk.LabelFrame(self, text="Output", padding=PAD)
        box.grid(row=2, column=0, sticky="ew", pady=(0, PAD))

        self.quality_var = tk.IntVar(value=heic2jpg.DEFAULTS["quality"])
        self.max_size_var = tk.IntVar(value=heic2jpg.DEFAULTS["max_size"])
        self.jobs_var = tk.IntVar(value=heic2jpg.DEFAULTS["jobs"])

        ttk.Label(box, text="JPEG quality").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(box, from_=1, to=95, width=6, textvariable=self.quality_var) \
            .grid(row=0, column=1, sticky="w", padx=(PAD, 24))

        ttk.Label(box, text="Longest edge").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(box, from_=0, to=20000, increment=100, width=8,
                    textvariable=self.max_size_var) \
            .grid(row=0, column=3, sticky="w", padx=(PAD, 4))
        ttk.Label(box, text="px, 0 = original", foreground="#555") \
            .grid(row=0, column=4, sticky="w", padx=(0, 24))

        ttk.Label(box, text="Workers").grid(row=1, column=0, sticky="w", pady=(PAD, 0))
        ttk.Spinbox(box, from_=0, to=64, width=6, textvariable=self.jobs_var) \
            .grid(row=1, column=1, sticky="w", padx=(PAD, 24), pady=(PAD, 0))
        ttk.Label(box, text="1 = serial, 0 = one per CPU core", foreground="#555") \
            .grid(row=1, column=2, columnspan=3, sticky="w", pady=(PAD, 0))

        self.overwrite_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Overwrite files that already exist",
                        variable=self.overwrite_var) \
            .grid(row=2, column=0, columnspan=5, sticky="w", pady=(PAD, 0))

    def _build_actions(self) -> None:
        bar = ttk.Frame(self)
        bar.grid(row=3, column=0, sticky="ew", pady=(0, PAD))
        bar.columnconfigure(2, weight=1)

        self.preview_button = ttk.Button(bar, text="Preview", command=self.preview)
        self.preview_button.grid(row=0, column=0)

        self.start_button = ttk.Button(bar, text="Convert", command=self.start)
        self.start_button.grid(row=0, column=1, padx=(PAD, PAD))

        self.progress = ttk.Progressbar(bar, mode="determinate")
        self.progress.grid(row=0, column=2, sticky="ew")

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(bar, textvariable=self.status_var).grid(row=0, column=3, padx=(PAD, 0))

    def _build_log(self) -> None:
        box = ttk.LabelFrame(self, text="Log", padding=PAD)
        box.grid(row=4, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)

        self.log = tk.Text(box, height=12, wrap="none", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(box, orient="vertical", command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

        self.log.tag_configure("error", foreground="#b00020")
        self.log.tag_configure("muted", foreground="#666")

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------

    def _browse(self, var: tk.StringVar) -> None:
        chosen = filedialog.askdirectory(initialdir=var.get() or ".")
        if chosen:
            var.set(chosen)

    def _update_example(self) -> None:
        """Show what the current naming settings would produce."""
        try:
            name = heic2jpg.build_name(
                datetime(2026, 2, 5, 9, 46, 12), "42", Path("IMG_9774.HEIC"),
                pattern=self.pattern_var.get(),
                prefix=self.prefix_var.get(),
                suffix=self.suffix_var.get(),
                use_subsec=self.subseconds_var.get(),
            )
            self.example_var.set(f"Example: {name}")
        except (KeyError, IndexError, ValueError):
            self.example_var.set("Example: unknown placeholder in the pattern")

    def _write(self, line: str, tag: str | None = None) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.preview_button.configure(state=state)
        self.start_button.configure(state=state)

    def _settings(self) -> dict | None:
        """Collect and validate the current settings, or report why they fail."""
        try:
            quality = int(self.quality_var.get())
            max_size = int(self.max_size_var.get())
            jobs = int(self.jobs_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("Invalid value",
                                 "Quality, longest edge and workers must be numbers.")
            return None

        pattern = self.pattern_var.get()
        problems = heic2jpg.validate_settings(pattern, quality, max_size)
        if problems:
            messagebox.showerror("Invalid settings", "\n\n".join(problems))
            return None

        source = Path(self.source_var.get()).expanduser()
        if not source.is_dir():
            messagebox.showerror("Missing folder", f"Source folder not found:\n{source}")
            return None

        return {
            "source": source,
            "target": Path(self.target_var.get()).expanduser(),
            "recursive": self.recursive_var.get(),
            "jobs": jobs,
            "plan": {
                "pattern": pattern,
                "prefix": self.prefix_var.get(),
                "suffix": self.suffix_var.get(),
                "subseconds": self.subseconds_var.get(),
                "overwrite": self.overwrite_var.get(),
                "quality": quality,
                "max_size": max_size,
            },
        }

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def preview(self) -> None:
        """Plan the conversion and show it, exactly like --dry-run."""
        settings = self._settings()
        if settings is None:
            return

        self._clear_log()
        files = heic2jpg.collect_sources(settings["source"], settings["recursive"])
        if not files:
            self._write("No HEIC or HEIF files found.", "muted")
            return

        jobs, skipped, without_exif = heic2jpg.plan(
            files, settings["target"], **settings["plan"]
        )

        self._write(f"{len(files)} file(s) found. Nothing has been written.", "muted")
        for job in jobs:
            self._write(f"  {job.source.name}  ->  {job.target.name}")
        for entry in skipped:
            tag = "error" if entry.status == "failed" else "muted"
            self._write(f"  {entry.source}  ->  {entry.status}, {entry.detail}", tag)
        if without_exif:
            self._write(f"{len(without_exif)} file(s) have no EXIF capture time, "
                        f"their file date will be used.", "muted")
        self.status_var.set(f"{len(jobs)} to convert")

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        settings = self._settings()
        if settings is None:
            return

        self._clear_log()
        self._busy(True)
        self.status_var.set("Working...")
        self.progress.configure(value=0, maximum=1)

        self.worker = threading.Thread(target=self._convert, args=(settings,), daemon=True)
        self.worker.start()

    def _convert(self, settings: dict) -> None:
        """Runs on a worker thread. Talks to the interface only via the queue."""
        try:
            files = heic2jpg.collect_sources(settings["source"], settings["recursive"])
            if not files:
                self.messages.put(("done", ("No HEIC or HEIF files found.", 0, 0)))
                return

            jobs, skipped, without_exif = heic2jpg.plan(
                files, settings["target"], **settings["plan"]
            )

            self.messages.put(("total", len(jobs)))
            for entry in skipped:
                self.messages.put(("skipped", entry))

            settings["target"].mkdir(parents=True, exist_ok=True)
            workers = heic2jpg.resolve_workers(settings["jobs"])

            results = heic2jpg.run_jobs(
                jobs, workers, on_result=lambda r: self.messages.put(("result", r))
            )

            converted = sum(1 for r in results if r.status == "converted")
            failed = sum(1 for r in results if r.status == "failed")
            summary = (f"Done. {converted} of {len(files)} file(s) written to "
                       f"{settings['target']}")
            if without_exif:
                summary += (f"\n{len(without_exif)} file(s) had no EXIF capture time, "
                            f"their file date was used instead.")
            self.messages.put(("done", (summary, converted, failed)))

        except Exception as error:  # noqa: BLE001 - never kill the thread silently
            self.messages.put(("crash", str(error)))

    def _drain_messages(self) -> None:
        """Move anything the worker produced into the widgets."""
        try:
            while True:
                kind, payload = self.messages.get_nowait()

                if kind == "total":
                    self.progress.configure(value=0, maximum=max(1, payload))

                elif kind == "skipped":
                    tag = "error" if payload.status == "failed" else "muted"
                    self._write(f"  {payload.source}  ->  {payload.status}, "
                                f"{payload.detail}", tag)

                elif kind == "result":
                    self.progress.step(1)
                    if payload.status == "failed":
                        self._write(f"  {payload.source}  ->  FAILED: {payload.detail}",
                                    "error")
                    else:
                        self._write(f"  {payload.source}  ->  {payload.target}")

                elif kind == "done":
                    summary, _converted, failed = payload
                    self._write("")
                    self._write(summary, "error" if failed else None)
                    self.status_var.set("Finished" if not failed else "Finished with errors")
                    self.progress.configure(value=self.progress["maximum"])
                    self._busy(False)

                elif kind == "crash":
                    self._write(f"Unexpected error: {payload}", "error")
                    self.status_var.set("Failed")
                    self._busy(False)

        except queue.Empty:
            pass

        self.after(80, self._drain_messages)


def main() -> None:
    root = tk.Tk()
    try:
        root.call("ttk::style", "theme", "use", "vista")
    except tk.TclError:
        pass  # not on Windows, the default theme is fine
    ConverterWindow(root)
    root.mainloop()


if __name__ == "__main__":
    # Required on Windows: worker processes re-import this module.
    main()
