"""Convert HEIC/HEIF photos to JPEG and rename them by their capture time.

By default the output is named after the moment the photo was taken, with the
original file name appended so every result can be traced back to its source:

    2026-02-05 09-46-12-IMG_9774.jpg

The layout is configurable through --pattern, --prefix and --suffix.

Run ``python heic2jpg.py --help`` for the available options.
"""

from __future__ import annotations

import argparse
import os
import re
import string
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps
import pillow_heif

pillow_heif.register_heif_opener()

__version__ = "1.0.0"

# EXIF tag numbers we care about.
TAG_DATETIME = 0x0132           # DateTime, in the main IFD
TAG_EXIF_IFD = 0x8769           # pointer to the Exif sub-IFD
TAG_DATETIME_ORIGINAL = 0x9003  # when the shutter was released
TAG_DATETIME_DIGITIZED = 0x9004
TAG_SUBSEC_ORIGINAL = 0x9291    # fractional seconds for DateTimeOriginal

SOURCE_SUFFIXES = {".heic", ".heif"}

# Characters that are illegal in Windows file names, plus control characters.
ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

DEFAULTS = {
    "source": "source",
    "target": "target",
    "quality": 88,
    "max_size": 2400,
    "jobs": 1,
    "pattern": "{datetime}-{original}",
}

# Placeholders accepted in --pattern.
PLACEHOLDERS = ("datetime", "date", "time", "subsec", "original")


# --------------------------------------------------------------------------
# Reading capture time
# --------------------------------------------------------------------------

def _parse_exif_datetime(value) -> datetime | None:
    """Parse an EXIF date string such as ``2026:02:05 09:46:12``."""
    if not value:
        return None
    if isinstance(value, bytes):
        value = value.decode("ascii", "ignore")
    text = str(value).strip().strip("\x00").replace("/", ":")
    for pattern in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def read_capture_time(image: Image.Image, path: Path) -> tuple[datetime, str, str]:
    """Return (timestamp, subseconds, source) for one image.

    ``source`` is either ``"exif"`` or ``"mtime"`` so the caller can warn about
    files that had no embedded capture time.
    """
    subsec = ""
    try:
        exif = image.getexif()
    except Exception:
        exif = None

    if exif:
        # DateTimeOriginal lives in the Exif sub-IFD, not in the main one.
        try:
            sub_ifd = exif.get_ifd(TAG_EXIF_IFD)
        except Exception:
            sub_ifd = {}

        candidates = (
            sub_ifd.get(TAG_DATETIME_ORIGINAL),
            sub_ifd.get(TAG_DATETIME_DIGITIZED),
            exif.get(TAG_DATETIME),
        )
        for candidate in candidates:
            parsed = _parse_exif_datetime(candidate)
            if parsed:
                raw_subsec = sub_ifd.get(TAG_SUBSEC_ORIGINAL)
                if isinstance(raw_subsec, bytes):
                    raw_subsec = raw_subsec.decode("ascii", "ignore")
                if raw_subsec:
                    subsec = re.sub(r"\D", "", str(raw_subsec))[:3]
                return parsed, subsec, "exif"

    return datetime.fromtimestamp(path.stat().st_mtime), "", "mtime"


def sanitise(name: str) -> str:
    """Strip characters that are not safe in a file name."""
    cleaned = ILLEGAL_CHARS.sub("_", name).strip().rstrip(".")
    return cleaned or "unnamed"


def validate_pattern(pattern: str) -> list[str]:
    """Return the list of unknown placeholders used in a naming pattern."""
    used = {
        field for _, field, _, _ in string.Formatter().parse(pattern)
        if field is not None
    }
    return sorted(field for field in used if field not in PLACEHOLDERS)


def validate_settings(pattern: str, quality: int, max_size: int) -> list[str]:
    """Return human readable problems with these settings, empty when valid.

    Shared by every front end so the rules are stated in exactly one place.
    """
    problems: list[str] = []
    if not 1 <= quality <= 95:
        problems.append("Quality must be between 1 and 95.")
    if max_size < 0:
        problems.append("Maximum size cannot be negative.")
    if not pattern.strip():
        problems.append("The naming pattern cannot be empty.")
    else:
        unknown = validate_pattern(pattern)
        if unknown:
            available = ", ".join("{%s}" % name for name in PLACEHOLDERS)
            problems.append(
                f"Unknown placeholder(s) in the pattern: {', '.join(unknown)}. "
                f"Available: {available}"
            )
    return problems


def build_name(moment: datetime, subsec: str, original: Path, *,
               pattern: str = DEFAULTS["pattern"], prefix: str = "",
               suffix: str = "", use_subsec: bool = False) -> str:
    """Render one output file name from the naming pattern."""
    date_part = moment.strftime("%Y-%m-%d")
    time_part = moment.strftime("%H-%M-%S")

    stamp = f"{date_part} {time_part}"
    if use_subsec and subsec:
        stamp = f"{stamp}.{subsec}"

    body = pattern.format(
        datetime=stamp,
        date=date_part,
        time=time_part,
        subsec=subsec,
        original=original.stem,
    )
    return f"{sanitise(prefix + body + suffix)}.jpg"


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------

@dataclass
class Job:
    """One file to convert. Kept picklable so it can cross a process boundary."""
    source: Path
    target: Path
    timestamp: float
    quality: int
    max_size: int


@dataclass
class Result:
    source: str
    target: str
    status: str      # "converted", "skipped" or "failed"
    detail: str = ""


def convert_one(job: Job) -> Result:
    """Decode one HEIC file and write it out as JPEG."""
    try:
        with Image.open(job.source) as image:
            exif_bytes = image.info.get("exif")

            # pillow-heif already applies the EXIF orientation when decoding,
            # so this is normally a no-op. It is kept as a safety net in case
            # that behaviour changes or a non-HEIC input is passed in.
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGB")

            if job.max_size and max(image.size) > job.max_size:
                ratio = job.max_size / max(image.size)
                new_size = (round(image.width * ratio), round(image.height * ratio))
                image = image.resize(new_size, Image.LANCZOS)

            save_options = {"quality": job.quality, "optimize": True}
            if exif_bytes:
                save_options["exif"] = exif_bytes

            job.target.parent.mkdir(parents=True, exist_ok=True)
            image.save(job.target, "JPEG", **save_options)

        # Keep the file date in sync with the capture time, so the photo sorts
        # correctly even in tools that ignore EXIF.
        os.utime(job.target, (job.timestamp, job.timestamp))

        return Result(job.source.name, job.target.name, "converted")

    except Exception as error:  # noqa: BLE001 - report, never abort the batch
        return Result(job.source.name, job.target.name, "failed", str(error))


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------

def collect_sources(source: Path, recursive: bool) -> list[Path]:
    walker = source.rglob("*") if recursive else source.iterdir()
    return sorted(
        path for path in walker
        if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES
    )


def plan(files: list[Path], target: Path, *,
         pattern: str = DEFAULTS["pattern"],
         prefix: str = "",
         suffix: str = "",
         subseconds: bool = False,
         overwrite: bool = False,
         quality: int = DEFAULTS["quality"],
         max_size: int = DEFAULTS["max_size"],
         ) -> tuple[list[Job], list[Result], list[str]]:
    """Work out the output name for every file before anything is written.

    Names are resolved here, in a single process, so parallel workers can never
    race for the same output path. The caller passes plain values rather than a
    parsed argument namespace, so the planner can be driven from any front end.
    """
    jobs: list[Job] = []
    skipped: list[Result] = []
    without_exif: list[str] = []
    taken: set[str] = set()

    for path in files:
        try:
            with Image.open(path) as image:
                moment, subsec, origin = read_capture_time(image, path)
        except Exception as error:  # noqa: BLE001
            skipped.append(Result(path.name, "", "failed", str(error)))
            continue

        if origin != "exif":
            without_exif.append(path.name)

        name = build_name(
            moment, subsec, path,
            pattern=pattern,
            prefix=prefix,
            suffix=suffix,
            use_subsec=subseconds,
        )

        # Two different sources could still collide, for example when the same
        # photo appears twice under different names in recursive mode.
        candidate, index = name, 2
        while candidate.lower() in taken:
            candidate = f"{name[:-4]}_{index}.jpg"
            index += 1
        taken.add(candidate.lower())

        destination = target / candidate
        if destination.exists() and not overwrite:
            skipped.append(Result(path.name, candidate, "skipped", "already exists"))
            continue

        jobs.append(Job(path, destination, moment.timestamp(), quality, max_size))

    return jobs, skipped, without_exif


def run_jobs(jobs: list[Job], workers: int,
             on_result: Callable[[Result], None] | None = None) -> list[Result]:
    """Convert every planned job and return the results.

    ``on_result`` is called once per finished file, which lets a front end show
    progress while the batch is still running. It is called from the thread
    that drives this function, never from a worker process.
    """
    if not jobs:
        return []

    results: list[Result] = []

    if workers <= 1:
        for job in jobs:
            result = convert_one(job)
            results.append(result)
            if on_result:
                on_result(result)
        return results

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(convert_one, job) for job in jobs]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if on_result:
                on_result(result)

    return results


def resolve_workers(requested: int) -> int:
    """``0`` means one worker per CPU core, anything else is taken literally."""
    if requested == 0:
        return os.cpu_count() or 1
    return max(1, requested)


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="heic2jpg",
        description="Convert HEIC photos to JPEG and rename them by capture time.",
        epilog="Example: python heic2jpg.py --source photos --jobs 0",
    )
    parser.add_argument("--source", type=Path, default=Path(DEFAULTS["source"]),
                        help="folder holding the HEIC files (default: %(default)s)")
    parser.add_argument("--target", type=Path, default=Path(DEFAULTS["target"]),
                        help="folder for the JPEG files, created if missing "
                             "(default: %(default)s)")
    parser.add_argument("--quality", type=int, default=DEFAULTS["quality"],
                        help="JPEG quality, 1 to 95 (default: %(default)s)")
    parser.add_argument("--max-size", type=int, default=DEFAULTS["max_size"],
                        dest="max_size",
                        help="longest edge in pixels, 0 keeps the original size "
                             "(default: %(default)s)")
    parser.add_argument("--jobs", type=int, default=DEFAULTS["jobs"],
                        help="parallel worker processes: 1 runs serially, "
                             "0 uses one per CPU core (default: %(default)s)")
    parser.add_argument("--pattern", default=DEFAULTS["pattern"],
                        help="naming pattern built from {datetime}, {date}, "
                             "{time}, {subsec} and {original} "
                             "(default: %(default)s)")
    parser.add_argument("--prefix", default="",
                        help="text placed in front of the rendered pattern")
    parser.add_argument("--suffix", default="",
                        help="text placed after the rendered pattern")
    parser.add_argument("--recursive", action="store_true",
                        help="also search sub-folders of the source folder")
    parser.add_argument("--overwrite", action="store_true",
                        help="replace existing files instead of skipping them")
    parser.add_argument("--subseconds", action="store_true",
                        help="include fractional seconds in the file name when "
                             "the camera recorded them")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="show what would happen without writing anything")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    problems = validate_settings(args.pattern, args.quality, args.max_size)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 2

    source: Path = args.source
    target: Path = args.target

    if not source.is_dir():
        print(f"Source folder not found: {source}", file=sys.stderr)
        print("Create it and put the HEIC files inside.", file=sys.stderr)
        return 1

    files = collect_sources(source, args.recursive)
    if not files:
        print(f"No HEIC or HEIF files in {source}")
        return 0

    jobs, skipped, without_exif = plan(
        files, target,
        pattern=args.pattern,
        prefix=args.prefix,
        suffix=args.suffix,
        subseconds=args.subseconds,
        overwrite=args.overwrite,
        quality=args.quality,
        max_size=args.max_size,
    )

    if args.dry_run:
        print(f"Dry run, nothing will be written. {len(files)} file(s) found.\n")
        for job in jobs:
            print(f"  {job.source.name}  ->  {job.target.name}")
        for entry in skipped:
            print(f"  {entry.source}  ->  {entry.status}: {entry.detail}")
        return 0

    if not target.exists():
        target.mkdir(parents=True)
        print(f"Created target folder: {target}")

    workers = resolve_workers(args.jobs)
    if workers > 1:
        print(f"Converting {len(jobs)} file(s) using {workers} workers...\n")
    else:
        print(f"Converting {len(jobs)} file(s)...\n")

    results = run_jobs(jobs, workers) + skipped

    converted = sum(1 for r in results if r.status == "converted")
    failed = [r for r in results if r.status == "failed"]

    for result in sorted(results, key=lambda r: r.target or r.source):
        if result.status == "converted":
            print(f"  {result.source}  ->  {result.target}")
        elif result.status == "skipped":
            print(f"  {result.source}  ->  skipped, {result.detail}")
        else:
            print(f"  {result.source}  ->  FAILED: {result.detail}")

    print(f"\nDone. {converted} of {len(files)} file(s) written to {target}")

    if without_exif:
        print(f"Note: {len(without_exif)} file(s) had no EXIF capture time, "
              f"their file modification date was used instead.")
    if failed:
        print(f"{len(failed)} file(s) failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    # The guard matters on Windows, where each worker re-imports this module.
    sys.exit(main())
