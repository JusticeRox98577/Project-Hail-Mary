#!/usr/bin/env python3
"""
Project Hail Mary - Planet World Map Generator
Generates equirectangular color, height, and normal map PNGs for all mod planets.
Kopernicus reads PNG and DDS — no conversion needed.

Requirements:
    pip install Pillow numpy

Run from the repo root:
    python Tools/generate_world_maps.py

Output: GameData/ProjectHailMary/Textures/<PlanetName>_color.png
                                              <PlanetName>_height.png
                                              <PlanetName>_normal.png
"""

import os
import sys
import numpy as np
from PIL import Image, ImageFilter

OUTPUT_DIR = os.path.join("GameData", "ProjectHailMary", "Textures")
WIDTH  = 2048
HEIGHT = 1024


# ── Noise ─────────────────────────────────────────────────────────────────────

def fbm(width, height, seed, octaves=7, roughness=0.55):
    """Fractal Brownian Motion via multi-scale bilinear-upsampled random grids.
    No external noise library needed — uses only numpy + Pillow."""
    np.random.seed(seed)
    terrain = np.zeros((height, width), dtype=np.float64)
    amp = 1.0
    for i in range(octaves):
        scale = 2 ** (octaves - i - 1)
        sh = max(2, height // scale)
        sw = max(2, width // scale)
        layer = np.random.random((sh, sw))
        img = Image.fromarray((layer * 255).astype(np.uint8)).resize(
            (width, height), Image.BILINEAR
        )
        terrain += amp * (np.array(img, dtype=np.float64) / 255.0)
        amp *= roughness
    lo, hi = terrain.min(), terrain.max()
    return (terrain - lo) / (hi - lo)


def warp(terrain, warp_seed, strength=0.12):
    """Domain-warp a height map for more natural continent shapes."""
    dx = fbm(WIDTH, HEIGHT, warp_seed,     octaves=4, roughness=0.6)
    dy = fbm(WIDTH, HEIGHT, warp_seed + 1, octaves=4, roughness=0.6)
    xs = np.clip(
        np.round((np.arange(WIDTH)  + (dx - 0.5) * strength * WIDTH )).astype(int),
        0, WIDTH  - 1
    )
    ys = np.clip(
        np.round((np.arange(HEIGHT) + (dy - 0.5) * strength * HEIGHT)).astype(int),
        0, HEIGHT - 1
    )
    # Apply warp using advanced indexing
    xi = np.tile(xs, (HEIGHT, 1))
    yi = np.tile(ys[:, np.newaxis], (1, WIDTH))
    return terrain[yi, xi]


# ── Color mapping ─────────────────────────────────────────────────────────────

def apply_colormap(terrain, stops):
    """
    Map a 0-1 float terrain array to RGB using gradient color stops.
    stops = [(threshold, (R, G, B)), ...] sorted ascending.
    """
    h, w = terrain.shape
    rgb = np.zeros((h, w, 3), dtype=np.float64)
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        mask = (terrain >= t0) & (terrain < t1)
        frac = np.where(mask, (terrain - t0) / max(t1 - t0, 1e-9), 0.0)
        for ch in range(3):
            rgb[..., ch] += mask * (c0[ch] + frac * (c1[ch] - c0[ch]))
    # Clamp anything above the last stop to the last color
    top_mask = terrain >= stops[-1][0]
    for ch in range(3):
        rgb[..., ch] += top_mask * stops[-1][1][ch]
    return np.clip(rgb, 0, 255).astype(np.uint8)


# ── Normal map ────────────────────────────────────────────────────────────────

def height_to_normal(terrain, strength=4.0):
    """
    Derive a DirectX normal map from a grayscale height map.
    DirectX convention: R=+X, G=-Y (green flipped vs OpenGL), B=+Z.
    KSP/Unity uses DirectX on Windows.
    """
    dx = np.gradient(terrain, axis=1) * strength
    dy = np.gradient(terrain, axis=0) * strength
    nx =  dx          # surface normal tilts opposite to slope direction
    ny = -dy          # image Y is flipped relative to world Y
    nz =  np.ones_like(dx)
    length = np.sqrt(nx**2 + ny**2 + nz**2)
    nx /= length;  ny /= length;  nz /= length
    r = np.clip(( nx + 1) * 127.5, 0, 255).astype(np.uint8)
    g = np.clip((-ny + 1) * 127.5, 0, 255).astype(np.uint8)  # DirectX: G inverted
    b = np.clip(( nz + 1) * 127.5, 0, 255).astype(np.uint8)
    return np.stack([r, g, b], axis=2)


# ── Cloud overlay ─────────────────────────────────────────────────────────────

def add_clouds(color, cloud_seed, coverage=0.35, color_rgb=(242, 248, 255)):
    """Blend a procedural cloud layer over a color map."""
    clouds = fbm(WIDTH, HEIGHT, cloud_seed, octaves=5, roughness=0.62)
    # Sharpen: only pixels above the coverage threshold become cloud
    threshold = 1.0 - coverage
    mask = np.clip((clouds - threshold) / max(1.0 - threshold, 1e-9), 0, 1)
    # Soften cloud edges
    mask_img = Image.fromarray((mask * 255).astype(np.uint8))
    mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=3))
    mask = np.array(mask_img, dtype=np.float64)[..., np.newaxis] / 255.0
    cloud_rgb = np.array(color_rgb, dtype=np.float64)
    blended = color.astype(np.float64) * (1 - mask) + cloud_rgb * mask
    return np.clip(blended, 0, 255).astype(np.uint8)


# ── Polar ice caps ────────────────────────────────────────────────────────────

def add_polar_ice(color, cap_lat=0.82, blend=0.06):
    """Paint white ice caps by fading in near the poles (top/bottom of the map)."""
    ys = np.linspace(0, 1, HEIGHT)
    # Distance from pole (top = 1.0 lat, bottom = 1.0 lat)
    dist_from_pole = np.minimum(ys, 1.0 - ys) * 2  # 0 at poles, 1 at equator
    mask = np.clip((cap_lat - dist_from_pole) / blend, 0, 1)
    mask = mask[:, np.newaxis, np.newaxis]
    ice = np.array([235, 242, 252], dtype=np.float64)
    blended = color.astype(np.float64) * (1 - mask) + ice * mask
    return np.clip(blended, 0, 255).astype(np.uint8)


# ── IO ────────────────────────────────────────────────────────────────────────

def save(arr, filename):
    path = os.path.join(OUTPUT_DIR, filename)
    mode = 'L' if arr.ndim == 2 else 'RGB'
    Image.fromarray(arr.astype(np.uint8), mode).save(path)
    print(f"    {filename}")


# ── Planet generator ──────────────────────────────────────────────────────────

def generate_planet(
    name,
    terrain_seed,
    cloud_seed,
    color_stops,
    normal_strength = 4.0,
    roughness       = 0.55,
    warp_strength   = 0.10,
    has_clouds      = True,
    cloud_coverage  = 0.35,
    cloud_color     = (242, 248, 255),
    polar_ice       = False,
    polar_lat       = 0.82,
):
    print(f"  {name} ...", flush=True)

    # Height map
    terrain = fbm(WIDTH, HEIGHT, terrain_seed, roughness=roughness)
    terrain = warp(terrain, terrain_seed + 500, strength=warp_strength)
    # Re-normalize after warp
    terrain = (terrain - terrain.min()) / (terrain.max() - terrain.min())

    # Color map
    color = apply_colormap(terrain, color_stops)
    if polar_ice:
        color = add_polar_ice(color, cap_lat=polar_lat)
    if has_clouds:
        color = add_clouds(color, cloud_seed,
                           coverage=cloud_coverage, color_rgb=cloud_color)

    # Height map (grayscale, 8-bit)
    height8 = (terrain * 255).astype(np.uint8)

    # Normal map
    normal = height_to_normal(terrain, strength=normal_strength)

    save(color,  f"{name}_color.png")
    save(height8, f"{name}_height.png")
    save(normal, f"{name}_normal.png")


# ── Planet definitions ────────────────────────────────────────────────────────
# Color stops: (height_threshold_0_to_1, (R, G, B))
# Thresholds are terrain height fractions — adjust to widen/narrow biomes.

PLANETS = [

    # ── Tau Ceti e ─── habitable zone, blue-teal ocean world, alien sky ────────
    dict(
        name         = "TauCetiE",
        terrain_seed = 91,
        cloud_seed   = 300,
        roughness    = 0.52,
        warp_strength= 0.14,
        normal_strength = 3.5,
        has_clouds   = True,
        cloud_coverage = 0.38,
        cloud_color  = (210, 235, 240),   # slightly blue-tinted clouds
        polar_ice    = True,
        polar_lat    = 0.84,
        color_stops  = [
            (0.00, ( 22,  52,  72)),      # abyss
            (0.35, ( 30,  72,  95)),      # deep ocean
            (0.44, ( 45,  95, 108)),      # shallow ocean
            (0.48, ( 55, 105,  90)),      # coast / reef
            (0.52, ( 62, 110,  85)),      # low plains
            (0.65, ( 68, 112,  88)),      # highland plains
            (0.78, ( 82, 118,  95)),      # upland
            (0.90, (130, 148, 152)),      # rocky high terrain
            (1.00, (195, 208, 212)),      # peaks
        ],
    ),

    # ── Eridian Home ─── Rocky's world, dense amber methane atmosphere ─────────
    dict(
        name         = "EridianHome",
        terrain_seed = 67,
        cloud_seed   = 301,
        roughness    = 0.58,
        warp_strength= 0.12,
        normal_strength = 3.2,
        has_clouds   = True,
        cloud_coverage = 0.55,            # thick methane-ammonia clouds
        cloud_color  = (215, 175,  90),   # amber-orange clouds
        polar_ice    = False,
        color_stops  = [
            (0.00, ( 80,  48,  12)),      # deep basin
            (0.22, (108,  68,  22)),      # lowland plains
            (0.45, (148,  95,  35)),      # mid terrain
            (0.65, (172, 118,  48)),      # highland
            (0.82, (192, 140,  65)),      # ridge
            (1.00, (212, 170, 100)),      # peaks
        ],
    ),

    # ── Tau Ceti d ─── warm inner super-Earth, arid tan desert ────────────────
    dict(
        name         = "TauCetiD",
        terrain_seed = 58,
        cloud_seed   = 302,
        roughness    = 0.50,
        warp_strength= 0.10,
        normal_strength = 3.0,
        has_clouds   = True,
        cloud_coverage = 0.18,
        cloud_color  = (240, 238, 228),
        polar_ice    = True,
        polar_lat    = 0.75,              # small caps — mostly frozen
        color_stops  = [
            (0.00, ( 92,  70,  35)),      # shallow basin
            (0.25, (132, 105,  55)),      # desert plains
            (0.55, (162, 132,  70)),      # highland desert
            (0.75, (178, 150,  85)),      # ridge
            (0.90, (198, 172, 108)),      # high terrain
            (1.00, (225, 212, 185)),      # pale peaks
        ],
    ),

    # ── Tau Ceti f ─── icy outer world, pale blue-white ───────────────────────
    dict(
        name         = "TauCetiF",
        terrain_seed = 44,
        cloud_seed   = 303,
        roughness    = 0.48,
        warp_strength= 0.08,
        normal_strength = 2.5,
        has_clouds   = True,
        cloud_coverage = 0.28,
        cloud_color  = (248, 250, 255),
        polar_ice    = True,
        polar_lat    = 0.60,              # large ice caps
        color_stops  = [
            (0.00, (162, 185, 208)),      # low ice plain
            (0.30, (178, 200, 222)),      # mid ice
            (0.60, (195, 215, 235)),      # highland ice
            (0.82, (212, 228, 244)),      # ridge ice
            (1.00, (238, 246, 254)),      # peaks
        ],
    ),

    # ── Tau Ceti g ─── iron-rich inner world, tidal heating ───────────────────
    dict(
        name         = "TauCetiG",
        terrain_seed = 12,
        cloud_seed   = 304,
        roughness    = 0.62,
        warp_strength= 0.06,
        normal_strength = 5.0,
        has_clouds   = False,
        polar_ice    = False,
        color_stops  = [
            (0.00, ( 48,  14,   4)),      # deep basin (lava shadow)
            (0.20, ( 78,  26,   9)),      # plains
            (0.48, (115,  44,  16)),      # highland
            (0.72, (152,  66,  25)),      # ridge
            (0.90, (185,  90,  35)),      # peaks
            (1.00, (210, 120,  50)),      # bright volcanic peaks
        ],
    ),

    # ── Tau Ceti b ─── scorched innermost rock ────────────────────────────────
    dict(
        name         = "TauCetiB",
        terrain_seed = 7,
        cloud_seed   = 305,
        roughness    = 0.65,
        warp_strength= 0.05,
        normal_strength = 5.0,
        has_clouds   = False,
        polar_ice    = False,
        color_stops  = [
            (0.00, ( 65,  24,   6)),
            (0.28, (105,  44,  14)),
            (0.55, (148,  72,  24)),
            (0.80, (182, 100,  38)),
            (1.00, (210, 135,  58)),
        ],
    ),

    # ── Tau Ceti c ─── Venus analog, dense amber cloud deck ───────────────────
    dict(
        name         = "TauCetiC",
        terrain_seed = 33,
        cloud_seed   = 306,
        roughness    = 0.55,
        warp_strength= 0.08,
        normal_strength = 2.0,
        has_clouds   = True,
        cloud_coverage = 0.75,            # nearly overcast like Venus
        cloud_color  = (205, 155,  60),   # amber clouds
        polar_ice    = False,
        color_stops  = [
            (0.00, ( 98,  52,  12)),
            (0.35, (138,  80,  24)),
            (0.65, (168, 108,  38)),
            (1.00, (195, 138,  55)),
        ],
    ),

    # ── 40 Eridani I ─── hot inner rock ───────────────────────────────────────
    dict(
        name         = "FortyEridaniI",
        terrain_seed = 15,
        cloud_seed   = 307,
        roughness    = 0.65,
        warp_strength= 0.06,
        normal_strength = 5.0,
        has_clouds   = False,
        polar_ice    = False,
        color_stops  = [
            (0.00, ( 52,  16,   4)),
            (0.28, ( 88,  32,  12)),
            (0.55, (128,  54,  20)),
            (0.80, (162,  78,  30)),
            (1.00, (192, 105,  42)),
        ],
    ),

    # ── 40 Eridani III ─── cold outer world ───────────────────────────────────
    dict(
        name         = "FortyEridaniIII",
        terrain_seed = 29,
        cloud_seed   = 308,
        roughness    = 0.52,
        warp_strength= 0.09,
        normal_strength = 3.0,
        has_clouds   = True,
        cloud_coverage = 0.15,
        cloud_color  = (235, 232, 225),
        polar_ice    = True,
        polar_lat    = 0.70,
        color_stops  = [
            (0.00, ( 72,  58,  44)),
            (0.28, (102,  84,  64)),
            (0.55, (132, 110,  86)),
            (0.78, (158, 135, 108)),
            (1.00, (185, 162, 132)),
        ],
    ),
]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Writing to: {os.path.abspath(OUTPUT_DIR)}\n")

    for planet in PLANETS:
        generate_planet(**planet)

    total = len(PLANETS) * 3
    print(f"\nDone — {total} textures generated ({len(PLANETS)} planets × 3 maps).")
    print()
    print("Next steps:")
    print("  1. Reload KSP — Kopernicus reads PNG directly, no conversion needed.")
    print("  2. For better performance, convert to DDS with texconv or GIMP DDS plugin:")
    print("       Color/height: BC1 (DXT1) compression")
    print("       Normal maps:  BC5 (ATI2/3Dc) compression, linear color space")
    print("  3. To tweak a planet's look: edit its color_stops in this script and re-run.")
    print("  4. Delete GameData/Kopernicus/Cache/*.bin after changes to force reload.")


if __name__ == "__main__":
    try:
        from PIL import Image, ImageFilter
        import numpy as np
    except ImportError:
        print("Missing dependencies. Run:  pip install Pillow numpy")
        sys.exit(1)

    main()
