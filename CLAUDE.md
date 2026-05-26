# Project Hail Mary — KSP 1.12 Mod

A Kerbal Space Program mod based on Andy Weir's novel *Project Hail Mary*. Adds the Tau Ceti and 40 Eridani star systems, Astrophage propulsion, alien science experiments, and story-accurate parts.

**The user handles all 3D modelling (Unity/Blender). Claude handles all cfg files, C# plugin code, Kopernicus configs, science, tech tree, and MM patches.**

---

## Repository layout

```
GameData/ProjectHailMary/
├── Kopernicus/
│   ├── TauCeti/
│   │   ├── TauCetiStar.cfg          — Tau Ceti star (G-type, orbits stock Sun)
│   │   └── TauCetiPlanets.cfg       — TauCetiB/C/D/E/F/G (b–g = real candidates)
│   └── FortyEridani/
│       ├── FortyEridaniStar.cfg     — 40 Eridani A star
│       └── FortyEridaniPlanets.cfg  — FortyEridaniI, EridianHome, FortyEridaniIII
├── Textures/
│   ├── *.dds   — BC1/DXT1 world maps (color, height, normal) for all 9 bodies
│   └── *.png   — source PNGs (regenerate via Tools/generate_world_maps.py)
├── Parts/
│   ├── AstrophageEngine/part.cfg   — Spin-drive, 500,000s ISP, 30,870 kN
│   ├── AstrophageTank/part.cfg     — Large + small Astrophage tanks
│   ├── HailMaryPod/part.cfg        — Command pod (15t)
│   ├── BlipA/part.cfg              — Rocky's probe core (Blip-A)
│   ├── PetrovaScanner/part.cfg     — Petrova line spectrometer
│   └── RockyComms/part.cfg         — Eridian communications array
├── Resources/Astrophage.cfg        — Astrophage resource definition
├── Science/Experiments.cfg         — Custom science experiments
├── PHM_StockClones.cfg             — +PART clones: phm_spin_drive_array, phm_astrophage_tank_main
├── PHM_ModelFallbacks.cfg          — Stock model stand-ins until custom .mu files are made
├── MM_TechTree.cfg                 — Tech tree nodes: astrophagePropulsion, astrophageCulture
├── MM_LifeSupport.cfg              — TAC-LS / Snacks patches (NEEDS guards)
├── Parallax/PHM_Parallax.cfg       — Parallax Continued 2.0 terrain configs
└── Localization/en-us.cfg          — String table
Tools/
└── generate_world_maps.py          — Python script: generates planet PNGs → convert to DDS
```

---

## Key planet names (internal Kopernicus `name =`)

| Internal name     | Display name  | System      | Template | Notes |
|-------------------|---------------|-------------|----------|-------|
| TauCeti           | Tau Ceti      | —           | Sun      | Star, orbits stock Sun at 18 Tm |
| TauCetiB          | Tau Ceti b    | Tau Ceti    | Moho     | Charcoal gray, flightGlobalsIndex 101 |
| TauCetiC          | Tau Ceti c    | Tau Ceti    | Eve      | Charcoal gray, index 103 |
| TauCetiD          | Tau Ceti d    | Tau Ceti    | Duna     | Charcoal gray, index 104 |
| TauCetiE          | Adrian        | Tau Ceti    | Eve      | **The green planet** — Astrophage/Taumoeba, 5 atm CO2/methane, index 105 |
| TauCetiF          | Tau Ceti f    | Tau Ceti    | Duna     | Icy outer world, index 106 |
| TauCetiG          | Tau Ceti g    | Tau Ceti    | Moho     | Hot volcanic inner rock, index 102 |
| FortyEridani      | 40 Eridani A  | —           | Sun      | K-dwarf star, orbits stock Sun at 24 Tm |
| FortyEridaniI     | 40 Eridani I  | 40 Eridani  | Moho     | Hot inner rock, index 202 |
| EridianHome       | Erid          | 40 Eridani  | Eve      | Rocky's homeworld, 28 atm ammonia, index 201 |
| FortyEridaniIII   | 40 Eridani III| 40 Eridani  | Duna     | Cold outer world, index 203 |

---

## Critical technical rules

### Kopernicus body definitions
- Every body uses `@Kopernicus:AFTER[Kopernicus] { Body { ... } }` — one block per body, one body per block.
- **Never split a body across two cfg files** — duplicate `Body { name = X }` blocks cause Kopernicus to NRE on the second one (ScaledVersionLoader.get_Type() on null mesh).
- Texture references (`texture =`, `normals =`, `VertexColorMap.map`, `VertexHeightMap.map`) must live **inside the same Body block** as Template/Orbit/Properties — not in a separate patch file.
- File load order matters: MM processes files alphabetically by full path. Bodies must be defined before any patch references them.

### Kopernicus known crash (fixed)
- `ScaledVersionLoader.get_Type()` NRE: happens when a Body block has ScaledVersion but no Template. Always include a Template.
- Kerbin template + custom Atmosphere block = NRE due to Kerbin's ocean renderer. Use Eve or Duna templates for atmospheric bodies instead.
- `invWaveLength` values above ~10 cause NRE in AtmosphereFromGround. Keep all four values ≤ 10.
- `pressureCurve` key=0 value (in kPa) must match `atmospherePressureSeaLevel` (in Pa ÷ 1000).

### DDS textures
- Format: BC1/DXT1, 2048×1024, no mipmaps.
- Header flags must be `0x81007` (includes `DDSD_LINEARSIZE = 0x80000`).
- `dwPitchOrLinearSize` = total compressed bytes = `((w+3)//4) * ((h+3)//4) * 8` = 1,048,576 for 2048×1024.
- Wrong flags (0x1007) cause KSP to silently load a gray default texture.
- Regenerate PNGs: `python Tools/generate_world_maps.py`
- Convert to DDS: see the BC1 encoder in the tool or use texconv.

### Parts
- All custom parts currently use stock model fallbacks (PHM_ModelFallbacks.cfg) — no custom `.mu` files yet.
- When a custom model is ready: export from Unity with KSP PartTools → place `.mu` in `Parts/<PartName>/Models/` → remove that part's block from PHM_ModelFallbacks.cfg.
- Stock clone parts (`PHM_StockClones.cfg`) use `+PART[Size3EngineCluster]:FIRST` syntax. Base part must exist in stock KSP.

### Astrophage resource
- Defined in `Resources/Astrophage.cfg`. Do not redefine it elsewhere (duplicate RESOURCE_DEFINITION causes KSP warnings).
- Engine ISP: 500,000s. Thrust: 30,870 kN. Do not set `maxFuelFlow` manually — KSP derives it automatically.

### Module Manager
- `NEEDS[!CUSTOM_PHM_MODELS]` guards the model fallbacks so they auto-remove when real models exist.
- `NEEDS[TACLifeSupport]`, `NEEDS[SnacksUtils]` guard life support patches.
- `NEEDS[Parallax]` guards Parallax terrain configs.

---

## Current status

### Working
- Tau Ceti star + 6 planets load without errors
- 40 Eridani star + 3 planets load without errors
- Adrian (TauCetiE) has green atmosphere glow from AtmosphereFromGround
- DDS world map textures committed (BC1, fixed header) — awaiting in-game confirmation
- All parts visible in VAB via stock model fallbacks
- Astrophage engine + tanks functional
- Science experiments defined
- Tech tree nodes defined

### Not yet done / known issues
- DDS textures: gray planet issue may persist — needs in-game test after latest fix
- Custom 3D models: all parts still use stock model placeholders
- Parallax tiling textures: DDS files listed in TEXTURE_MANIFEST.txt not yet created
- EridianHome AtmosphereFromGround produces bluish sky (invWaveLength tuned for Rayleigh, not orange)
- No biomes defined for custom planets
- No surface scatter (rocks/features) beyond what Parallax config references

### How to regenerate textures
```
pip install Pillow numpy
python Tools/generate_world_maps.py        # writes PNGs to GameData/ProjectHailMary/Textures/
# then convert PNGs to DDS with correct BC1 header (see Tools/generate_world_maps.py comments
# or use texconv: texconv -f DXT1 -o GameData/ProjectHailMary/Textures/ *.png)
```

---

## Git workflow
- Branch: `main`
- Remote: `https://github.com/justicerox98577/project-hail-mary`
- Always commit and push after changes so the user can pull to their KSP install.
- After any Kopernicus cfg change: user must delete `GameData/Kopernicus/Cache/*.bin` before launching KSP.
