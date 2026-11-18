# MorseDecode development

Use the regular Git checkout at `C:\Users\c10ha\MorseDecode` on this Windows machine. If that checkout is missing, clone `parsimo2010/MorseDecode` into that path. If the current session cannot access it, tell the user so they can open the checkout with the correct permissions. Use the user's normal Git workflow and verify the working tree and remote before making changes.

- Install Python development dependencies with `python -m pip install -e ".[dev]"` and run `python -m pytest` from the repository root.
- Run the browser decoder regression and performance suite with `node tests/performance.mjs`.
- Preview the browser locally with `python -m http.server 8000 --bind 127.0.0.1 --directory web` and open `http://localhost:8000` in Chrome.
- Keep decoder changes deterministic and preserve the Python CLI's existing entry points.
