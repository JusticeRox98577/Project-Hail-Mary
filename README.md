# Project Hail Mary — KSP 1.12 Mod

A Kerbal Space Program mod based on Andy Weir's novel and film *Project Hail Mary*.

---

## What's Included

### New Resource
- **Astrophage** — the star-eating organism that powers the Hail Mary drive and threatens all stellar life. Dense, orange-glowing, alive.
- **Astrophage Culture (Seed)** — a living seed culture stored in the command pod for science experiments.

### New Parts

| Part | Description |
|------|-------------|
| **Hail Mary Command Module** | Single-crew pod with integrated coma life-support, deep-space comms (5 TW antenna), and an Astrophage culture chamber. Autonomous — no crew required to function. |
| **Astrophage Photon Drive** | Extremely high ISP (85,000 s in vacuum) engine using Astrophage as fuel. Includes **Breeding Mode** — when near a star with the engine off, it slowly grows more Astrophage. Engine glow shifts from orange to blue-white at high throttle. |
| **Astrophage Tank (Large)** | 4,500 units of Astrophage. Enough for serious interstellar delta-v. |
| **Astrophage Tank (Small)** | 800 units. For lighter missions or supplemental capacity. |
| **Eridian Communication Array** | Deep-space antenna optimized for Eridian contact. Includes a science experiment: *Eridian Communication Attempt*. Named after Rocky. |
| **Petrova Spectrometer** | Detects Astrophage infrared signatures around stars. Run near Kerbol's inner planets to find the Petrova Line equivalent. |

### New Star System (requires Kopernicus)

**Tau Ceti** — placed at ~1.8 × 10¹³ m from Kerbol (interstellar distance, requires max timewarp or realistic transit time with the Astrophage drive).

| Body | Description |
|------|-------------|
| **Tau Ceti** | Slightly smaller, cooler, orange-tinted G-type star. 52% of Kerbol's luminosity. The Petrova Line here is catastrophically thick. |
| **Tau Ceti b** | Innermost scorched rock, deep in the Astrophage feeding zone. |
| **Tau Ceti e** | **Rocky's homeworld.** Habitable-zone planet with a methane/nitrogen atmosphere. Roughly 1.5× Kerbin's radius. Where the Eridians live — a civilisation millions of years old. Has unique science results throughout. |
| **Tau Ceti f** | Cold outer habitable-zone world with thin CO2 atmosphere, polar ice caps. As Tau Ceti dims, this world freezes first. |

### Science Experiments

| Experiment | Part |
|------------|------|
| Petrova Astrophage Survey | Petrova Spectrometer |
| Eridian Communication Attempt | Eridian Comms Array |
| Astrophage Biological Study | Hail Mary Pod |

All experiments have unique results depending on where you run them — especially around Tau Ceti.

### Astrophage Crisis Scenario

A background scenario module tracks the crisis timeline:
- After one in-game year, the **Astrophage Crisis** begins: news messages appear, and Kerbol gradually dims (up to 25% over ~7 in-game years).
- Launching a vessel with both the Hail Mary pod and Astrophage drive on an escape trajectory triggers a special **mission launch message**.

### Tech Tree Nodes

Four new research nodes branch off `Advanced Exploration` and `Nuclear Propulsion`:

```
Advanced Exploration ──→ Astrophage Biology
                              │
                              ↓
                     Astrophage Cultivation ──→ Astrophage Photon Drive
                                                          │
                                                Nuclear Propulsion
                                                          │
                                                          ↓
                                                 Eridian Engineering
```

---

## Requirements

| Mod | Required? |
|-----|-----------|
| **Kerbal Space Program 1.12.x** | Yes |
| **Module Manager 4.2+** | Yes — for MM patches |
| **Kopernicus 1.12.x** | Yes — for Tau Ceti system |
| TAC Life Support | Optional — patches included |
| Kerbalism | Optional — patches included |
| USI Life Support | Optional — patches included |

---

## Installation

1. Install **Module Manager** and **Kopernicus** for KSP 1.12 first.
2. Copy `GameData/ProjectHailMary/` into your KSP `GameData/` folder.
3. **Build the plugin:** open `GameData/ProjectHailMary/Plugins/Source/` and build `ProjectHailMary.csproj` with .NET 4.8 against your KSP assemblies. The compiled `ProjectHailMary.dll` goes in `GameData/ProjectHailMary/Plugins/`.
4. Launch KSP. The Tau Ceti system will appear in the Tracking Station.

> **Note on textures:** Part models currently use stock mesh rescales. To add custom meshes, place `.mu` model files in each Part subfolder and update the `MODEL { model = ... }` path in `part.cfg`.

---

## Lore Accuracy Notes

- **Astrophage ISP** is scaled down from the true value (~30,000,000 s) to 85,000 s to keep KSP's physics engine sane. At true ISP you could reach 0.1c with a full tank.
- **Tau Ceti distance** is compressed from 11.9 light-years to ~1.8 × 10¹³ m. The orbital period around Kerbol at this distance is enormous — plan transit times accordingly.
- **Rocky's species** is called *Eridian* in fan discourse; the book never names them. The communication array uses pressure waves (not radio) because Eridians "hear" via organs that sense pressure directly.
- **The Petrova Line** is the band of Astrophage between Venus-equivalent orbit and the Sun. In-game it's simulated by science experiment results and the crisis scenario's dimming effect.

---

## Changelog

### v0.1.0
- Initial release
- All parts, resources, science experiments
- Tau Ceti system (star + 3 planets)
- Astrophage Crisis scenario
- ModuleAstrophageDrive plugin with Breeding Mode
- Life support compatibility patches
- Tech tree integration

---

*"It's a story about grace."*
