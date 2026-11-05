# Doubled NMC capacity: controlled sensitivity experiment

The two `PV60_NMC_2x.idf` and `PV80_NMC_2x.idf` models retain the original building, PV, inverter, schedules and cell chemistry. Parallel strings, mass and heat-transfer area are doubled to represent two identical banks in parallel. The original 207 kWh files remain available.

| Parameter | Reference bank | Larger bank |
|---|---:|---:|
| Nominal energy (kWh) | 206.6265 | 413.2530 |
| Series cells | 139 | 139 |
| Parallel strings | 139 | 278 |
| Nominal pack voltage (V) | 464.538 | 464.538 |
| Nominal charge capacity (Ah) | 444.8 | 889.6 |
| Charge/discharge design request (kW DC) | 50 / 50 | 50 / 50 |
| Pack mass (kg) | 1901.52 | 3803.04 |
| Heat-transfer area (m2) | 23.6856 | 47.3712 |
| Native SOC limits (%) | 24–94 | 24–94 |
| Default MPC planning limits (%) | 24–92 | 24–92 |
| Nominal energy in planning window (kWh) | 140.51 | 281.01 |

This is a capacity sensitivity, not a commercially sized or economically optimal battery design. Series voltage, cell parameters and power requests are fixed. Parallel scaling also changes effective pack resistance in the native NMC model, so it is not simply a larger ideal energy tank. Generic cell defaults and thermal/lifetime limitations remain those documented in `README_NMC.md`. The 50 kW value is a design request; achieved native NMC power is audited separately.

The MPC runner uses the original bank as its source and applies `--capacity-multiplier 2` consistently to every controller. It derives controller capacity from the modified physical input. The standalone files here provide the same resized plant for inspection. `manifest_nmc_capacity2x.json` records sizing and source/file hashes.

The new 80% PV comparisons include the conditioning Sunday, seven control days and a recovery day. Battery charging/discharging is disabled during EnergyPlus warmup by the Python API for all controllers. The first begin-timestep SOC can still be stale; the end of the first zero-flow interval establishes settled initial inventory, with the raw value retained. Both sizes begin and end at the 24% reserve. Earlier runs also reset their warmup SOC before delivering energy; the correction fixes inventory reporting, not an observed source of free electrical energy. Use the Python API runner and the documented dates for the matched finite-window comparison.

The 60% resized plant has been checked structurally; the new matched MPC sensitivity runs use 80% PV. No new annual or 60% MPC performance is implied by this export.

See `../../mpc/pv_bess_mpc/FLEXIBILITY_RESULTS.md` and the editable `PV_BESS_NMC_Demonstration.ipynb` for measured comparisons, settings and limitations.

Field definitions: [EnergyPlus 25.2 NMC input/output reference](https://bigladdersoftware.com/epx/docs/25-2/input-output-reference/group-electric-load-center-generator.html#electricloadcenterstorageliionnmcbattery).
