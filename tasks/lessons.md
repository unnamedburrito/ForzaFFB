# Lessons

Format: [date] | what went wrong | rule to prevent it

- [2026-05-28] | Forza titles change packet length between games (Sled 232 / FM7 311 /
  FM2023 331 / Horizon 324). | Never hardcode one layout; detect by length and compute
  every field offset from a single ordered field table so offsets can't drift.
- [2026-05-28] | "FFB data" does not exist in Forza Data Out — it's physics only. | Treat
  the deliverable as FFB *synthesis* from physics, and say so explicitly to the user so
  expectations are correct.
- [2026-05-28] | vJoy is a virtual *input* device, not a haptic output. Feeding a "force"
  to a vJoy axis does not move a wheel motor by itself. | Be explicit about what consumes
  the axis; document the DirectInput constant-force path for real FFB wheels separately.
- [2026-05-28] | This runs on Windows but is developed/tested in WSL where vJoy/DirectInput
  don't exist. | Keep core (parse + FFB math) pure-stdlib and OS-independent; import
  pyvjoy lazily inside the vJoy backend only; provide a console backend so the full
  pipeline is testable in WSL.
- [2026-05-28] | (review) Length-based format autodetect skipped a rung: packets between
  FM7 (311) and Horizon (324) fell through to Sled, silently dropping all dash fields
  (incl. Speed -> FFB would collapse to zero). | Degrade to the LARGEST format that still
  fits: Horizon>=324, FM7>=311, Sled>=232 — never skip an intermediate format.
- [2026-05-28] | (review) src/ layout with no pyproject.toml meant `python -m forza_ffb`
  only worked with a manual PYTHONPATH. | Ship a pyproject.toml (package-dir=src, console
  entry point, optional extras) so `pip install -e .` works on the target machine.
- [2026-05-28] | (proactive) A single NaN/inf physics value would latch forever in the EMA
  smoother (alpha*NaN+(1-alpha)*old = NaN). | Sanitize non-finite values to 0 in _clamp
  (so they can't enter EMA state) and again in the axis scaler. Add a regression test.
- [2026-05-28] | (Phase 2) vJoy / Joystick Gremlin are virtual *input* devices and CANNOT
  drive a real FFB wheel's motor — the original goal's named tools were wrong for real force.
  | When a user names a tool, confirm it can actually do the job before building; correct the
  misconception early. Real wheel torque needs DirectInput/SDL_Haptic or a vendor SDK.
- [2026-05-28] | (Phase 2) Only one app can own a wheel's FFB at a time. | A custom FFB tool
  REPLACES the game's FFB — document that the user must turn the game's own wheel FFB off, and
  offer the "augment via vendor LFE/SDK" alternative for layering effects on top.
- [2026-05-28] | (Phase 2) Could not run pysdl2/hardware in WSL. | Verified the SDL_Haptic API
  from SDL_haptic.h + the py-sdl2 source BEFORE coding (no hallucinated signatures), factored
  the force->level math into pure unit-tested functions, kept pysdl2 import lazy, and had an
  agent adversarially verify the binding usage. Final feel still needs on-hardware tuning.
