# PX4 + RealFlight SITL

[![Checks](https://github.com/isso11/PX4-SITL-RealFlight/actions/workflows/checks.yml/badge.svg)](https://github.com/isso11/PX4-SITL-RealFlight/actions/workflows/checks.yml)

Run **PX4 fixed-wing SITL, RealFlight Evolution and QGroundControl on one
Windows PC**.

PX4 and the FlightAxis bridge run in Ubuntu/WSL2. RealFlight and QGroundControl
stay on Windows. You do not need to work in Linux during normal use.

## What you need

- Windows 10 or 11 with hardware virtualization enabled
- [QGroundControl for Windows](https://docs.qgroundcontrol.com/Stable_V5.1/en/qgc-user-guide/getting_started/download_and_install.html)
- Steam and a licensed copy of RealFlight Evolution
- Internet access and enough free disk space for PX4 and its build tools

Windows Python is not required for normal setup or use.

## First-time setup

1. **Download the project.**

   Use [Download ZIP](https://github.com/isso11/PX4-SITL-RealFlight/archive/refs/heads/main.zip)
   or clone the repository. Extract it to a permanent folder and do not move the
   folder after installing WSL into it.

2. **Configure the Windows paths.**

   Double-click **0-Configure.cmd**. A local `settings.json` file opens in
   Notepad. Check the QGroundControl, Steam and RealFlight paths, then save it.

   Use `"AircraftProfile": "AeroScoutAPM"` only with the built-in HobbyZone
   AeroScout APM profile. Use `"generic"` for other aircraft.

3. **Install Ubuntu/WSL2 if it is not already installed.**

   Right-click **1-Install-WSL.cmd**, select **Run as administrator**, and restart
   Windows if requested. Open Ubuntu once and create your Linux username and
   password.

   If Ubuntu 22.04 is already installed, reuse it. Do not unregister or delete an
   existing distribution.

4. **Build PX4 and the bridge.**

   Double-click **2-Build-SITL.cmd** as a normal Windows user. Enter your Ubuntu
   password if requested. The first build downloads and installs the required
   Linux tools, so it can take some time.

5. **Prepare RealFlight.**

   Open RealFlight, load a fixed-wing aircraft, enable **RealFlight Link**, set
   physics speed to **100% / 1.0**, and disable flight assistance. New aircraft
   must be prepared as described in
   [Configuration and aircraft preparation](docs/CONFIGURATION.md).

6. **Start and test everything.**

   Open QGroundControl, then double-click **7-Start-and-Test.cmd**. Keep the
   console window open while using the simulator.

   A working setup ends with:

   ```text
   Diagnostic result: PASS
   ```

   The detailed result is saved in `reports/sitl-smoke-test.md`.

> **Do I need to open Linux every time?** No. Open Ubuntu once to create its user.
> After that, use the numbered Windows `.cmd` files.

## Every time you use the simulator

1. Open RealFlight and select the prepared aircraft.
2. Enable **RealFlight Link** and confirm physics speed is **1.0**.
3. Open QGroundControl.
4. Double-click **7-Start-and-Test.cmd**.
5. Wait for `Diagnostic result: PASS`, then use QGroundControl.
6. When finished, press **Ctrl+C** in the start console or run
   **4-Stop-SITL.cmd**.

The stop command ends this project's PX4/bridge runtime but leaves RealFlight and
QGroundControl open.

## vJoy users

The control path is:

`vJoy -> RealFlight -> FlightAxis bridge -> PX4 -> QGroundControl`

1. Confirm that RealFlight receives the vJoy controls.
2. Disable joystick input in QGroundControl; vJoy must enter through RealFlight.
3. For the built-in AeroScout APM profile, run **8-Check-vJoy.cmd** while the
   vehicle is disarmed and follow its axis prompts.
4. In QGroundControl, open **Vehicle Setup -> Radio** and complete radio
   calibration.
5. Center the controls, keep throttle low, and run **6-Test-SITL.cmd**.

Do not assume the usual transmitter channel order. Verify every channel and
direction before arming.

## Command guide

| Run this | Use it for |
|---|---|
| **0-Configure.cmd** | Create or edit local settings |
| **1-Install-WSL.cmd** | Install Ubuntu/WSL2; run as Administrator |
| **2-Build-SITL.cmd** | Download, install and build PX4 plus the bridge |
| **3-Start-SITL.cmd** | Start without automatically collecting a test report |
| **4-Stop-SITL.cmd** | Stop this project's PX4/bridge runtime |
| **5-Check-Setup.cmd** | Check applications, networking and the build |
| **6-Test-SITL.cmd** | Test the currently running setup |
| **7-Start-and-Test.cmd** | Recommended normal start: restart, then test |
| **8-Check-vJoy.cmd** | Check vJoy/RC axes for the AeroScout APM profile |

## If it does not work

1. Run **5-Check-Setup.cmd** and read the failed item.
2. Run **0-Configure.cmd** and correct any application paths.
3. Confirm RealFlight is running with **RealFlight Link** enabled.
4. Allow Windows Firewall access if Windows displays an application prompt.
5. Use **7-Start-and-Test.cmd** to cleanly restart a duplicate or stale runtime.
6. Check `reports/sitl-smoke-test.md` for the exact failing test.

If you see **Wsl/E_ACCESSDENIED**, run the launchers from your normal interactive
Windows desktop account. Do not reinstall WSL or delete Ubuntu because of that
message alone.

## Important

This repository is for simulation and integration testing only. The automated
test proves that the main connections and telemetry are working; it does not
prove that an aircraft model, control direction or mission is safe or correct.
Keep the vehicle disarmed until every control has been checked.

For model setup and advanced details, see:

- [Configuration and aircraft preparation](docs/CONFIGURATION.md)
- [Staged validation procedure](VALIDATION.md)
- [Development and testing](CONTRIBUTING.md)
- [Pinned upstream software and licenses](THIRD_PARTY.md)

The setup pins PX4 v1.16.0 and community bridge commit
`11f769d0e894416f405339e808eded5dc71c46b1`. Bridge credit belongs to
[evandas11/PX4-FlightAxis-Bridge](https://github.com/evandas11/PX4-FlightAxis-Bridge).

## License

The original scripts and documentation in this repository use the
[BSD 3-Clause License](LICENSE). RealFlight, QGroundControl, aircraft assets and
local simulation data are installed or supplied separately.
