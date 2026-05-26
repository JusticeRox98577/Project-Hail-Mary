#!/usr/bin/env python3
"""
Project Hail Mary - Planet World Map Generator
Generates equirectangular color, height, and normal map PNGs for all mod planets.

Requirements:  pip install Pillow numpy
Run from repo root:  python Tools/generate_world_maps.py
Output: GameData/ProjectHailMary/Textures/
"""

import os, sys
import numpy as np
from PIL import Image, ImageFilter

OUTPUT_DIR = os.path.join("GameData", "ProjectHailMary", "Textures")
WIDTH, HEIGHT = 2048, 1024


# ── Noise ─────────────────────────────────────────────────────────────────────

def fbm(width, height, seed, octaves=7, roughness=0.55):
    """Fractal Brownian Motion via multi-scale bilinear-upsampled grids."""
    np.random.seed(seed)
    terrain = np.zeros((height, width), dtype=np.float64)
    amp = 1.0
    for i in range(octaves):
        scale = 2 ** (octaves - i - 1)
        sh, sw = max(2, height // scale), max(2, width // scale)
        layer = np.random.random((sh, sw))
        img = Image.fromarray((layer * 255).astype(np.uint8)).resize(
            (width, height), Image.BILINEAR)
        terrain += amp * (np.array(img, dtype=np.float64) / 255.0)
        amp *= roughness
    lo, hi = terrain.min(), terrain.max()
    return (terrain - lo) / (hi - lo)


def warp(terrain, warp_seed, strength=0.12):
    """Domain-warp for natural continent shapes. Bug-fixed: uses 2D coord grids."""
    dx = fbm(WIDTH, HEIGHT, warp_seed,     octaves=4, roughness=0.6)
    dy = fbm(WIDTH, HEIGHT, warp_seed + 1, octaves=4, roughness=0.6)
    # 2D coordinate grids — fixes the (1024,) vs (1024,2048) broadcast error
    base_xs = np.tile(np.arange(WIDTH)[np.newaxis, :],  (HEIGHT, 1))
    base_ys = np.tile(np.arange(HEIGHT)[:, np.newaxis], (1, WIDTH))
    xs = np.clip(np.round(base_xs + (dx - 0.5) * strength * WIDTH ).astype(int), 0, WIDTH  - 1)
    ys = np.clip(np.round(base_ys + (dy - 0.5) * strength * HEIGHT).astype(int), 0, HEIGHT - 1)
    return terrain[ys, xs]


# ── Color mapping ─────────────────────────────────────────────────────────────

def apply_colormap(terrain, stops):
    h, w = terrain.shape
    rgb = np.zeros((h, w, 3), dtype=np.float64)
    for i in range(len(stops) - 1):
        t0, c0 = stops[i];  t1, c1 = stops[i + 1]
        mask = (terrain >= t0) & (terrain < t1)
        frac = np.where(mask, (terrain - t0) / max(t1 - t0, 1e-9), 0.0)
        for ch in range(3):
            rgb[..., ch] += mask * (c0[ch] + frac * (c1[ch] - c0[ch]))
    mask = terrain >= stops[-1][0]
    for ch in range(3):
        rgb[..., ch] += mask * stops[-1][1][ch]
    return np.clip(rgb, 0, 255).astype(np.uint8)


# ── Normal map ────────────────────────────────────────────────────────────────

def height_to_normal(terrain, strength=4.0):
    """DirectX normal map (G channel inverted — matches KSP/Unity on Windows)."""
    dx = np.gradient(terrain, axis=1) * strength
    dy = np.gradient(terrain, axis=0) * strength
    nx, ny, nz = dx, -dy, np.ones_like(dx)
    length = np.sqrt(nx**2 + ny**2 + nz**2)
    nx /= length;  ny /= length;  nz /= length
    r = np.clip(( nx + 1) * 127.5, 0, 255).astype(np.uint8)
    g = np.clip((-ny + 1) * 127.5, 0, 255).astype(np.uint8)
    b = np.clip(( nz + 1) * 127.5, 0, 255).astype(np.uint8)
    return np.stack([r, g, b], axis=2)


# ── Clouds ────────────────────────────────────────────────────────────────────

def add_clouds(color, cloud_seed, coverage=0.35, cloud_rgb=(242, 248, 255),
               octaves=5, roughness=0.62, blur=3):
    clouds = fbm(WIDTH, HEIGHT, cloud_seed, octaves=octaves, roughness=roughness)
    threshold = 1.0 - coverage
    mask = np.clip((clouds - threshold) / max(1.0 - threshold, 1e-9), 0, 1)
    mask_img = Image.fromarray((mask * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(radius=blur))
    mask = np.array(mask_img, dtype=np.float64)[..., np.newaxis] / 255.0
    blended = color.astype(np.float64) * (1 - mask) + np.array(cloud_rgb) * mask
    return np.clip(blended, 0, 255).astype(np.uint8)


# ── Polar ice ─────────────────────────────────────────────────────────────────

def add_polar_ice(color, cap_lat=0.82, blend_width=0.06,
                  ice_rgb=(235, 242, 252)):
    ys = np.linspace(0, 1, HEIGHT)
    dist = np.minimum(ys, 1.0 - ys) * 2
    mask = np.clip((cap_lat - dist) / blend_width, 0, 1)[:, np.newaxis, np.newaxis]
    blended = color.astype(np.float64) * (1 - mask) + np.array(ice_rgb) * mask
    return np.clip(blended, 0, 255).astype(np.uint8)


# ── IO ────────────────────────────────────────────────────────────────────────

def save(arr, name):
    path = os.path.join(OUTPUT_DIR, name)
    mode = 'L' if arr.ndim == 2 else 'RGB'
    Image.fromarray(arr.astype(np.uint8), mode).save(path)
    print(f"    {name}")


# ── Planet generator ──────────────────────────────────────────────────────────

def generate_planet(name, terrain_seed, cloud_seed, color_stops,
                    normal_strength=4.0, roughness=0.55, warp_strength=0.10,
                    has_clouds=True, cloud_coverage=0.35,
                    cloud_color=(242, 248, 255), cloud_octaves=5,
                    cloud_roughness=0.62, cloud_blur=3,
                    polar_ice=False, polar_lat=0.82):
    print(f"  {name} ...", flush=True)
    terrain = fbm(WIDTH, HEIGHT, terrain_seed, roughness=roughness)
    terrain = warp(terrain, terrain_seed + 500, strength=warp_strength)
    terrain = (terrain - terrain.min()) / (terrain.max() - terrain.min())

    color = apply_colormap(terrain, color_stops)
    if polar_ice:
        color = add_polar_ice(color, cap_lat=polar_lat)
    if has_clouds:
        color = add_clouds(color, cloud_seed, coverage=cloud_coverage,
                           cloud_rgb=cloud_color, octaves=cloud_octaves,
                           roughness=cloud_roughness, blur=cloud_blur)

    save(color, f"{name}_color.png")
    save((terrain * 255).astype(np.uint8), f"{name}_height.png")
    save(height_to_normal(terrain, strength=normal_strength), f"{name}_normal.png")


# ── Planet definitions ────────────────────────────────────────────────────────

PLANETS = [

    # ── Adrian (Tau Ceti e) ───────────────────────────────────────────────────
    # Film reference: pure saturated lime-green planet, bright glowing limb,
    # dense cloud texture like cauliflower tops, NO visible surface, 100% cloud.
    # Color is uniform lime-green — only luminance varies with cloud height.
    dict(
        name          = "TauCetiE",
        terrain_seed  = 91,
        cloud_seed    = 300,
        roughness     = 0.68,           # high roughness = fine bumpy cloud texture
        warp_strength = 0.06,           # minimal warp — clouds don't need continents
        normal_strength = 2.0,
        has_clouds    = True,
        cloud_coverage = 0.96,          # near-total — this is ALL clouds, no surface
        cloud_color   = (100, 210, 22), # saturated lime green matching film
        cloud_octaves = 8,              # more octaves = finer cloud cell texture
        cloud_roughness = 0.68,
        cloud_blur    = 2,              # less blur = crisper cloud cells
        polar_ice     = False,
        color_stops   = [               # pure green luminance ramp — NO red/orange
            (0.00, ( 15,  58,   4)),
            (0.15, ( 28,  88,   8)),
            (0.30, ( 45, 125,  13)),
            (0.48, ( 68, 165,  18)),
            (0.62, ( 88, 195,  23)),
            (0.76, (108, 218,  28)),
            (0.88, (125, 235,  34)),
            (1.00, (142, 250,  40)),
        ],
    ),

    # ── Tau Ceti b (innermost, scorched charcoal gray) ────────────────────────
    dict(
        name          = "TauCetiB",
        terrain_seed  = 7,
        cloud_seed    = 301,
        roughness     = 0.70,           # very rough = heavily cratered
        warp_strength = 0.04,
        normal_strength = 6.0,          # sharp craters
        has_clouds    = False,
        polar_ice     = False,
        color_stops   = [               # charcoal gray, darkest of the three
            (0.00, (22, 21, 22)),
            (0.25, (35, 34, 35)),
            (0.52, (52, 50, 52)),
            (0.76, (70, 68, 70)),
            (1.00, (90, 87, 90)),
        ],
    ),

    # ── Tau Ceti c (middle inner rock, charcoal gray) ─────────────────────────
    dict(
        name          = "TauCetiC",
        terrain_seed  = 33,
        cloud_seed    = 302,
        roughness     = 0.68,
        warp_strength = 0.04,
        normal_strength = 5.5,
        has_clouds    = False,
        polar_ice     = False,
        color_stops   = [
            (0.00, (25, 24, 25)),
            (0.25, (40, 38, 40)),
            (0.52, (58, 56, 58)),
            (0.76, (76, 73, 76)),
            (1.00, (98, 94, 98)),
        ],
    ),

    # ── Tau Ceti d (outer inner rock, charcoal gray) ──────────────────────────
    dict(
        name          = "TauCetiD",
        terrain_seed  = 58,
        cloud_seed    = 303,
        roughness     = 0.66,
        warp_strength = 0.05,
        normal_strength = 5.0,
        has_clouds    = False,
        polar_ice     = False,
        color_stops   = [               # very slightly warmer gray (farther from star)
            (0.00, (28, 26, 24)),
            (0.25, (44, 41, 38)),
            (0.52, (62, 59, 55)),
            (0.76, (82, 78, 73)),
            (1.00, (105, 100, 93)),
        ],
    ),

    # ── Tau Ceti f (outer icy world, pale blue-white) ─────────────────────────
    dict(
        name          = "TauCetiF",
        terrain_seed  = 44,
        cloud_seed    = 304,
        roughness     = 0.48,
        warp_strength = 0.08,
        normal_strength = 2.5,
        has_clouds    = True,
        cloud_coverage = 0.28,
        cloud_color   = (248, 250, 255),
        polar_ice     = True,
        polar_lat     = 0.60,
        color_stops   = [
            (0.00, (162, 185, 208)),
            (0.30, (178, 200, 222)),
            (0.60, (195, 215, 235)),
            (0.82, (212, 228, 244)),
            (1.00, (238, 246, 254)),
        ],
    ),

    # ── Tau Ceti g (volcanic inner world, dark red-orange) ────────────────────
    dict(
        name          = "TauCetiG",
        terrain_seed  = 12,
        cloud_seed    = 305,
        roughness     = 0.62,
        warp_strength = 0.06,
        normal_strength = 5.0,
        has_clouds    = False,
        polar_ice     = False,
        color_stops   = [
            (0.00, ( 48,  14,   4)),
            (0.20, ( 78,  26,   9)),
            (0.48, (115,  44,  16)),
            (0.72, (152,  66,  25)),
            (1.00, (200, 110,  42)),
        ],
    ),

    # ── Erid (40 Eridani A b, Rocky's homeworld) ─────────────────────────────
    # Dense orange-brown ammonia smog, near-total cloud cover.
    # Below the clouds: pitch-black volcanic landscape, permanent twilight.
    dict(
        name          = "EridianHome",
        terrain_seed  = 67,
        cloud_seed    = 306,
        roughness     = 0.62,
        warp_strength = 0.05,
        normal_strength = 2.0,
        has_clouds    = True,
        cloud_coverage = 0.92,          # near-total ammonia smog
        cloud_color   = (172, 108, 38), # dark orange-brown ammonia
        cloud_octaves = 7,
        cloud_roughness = 0.60,
        cloud_blur    = 4,
        polar_ice     = False,
        color_stops   = [               # pitch-black volcanic under the clouds
            (0.00, ( 12,   8,   4)),
            (0.15, ( 35,  22,   8)),
            (0.35, ( 72,  46,  16)),
            (0.55, (108,  70,  26)),
            (0.75, (145,  95,  38)),
            (1.00, (178, 122,  50)),
        ],
    ),

    # ── 40 Eridani I (hot inner rock, red-orange) ────────────────────────────
    dict(
        name          = "FortyEridaniI",
        terrain_seed  = 15,
        cloud_seed    = 307,
        roughness     = 0.65,
        warp_strength = 0.06,
        normal_strength = 5.0,
        has_clouds    = False,
        polar_ice     = False,
        color_stops   = [
            (0.00, ( 52,  16,   4)),
            (0.28, ( 88,  32,  12)),
            (0.55, (128,  54,  20)),
            (0.80, (162,  78,  30)),
            (1.00, (192, 105,  42)),
        ],
    ),

    # ── 40 Eridani III (cold outer world, dusty gray-brown) ──────────────────
    dict(
        name          = "FortyEridaniIII",
        terrain_seed  = 29,
        cloud_seed    = 308,
        roughness     = 0.52,
        warp_strength = 0.09,
        normal_strength = 3.0,
        has_clouds    = True,
        cloud_coverage = 0.15,
        cloud_color   = (235, 232, 225),
        polar_ice     = True,
        polar_lat     = 0.70,
        color_stops   = [
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
    print(f"Output → {os.path.abspath(OUTPUT_DIR)}\n")
    for p in PLANETS:
        generate_planet(**p)
    print(f"\nDone — {len(PLANETS) * 3} PNG files generated.")
    print("Reload KSP — Kopernicus reads PNG directly.")
    print("Delete GameData/Kopernicus/Cache/*.bin to force planet rebuild.")

if __name__ == "__main__":
    try:
        from PIL import Image, ImageFilter
        import numpy as np
    except ImportError:
        print("Run: pip install Pillow numpy")
        sys.exit(1)
    main()
