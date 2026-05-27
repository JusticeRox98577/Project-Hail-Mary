#!/usr/bin/env python3
"""
Project Hail Mary - Planet World Map Generator  v3
Generates equirectangular color/height/normal PNGs for all mod planets.
Also generates EVE cloud-map PNGs (grayscale, white=cloud, black=clear).

Generation modes:
  ASTROPHAGE WORLD — Voronoi biological-channel networks + crater rings +
                     gas-world density variation. Used for Adrian (TauCetiE).
                     Visual target: Eeloo-quality depth, lime-green biosphere.
  GAS WORLD        — latitude-banded atmosphere with turbulent edges + cyclones.
  ROCKY WORLD      — FBM terrain with craters/erosion.

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

def gas_band_field(width, height, seed, band_count=8, warp_y=0.12, warp_x=0.02,
                   sub_weight=0.12, cell_weight=0.10):
    """
    Core gas-giant atmosphere field.
    Returns float [0,1] — low = dark belt, high = bright zone.

    sub_weight:  fine sub-band sine detail along belt edges (0 = clean belts)
    cell_weight: FBM cloud-cell texture (0 = smooth)
    """
    np.random.seed(seed)

    lat = np.linspace(0.0, 1.0, height)[:, np.newaxis]
    lat = np.tile(lat, (1, width))

    w1 = fbm_horizontal(width, height, seed + 1, h_stretch=8.0,  octaves=6, roughness=0.52)
    w2 = fbm_horizontal(width, height, seed + 2, h_stretch=16.0, octaves=3, roughness=0.44)
    lat_warp = w1 * 0.70 + w2 * 0.30

    lon_drift = fbm_horizontal(width, height, seed + 3, h_stretch=22.0, octaves=3, roughness=0.38)

    lat_w = np.clip(lat + (lat_warp - 0.5) * warp_y * 2.0
                        + (lon_drift - 0.5) * warp_x, 0.0, 1.0)

    primary_w = 1.0 - sub_weight - cell_weight
    primary = 0.5 + 0.5 * np.sin(lat_w * np.pi * band_count * 2.0)
    result  = primary * primary_w

    if sub_weight > 0:
        sub = 0.5 + 0.5 * np.sin(lat_w * np.pi * band_count * 4.1 + 0.6)
        result += sub * sub_weight

    if cell_weight > 0:
        cells = fbm_horizontal(width, height, seed + 4, h_stretch=3.5, octaves=7, roughness=0.60)
        result += cells * cell_weight

    lo, hi = result.min(), result.max()
    return (result - lo) / (hi - lo) if hi > lo else result


def add_swirl(field, cx, cy, radius, strength):
    """Add a cyclone/anticyclone swirl at (cx,cy) [0-1 normalised]."""
    H, W = field.shape
    xs = np.linspace(0, 1, W)[np.newaxis, :] - cx
    ys = np.linspace(0, 1, H)[:, np.newaxis] - cy
    dist = np.sqrt(xs ** 2 + ys ** 2)

    angle = strength * np.exp(-dist ** 2 / (2.0 * (radius * 0.35) ** 2))

    cos_a = np.cos(angle);  sin_a = np.sin(angle)
    new_xs = xs * cos_a - ys * sin_a + cx
    new_ys = xs * sin_a + ys * cos_a + cy

    sx = np.clip((new_xs * W).astype(np.int32), 0, W - 1)
    sy = np.clip((new_ys * H).astype(np.int32), 0, H - 1)
    return field[sy, sx]


# ── Fracture & crater helpers (for Astrophage world) ─────────────────────────

def voronoi_edges(width, height, seed, n_points=75):
    """
    Voronoi cell-edge distance field — generates biological crack/channel networks.

    Returns [0,1] where 0 = along a fracture boundary, 1 = deep in cell interior.
    Edges wrap in X (longitude) for a seamless equirectangular map.
    """
    np.random.seed(seed)
    pts_x = np.random.rand(n_points) * width
    pts_y = np.random.rand(n_points) * height

    ys, xs = np.mgrid[0:height, 0:width]
    dist1 = np.full((height, width), np.inf)
    dist2 = np.full((height, width), np.inf)

    for i in range(n_points):
        # Toroidal distance in X — seamless longitude wrap
        dx = np.abs(xs - pts_x[i])
        dx = np.minimum(dx, width - dx)
        d  = np.sqrt(dx * dx + (ys - pts_y[i]) ** 2)

        closer = d < dist1
        dist2  = np.where(closer, dist1, np.minimum(dist2, d))
        dist1  = np.where(closer, d,     dist1)

    # Edge proximity = dist2 - dist1:  0 at exact boundary, grows toward interior
    edge = dist2 - dist1
    lo, hi = edge.min(), edge.max()
    return (edge - lo) / (hi - lo + 1e-8)


def add_craters(width, height, seed, n_craters=45,
                max_radius_frac=0.035, min_radius_frac=0.005):
    """
    Stamp circular impact craters into a height field.

    Returns [0,1] with:
      - concave floor inside crater
      - raised Gaussian rim ring at crater edge
      - smooth decay outside the rim
    """
    np.random.seed(seed)
    field = np.zeros((height, width), dtype=np.float64)

    ys_norm = np.linspace(0, 1, height)[:, np.newaxis]
    xs_norm = np.linspace(0, 1, width)[np.newaxis, :]

    for _ in range(n_craters):
        cx    = np.random.rand()
        cy    = np.random.rand()
        r     = np.random.uniform(min_radius_frac, max_radius_frac)
        depth = np.random.uniform(0.3, 1.0)

        dx   = np.abs(xs_norm - cx)
        dx   = np.minimum(dx, 1.0 - dx)          # wrap in X
        dist = np.sqrt(dx ** 2 + (ys_norm - cy) ** 2)

        # Concave floor (parabolic inside r*0.75)
        floor = np.where(dist < r * 0.75,
                         -depth * (1.0 - (dist / (r * 0.75)) ** 2) * 0.5,
                         0.0)

        # Gaussian rim ring centred at r
        rim = depth * 0.45 * np.exp(-((dist - r) / (r * 0.30)) ** 2)

        field += floor + rim

    lo, hi = field.min(), field.max()
    return (field - lo) / (hi - lo + 1e-8)


# ── Rocky terrain helpers ─────────────────────────────────────────────────────

def warp(terrain, warp_seed, strength=0.12):
    """Domain-warp for natural continent shapes."""
    height, width = terrain.shape
    dx = fbm(width, height, warp_seed,     octaves=4, roughness=0.6)
    dy = fbm(width, height, warp_seed + 1, octaves=4, roughness=0.6)
    base_xs = np.tile(np.arange(width) [np.newaxis, :], (height, 1))
    base_ys = np.tile(np.arange(height)[:, np.newaxis], (1,  width))
    xs = np.clip(np.round(base_xs + (dx - 0.5) * strength * width ).astype(int),
                 0, width  - 1)
    ys = np.clip(np.round(base_ys + (dy - 0.5) * strength * height).astype(int),
                 0, height - 1)
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
    height, width = color.shape[:2]
    clouds = fbm(width, height, cloud_seed, octaves=octaves, roughness=roughness)
    threshold = 1.0 - coverage
    mask = np.clip((clouds - threshold) / max(1.0 - threshold, 1e-9), 0, 1)
    mask_img = Image.fromarray((mask * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(radius=blur))
    mask = np.array(mask_img, dtype=np.float64)[..., np.newaxis] / 255.0
    blended = color.astype(np.float64) * (1 - mask) + np.array(cloud_rgb) * mask
    return np.clip(blended, 0, 255).astype(np.uint8)


def add_polar_ice(color, cap_lat=0.82, blend_width=0.06,
                  ice_rgb=(235, 242, 252)):
    height = color.shape[0]
    ys = np.linspace(0, 1, height)
    dist = np.minimum(ys, 1.0 - ys) * 2
    mask = np.clip((cap_lat - dist) / blend_width, 0, 1)[:, np.newaxis, np.newaxis]
    blended = color.astype(np.float64) * (1 - mask) + np.array(ice_rgb) * mask
    return np.clip(blended, 0, 255).astype(np.uint8)


def add_polar_fade(color, fade_frac=0.18, pole_color=None):
    """Fade band texture to a solid colour near the poles to avoid sphere-pinching."""
    H = color.shape[0]
    if pole_color is None:
        mid_s = int(H * 0.38);  mid_e = int(H * 0.62)
        pole_color = color[mid_s:mid_e].mean(axis=(0, 1))
    pole_color = np.array(pole_color, dtype=np.float64)
    ys    = np.linspace(0.0, 1.0, H)
    pdist = np.minimum(ys, 1.0 - ys) * 2.0
    raw   = np.clip(pdist / fade_frac, 0.0, 1.0)
    mask  = raw * raw * (3.0 - 2.0 * raw)
    mask  = mask[:, np.newaxis, np.newaxis]
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

def generate_astrophage_world(name, seed):
    """
    Astrophage biosphere world — Adrian (TauCetiE).

    Visual style inspired by Eeloo: Voronoi biological-channel networks give
    branching dark fractures; crater rings create raised rims; combined height
    drives a strong (5.5x) normal map for genuine 3-D depth at orbital view.

    Height composition:
      45% large-scale bio-density (gas-world bands + cyclone swirls)
      35% crater field (45 impacts, parabolic floor + Gaussian rim)
      20% micro-roughness FBM
    Cracks further depress height along fracture lines.
    """
    W, H = WIDTH, HEIGHT
    print(f"  {name}  [astrophage world — Eeloo-style depth] ...", flush=True)

    # ── 1. Large-scale biological density (latitude-banded like a gas world) ──
    # 4 bands → broad, smooth Astrophage density zones (not tight stripes)
    bio = gas_band_field(W, H, seed, band_count=4, warp_y=0.10, warp_x=0.025)
    for (cx, cy, r, s) in [
        (0.30, 0.55, 0.10, +2.0),   # Great Astrophage Vortex (anticyclone)
        (0.68, 0.43, 0.07, -1.5),   # southern cyclone
        (0.14, 0.60, 0.06, +1.6),   # northern swirl
        (0.80, 0.38, 0.05, -1.1),   # small southern eddy
    ]:
        bio = add_swirl(bio, cx, cy, r, s)
    lo, hi = bio.min(), bio.max()
    bio = (bio - lo) / (hi - lo)
    # Very gentle contrast — smooth terrain-like biological density, not Jool bands
    bio = 0.5 + 0.5 * np.tanh((bio - 0.5) * 2.0)

    # ── 2. Voronoi biological channel / fracture network ──────────────────────
    # 22 points → sparse cracks like Eeloo (a few long branching fractures)
    frac = voronoi_edges(W, H, seed + 100, n_points=22)
    # crack_mask: 0 = at fracture centreline, 1 = cell interior
    # threshold 0.07 → thin lines (roughly 7% of the normalised range)
    crack_mask = np.clip(frac / 0.07, 0, 1) ** 2.0

    # Domain-warp the cracks lightly for an organic, non-geometric look
    wdx = fbm(W, H, seed + 150, octaves=4, roughness=0.60) - 0.5
    wdy = fbm(W, H, seed + 151, octaves=4, roughness=0.60) - 0.5
    row_idx = np.tile(np.arange(H)[:, np.newaxis], (1, W))
    col_idx = np.tile(np.arange(W)[np.newaxis, :], (H, 1))
    row_w = np.clip((row_idx + wdy * H * 0.025).astype(np.int32), 0, H - 1)
    col_w = np.clip((col_idx + wdx * W * 0.025).astype(np.int32), 0, W - 1)
    crack_mask = crack_mask[row_w, col_w]

    # ── 3. Crater height field ────────────────────────────────────────────────
    crater_h = add_craters(W, H, seed + 200, n_craters=40, max_radius_frac=0.040)

    # ── 4. Micro-roughness (Astrophage mat surface texture) ───────────────────
    micro = fbm(W, H, seed + 300, octaves=8, roughness=0.68)

    # ── 5. Composite height map ───────────────────────────────────────────────
    hfield = bio * 0.45 + crater_h * 0.35 + micro * 0.20
    # Biological channels sit lower in the topography
    hfield = hfield * (0.70 + crack_mask * 0.30)
    lo, hi = hfield.min(), hfield.max()
    hfield = (hfield - lo) / (hi - lo)

    # ── 6. Color map ──────────────────────────────────────────────────────────
    ADRIAN_COLORS = [
        (0.00, (  3,  16,   1)),   # near-black — deepest biological channels
        (0.12, (  8,  36,   4)),   # very dark green
        (0.25, ( 20,  78,  12)),   # dark forest green
        (0.40, ( 48, 148,  22)),   # medium-dark green
        (0.55, ( 88, 210,  35)),   # vivid mid green
        (0.70, (128, 245,  46)),   # bright lime
        (0.85, (148, 255,  52)),   # intense lime
        (1.00, (158, 255,  54)),   # peak lime — storm crests / Astrophage peak density
    ]
    color = apply_colormap(bio, ADRIAN_COLORS).astype(np.float64)

    # Darken crack/channel lines to near-black (biological channel valleys)
    crack_inf  = (1.0 - crack_mask)[..., np.newaxis]
    dark_ch    = np.array([4, 18, 2], dtype=np.float64)
    color      = color * (1.0 - crack_inf * 0.75) + dark_ch * crack_inf * 0.75

    # Slightly brighten crater rims — raised terrain hosts richer Astrophage growth
    rim_inf    = crater_h[..., np.newaxis]
    bright_rim = np.array([152, 255, 54], dtype=np.float64)
    color      = color * (1.0 - rim_inf * 0.10) + bright_rim * rim_inf * 0.10

    color = np.clip(color, 0, 255).astype(np.uint8)

    # Polar fade: Astrophage thins toward poles → dark forest green at caps
    color = add_polar_fade(color, fade_frac=0.20, pole_color=(12, 52, 6))

    # ── 7. Save ───────────────────────────────────────────────────────────────
    save_png(color,                                   f"{name}_color.png")
    save_png((hfield * 255).astype(np.uint8),         f"{name}_height.png")
    save_png(height_to_normal(hfield, strength=5.5),  f"{name}_normal.png")


def generate_gas_world(name, seed, band_count, band_colors, cell_colors=None,
                        warp_y=0.16, warp_x=0.04, swirls=None,
                        normal_strength=1.2, contrast_k=4.0,
                        sub_weight=0.12, cell_weight=0.10):
    """
    Gas / thick-atmosphere world.

    contrast_k:  tanh sharpness — 4.0 standard, 5.0 crisp Jool-quality.
    sub_weight:  fine sub-band teeth detail (set 0 for clean band edges).
    cell_weight: FBM cloud-cell noise (set 0 for clean bands).
    The band field is used for the normal map so sun-lighting tracks the cloud bands.
    """
    print(f"  {name}  [gas world] ...", flush=True)

    field = gas_band_field(WIDTH, HEIGHT, seed,
                            band_count=band_count, warp_y=warp_y, warp_x=warp_x,
                            sub_weight=sub_weight, cell_weight=cell_weight)

    if swirls:
        for (cx, cy, radius, strength) in swirls:
            field = add_swirl(field, cx, cy, radius, strength)

    lo, hi = field.min(), field.max()
    field = (field - lo) / (hi - lo) if hi > lo else field

    # Pre-blur before tanh: kills high-frequency warp noise so belt edges look
    # like rolling cloud layers, not teeth.  Large radius (14) smooths the
    # variation while keeping the overall band structure intact; tanh then
    # adds the high-contrast belt/zone snap back.
    field_img = Image.fromarray((field * 255).astype(np.uint8))
    field_img = field_img.filter(ImageFilter.GaussianBlur(radius=14))
    field = np.array(field_img, dtype=np.float64) / 255.0
    lo, hi = field.min(), field.max()
    field = (field - lo) / (hi - lo) if hi > lo else field

    # tanh contrast: pushes pixels toward belt-dark or zone-bright extremes
    field = 0.5 + 0.5 * np.tanh((field - 0.5) * contrast_k)

    color = apply_colormap(field, band_colors)

    if cell_colors:
        # Cloud-cell detail overlay — fine bright/dark patches within each band
        cells = fbm_horizontal(WIDTH, HEIGHT, seed + 10,
                                h_stretch=3.5, octaves=8, roughness=0.62)
        hi_mask = np.clip((cells - 0.48) / 0.36, 0, 1)
        hi_img  = Image.fromarray((hi_mask * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(radius=2))
        hi_mask  = np.array(hi_img, dtype=np.float64)[..., np.newaxis] / 255.0
        cell_rgb = apply_colormap(cells, cell_colors).astype(np.float64)
        color = np.clip(
            color.astype(np.float64) * (1 - hi_mask * 0.50)
            + cell_rgb * hi_mask * 0.50,
            0, 255
        ).astype(np.uint8)

    pole_rgb = band_colors[-1][1]
    color = add_polar_fade(color, fade_frac=0.18, pole_color=pole_rgb)

    # Height map: use band field for realistic depth → normal map lights up the bands
    save_png(color,                                    f"{name}_color.png")
    save_png((field * 255).astype(np.uint8),           f"{name}_height.png")
    save_png(height_to_normal(field, normal_strength),  f"{name}_normal.png")


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

    save_png(color,                                    f"{name}_color.png")
    save_png((terrain * 255).astype(np.uint8),         f"{name}_height.png")
    save_png(height_to_normal(terrain, normal_strength), f"{name}_normal.png")


# ── EVE cloud-map textures ────────────────────────────────────────────────────

def generate_eve_cloud_textures():
    """
    Generate grayscale cloud-map PNGs for EVE.
    white = opaque cloud,  black = clear sky (transparent).
    """
    print("\n  EVE cloud textures ...", flush=True)

    # cloud_dense: thick banded cloud deck
    field = gas_band_field(WIDTH, HEIGHT, seed=500, band_count=9,
                            warp_y=0.18, warp_x=0.05)
    cloud_mask = np.clip((field - 0.18) / 0.62, 0, 1)
    cloud_blur = Image.fromarray((cloud_mask * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(radius=3))
    save_png(np.array(cloud_blur), "EVE/cloud_dense.png")

    # cloud_medium
    field2 = gas_band_field(WIDTH, HEIGHT, seed=501, band_count=7,
                             warp_y=0.14, warp_x=0.04)
    cloud_mask2 = np.clip((field2 - 0.30) / 0.55, 0, 1)
    cloud_blur2 = Image.fromarray((cloud_mask2 * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(radius=2))
    save_png(np.array(cloud_blur2), "EVE/cloud_medium.png")

    # cloud_thin: sparse wisps
    field3 = gas_band_field(WIDTH, HEIGHT, seed=502, band_count=5,
                             warp_y=0.10, warp_x=0.03)
    cloud_mask3 = np.clip((field3 - 0.48) / 0.42, 0, 1)
    cloud_blur3 = Image.fromarray((cloud_mask3 * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(radius=2))
    save_png(np.array(cloud_blur3), "EVE/cloud_thin.png")

    # cloud_detail: high-frequency tiling cell texture
    detail = fbm_horizontal(512, 256, seed=503, h_stretch=2.5,
                             octaves=8, roughness=0.62)
    detail_img = Image.fromarray((detail * 255).astype(np.uint8)).resize(
        (WIDTH, HEIGHT), Image.BILINEAR)
    detail_sharp = np.clip(
        (np.array(detail_img, dtype=np.float64) / 255.0 - 0.3) / 0.55, 0, 1)
    save_png((detail_sharp * 255).astype(np.uint8), "EVE/cloud_detail.png")

    # smog_dense: near-uniform haze (68-100% coverage)
    smog = fbm_horizontal(WIDTH, HEIGHT, seed=504, h_stretch=10.0,
                           octaves=5, roughness=0.48)
    smog_base = 0.68 + (smog - smog.min()) / (smog.max() - smog.min() + 1e-8) * 0.32
    smog_blur = Image.fromarray((smog_base * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(radius=5))
    save_png(np.array(smog_blur), "EVE/smog_dense.png")

    # smog_detail: turbulent smog variation
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

    # ── ASTROPHAGE GAS WORLD ──────────────────────────────────────────────────

    # Adrian (TauCetiE) — THE GREEN PLANET
    # Gas-giant style: 4 wide bold belts, vivid lime zones — clean Jool look.
    # Low band count + low warp keeps bands wide, smooth, and clearly readable.
    generate_gas_world(
        name        = "TauCetiE",
        seed        = 91,
        band_count  = 6,
        warp_y      = 0.10,
        warp_x      = 0.025,
        sub_weight  = 0.0,
        cell_weight = 0.06,
        band_colors = [
            (0.00, ( 38, 100,  16)),   # dark forest belt — clearly green, not black
            (0.20, ( 50, 128,  22)),   # forest belt body
            (0.38, ( 76, 175,  30)),   # belt-to-zone transition
            (0.54, (108, 228,  40)),   # mid transition
            (0.68, (136, 250,  47)),   # vivid lime zone
            (0.84, (148, 255,  50)),   # bright lime
            (1.00, (155, 255,  52)),   # peak
        ],
        cell_colors = [
            (0.00, ( 30,  90,  14)),
            (0.50, ( 88, 200,  36)),
            (1.00, (145, 252,  50)),
        ],
        swirls = [
            (0.28, 0.56, 0.10, +2.5),
            (0.68, 0.42, 0.07, -1.8),
            (0.12, 0.62, 0.06, +1.6),
            (0.82, 0.38, 0.05, -1.2),
        ],
        normal_strength = 2.5,
        contrast_k      = 2.8,
    )

    # ── GAS / THICK-ATMOSPHERE WORLDS ─────────────────────────────────────────

    # Erid (EridianHome) — Rocky's homeworld; near-lightless under 28 atm ammonia smog
    generate_gas_world(
        name        = "EridianHome",
        seed        = 67,
        band_count  = 7,
        warp_y      = 0.14,
        warp_x      = 0.04,
        band_colors = [
            (0.00, (  5,   2,   1)),
            (0.18, ( 15,   8,   2)),
            (0.35, ( 40,  22,   6)),
            (0.50, ( 80,  48,  15)),
            (0.65, (130,  80,  28)),
            (0.82, (162, 102,  38)),
            (1.00, (178, 115,  44)),
        ],
        swirls = [
            (0.48, 0.50, 0.11, +2.5),
            (0.20, 0.58, 0.07, -1.9),
            (0.72, 0.40, 0.06, +1.7),
            (0.35, 0.32, 0.05, -1.3),
        ],
        normal_strength = 0.9,
    )

    # Tau Ceti c — Venus analog, 50 atm sulfuric acid clouds
    generate_gas_world(
        name        = "TauCetiC",
        seed        = 33,
        band_count  = 6,
        warp_y      = 0.08,
        warp_x      = 0.02,
        band_colors = [
            (0.00, ( 35,  20,   4)),
            (0.18, ( 65,  40,  10)),
            (0.35, (110,  75,  22)),
            (0.50, (165, 128,  45)),
            (0.65, (205, 168,  68)),
            (0.82, (228, 195,  82)),
            (1.00, (245, 215,  95)),
        ],
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
    print("Delete GameData/Kopernicus/Cache/*.bin, then relaunch KSP.")


if __name__ == "__main__":
    try:
        from PIL import Image, ImageFilter
        import numpy as np
    except ImportError:
        print("pip install Pillow numpy")
        sys.exit(1)
    main()
