# forza_ffb — Forza telemetry → synthesized Force Feedback

Reads a Forza game's **Data Out** UDP telemetry (default `127.0.0.1:2066`), **synthesizes a
force-feedback signal** from the car physics, and sends it to your wheel one of three ways:

- **`ffbwheel`** — **real force feedback** to a physical wheel (MOZA R3 & any DirectInput FFB wheel) via SDL_Haptic;
- **`vjoy`** — the effect channels as **vJoy axes**, for remapping in **Joystick Gremlin** or feeding a DIY device;
- **`console`** — prints the channels for tuning / verification (runs on any OS).

> ### ⚠️ Read this first — what this tool actually does
> **Forza's Data Out stream contains no force-feedback channel.** It carries *physics* —
> slip angles, lateral G, surface rumble, suspension travel, wheel speeds. There is no "FFB"
> value to copy out. This tool **computes** a force signal from that physics (cornering load +
> tyre self-aligning torque, road texture, kerb impacts, understeer lightening) and sends it to
> your wheel. That synthesis is the whole point — the steering force you feel is *this tool's*,
> not the game's own FFB.

---

## Supported games

The bridge works with any Forza title that has the **Data Out** UDP feature:

| Game | Data Out? | Packet format | Works here |
|------|-----------|---------------|------------|
| Forza Horizon 6 | ✅ | Horizon, 324 B | ✅ (primary target) |
| Forza Horizon 5 | ✅ | Horizon, 324 B | ✅ |
| Forza Horizon 4 | ✅ | Horizon, 324 B | ✅ |
| Forza Motorsport (2023) | ✅ | Car Dash, 331 B | ✅ (auto-detected) |
| Forza Motorsport 7 | ✅ | Car Dash, 311 B | ✅ (auto-detected) |
| **Forza Horizon 3 and older** | ❌ | — | ❌ — no Data Out feature exists |

Data Out was introduced in Forza Motorsport 7 (2017); the first *Horizon* title with it is FH4.
**FH3 and earlier emit no telemetry on any port**, so this tool has nothing to read from them.

---

## How it works

```
Forza game        ──UDP packets──▶  TelemetryListener ──▶  FFBEngine ──▶  Output backend
(Data Out, :2066)                    (parse, autodetect)    (physics→force)  ffbwheel / vjoy / console
```

The packet format is detected by length and parsed from a single field table whose offsets are
computed and self-asserted at import (Sled 232 / FM7 311 / Horizon 324 / FM2023 331). Forza only
streams **while you're driving** (not menus/pauses/replays); when packets stop, the wheel relaxes
to neutral after `stale_timeout_s`.

---

## Effect channels

| Channel | Range | Derived from | Feel |
|---------|-------|--------------|------|
| `steer_force` | −1…+1 | lateral G + front slip-angle, speed-gated, reduced on front grip loss | main wheel torque |
| `g_lat` | −1…+1 | `AccelerationX` | cornering G |
| `g_long` | −1…+1 | `AccelerationZ` | accel / brake G |
| `road_texture` | 0…1 | front `SurfaceRumble` | road roughness / fine vibration |
| `kerb` | 0…1 | sudden `SuspensionTravelMeters` deltas + rumble strips | kerb / bump jolts |
| `understeer` | 0…1 | front `TireCombinedSlip` past grip limit | front washing out |
| `oversteer` | 0…1 | rear `TireCombinedSlip` past grip limit | rear sliding / wheelspin |

`ffbwheel` uses `steer_force` for the constant motor torque and `road_texture` + `kerb` for the
sine vibration. `vjoy` maps every channel to an axis (configurable).

---

## Install

Requires **Python 3.8+**. The core (telemetry parse + FFB synthesis) and the **console** backend
and test-suite need **only the standard library**.

```bash
pip install -e .                 # core + console backend
pip install -e .[ffbwheel]       # + real FFB to a physical wheel (pysdl2 + bundled SDL2)
pip install -e .[vjoy]           # + vJoy axis output (Windows + vJoy driver)
```

This registers a `forza_ffb` command and makes `python -m forza_ffb` work from anywhere.
(No install? Run in place with `set PYTHONPATH=src` then `python -m forza_ffb ...`.)

| Backend | Extra needed | Notes |
|---------|--------------|-------|
| `console` | none | any OS |
| `ffbwheel` | `pysdl2` + `pysdl2-dll` | Windows; `pysdl2-dll` bundles SDL2.dll |
| `vjoy` | `pyvjoy` + vJoy driver | Windows; enable a device in *Configure vJoy* |

---

## Quick start

**1. Enable Data Out in the game** — Settings → HUD & Gameplay → **Data Out**:
`Data Out = ON`, `IP = 127.0.0.1` (or the bridge PC's IP), `Port = 2066` (match `--port`).

**2. Confirm data is flowing with the console backend:**
```bat
python -m forza_ffb --backend console --port 2066 -v
```
Drive; you should see live channel values and a centered `steer[--##--]` meter. No game? Replay
synthetic packets from another terminal: `python tools/fake_forza_sender.py --scenario sweep --port 2066`.

**3. Send it to your wheel (e.g. MOZA R3):**
```bat
python -m forza_ffb --list-devices
REM ->  [0] MOZA R3 Racing Wheel  (FFB-capable)
python -m forza_ffb --backend ffbwheel --device-name "MOZA" --port 2066
```

Press **`Ctrl+C`** to stop — the wheel relaxes (force zeroed) and is released on exit.

---

## Output backends

### `ffbwheel` — real force feedback (MOZA R3 & any FFB wheel)
Sends `steer_force` as an SDL_Haptic **constant-force** effect (SDL wraps DirectInput on Windows),
plus an optional **sine** vibration from `road_texture`/`kerb`. Auto-selects a device whose name
contains `device_name_match` (default `"moza"`), else the first FFB-capable device; or pin it with
`--device-index`.

> **⚠️ Only one app can drive the wheel's FFB at a time.** This backend **takes over** the wheel,
> so turn the game's own wheel FFB down/off (in-game FFB = 0, and/or disable FFB in MOZA Pit House
> Horizon-compatibility mode) so they don't fight. The force you feel is then this tool's.
>
> **Centering spring:** this tool adds no spring and disables the DirectInput autocenter. On a
> MOZA the centering is a **Pit House** setting — set `Spring` (and `Damper`/`Friction`/`Inertia`)
> to 0 in Pit House for a clean/raw feel.

### `vjoy` — effect channels as joystick axes
Maps each channel to a vJoy axis (default: X=steer_force, Y=g_long, Z=road_texture, Rx=kerb,
Ry=understeer, Rz=oversteer; remap via `output.vjoy.axis_map`). A vJoy axis is a virtual **input**,
so it does **not** move a wheel motor by itself — use it to feed Joystick Gremlin, SimHub, or a DIY
device that consumes an axis.

### `console` — print channels
Prints 1 of every `output.console.every` updates with an ASCII meter. Runs on any OS; use it to
verify data flow and tune the feel before switching to a wheel.

---

## CLI reference

```
python -m forza_ffb [options]      (or: forza_ffb [options] after install)
```

| Flag | Type | Applies to | Description |
|------|------|------------|-------------|
| `--config PATH` | path | all | JSON config file, deep-merged over the built-in defaults |
| `--ip IP` | str | all | Listen IP (default `127.0.0.1`) |
| `--port PORT` | int | all | Listen UDP port (default `2066`; must match the game's Data Out port) |
| `--backend NAME` | choice | all | `console`, `vjoy`, `ffbwheel` (aliases `wheel`/`moza`/`sdl`), or `null` |
| `--device-id N` | int | vjoy | vJoy device id (default `1`) |
| `--device-index N` | int | ffbwheel | Wheel index from `--list-devices` (`-1` = auto) |
| `--device-name STR` | str | ffbwheel | Match wheel by name substring, e.g. `moza` (default `moza`) |
| `--gain F` | float | ffb | `master_gain` — overall steering-force strength |
| `--wheel-gain F` | float | ffbwheel | `constant_gain` — peak motor torque the wheel reaches (raise if too light) |
| `--lat-g-ref F` | float | ffb | `lateral_g_ref_mps2` — RAISE to soften how fast force builds with cornering/speed |
| `--invert` | flag | ffb | Invert steering-force sign (if the wheel pulls the wrong way) |
| `-v`, `--verbose` | count | all | `-v` = info logging, `-vv` = debug |
| `--show-format` | flag | — | Print the Forza packet formats & key offsets, then exit |
| `--list-devices` | flag | — | List FFB-capable wheels/joysticks SDL can see, then exit |

CLI flags override the config file, which overrides the built-in defaults.

---

## Configuration reference

Copy `config.example.json`, edit, and pass `--config my.json`. Any subset can be supplied; missing
keys fall back to the defaults below (deep-merged).

### `listen`
| Key | Default | Meaning |
|-----|---------|---------|
| `listen.ip` | `"127.0.0.1"` | Interface to bind the UDP listener to |
| `listen.port` | `2066` | UDP port to receive Data Out on |

### `output`
| Key | Default | Meaning |
|-----|---------|---------|
| `output.backend` | `"console"` | `console` / `vjoy` / `ffbwheel` / `null` |
| `output.rate_hz` | `0` | Output rate cap in Hz; `0` = emit once per received packet (~60 Hz) |
| `output.console.every` | `10` | Print 1 of every N updates (console backend) |
| `output.vjoy.device_id` | `1` | vJoy device id |
| `output.vjoy.axis_map` | see below | channel → axis (`X Y Z RX RY RZ SL0 SL1`); omit a channel to skip it |
| `output.ffbwheel.device_index` | `-1` | Wheel index (`-1` = first FFB-capable) |
| `output.ffbwheel.device_name_match` | `"moza"` | Name substring to match (case-insensitive) |
| `output.ffbwheel.constant_gain` | `1.0` | Scales `steer_force` → motor torque (peak strength) |
| `output.ffbwheel.invert` | `false` | Flip force direction at the backend |
| `output.ffbwheel.disable_autocenter` | `true` | Turn off the device's DirectInput autocenter spring |
| `output.ffbwheel.rumble` | `true` | Add a sine vibration from `road_texture` + `kerb` |
| `output.ffbwheel.rumble_road_gain` | `0.6` | Road-texture → rumble magnitude |
| `output.ffbwheel.rumble_kerb_gain` | `1.0` | Kerb → rumble magnitude |
| `output.ffbwheel.rumble_period_ms` | `20` | Sine period (smaller = higher-frequency buzz) |

Default `axis_map`: `steer_force→X, g_long→Y, road_texture→Z, kerb→RX, understeer→RY, oversteer→RZ`.

### `ffb` (force synthesis — shapes the *feel*)
| Key | Default | Meaning |
|-----|---------|---------|
| `ffb.master_gain` | `1.0` | Overall strength of `steer_force` |
| `ffb.invert_steer` | `false` | Flip steering-force sign |
| `ffb.steer_deadzone` | `0.02` | Suppress tiny centre forces (anti-hum) |
| `ffb.weight_lateral` | `0.6` | Contribution of lateral G (cornering load) |
| `ffb.weight_aligning` | `0.4` | Contribution of front slip-angle (self-aligning torque) |
| `ffb.lateral_g_ref_mps2` | `18.0` | Lateral accel mapped to full force; **higher = more progressive / gentler ramp** |
| `ffb.slip_angle_ref_rad` | `0.22` | Front slip angle mapped to full aligning term (≈12.6°) |
| `ffb.speed_ref_mps` | `6.0` | Below this the wheel goes progressively light (parking) |
| `ffb.understeer.threshold` | `1.0` | Front combined-slip where lightening begins |
| `ffb.understeer.limit` | `1.8` | Front combined-slip for full understeer |
| `ffb.understeer.drop` | `0.6` | Fraction of force removed at full understeer |
| `ffb.oversteer.threshold` | `1.0` | Rear combined-slip where oversteer is reported |
| `ffb.oversteer.limit` | `2.0` | Rear combined-slip for full oversteer |
| `ffb.road_gain` | `1.0` | Surface-rumble → `road_texture` |
| `ffb.kerb_gain` | `6.0` | Suspension-compression spikes → `kerb` |
| `ffb.kerb_strip_boost` | `0.4` | Added `kerb` when a wheel is on a rumble strip |
| `ffb.smoothing_alpha` | `0.5` | EMA per channel: `1.0` = none, lower = smoother but laggier |

### top level
| Key | Default | Meaning |
|-----|---------|---------|
| `stale_timeout_s` | `0.5` | If no packet arrives within this many seconds, output neutral (wheel relaxes) |

---

## Tuning the feel

Start with `--backend console`, take a corner, then switch to `ffbwheel`. The knobs that matter
most (all overridable live via CLI without editing files):

- **Wheel gets hard too fast / too heavy in normal corners** → raise `--lat-g-ref` (e.g. `18`→`24`→`30`).
  Higher = more progressive; full torque is reserved for genuinely high-G moments.
- **Too light at the limit** → raise `--wheel-gain` (e.g. `1.3`).
- **Everything too strong/weak** → adjust `--gain` (overall) or your wheel's FFB % in its driver.
- **Pulls the wrong way** → add `--invert`.
- **Jittery / notchy** → lower `ffb.smoothing_alpha` (e.g. `0.3`); **laggy** → raise it toward `1.0`.

The MOZA R3 is a low-torque (≈3.8 Nm) base, so keep Pit House FFB strength near 100% and shape the
*feel* here. Iterate by `Ctrl+C` and relaunching with new flag values.

---

## Stopping / safety

- **Normal stop:** `Ctrl+C` in the bridge terminal — it zeroes the force, stops effects, and
  releases the wheel. Don't just close the terminal window (a hard kill can skip that cleanup).
- **Instant physical stop:** power off the wheelbase.
- **Auto-relax:** leaving a race / pausing stops Forza's telemetry, so the wheel goes neutral within
  `stale_timeout_s` (default 0.5 s).
- **Run with no force:** `--backend console`, or set `output.ffbwheel.constant_gain: 0`.

---

## Testing / development

Pure standard library — runs anywhere (no game/wheel/SDL needed):

```bash
python -m unittest discover -s tests       # parser, FFB math, axis/level scaling, UDP loopback
python -m forza_ffb --show-format          # print packet layouts & key offsets
```

`tools/fake_forza_sender.py` emits real 324-byte Horizon packets for scenarios
`sweep | corner | kerbs | straight | idle`, so the full pipeline is exercisable offline.

---

## Project layout

```
src/forza_ffb/
  packet.py      Forza packet parsing (field table + length autodetect; self-asserting offsets)
  ffb.py         FFBEngine: physics -> normalized effect channels (smoothing, understeer, NaN-safe)
  telemetry.py   UDP listener (stdlib sockets, receive timeout)
  config.py      defaults + JSON deep-merge
  bridge.py      listen -> parse -> synth -> output loop, plus the CLI
  outputs/       base.py (scaling), console.py, vjoy.py, ffbwheel.py (SDL_Haptic); make_output() factory
tools/           fake_forza_sender.py  (synthetic telemetry generator)
tests/           test_packet.py  test_ffb.py  test_ffbwheel.py  test_integration.py
config.example.json   full config you can copy and edit
```

---

## Packet format reference (Horizon / FH4-5-6, 324 B, little-endian)

Bytes 0–231 are the shared "sled"; Horizon titles insert a 12-byte block (232–243), so the dash
section starts at 244. Selected cross-validated offsets:

```
IsRaceOn @0(s32)   AccelerationX @20(f32)   TireSlipAngle FL @164(f32)
TireCombinedSlip FL @180   SurfaceRumble FL @148   SuspensionTravelMeters FL @196
Speed @256(f32, m/s)   Accel @315(u8)   Brake @316(u8)   Gear @319(u8)   Steer @320(s8, -127..127)
```
Run `python -m forza_ffb --show-format` for the full list.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| No data / "telemetry stale" | Data Out off, IP/port mismatch, or you're in a menu/replay (Forza only streams while driving). Confirm with `--backend console` first. |
| `WinError 10013` on start | The UDP port is reserved (Hyper-V/WSL) or in use. Check `netsh int ipv4 show excludedportrange protocol=udp` and `netstat -ano \| findstr :2066`; pick a free port and match it in-game. |
| Wheel doesn't appear in `--list-devices` | Power on the base; make sure it's not in a mode that hides FFB; install `pysdl2 pysdl2-dll`. |
| Force pulls the wrong way | `--invert`. |
| Wheel feels dead / too strong | `--wheel-gain` / `--gain`; check `speed_ref_mps` (no force at standstill is intentional). |
| Heavy too quickly | raise `--lat-g-ref`. |
| Persistent centering spring | Set `Spring`/`Damper` to 0 in MOZA Pit House (it's a driver setting, not this tool). |
| vJoy "failed to set axis" | Enable that axis for the device in *Configure vJoy*. |
| Forza Horizon 3 / older | Not supported — those games have no Data Out telemetry. |

---

## License

MIT — see `LICENSE`.
