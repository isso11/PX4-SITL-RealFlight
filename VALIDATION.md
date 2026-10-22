# Validation

Connection checks, RC calibration, model direction and flight performance are
separate acceptance stages. Passing one stage does not establish the others.

## Bench acceptance

Keep the virtual aircraft stationary and disarmed. Run `7-Start-and-Test.cmd`
for a controlled project restart or `6-Test-SITL.cmd` for an existing session.
Read `reports/sitl-smoke-test.md` and its raw JSON evidence.

Verify:

- One exact-build PX4 server and one FlightAxis bridge remain stable.
- Airframe 1200, fixed-wing controllers, and both simulator/RF TCP links.
- Fresh gyro, accelerometer, magnetometer, GPS, pressure and airspeed streams.
- Fresh advancing attitude; usable position output and passing preflight checks.
- Stationary GPS/EKF vertical speed and MSL altitude agree within the diagnostic
  bench tolerances (1 m/s and 5 m respectively). These thresholds detect gross
  inconsistency and are not aircraft performance specifications.
- Read all warnings, including heading readiness and timing. A report can say
  PASS with warnings; that result is not permission to fly.

The collector never arms, moves controls, changes parameters or uploads missions.
Keep `reports/` locally; raw reports contain paths, addresses and field coordinates.

## RC acceptance

For RF/vJoy RC passthrough:

1. Disable QGC joystick control and verify fresh `input_rc` changes from each axis.
2. Set RC-only input (`COM_RC_IN_MODE=0`) and complete QGC Radio calibration.
3. Verify nonzero distinct `RC_MAP_ROLL`, `RC_MAP_PITCH`, `RC_MAP_THROTTLE` and
   `RC_MAP_YAW` values that match the controls actually moved.
4. With controls centered and throttle low, verify zero roll/pitch/yaw, low
   throttle and a valid RC-sourced manual control setpoint.
5. Confirm directions from signed movement, not only min/max travel.

`8-Check-vJoy.cmd` automates raw-axis verification and RC-only selection for the
AeroScout profile. It does not replace calibration or direction verification.

## Model and control acceptance

Prepare the selected RF model as described in [configuration](docs/CONFIGURATION.md).
Check physical output wiring against the PX4 functions, independently of RC
input channel numbers. On AeroScout APM, hold output channel 5 neutral because
it drives steering rather than a second aileron.

Control-direction and stabilizing-response tests require a controlled test of
the virtual aircraft after input and health checks. The PX4/bridge disarmed
output gates mean disarmed slider movement alone cannot establish RF direction.
Do not remove those gates or force arming past failed checks.

Verify surface movement, throttle idle/range and stabilizing response, then a
manual Stabilized circuit, before autonomous takeoff or mission tracking. Record
estimator versus ground-truth behavior and any reconnects, resets or timeouts.

GitHub Actions verifies software checks only. Live tests require the user's
Windows/WSL/RealFlight environment and must be described separately.
