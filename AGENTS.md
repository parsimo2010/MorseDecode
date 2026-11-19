# MorseDecode development

Use the regular Git checkout at `C:\Users\c10ha\MorseDecode` on this Windows machine. If that checkout is missing, clone `parsimo2010/MorseDecode` into that path. If the current session cannot access it, tell the user so they can open the checkout with the correct permissions. Use the user's normal Git workflow and verify the working tree and remote before making changes.

- Use Node.js 24 for the shared decoder, web build, and terminal integration tests. Install Python development dependencies with `python -m pip install -e ".[dev]"` and run `python -m pytest` from the repository root.
- Keep decoding behavior and defaults in `morse_decode/core/decoder.mjs`. The terminal bridge forwards explicit config overrides. The browser bundles the core through `node web/build.mjs`. Run `node tests/performance.mjs` for regression checks and use [the decoder benchmarks](docs/decoder-benchmarks.md) to compare accuracy and CPU time before shipping a detector change.
- Use the [public recording corpus](benchmarks/cw/README.md) for field regressions. Compare the same labeled WAVs with `python tests/recordings.py --utah --baseline REV`.
- Build the portable HTML and static hosting assets with `node web/build.mjs`. Open `dist/index.html` directly in Chrome to check local-file mode.
- To check installation and offline loading, serve `dist/` with `python -m http.server 8000 --bind 127.0.0.1 --directory dist` and open `http://127.0.0.1:8000/` in Chrome.
- Track unfinished work in GitHub Issues. Link to the issue when the source needs more context.
- Keep decoder changes deterministic and preserve the Python CLI's existing entry points.
