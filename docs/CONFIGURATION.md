# Configuration and model preparation

Run `0-Configure.cmd` or copy `settings.example.json` to `settings.json`.
Local settings are ignored by Git. Running configuration again preserves them.

| Setting | Meaning |
|---|---|
| `Distro` | Ubuntu-22.04 WSL2 distribution; installer targets this distribution name |
| `LinuxDirectory` | Single folder name under the normal Linux user's home; use a new name for a new source revision |
| `Px4Ref` | Currently supported PX4 release: v1.16.0 |
| `BridgeRef` | Git ref or full commit ID; example pins the reviewed commit |
| `AircraftProfile` | `generic` or the specific `AeroScoutAPM` profile |
| `WindowsHostAddress` | `auto` detects the NAT gateway or uses localhost in mirrored mode; explicit IPv4 is supported |
| `FlightAxisAddress` | `auto` uses the Windows host; explicit IPv4 is supported |
| `QgcExecutable` | Existing QGroundControl executable |
| `SteamExecutable` | Existing Steam executable used to launch RF |
| `RealFlightExecutable` | Existing RF executable used by setup checks |
| `SteamAppId` | RealFlight Evolution app ID, supplied as `2069310` |
| `Home` | Simulated latitude/longitude, MSL altitude in metres, yaw/heading in degrees |

The example geographic origin is a public example location, not a selected
flight-test field. Set the intended field and initial runway heading. Rotating
the FlightAxis world does not make RF scenery terrain match QGC map terrain.

## Source and parameter persistence

Sources live in `~/<LinuxDirectory>/PX4-Autopilot` and
`~/<LinuxDirectory>/PX4-FlightAxis-Bridge`. The bootstrap clones fresh sources at
the configured tag/branch/commit and detaches HEAD. Source-lock and build-state
records detect changes. Existing repositories are checked, not silently reset.

The saved `source-lock.json` includes configured ref strings as well as resolved
commits. Changing a ref string, even to an equivalent commit, changes that lock's
identity. Use a separate `LinuxDirectory` when adopting different source revisions.

Parameters and missions are stored in `~/<LinuxDirectory>/rootfs/plane` outside
the build tree. Startup defaults do not necessarily replace saved parameters.
Inspect effective values rather than clearing the parameter store. In QGC, keep
the intended FlightAxis fixed-wing airframe 1200; do not select a different
airframe to fix a missing calibration page.

## RF aircraft preparation

Follow the pinned upstream [operating guide](https://github.com/evandas11/PX4-FlightAxis-Bridge/blob/11f769d0e894416f405339e808eded5dc71c46b1/RUNNING.md)
and [README](https://github.com/evandas11/PX4-FlightAxis-Bridge/blob/11f769d0e894416f405339e808eded5dc71c46b1/README.md).

- Enable RealFlight Link and use physics speed 1.0.
- Remove model gyro/stabilization/flight assistance.
- Use linear inputs without expo or additional channel mixing.
- Use the fastest servo response/minimum lag recommended by the bridge guide.
- Match each physical output to the PX4 actuator function; verify direction.

The `AeroScoutAPM` profile is tailored to a particular RF model variant:

| RF output channel | Physical function | PX4 output function |
|---|---|---|
| 1 | Combined ailerons | `PWM_MAIN_FUNC1=201` |
| 2 | Elevator | `PWM_MAIN_FUNC2=203` |
| 3 | Throttle | `PWM_MAIN_FUNC3=101` |
| 4 | Rudder | `PWM_MAIN_FUNC4=204` |
| 5 | Nose-wheel steering | `PWM_MAIN_FUNC5=0`, neutral |

Do not apply this profile to an aircraft with a different channel-5 function.
It appends a narrow startup override to recognized upstream airframe files and
rejects unknown edits. Selecting `generic` removes this project's source block,
but a saved parameter value can persist; inspect `PWM_MAIN_FUNC5` explicitly.

These are actuator output channels. RC input channel assignments are independent
and determined by Radio calibration. No reversal is inferred from an axis name
or another user's InterLink/vJoy setup.

## Runtime limitations

This launcher currently runs the `flightaxis_plane` target with one instance.
HITL, multirotor, ROS 2, arbitrary model targets and multiple simultaneous
instances are not configured by these scripts. Do not transfer the SITL
parameter store directly onto a real autopilot.

The generic fixed-wing gains and airspeed limits are a starting point. An RF
model/profile and a good bench capture do not establish performance of a real
Cube Orange installation. Follow the staged [validation procedure](../VALIDATION.md).
