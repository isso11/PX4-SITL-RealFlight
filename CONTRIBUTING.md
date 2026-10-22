# Contributing

Use Python 3.10 or newer. The project's Python utilities and tests use the
standard library; the upstream PX4 build installs its own dependencies.

Run these checks from the repository root:

```sh
python -m compileall -q linux tests
python -m unittest discover -s tests -v
bash -n linux/bootstrap.sh
```

GitHub Actions runs the Python checks on Linux and Windows and parses the
PowerShell scripts on Windows. CI does not install RealFlight, build PX4, connect
to a simulator, arm a vehicle or validate a flight.

Keep runtime changes scoped to the exact build, Linux user and rootfs. Preserve
PID-birth checks and source locks. A passing sensor/connection check must not be
reported as a passing flight test. Add regression coverage for meaningful
changes to process cleanup, source selection, input handling or readiness checks.

Use `settings.example.json` for defaults and test fixtures. Personal paths,
addresses, parameters and captures belong in ignored local configuration or
reports. Reports can contain geographic coordinates and local usernames; share
reviewed excerpts when opening an issue. Don't attach WSL disks or RealFlight
aircraft assets.

Changes to upstream revisions need a separate LinuxDirectory and a fresh build;
do not edit an existing source-lock.json to hide a revision mismatch.
