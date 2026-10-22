# Upstream software and assets

This repository contains Windows launch/setup scripts and Python utilities for
an existing PX4/FlightAxis integration. It does not implement the FlightAxis
bridge, bundle a PX4 checkout, or redistribute RealFlight or QGroundControl.

| Dependency | Source / acquisition | License / terms |
|---|---|---|
| PX4 Autopilot | https://github.com/PX4/PX4-Autopilot ; built separately at v1.16.0 | BSD 3-Clause; preserve upstream LICENSE and component notices |
| PX4 FlightAxis Bridge | https://github.com/evandas11/PX4-FlightAxis-Bridge ; built separately | GPL v3, as stated in the upstream LICENSE; preserve its notices |
| QGroundControl | https://qgroundcontrol.com/ ; installed separately | See QGC's distribution and source licenses |
| RealFlight Evolution and aircraft models | User's licensed Steam installation | Proprietary simulator and asset terms; no assets are included here |
| WSL / Ubuntu | Installed separately by Windows / Ubuntu tooling | Their respective licenses and package terms |

Tested source revisions:

- PX4 v1.16.0: `6ea3539157ca358c70a515878b77077af7d4611d`
- Bridge: `11f769d0e894416f405339e808eded5dc71c46b1`

The example configuration pins the bridge commit. Existing installations keep
their own `source-lock.json`, local settings and source checkouts.

The original wrapper utilities and documentation in this repository use the
BSD 3-Clause License in [LICENSE](LICENSE). Upstream software and assets retain
their own licenses and terms; their license texts are authoritative.
