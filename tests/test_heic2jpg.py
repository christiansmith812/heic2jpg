"""Tests for heic2jpg.

Fixtures are generated at run time, so the repository does not need to carry
binary sample photos.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import heic2jpg  # noqa: E402

piexif = pytest.importorskip("piexif", reason="piexif is needed to build fixtures")


def make_heic(path: Path, captured: str | None = "2026:02:05 09:46:12",
              orientation: int = 1, size=(1200, 800), subsec: str | None = None):
    """Write a small HEIC file with the requested EXIF metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, (30, 40, 50))

    exif_bytes = None
    if captured or orientation != 1:
        zeroth = {piexif.ImageIFD.Orientation: orientation}
        exif_block = {}
        if captured:
            exif_block[piexif.ExifIFD.DateTimeOriginal] = captured.encode()
        if subsec:
            exif_block[piexif.ExifIFD.SubSecTimeOriginal] = subsec.encode()
        exif_bytes = piexif.dump({"0th": zeroth, "Exif": exif_block})

    image.save(path, format="HEIF", exif=exif_bytes)
    return path


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "source").mkdir()
    return tmp_path


def run(workspace, *extra):
    return heic2jpg.main([
        "--source", str(workspace / "source"),
        "--target", str(workspace / "target"),
        *extra,
    ])


def test_name_uses_capture_time_and_original_name(workspace):
    make_heic(workspace / "source" / "IMG_9774.HEIC")
    assert run(workspace) == 0
    assert (workspace / "target" / "2026-02-05 09-46-12-IMG_9774.jpg").exists()


def test_target_folder_is_created(workspace):
    make_heic(workspace / "source" / "IMG_1.HEIC")
    assert not (workspace / "target").exists()
    run(workspace)
    assert (workspace / "target").is_dir()


def test_falls_back_to_file_date_without_exif(workspace):
    source = make_heic(workspace / "source" / "IMG_2.HEIC", captured=None)
    run(workspace)
    expected = datetime.fromtimestamp(source.stat().st_mtime)
    name = f"{expected:%Y-%m-%d %H-%M-%S}-IMG_2.jpg"
    assert (workspace / "target" / name).exists()


def test_orientation_is_applied(workspace):
    # Orientation 6 means the image is stored rotated by 90 degrees.
    make_heic(workspace / "source" / "IMG_3.HEIC", orientation=6, size=(1200, 800))
    run(workspace, "--max-size", "0")
    output = next((workspace / "target").glob("*.jpg"))
    with Image.open(output) as image:
        assert image.size == (800, 1200)


def test_exif_is_copied_to_the_jpeg(workspace):
    make_heic(workspace / "source" / "IMG_4.HEIC")
    run(workspace)
    output = next((workspace / "target").glob("*.jpg"))
    with Image.open(output) as image:
        sub_ifd = image.getexif().get_ifd(heic2jpg.TAG_EXIF_IFD)
    assert sub_ifd.get(heic2jpg.TAG_DATETIME_ORIGINAL) == "2026:02:05 09:46:12"


def test_file_date_matches_capture_time(workspace):
    make_heic(workspace / "source" / "IMG_5.HEIC")
    run(workspace)
    output = next((workspace / "target").glob("*.jpg"))
    stamp = datetime.fromtimestamp(output.stat().st_mtime)
    assert stamp.replace(microsecond=0) == datetime(2026, 2, 5, 9, 46, 12)


def test_max_size_limits_the_longest_edge(workspace):
    make_heic(workspace / "source" / "IMG_6.HEIC", size=(4000, 3000))
    run(workspace, "--max-size", "1000")
    output = next((workspace / "target").glob("*.jpg"))
    with Image.open(output) as image:
        assert max(image.size) == 1000


def test_existing_files_are_skipped_then_overwritten(workspace):
    make_heic(workspace / "source" / "IMG_7.HEIC")
    run(workspace)
    output = next((workspace / "target").glob("*.jpg"))
    output.write_bytes(b"placeholder")

    run(workspace)
    assert output.read_bytes() == b"placeholder"

    run(workspace, "--overwrite")
    assert output.read_bytes() != b"placeholder"


def test_dry_run_writes_nothing(workspace):
    make_heic(workspace / "source" / "IMG_8.HEIC")
    assert run(workspace, "--dry-run") == 0
    assert not (workspace / "target").exists()


def test_same_second_gets_a_suffix(workspace):
    make_heic(workspace / "source" / "A.HEIC", captured="2026:03:01 08:00:00")
    make_heic(workspace / "source" / "B.HEIC", captured="2026:03:01 08:00:00")
    run(workspace)
    names = sorted(p.name for p in (workspace / "target").glob("*.jpg"))
    assert names == ["2026-03-01 08-00-00-A.jpg", "2026-03-01 08-00-00-B.jpg"]


def test_subseconds_flag(workspace):
    make_heic(workspace / "source" / "IMG_9.HEIC", subsec="42")
    run(workspace, "--subseconds")
    assert (workspace / "target" / "2026-02-05 09-46-12.42-IMG_9.jpg").exists()


def test_recursive_search(workspace):
    make_heic(workspace / "source" / "nested" / "IMG_10.HEIC")
    run(workspace)
    assert not (workspace / "target").exists() or not list((workspace / "target").glob("*.jpg"))
    run(workspace, "--recursive")
    assert list((workspace / "target").glob("*.jpg"))


def test_parallel_matches_serial(workspace):
    for index in range(4):
        make_heic(workspace / "source" / f"IMG_{index}.HEIC",
                  captured=f"2026:04:0{index + 1} 07:00:00")
    run(workspace, "--jobs", "2")
    assert len(list((workspace / "target").glob("*.jpg"))) == 4


def test_resolve_workers():
    assert heic2jpg.resolve_workers(1) == 1
    assert heic2jpg.resolve_workers(3) == 3
    assert heic2jpg.resolve_workers(0) == (os.cpu_count() or 1)


def test_missing_source_folder_returns_error(tmp_path):
    assert heic2jpg.main(["--source", str(tmp_path / "nope"),
                          "--target", str(tmp_path / "out")]) == 1


def test_invalid_quality_is_rejected(workspace):
    assert run(workspace, "--quality", "200") == 2


def test_pattern_can_lead_with_the_original_name(workspace):
    make_heic(workspace / "source" / "IMG_9774.HEIC")
    run(workspace, "--pattern", "{original}")
    assert (workspace / "target" / "IMG_9774.jpg").exists()


def test_prefix_and_suffix(workspace):
    make_heic(workspace / "source" / "IMG_9774.HEIC")
    run(workspace, "--pattern", "{original}", "--prefix", "BP_", "--suffix", "_orig")
    assert (workspace / "target" / "BP_IMG_9774_orig.jpg").exists()


def test_prefix_applies_to_the_default_pattern(workspace):
    make_heic(workspace / "source" / "IMG_9774.HEIC")
    run(workspace, "--prefix", "run1-")
    assert (workspace / "target" / "run1-2026-02-05 09-46-12-IMG_9774.jpg").exists()


def test_date_and_time_placeholders(workspace):
    make_heic(workspace / "source" / "IMG_9774.HEIC")
    run(workspace, "--pattern", "{date}_{time}_{original}")
    assert (workspace / "target" / "2026-02-05_09-46-12_IMG_9774.jpg").exists()


def test_unknown_placeholder_is_rejected(workspace):
    make_heic(workspace / "source" / "IMG_9774.HEIC")
    assert run(workspace, "--pattern", "{nope}") == 2


def test_illegal_characters_are_replaced(workspace):
    make_heic(workspace / "source" / "IMG_9774.HEIC")
    run(workspace, "--pattern", "{original}", "--prefix", "a/b:c")
    assert (workspace / "target" / "a_b_cIMG_9774.jpg").exists()


def test_same_name_from_two_folders_gets_a_suffix(workspace):
    make_heic(workspace / "source" / "one" / "IMG_1.HEIC")
    make_heic(workspace / "source" / "two" / "IMG_1.HEIC")
    run(workspace, "--recursive", "--pattern", "{original}")
    names = sorted(p.name for p in (workspace / "target").glob("*.jpg"))
    assert names == ["IMG_1.jpg", "IMG_1_2.jpg"]


# --------------------------------------------------------------------------
# The planner is callable without argparse, which is what front ends rely on.
# --------------------------------------------------------------------------

def test_plan_can_be_called_directly(workspace):
    make_heic(workspace / "source" / "IMG_9774.HEIC")
    files = heic2jpg.collect_sources(workspace / "source", recursive=False)

    jobs, skipped, missing = heic2jpg.plan(
        files, workspace / "target", pattern="{original}", prefix="x-",
    )

    assert [job.target.name for job in jobs] == ["x-IMG_9774.jpg"]
    assert skipped == [] and missing == []


def test_plan_uses_defaults_for_omitted_settings(workspace):
    make_heic(workspace / "source" / "IMG_9774.HEIC")
    files = heic2jpg.collect_sources(workspace / "source", recursive=False)

    jobs, _, _ = heic2jpg.plan(files, workspace / "target")

    assert jobs[0].target.name == "2026-02-05 09-46-12-IMG_9774.jpg"
    assert jobs[0].quality == heic2jpg.DEFAULTS["quality"]
    assert jobs[0].max_size == heic2jpg.DEFAULTS["max_size"]


def test_plan_rejects_a_positional_settings_object(workspace):
    # Keyword-only arguments stop an argparse namespace being passed by accident.
    files = heic2jpg.collect_sources(workspace / "source", recursive=False)
    with pytest.raises(TypeError):
        heic2jpg.plan(files, workspace / "target", object())


def test_validate_settings_accepts_good_values():
    assert heic2jpg.validate_settings("{datetime}-{original}", 88, 2400) == []


@pytest.mark.parametrize("pattern,quality,max_size", [
    ("{datetime}", 200, 2400),
    ("{datetime}", 88, -1),
    ("", 88, 2400),
    ("{nope}", 88, 2400),
])
def test_validate_settings_reports_problems(pattern, quality, max_size):
    assert heic2jpg.validate_settings(pattern, quality, max_size)


def test_run_jobs_reports_each_result(workspace):
    for index in range(3):
        make_heic(workspace / "source" / f"IMG_{index}.HEIC",
                  captured=f"2026:05:0{index + 1} 06:00:00")
    files = heic2jpg.collect_sources(workspace / "source", recursive=False)
    jobs, _, _ = heic2jpg.plan(files, workspace / "target")
    (workspace / "target").mkdir()

    seen = []
    results = heic2jpg.run_jobs(jobs, workers=1, on_result=seen.append)

    assert len(seen) == len(results) == 3
    assert all(result.status == "converted" for result in seen)
