# Sample photos

This folder is empty on purpose, and its contents are ignored by git.

The main test suite builds its own HEIC fixtures at run time, so it never needs
real photos. Those fixtures are written by the same library that reads them
back, though, which means they cannot show whether the tool copes with what an
actual camera produces.

To check that, copy a handful of genuine `.heic` or `.heif` files here, straight
off a phone rather than through a chat app, which tends to strip EXIF. Then run
the tests as usual:

```bash
pytest
```

`tests/test_real_samples.py` will pick them up. With this folder empty those
tests are skipped, so a clean checkout still passes.

Nothing you put here is committed. Do not add photos to the repository itself,
both to keep the checkout small and because sample images usually carry their
own licensing and privacy questions.
