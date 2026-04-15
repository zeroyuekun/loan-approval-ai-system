# Demo GIF recording protocol

## Target
20–30 seconds, ≤2 MB, 960×540 or 1280×720, 10 fps.

## Storyboard
| Time | Frame |
|---|---|
| 00:00–00:05 | Terminal: `git clone ... && cp .env.example .env && make demo` (asciinema); fast-cut to browser loading http://localhost:3000 |
| 00:05–00:12 | Customer fills the 5-step application (speed-ramped) and submits |
| 00:12–00:18 | Wait state → decision result screen (approval example with the Neville Zeng fixture) |
| 00:18–00:25 | Cut to officer dashboard: application detail with SHAP waterfall + bias report + model-card link |
| 00:25–00:30 | Cut to `/dashboard/model-card` page and `/rights` page |

## Tools
- **Terminal recording:** `asciinema rec demo.cast`
- **Browser recording:** OBS Studio (or QuickTime on macOS, Game Bar on Windows)
- **Combine:** `ffmpeg -i browser.mp4 -vf "fps=10,scale=1280:-1:flags=lanczos" browser.mp4 && ffmpeg -i browser.mp4 -i terminal.mp4 -filter_complex hstack combined.mp4`
- **GIF export:** `gifski --fps 10 --width 1280 --quality 80 combined.mp4 --output demo.gif`
- **Final check:** `du -h demo.gif` should be ≤2 MB.

## Output

Save the real recording to `docs/media/demo.gif`. Until that lands, the README references `docs/media/demo.svg` (a text-only placeholder).

## Refresh cadence
Refresh when UX changes materially: a new application step, a new decision surface, or a new dashboard section.
