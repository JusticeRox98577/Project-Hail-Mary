#!/usr/bin/env python3
"""
Project Hail Mary - Planet World Map Generator  v2
Generates equirectangular color/height/normal PNGs for all mod planets.
Also generates EVE cloud-map PNGs (grayscale, white=cloud, black=clear).

Two generation modes:
  GAS WORLD  — latitude-banded atmosphere with turbulent edges + cyclone swirls.
               Looks like Jool/Jupiter. Used for thick-atmosphere planets.
  ROCKY WORLD — FBM terrain with craters/erosion. Used for airless/thin-atm worlds.

Requirements:  pip install Pillow numpy
Run from repo root:  python Tools/generate_world_maps.py
Output: GameData/ProjectHailMary/Textures/
        GameData/ProjectHailMary/Textures/EVE/
"""

import os, sys
import numpy as np
from PIL import Image, ImageFilter

TEXTURE_DIR = os.path.join("GameData", "ProjectHailMary", "Textures")
EVE_DIR     = os.path.join(TEXTURE_DIR, "EVE")
WIDTH, HEIGHT = 2048, 1024


# ── Noise primitives ──────────────────────────────────────────────────────────

def fbm(width, height, seed, octaves=7, roughness=0.55):
    """Isotropic fractal Brownian motion."""
    np.random.seed(seed)
    out = np.zeros((height, width), dtype=np.float64)
    amp = 1.0
    for i in range(octaves):
        scale = 2 ** (octaves - i - 1)
        sh, sw = max(2, height // scale), max(2, width // scale)
        layer = np.random.random((sh, sw))
        img = Image.fromarray((layer * 255).astype(np.uint8)).resize(
            (width, height), Image.BILINEAR)
        out += amp * (np.array(img, dtype=np.float64) / 255.0)
        amp *= roughness
    lo, hi = out.min(), out.max()
    return (out - lo) / (hi - lo) if hi > lo else out


def fbm_horizontal(width, height, seed, h_stretch=6.0, octaves=6, roughness=0.55):
    """FBM with horizontal stretch — models atmospheric circulation."""
    np.random.seed(seed)
    out = np.zeros((height, width), dtype=np.float64)
    amp = 1.0
    for i in range(octaves):
        sh = max(2, height // (2 ** (octaves - i - 1)))
        sw = max(2, int(sh * h_stretch))
        layer = np.random.random((sh, sw))
        img = Image.fromarray((layer * 255).astype(np.uint8)).resize(
            (width, height), Image.BILINEAR)
        out += amp * (np.array(img, dtype=np.float64) / 255.0)
        amp *= roughness
    lo, hi = out.min(), out.max()
    return (out - lo) / (hi - lo) if hi > lo else out


# ── Gas giant band field ──────────────────────────────────────────────────────

def gas_band_field(width, height, seed, band_count=8,
                   warp_y=0.12, warp_x=0.02):
    """
    Core gas-giant atmosphere field.
    Returns float [0,1] — low = dark belt, high = bright zone.

    Key design: use a single primary sine (no harmonic averaging that kills contrast)
    with cells at only 10% so the bold dark/bright alternation survives.
    Caller applies tanh contrast sharpening AFTER swirls.
    """
    np.random.seed(seed)

    # Latitude (0=north pole, 1=south pole)
    lat = np.linspace(0.0, 1.0, height)[:, np.newaxis]
    lat = np.tile(lat, (1, width))          # (H, W)

    # Turbulent latitude warp — makes band boundaries wavy but not unrecognisable
    w1 = fbm_horizontal(width, height, seed + 1, h_stretch=8.0,  octaves=6, roughness=0.52)
    w2 = fbm_horizontal(width, height, seed + 2, h_stretch=16.0, octaves=3, roughness=0.44)
    lat_warp = w1 * 0.70 + w2 * 0.30

    # Longitudinal drift (jet-stream shear)
    lon_drift = fbm_horizontal(width, height, seed + 3, h_stretch=22.0, octaves=3, roughness=0.38)

    lat_w = np.clip(lat + (lat_warp  - 0.5) * warp_y * 2.0
                       + (lon_drift  - 0.5) * warp_x, 0.0, 1.0)

    # PRIMARY bands — single sine only.  Harmonics average out and kill contrast.
    primary = 0.5 + 0.5 * np.sin(lat_w * np.pi * band_count * 2.0)

    # Sub-band detail at 2× frequency (fine structure within each band)
    sub = 0.5 + 0.5 * np.sin(lat_w * np.pi * band_count * 4.1 + 0.6)

    # Cloud-cell texture — horizontally stretched, very low weight
    cells = fbm_horizontal(width, height, seed + 4, h_stretch=3.5,
                            octaves=7, roughness=0.60)

    # Bands dominate: primary 78%, sub 12%, cells 10%
    result = primary * 0.78 + sub * 0.12 + cells * 0.10
    lo, hi = result.min(), result.max()
    return (result - lo) / (hi - lo) if hi > lo else result


def add_swirl(field, cx, cy, radius, strength):
    """
    Add a cyclone / anticyclone swirl at position (cx,cy) [0-1 normalised].
    strength > 0 = counterclockwise (anticyclone in NH), < 0 = clockwise.
    """
    H, W = field.shape
    xs = np.linspace(0, 1, W)[np.newaxis, :] - cx   # (1, W)
    ys = np.linspace(0, 1, H)[:, np.newaxis] - cy   # (H, 1)
    dist = np.sqrt(xs ** 2 + ys ** 2)

    # Gaussian rotation — strongest at centre, falls off with distance
    angle = strength * np.exp(-dist ** 2 / (2.0 * (radius * 0.35) ** 2))

    cos_a = np.cos(angle);  sin_a = np.sin(angle)
    new_xs = xs * cos_a - ys * sin_a + cx
    new_ys = xs * sin_a + ys * cos_a + cy

    sx = np.clip((new_xs * W).astype(np.int32), 0, W - 1)
    sy = np.clip((new_ys * H).astype(np.int32), 0, H - 1)
    return field[sy, sx]


# ── Rocky terrain helpers ─────────────────────────────────────────────────────

def warp(terrain, warp_seed, strength=0.12):
    """Domain-warp for natural continent shapes."""
    dx = fbm(WIDTH, HEIGHT, warp_seed,     octaves=4, roughness=0.6)
    dy = fbm(WIDTH, HEIGHT, warp_seed + 1, octaves=4, roughness=0.6)
    base_xs = np.tile(np.arange(WIDTH) [np.newaxis, :], (HEIGHT, 1))
    base_ys = np.tile(np.arange(HEIGHT)[:, np.newaxis], (1,  WIDTH))
    xs = np.clip(np.round(base_xs + (dx - 0.5) * strength * WIDTH ).astype(int),
                 0, WIDTH  - 1)
    ys = np.clip(np.round(base_ys + (dy - 0.5) * strength * HEIGHT).astype(int),
                 0, HEIGHT - 1)
    return terrain[ys, xs]


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


def height_to_normal(terrain, strength=4.0):
    """DirectX-style normal map (G inverted — matches KSP/Unity on Windows)."""
    dx = np.gradient(terrain, axis=1) * strength
    dy = np.gradient(terrain, axis=0) * strength
    nx, ny, nz = dx, -dy, np.ones_like(dx)
    length = np.sqrt(nx ** 2 + ny ** 2 + nz ** 2)
    nx /= length;  ny /= length;  nz /= length
    r = np.clip(( nx + 1) * 127.5, 0, 255).astype(np.uint8)
    g = np.clip((-ny + 1) * 127.5, 0, 255).astype(np.uint8)
    b = np.clip(( nz + 1) * 127.5, 0, 255).astype(np.uint8)
    return np.stack([r, g, b], axis=2)


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


def add_polar_ice(color, cap_lat=0.82, blend_width=0.06,
                  ice_rgb=(235, 242, 252)):
    ys = np.linspace(0, 1, HEIGHT)
    dist = np.minimum(ys, 1.0 - ys) * 2
    mask = np.clip((cap_lat - dist) / blend_width, 0, 1)[:, np.newaxis, np.newaxis]
    blended = color.astype(np.float64) * (1 - mask) + np.array(ice_rgb) * mask
    return np.clip(blended, 0, 255).astype(np.uint8)


def add_polar_fade(color, fade_frac=0.18, pole_color=None):
    """
    Fade horizontal band texture to a solid colour near the poles.
    Prevents the ugly 'scrunching' that happens when bands converge at the
    top/bottom of a sphere.  fade_frac = fraction of image height over which
    the fade occurs (e.g. 0.18 = top/bottom 18% fades to solid).
    pole_color defaults to the average colour of the equatorial strip.
    """
    H, W = color.shape[:2]
    if pole_color is None:
        # Sample the mid-latitude strip to get a representative zone colour
        mid_s = int(H * 0.38)
        mid_e = int(H * 0.62)
        pole_color = color[mid_s:mid_e].mean(axis=(0, 1))

    pole_color = np.array(pole_color, dtype=np.float64)

    # Distance from nearest pole: 0 at pole, 1 at equator
    ys    = np.linspace(0.0, 1.0, H)
    pdist = np.minimum(ys, 1.0 - ys) * 2.0          # 0 at poles, 1 at equator

    # Smooth S-curve mask (squared cosine feel)
    raw  = np.clip(pdist / fade_frac, 0.0, 1.0)
    mask = raw * raw * (3.0 - 2.0 * raw)             # smoothstep
    mask = mask[:, np.newaxis, np.newaxis]            # (H,1,1)

    blended = color.astype(np.float64) * mask + pole_color * (1.0 - mask)
    return np.clip(blended, 0, 255).astype(np.uint8)


# ── I/O ────────────────────────────────────────────────────────────────────────

def save_png(arr, rel_path):
    path = os.path.join("GameData", "ProjectHailMary", "Textures", rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = 'L' if arr.ndim == 2 else 'RGB'
    Image.fromarray(arr.astype(np.uint8), mode).save(path)
    print(f"    {rel_path}")


# ── Planet generators ─────────────────────────────────────────────────────────

def generate_gas_world(name, seed, band_count, band_colors, cell_colors=None,
                        warp_y=0.16, warp_x=0.04, swirls=None,
                        normal_strength=1.2):
    """
    Gas / thick-atmosphere world.
    Produces horizontal cloud bands with turbulent edges, swirl features,
    and cloud-cell detail — like Jool/Jupiter but coloured for the planet.
    """
    print(f"  {name}  [gas world] ...", flush=True)

    # Primary band field
    field = gas_band_field(WIDTH, HEIGHT, seed,
                            band_count=band_count,
                            warp_y=warp_y, warp_x=warp_x)

    # Cyclone / anticyclone swirl features
    if swirls:
        for (cx, cy, radius, strength) in swirls:
            field = add_swirl(field, cx, cy, radius, strength)

    # Renormalise after swirls
    lo, hi = field.min(), field.max()
    field = (field - lo) / (hi - lo) if hi > lo else field

    # Contrast sharpening — push pixels toward dark or bright extremes.
    # tanh with k=4 creates nearly-bimodal distribution: dark belts stay dark,
    # bright zones stay bright, transitions are sharp (Jool-style crisp edges).
    field = 0.5 + 0.5 * np.tanh((field - 0.5) * 4.0)

    # Apply band colormap
    color = apply_colormap(field, band_colors)

    # Cloud-cell highlight overlay (bright patches within bands)
    if cell_colors:
        cells = fbm_horizontal(WIDTH, HEIGHT, seed + 10,
                                h_stretch=3.0, octaves=8, roughness=0.62)
        hi_mask = np.clip((cells - 0.55) / 0.30, 0, 1)
        hi_img = Image.fromarray((hi_mask * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(radius=2))
        hi_mask = np.array(hi_img, dtype=np.float64)[..., np.newaxis] / 255.0
        cell_rgb = apply_colormap(cells, cell_colors).astype(np.float64)
        color = np.clip(
            color.astype(np.float64) * (1 - hi_mask * 0.45)
            + cell_rgb * hi_mask * 0.45,
            0, 255
        ).astype(np.uint8)

    # Fade bands to a solid colour near the poles to prevent sphere-pinching.
    # Use the bright zone colour (last stop in band_colors) as the pole colour
    # so the caps look like zone cloud-tops rather than a blended smear.
    pole_rgb = band_colors[-1][1]
    color = add_polar_fade(color, fade_frac=0.18, pole_color=pole_rgb)

    # Height map: simple FBM (surface invisible, but MapSODemand needs a file)
    hfield = fbm(WIDTH, HEIGHT, seed + 20, octaves=5, roughness=0.50)

    save_png(color,                               f"{name}_color.png")
    save_png((hfield * 255).astype(np.uint8),     f"{name}_height.png")
    save_png(height_to_normal(field, normal_strength), f"{name}_normal.png")


def generate_rocky_world(name, terrain_seed, cloud_seed, color_stops,
                          normal_strength=4.0, roughness=0.55, warp_strength=0.10,
                          has_clouds=True, cloud_coverage=0.35,
                          cloud_color=(242, 248, 255), cloud_octaves=5,
                          cloud_roughness=0.62, cloud_blur=3,
                          polar_ice=False, polar_lat=0.82):
    """Rocky / icy world — FBM terrain with optional clouds and ice caps."""
    print(f"  {name}  [rocky world] ...", flush=True)
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

    save_png(color,                                   f"{name}_color.png")
    save_png((terrain * 255).astype(np.uint8),        f"{name}_height.png")
    save_png(height_to_normal(terrain, normal_strength), f"{name}_normal.png")


# ── EVE cloud-map textures ────────────────────────────────────────────────────

def generate_eve_cloud_textures():
    """
    Generate grayscale cloud-map PNGs for EVE.
    white = opaque cloud,  black = clear sky (transparent).
    Each texture covers the full equirectangular sphere.
    """
    print("\n  EVE cloud textures ...", flush=True)

    # --- cloud_dense: thick gas-world cloud banding (like Jool's cloud deck)
    field = gas_band_field(WIDTH, HEIGHT, seed=500, band_count=9,
                            warp_y=0.18, warp_x=0.05)
    # Push toward high coverage: threshold + stretch
    cloud_mask = np.clip((field - 0.18) / 0.62, 0, 1)
    cloud_blur = Image.fromarray((cloud_mask * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(radius=3))
    save_png(np.array(cloud_blur), "EVE/cloud_dense.png")

    # --- cloud_medium: similar but lower coverage
    field2 = gas_band_field(WIDTH, HEIGHT, seed=501, band_count=7,
                             warp_y=0.14, warp_x=0.04)
    cloud_mask2 = np.clip((field2 - 0.30) / 0.55, 0, 1)
    cloud_blur2 = Image.fromarray((cloud_mask2 * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(radius=2))
    save_png(np.array(cloud_blur2), "EVE/cloud_medium.png")

    # --- cloud_thin: sparse wispy bands (like Jool's thin cloud wisps)
    field3 = gas_band_field(WIDTH, HEIGHT, seed=502, band_count=5,
                             warp_y=0.10, warp_x=0.03)
    cloud_mask3 = np.clip((field3 - 0.48) / 0.42, 0, 1)
    cloud_blur3 = Image.fromarray((cloud_mask3 * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(radius=2))
    save_png(np.array(cloud_blur3), "EVE/cloud_thin.png")

    # --- cloud_detail: small-scale tiling cloud cell texture
    #     High frequency FBM — tiled many times by EVE (uScale = 10+)
    detail = fbm_horizontal(512, 256, seed=503, h_stretch=2.5,
                             octaves=8, roughness=0.62)
    detail_img = Image.fromarray((detail * 255).astype(np.uint8)).resize(
        (WIDTH, HEIGHT), Image.BILINEAR)
    # Sharpen contrast for crisp tiling detail
    detail_sharp = np.clip((np.array(detail_img, dtype=np.float64) / 255.0 - 0.3) / 0.55,
                            0, 1)
    save_png((detail_sharp * 255).astype(np.uint8), "EVE/cloud_detail.png")

    # --- smog_dense: near-uniform smog/haze (very high coverage, low contrast)
    smog = fbm_horizontal(WIDTH, HEIGHT, seed=504, h_stretch=10.0,
                           octaves=5, roughness=0.48)
    smog_mask = np.clip((smog - 0.05) / 0.55, 0, 1)
    smog_blur = Image.fromarray((smog_mask * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(radius=5))
    save_png(np.array(smog_blur), "EVE/smog_dense.png")

    # --- smog_detail: turbulent smog variation for detail tiling
    smog_d = fbm_horizontal(512, 256, seed=505, h_stretch=3.0,
                             octaves=7, roughness=0.58)
    smog_d_img = Image.fromarray((smog_d * 255).astype(np.uint8)).resize(
        (WIDTH, HEIGHT), Image.BILINEAR)
    save_png(np.array(smog_d_img), "EVE/smog_detail.png")


# ── Planet definitions ────────────────────────────────────────────────────────

def main():
    os.makedirs(TEXTURE_DIR, exist_ok=True)
    os.makedirs(EVE_DIR, exist_ok=True)
    print(f"Output -> {os.path.abspath(TEXTURE_DIR)}\n")

    # ── GAS / THICK-ATMOSPHERE WORLDS ─────────────────────────────────────────

    # Adrian (TauCetiE) — THE GREEN PLANET
    # Film: overwhelming lime-green sphere, completely covered in Astrophage.
    # Target look: Jool but lime-green — bold dark forest belts, vivid lime zones.
    # With tanh contrast: dark (<0.35) = near-black forest, bright (>0.65) = vivid lime.
    generate_gas_world(
        name        = "TauCetiE",
        seed        = 91,
        band_count  = 8,
        warp_y      = 0.12,
        warp_x      = 0.03,
        band_colors = [
            (0.00, (  4,  20,   2)),   # near-black forest belt
            (0.18, (  7,  35,   4)),   # very dark green
            (0.35, ( 18,  75,  10)),   # dark-to-mid transition
            (0.50, ( 55, 160,  22)),   # mid (tanh keeps few pixels here)
            (0.65, (110, 230,  38)),   # bright lime zone
            (0.82, (148, 252,  48)),   # vivid lime
            (1.00, (162, 255,  52)),   # peak lime — zone crests
        ],
        cell_colors = None,
        swirls = [
            (0.30, 0.57, 0.09, +2.2),   # large anticyclone (Great Green Spot)
            (0.65, 0.42, 0.06, -1.5),   # mid cyclone
            (0.12, 0.62, 0.05, +1.7),   # northern swirl
            (0.80, 0.35, 0.04, -1.2),   # small southern cyclone
        ],
        normal_strength = 1.0,
    )

    # Erid (EridianHome) — Rocky's homeworld
    # Book: near-lightless, pitch-black volcanic surface under 28 atm ammonia smog.
    # Target: dark stormy Jupiter — near-black belts, dull amber zones. Dramatic.
    generate_gas_world(
        name        = "EridianHome",
        seed        = 67,
        band_count  = 7,
        warp_y      = 0.14,
        warp_x      = 0.04,
        band_colors = [
            (0.00, (  5,   2,   1)),   # near-black volcanic belt
            (0.18, ( 15,   8,   2)),   # very dark
            (0.35, ( 40,  22,   6)),   # dark amber transition
            (0.50, ( 80,  48,  15)),   # mid amber (tanh pushes away from this)
            (0.65, (130,  80,  28)),   # bright amber zone
            (0.82, (162, 102,  38)),   # vivid amber
            (1.00, (178, 115,  44)),   # storm crest amber
        ],
        cell_colors = None,
        swirls = [
            (0.48, 0.50, 0.11, +2.5),  # massive planet-spanning storm
            (0.20, 0.58, 0.07, -1.9),
            (0.72, 0.40, 0.06, +1.7),
            (0.35, 0.32, 0.05, -1.3),
        ],
        normal_strength = 0.9,
    )

    # Tau Ceti c — Venus analog, 50 atm sulfuric acid clouds
    # Target: golden-amber gas world — dark caramel belts, bright pale-gold zones.
    generate_gas_world(
        name        = "TauCetiC",
        seed        = 33,
        band_count  = 6,
        warp_y      = 0.08,
        warp_x      = 0.02,
        band_colors = [
            (0.00, ( 35,  20,   4)),   # dark caramel belt
            (0.18, ( 65,  40,  10)),   # dark amber
            (0.35, (110,  75,  22)),   # mid transition
            (0.50, (165, 128,  45)),   # mid gold
            (0.65, (205, 168,  68)),   # bright gold zone
            (0.82, (228, 195,  82)),   # vivid pale gold
            (1.00, (245, 215,  95)),   # peak cloud-top gold
        ],
        cell_colors = None,
        swirls = [
            (0.40, 0.52, 0.08, +1.5),
            (0.72, 0.45, 0.05, -1.1),
        ],
        normal_strength = 0.8,
    )

    # ── ROCKY / ICY WORLDS ────────────────────────────────────────────────────

    # Tau Ceti b — scorched, airless, charcoal gray
    generate_rocky_world(
        name          = "TauCetiB",
        terrain_seed  = 7,
        cloud_seed    = 301,
        roughness     = 0.70,
        warp_strength = 0.04,
        normal_strength = 6.0,
        has_clouds    = False,
        color_stops   = [
            (0.00, (22, 21, 22)),
            (0.25, (35, 34, 35)),
            (0.52, (52, 50, 52)),
            (0.76, (70, 68, 70)),
            (1.00, (90, 87, 90)),
        ],
    )

    # Tau Ceti g — tidal volcanic, dark red-orange
    generate_rocky_world(
        name          = "TauCetiG",
        terrain_seed  = 12,
        cloud_seed    = 305,
        roughness     = 0.62,
        warp_strength = 0.06,
        normal_strength = 5.0,
        has_clouds    = False,
        color_stops   = [
            (0.00, ( 45,  12,   3)),
            (0.20, ( 78,  26,   9)),
            (0.45, (115,  44,  16)),
            (0.70, (155,  68,  26)),
            (1.00, (205, 112,  42)),
        ],
    )

    # Tau Ceti d — arid, cratered charcoal-grey, thin CO2 atmosphere
    generate_rocky_world(
        name          = "TauCetiD",
        terrain_seed  = 58,
        cloud_seed    = 303,
        roughness     = 0.66,
        warp_strength = 0.05,
        normal_strength = 5.0,
        has_clouds    = False,
        polar_ice     = False,
        color_stops   = [
            (0.00, (28, 26, 24)),
            (0.25, (44, 41, 38)),
            (0.52, (62, 59, 55)),
            (0.76, (82, 78, 73)),
            (1.00, (105, 100, 93)),
        ],
    )

    # Tau Ceti f — cold icy world, advancing ice sheets
    generate_rocky_world(
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
    )

    # 40 Eridani I — hot inner rock, red-orange iron surface
    generate_rocky_world(
        name          = "FortyEridaniI",
        terrain_seed  = 15,
        cloud_seed    = 307,
        roughness     = 0.65,
        warp_strength = 0.06,
        normal_strength = 5.0,
        has_clouds    = False,
        color_stops   = [
            (0.00, ( 50,  15,   4)),
            (0.28, ( 88,  32,  12)),
            (0.55, (128,  54,  20)),
            (0.80, (162,  78,  30)),
            (1.00, (192, 105,  42)),
        ],
    )

    # 40 Eridani III — cold outer world, dusty gray-brown
    generate_rocky_world(
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
    )

    # ── EVE cloud textures ────────────────────────────────────────────────────
    generate_eve_cloud_textures()

    total = 9 * 3 + 6
    print(f"\nDone — {total} PNG files written.")
    print("Copy GameData/ to KSP install, delete Kopernicus cache, relaunch.")


if __name__ == "__main__":
    try:
        from PIL import Image, ImageFilter
        import numpy as np
    except ImportError:
        print("pip install Pillow numpy")
        sys.exit(1)
    main()
