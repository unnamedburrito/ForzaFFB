# Forza Horizon 6 → FFB Bridge — TODO

## Goal
Read FH6 "Data Out" UDP telemetry (127.0.0.1:2066) and turn the physics data into a
force-feedback signal that can be consumed by vJoy (axes) / Joystick Gremlin, or printed
for debugging. There is **no native FFB field** in Forza telemetry — we *synthesize* force
from slip angles, lateral G, surface rumble, and suspension travel.

## Verified facts (2026-05-28, cross-checked across sources)
- FH6 uses the **Horizon "Car Dash"** wire format: **324 bytes, little-endian**.
- Sled physics block = bytes 0..231, identical across all Forza titles.
- Horizon-specific 12-byte block at 232..243 (CarCategory/Group + 2 unknown dwords).
- Dash block therefore starts at offset **244**.
- Cross-validated offsets: Speed@256 (f32, m/s), Accel@315 (u8), Brake@316 (u8),
  Gear@319 (u8), Steer@320 (s8, -127..127). MOZA-bridge reported input offsets match
  our computed offsets exactly.
- Forza only emits packets while actively driving (not menus/pause/replay); `IsRaceOn`@0.

## Plan
- [x] Confirm FH6 packet format & offsets from authoritative sources
- [x] Scaffold project (tasks/, src/, tests/, tools/)
- [x] `packet.py` — format table as single source of truth; offsets computed (not hand-typed);
      size self-asserts (232/311/324/331); `parse()` with length-based autodetect
- [x] `config.py` — JSON config load/merge over defaults
- [x] `ffb.py` — FFBEngine: physics → normalized effect channels
      (steer_force, road_texture, kerb, understeer, oversteer, g_lat) with smoothing + tunables
- [x] `telemetry.py` — UDP listener yielding parsed packets; stale-packet -> neutral
- [x] `outputs/` — base interface + console backend (cross-platform, testable) + vJoy backend (pyvjoy)
- [x] `bridge.py` + `__main__.py` — wire listen→parse→ffb→output; CLI/config
- [x] `tools/fake_forza_sender.py` — emit synthetic 324B Horizon packets (scenarios) for offline testing
- [x] `tests/` — packet round-trip + offset checks; FFB math (sign/clamp/understeer); UDP loopback integration
- [x] Run tests in WSL (stdlib only, no vJoy needed): 23/23 green
- [x] Live smoke test: bridge process + synthetic sender over UDP — cornering force, understeer
      lightening, direction reversal, kerb spikes (0.395) all confirmed
- [x] README — concept reality, setup (Forza Data Out + vJoy install), usage, tuning, real-FFB-wheel note
- [x] Adversarial review pass (21 agents): 4/17 findings confirmed & fixed:
      - HIGH: format autodetect gap (312-323B -> Sled) -> added FM7 fallback rung
      - HIGH: missing pyproject.toml -> added (pip install -e ., console entry point)
      - MED:  pack() now raises a field-named ValueError instead of bare struct.error
      - LOW:  clarified Steer s8 range comment
- [x] Proactive: NaN/inf hardening so a bad frame can't latch the EMA smoother
- [x] Final: 25/25 tests green; live smoke re-verified (build-up + understeer lightening)

## PHASE 2: Real FFB output for MOZA R3 (user has a MOZA R3 with real FFB)
Key correction surfaced to user: vJoy/Joystick Gremlin are virtual *inputs* and CANNOT drive a
real wheel's motor. Researched MOZA: FH6 supports R3 natively via Pit House Horizon mode; an
official MOZA SDK + SimHub plugin exist. User chose: build a custom SDL/DirectInput backend.
- [x] Verify SDL_Haptic API from SDL_haptic.h (constants, structs, prototypes) + PySDL2 example
- [x] `outputs/ffbwheel.py` — SDL_Haptic constant-force (steer_force) + optional sine rumble
      (road/kerb); lazy pysdl2 import; device select by index/name; autocenter off; clean teardown
- [x] `outputs/base.py` — pure force_to_level / rumble_magnitude (NaN-safe, clamped) for testing
- [x] Factory + config block (output.ffbwheel) + CLI (--backend ffbwheel/moza, --list-devices,
      --device-index/--device-name); deps in requirements.txt + pyproject [ffbwheel] extra
- [x] tests/test_ffbwheel.py — scaling math + lazy-import/factory (no SDL2 needed): 32/32 green
- [x] README — "Real force feedback on a physical wheel (MOZA R3)" incl. one-app-owns-the-wheel
      caveat (turn FH6 in-game FFB off), --list-devices, tuning, augment-vs-replace note
- [x] Adversarial review of ffbwheel.py vs PySDL2 API: verified CORRECT against py-sdl2 source
      (symbols, byref, union/array assignment, NULL checks, New->Run->Update, teardown). Added
      a defensive Uint16 clamp on rumble_period_ms.
- [x] Live: FFB confirmed working on user's MOZA R3 (3.8 Nm).
- [x] Tuning iter 1: force ramped too fast with speed/cornering -> raised lateral_g_ref 11.77->18.0
      and slip_angle_ref 0.16->0.22 (progressive; full torque now ~2g not ~1.3g). Added
      --wheel-gain / --lat-g-ref CLI flags for live tuning; improved autocenter-disable logging.
      Center spring: tool disables DI autocenter + adds no spring; MOZA centering = Pit House 'Spring'.
- [ ] Live verification on user's R3 of the softer ramp; fine-tune gains/feel iteratively

## REPO PREP (for GitHub push)
- [x] Rewrote README to match current script: supported-games matrix (FH4/5/6 + FM7/2023; NOT FH3),
      3 backends, full CLI table (14 flags), full config reference (every key + default), tuning,
      stopping/safety, troubleshooting, packet ref, project layout
- [x] Added .gitignore (py caches, venvs; excludes AGENTS.md + process_whitelist.json tooling artifacts)
- [x] Added LICENSE (MIT, matches pyproject) — holder placeholder <YOUR NAME> to fill in
- [x] Verified config.example.json == DEFAULTS; 32/32 tests green; --show-format offsets match README
- [x] Off-road vibration control: added rumble_gain master multiplier + --rumble-gain/--no-rumble.
- [x] Full CLI coverage: auto-generate a `--section-key` flag for EVERY config leaf (40 flags),
      generated from DEFAULTS so it can't drift; booleans take true/false; short friendly flags
      kept as aliases (take precedence). Documented in README; 39 tests green.
- [ ] User: git init + push to GitHub (replace LICENSE holder first)

## STATUS: core complete & verified on WSL; FFB-wheel backend authored & API-verified,
awaiting on-hardware confirmation of feel with the user.

## Output design decision
Primary backend = **vJoy axes** (matches user's stated tools + prior plan). Computed effect
channels map to configurable vJoy axes (X=steer_force, etc.) for use/remapping in Joystick
Gremlin. Console backend included for verification on any OS. A real-FFB-wheel (DirectInput
constant-force) path is documented in the README as the alternative when motor torque on a
physical wheel is the goal (vJoy is an *input* device, not a haptic output).
