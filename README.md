# heic2jpg

Convert HEIC photos to JPEG and rename them by the moment they were taken.

iPhones and many Android phones save photos as HEIC, with a file name like
`IMG_9774.HEIC` that tells you nothing about when the picture was taken. This
tool converts a folder of them to JPEG and, by default, names each result after
its capture time, keeping the original name at the end so every file can be
traced back to its source:

```
IMG_9774.HEIC  ->  2026-02-05 09-46-12-IMG_9774.jpg
```

Files named this way sort chronologically in any file manager. If you prefer a
different layout, the naming is fully configurable.

## What it does

- Reads the capture time from the EXIF `DateTimeOriginal` field, falling back to
  the file modification date and telling you which files needed the fallback.
- Applies the EXIF orientation, so photos taken sideways are not rotated in the
  output.
- Copies the EXIF block into the JPEG and sets the file date to the capture
  time, so the information survives outside the file name.
- Names files from a configurable pattern, with optional prefix and suffix.
- Optionally resizes, to keep the output small without losing detail.
- Skips files that already exist, so re-running it will not create duplicates.
- Runs in parallel when you ask it to.

## Requirements

Python 3.10 or newer, plus two packages:

```
pip install -r requirements.txt
```

On Windows `pillow-heif` installs as a pre-built wheel, so no compiler is
needed.

The desktop window additionally needs Tkinter. It is not a pip package, it
ships with Python itself, and is present in the official Windows and macOS
installers. On Debian or Ubuntu install it separately:

```bash
sudo apt install python3-tk
```

The command line tool does not need Tkinter at all.

## Installation

```bash
git clone https://github.com/christiansmith812/heic2jpg.git
cd heic2jpg

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS and Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Usage

Put your HEIC files in a folder called `source`, then run:

```bash
python heic2jpg.py
```

The JPEGs appear in `target`, which is created if it does not exist.

Other folders:

```bash
python heic2jpg.py --source "C:\Photos\iPhone" --target "C:\Photos\Converted"
```

See what would happen without writing anything:

```bash
python heic2jpg.py --dry-run
```

Use every CPU core, keep the original resolution:

```bash
python heic2jpg.py --jobs 0 --max-size 0
```

## Desktop window

If you would rather not use the command line, run:

```bash
python gui.py
```

The window exposes the same settings, shows an example file name as you type
the pattern, and has a Preview button that lists the planned conversions
without writing anything. Conversion runs on a background thread, so the window
stays responsive, and the progress bar advances as each file finishes.

Nothing in the window is exclusive to it: every setting has a command line
equivalent, and both front ends call the same code.

## Building a standalone executable

This step is optional. The tool runs fine from a Python installation, and
building is only worth it if you need to hand the window to someone who has no
Python at all.

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name heic2jpg gui.py
```

The result lands in `dist/`. Build on the platform you are targeting, because
PyInstaller does not cross-compile: a Windows `.exe` has to be built on
Windows.

Know what you are signing up for before you go down this route:

- The file will be around 60 MB, because Python, Tkinter and the HEIF decoder
  are all bundled in.
- `--onefile` unpacks to a temporary folder at every start, so the first launch
  takes a few seconds. Dropping `--onefile` gives a folder instead of a single
  file, which starts faster but is clumsier to hand over.
- Without a code signing certificate, Windows SmartScreen will warn about the
  unknown publisher, and some antivirus products flag PyInstaller output as
  suspicious. This is a known false positive pattern, and it cannot be resolved
  properly without signing.
- `--windowed` hides the console. Leave it off while you are testing, otherwise
  a crash on startup disappears without a trace.

## Naming

The file name is built from `--pattern`, wrapped in `--prefix` and `--suffix`.
These placeholders are available:

| Placeholder | Example |
| --- | --- |
| `{datetime}` | `2026-02-05 09-46-12` |
| `{date}` | `2026-02-05` |
| `{time}` | `09-46-12` |
| `{subsec}` | `42`, empty when the camera recorded none |
| `{original}` | `IMG_9774` |

The default pattern is `{datetime}-{original}`. Some alternatives:

```bash
--pattern "{original}"                          # IMG_9774.jpg
--pattern "{original}" --prefix "trip_"         # trip_IMG_9774.jpg
--pattern "{original}-{datetime}"               # IMG_9774-2026-02-05 09-46-12.jpg
--pattern "{date}_{original}"                   # 2026-02-05_IMG_9774.jpg
--prefix "batch1-"                              # batch1-2026-02-05 09-46-12-IMG_9774.jpg
```

Characters that are not valid in file names are replaced with an underscore.
If two files would end up with the same name, the later one gets a `_2`
suffix, so nothing is ever silently overwritten. That matters most with
`{original}` alone in recursive mode, where two folders can hold the same file
name. Use `--dry-run` first when you change the pattern.

## Options

Every option has a default, so the tool works with no arguments at all.

| Option | Default | Meaning |
| --- | --- | --- |
| `--source PATH` | `source` | Folder holding the HEIC files. |
| `--target PATH` | `target` | Folder for the JPEGs. Created if missing. |
| `--quality N` | `88` | JPEG quality, 1 to 95. |
| `--max-size N` | `2400` | Longest edge in pixels. `0` keeps the original size. |
| `--pattern TEXT` | `{datetime}-{original}` | Naming pattern. See above. |
| `--prefix TEXT` | empty | Text placed in front of the rendered pattern. |
| `--suffix TEXT` | empty | Text placed after the rendered pattern. |
| `--jobs N` | `1` | Worker processes. `1` runs serially, `0` uses one per CPU core, any other number is taken literally. |
| `--recursive` | off | Also search sub-folders of the source folder. |
| `--overwrite` | off | Replace existing output files instead of skipping them. |
| `--subseconds` | off | Include fractional seconds in the name when the camera recorded them. |
| `--dry-run` | off | Report the planned conversions without writing anything. |

### About `--jobs`

Decoding HEIC is CPU bound, so parallel runs help with large batches. On a
four-core machine, `--jobs 0` cuts the time for several hundred photos to
roughly a quarter. For a handful of files the startup cost of the worker
processes outweighs the gain, which is why serial is the default.

Output names are resolved in the main process before any worker starts, so
parallel runs can never race for the same file name.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Everything succeeded, or there was nothing to do. |
| `1` | The source folder was missing, or at least one file failed to convert. |
| `2` | An option had an invalid value, including an unknown placeholder. |

## Using it from your own code

The conversion logic does not depend on the command line, so it can be driven
from another program, a scheduled job or a graphical front end:

```python
from pathlib import Path
import heic2jpg

source, target = Path("source"), Path("target")

problems = heic2jpg.validate_settings(pattern="{date}_{original}",
                                      quality=88, max_size=2400)
if problems:
    raise SystemExit("\n".join(problems))

files = heic2jpg.collect_sources(source, recursive=False)
jobs, skipped, without_exif = heic2jpg.plan(
    files, target, pattern="{date}_{original}", quality=88, max_size=2400,
)

target.mkdir(parents=True, exist_ok=True)
results = heic2jpg.run_jobs(
    jobs, workers=heic2jpg.resolve_workers(0),
    on_result=lambda result: print(result.source, "->", result.status),
)
```

`on_result` is optional and fires once per finished file, which is how the
desktop window drives its progress bar.

`plan` takes keyword arguments only and fills in the documented defaults for
anything you leave out. It resolves every output name up front, so you can show
the user what would happen before a single file is written, which is exactly
what `--dry-run` does.

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests build their own HEIC fixtures at run time, so the repository carries
no binary sample files.

### Testing against real photos

The generated fixtures are written by the same library that reads them back, so
they cannot show whether the tool copes with what an actual camera produces:
multi-image containers, gain maps, unusual orientations, EXIF written by a
vendor rather than by a test helper.

To cover that, copy a few genuine `.heic` files into `tests/samples/` and run
`pytest` again. The checks in `tests/test_real_samples.py` convert them, confirm
the output is a decodable JPEG with a sortable name, and verify the EXIF block
survives. With that folder empty those tests are skipped, so a clean checkout
still passes.

The folder is ignored by git. Sample photos are deliberately not committed:
they bloat the checkout, and real images carry licensing and privacy questions
of their own. Take them straight off the device rather than through a chat app,
which usually strips EXIF and would leave the interesting path untested.

## Troubleshooting

**PowerShell refuses to run `activate`.** Either use `cmd` instead, or allow
local scripts once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**`pillow-heif` tries to build from source.** That usually means your Python
version is newer or older than the available wheels. Python 3.11 or 3.12 is the
safest choice.

**A file ends up with today's date in its name.** That file had no EXIF capture
time, so the file modification date was used. The summary at the end of the run
lists how many files this affected. Copying photos between devices can strip
EXIF, so prefer exporting originals rather than sending them through a chat app.

**`ModuleNotFoundError: No module named 'tkinter'`.** Only the desktop window
needs Tkinter, and on Linux it is a separate system package: `sudo apt install
python3-tk`. Inside a virtual environment, recreate it after installing the
package, because the environment is linked against the interpreter as it was at
creation time.

**The output looks rotated.** Report it as an issue with the camera model. The
tool applies the EXIF orientation, but some devices write unusual combinations.

## License

MIT. See [LICENSE](LICENSE.txt).
