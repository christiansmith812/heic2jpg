"""Optional checks against real camera files.

The main suite builds its own fixtures, which is fast and keeps the repository
free of binaries. Those fixtures are written by the same library that reads
them back, though, so they cannot prove the tool copes with what a real phone
produces: multi-image containers, gain maps, unusual orientations, EXIF written
by a vendor rather than by a test helper.

Drop a few genuine .heic files into tests/samples/ and these tests will run
against them. With an empty folder they are skipped, so a clean checkout still
passes. The folder is ignored by git, so sample photos never end up committed.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import heic2jpg  # noqa: E402

SAMPLES = Path(__file__).parent / "samples"


def sample_files() -> list[Path]:
    if not SAMPLES.is_dir():
        return []
    return sorted(
        path for path in SAMPLES.iterdir()
        if path.is_file() and path.suffix.lower() in heic2jpg.SOURCE_SUFFIXES
    )


pytestmark = pytest.mark.skipif(
    not sample_files(),
    reason=f"no sample files in {SAMPLES}, see the docstring in this file",
)


@pytest.fixture(scope="module")
def converted(tmp_path_factory):
    """Convert every sample once and hand the results to each test."""
    target = tmp_path_factory.mktemp("real")
    files = sample_files()
    jobs, skipped, without_exif = heic2jpg.plan(files, target)
    results = heic2jpg.run_jobs(jobs, workers=1)
    return {
        "target": target,
        "files": files,
        "jobs": jobs,
        "skipped": skipped,
        "without_exif": without_exif,
        "results": results,
    }


def test_every_sample_opens():
    for path in sample_files():
        with Image.open(path) as image:
            assert image.size[0] > 0 and image.size[1] > 0


def test_every_sample_converts(converted):
    failed = [r for r in converted["results"] if r.status == "failed"]
    assert not failed, [f"{r.source}: {r.detail}" for r in failed]
    assert len(list(converted["target"].glob("*.jpg"))) == len(converted["jobs"])


def test_output_is_a_readable_jpeg(converted):
    for output in converted["target"].glob("*.jpg"):
        with Image.open(output) as image:
            assert image.format == "JPEG"
            image.load()  # decodes the pixels, not just the header


def test_names_are_plausible(converted):
    """Whatever the source, the default pattern must produce a sortable name."""
    for job in converted["jobs"]:
        stamp = job.target.name[:19]
        parsed = datetime.strptime(stamp, "%Y-%m-%d %H-%M-%S")
        assert 1990 < parsed.year < 2100


def test_capture_times_come_from_exif(converted):
    """Warn loudly if the samples cannot exercise the EXIF path at all."""
    if len(converted["without_exif"]) == len(converted["files"]):
        pytest.skip("none of the samples carry an EXIF capture time, "
                    "only the file date fallback was exercised")
    assert len(converted["without_exif"]) < len(converted["files"])


def test_exif_survives_when_the_source_had_it(converted):
    for job in converted["jobs"]:
        with Image.open(job.source) as source:
            had_exif = bool(source.info.get("exif"))
        if not had_exif:
            continue
        with Image.open(job.target) as output:
            assert output.info.get("exif"), f"EXIF lost for {job.source.name}"
