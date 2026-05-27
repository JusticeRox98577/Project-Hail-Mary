#!/usr/bin/env python3
"""
Project Hail Mary — Terrain & Cloud Texture Generator
Generates tiling terrain textures for Parallax Continued and cloud textures for EVE.

Requirements:
    pip install Pillow numpy

Run from repo root:
    python Tools/generate_terrain_textures.py

Output:
    Tools/terrain_src/          ← source PNGs
    GameData/ProjectHailMary/Textures/Parallax/   ← DDS after conversion
    GameData/ProjectHailMary/Textures/EVE/         ← DDS after conversion

After running, convert to DDS with texconv:
    # Albedo (BC1/DXT1):
    texconv -f DXT1 -o GameData/ProjectHailMary/Textures/Parallax/ Tools/terrain_src/parallax/*.png
    texconv -f DXT1 -o GameData/ProjectHailMary/Textures/EVE/ Tools/terrain_src/eve/*.png

    # Normal maps (DXT5nm for Parallax):
    texconv -f DXT5 -ddn -o GameData/ProjectHailMary/Textures/Parallax/ Tools/terrain_src/parallax/*_nrm.png

    # Windows batch script (run_texconv.bat) is also generated automatically.
"""

import os, sys, struct
import numpy as np
from PIL import Image, ImageFilter

# ─── Output directories ───────────────────────────────────────────────────────

SRC_PARALLAX = os.path.join("Tools", "terrain_src", "parallax")
SRC_EVE      = os.path.join("Tools", "terrain_src", "eve")
DST_PARALLAX = os.path.join("GameData", "ProjectHailMary", "Textures", "Parallax")
DST_EVE      = os.path.join("GameData", "ProjectHailMary", "Textures", "EVE")

TILE_SIZE = 2048   # Parallax terrain tile resolution (2048×2048)
CLOUD_SIZE = 2048  # EVE cloud texture resolution


# ─── Fractal noise ────────────────────────────────────────────────────────────

def fbm(size, seed, octaves=8, roughness=0.55):
    """
    Fractal Brownian Motion — tileable by using bilinear-upsampled random grids.
    The base grid is small enough that it repeats cleanly when tiled.
    """
    np.random.seed(seed)
    terrain = np.zeros((size, size), dtype=np.float64)
    amp = 1.0
    for i in range(octaves):
        scale = max(2, 2 ** (octaves - i - 1))
        base  = np.random.random((scale, scale))
        # Tile the base grid before upsampling for seamless wrapping
        tiled = np.tile(base, (3, 3))
        img   = Image.fromarray((tiled * 255).astype(np.uint8))
        img   = img.resize((size * 3, size * 3), Image.BILINEAR)
        # Crop the centre tile — this guarantees the result tiles seamlessly
        arr   = np.array(img, dtype=np.float64)[size:size*2, size:size*2] / 255.0
        terrain += amp * arr
        amp   *= roughness
    lo, hi = terrain.min(), terrain.max()
    return (terrain - lo) / (hi - lo)


def fbm_detail(size, seed, octaves=6, roughness=0.62):
    """Higher roughness for detailed surface textures."""
    return fbm(size, seed, octaves=octaves, roughness=roughness)


# ─── Color mapping ────────────────────────────────────────────────────────────

def colorize(field, stops):
    """
    Map a [0,1] field to RGB using colour stops.
    stops: list of (value, (R,G,B)) tuples, values in ascending order.
    """
    h, w = field.shape
    rgb  = np.zeros((h, w, 3), dtype=np.float64)
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        span   = max(t1 - t0, 1e-9)
        mask   = (field >= t0) & (field < t1)
        frac   = np.where(mask, (field - t0) / span, 0.0)
        for ch in range(3):
            rgb[..., ch] += mask * (c0[ch] + frac * (c1[ch] - c0[ch]))
    t_last, c_last = stops[-1]
    mask = field >= t_last
    for ch in range(3):
        rgb[..., ch] += mask * c_last[ch]
    return np.clip(rgb, 0, 255).astype(np.uint8)


# ─── Normal map generation ────────────────────────────────────────────────────

def height_to_normal(field, strength=6.0):
    """
    Convert a [0,1] height field to a DirectX-convention normal map (RGB24).
    KSP/Unity on Windows: R=X, G=Y (inverted), B=Z.
    Returned as uint8 RGB array suitable for saving as PNG.
    """
    dx =  np.gradient(field, axis=1) * strength
    dy =  np.gradient(field, axis=0) * strength
    nx =  dx
    ny = -dy   # invert Y for DirectX convention
    nz =  np.ones_like(dx)
    length = np.sqrt(nx**2 + ny**2 + nz**2)
    nx /= length;  ny /= length;  nz /= length
    r = np.clip(( nx + 1) * 127.5, 0, 255).astype(np.uint8)
    g = np.clip(( ny + 1) * 127.5, 0, 255).astype(np.uint8)
    b = np.clip(( nz + 1) * 127.5, 0, 255).astype(np.uint8)
    return np.stack([r, g, b], axis=2)


# ─── DDS encoder (BC1 / DXT1) ─────────────────────────────────────────────────

def _rgb_to_565(r8, g8, b8):
    r5 = (r8.astype(np.uint32) >> 3) & 0x1F
    g6 = (g8.astype(np.uint32) >> 2) & 0x3F
    b5 = (b8.astype(np.uint32) >> 3) & 0x1F
    return ((r5 << 11) | (g6 << 5) | b5).astype(np.uint16)


def encode_bc1(img_rgb):
    """
    Encode a numpy uint8 RGB array (H×W×3, H and W multiples of 4) to BC1 bytes.
    Uses a simple min/max per-block approach — not maximum-quality but correct.
    Processing is chunked to stay under ~512 MB peak RAM.
    """
    H, W = img_rgb.shape[:2]
    assert H % 4 == 0 and W % 4 == 0, "Image dimensions must be multiples of 4"
    bH, bW = H // 4, W // 4
    N = bH * bW
    CHUNK = 2048  # blocks per chunk

    # Re-arrange: (bH, 4, bW, 4, 3) → (N, 16, 3)
    blocks_all = (img_rgb
                  .reshape(bH, 4, bW, 4, 3)
                  .swapaxes(1, 2)
                  .reshape(N, 16, 3)
                  .astype(np.int32))

    out_parts = []
    for start in range(0, N, CHUNK):
        blk = blocks_all[start:start + CHUNK]  # (chunk, 16, 3)
        C   = blk.shape[0]

        c0 = blk.max(axis=1).astype(np.uint8)   # (C, 3)
        c1 = blk.min(axis=1).astype(np.uint8)

        c0_565 = _rgb_to_565(c0[:, 0], c0[:, 1], c0[:, 2])
        c1_565 = _rgb_to_565(c1[:, 0], c1[:, 1], c1[:, 2])

        # Ensure c0 >= c1 (opaque mode)
        swap = c0_565 < c1_565
        tmp_565 = c0_565.copy(); c0_565[swap] = c1_565[swap]; c1_565[swap] = tmp_565[swap]
        tmp_c   = c0.copy();     c0[swap]     = c1[swap];     c1[swap]     = tmp_c[swap]

        # 4 interpolated palette entries: (C, 4, 3)
        c0f = c0[:, None, :].astype(np.float32)
        c1f = c1[:, None, :].astype(np.float32)
        col2 = ((2 * c0f + c1f) / 3)
        col3 = ((c0f + 2 * c1f) / 3)
        palette = np.concatenate([c0f, c1f, col2, col3], axis=1)  # (C, 4, 3)

        # Find closest palette entry for each pixel: (C, 16, 4) distance → index
        pix  = blk.astype(np.float32)                    # (C, 16, 3)
        diff = pix[:, :, None, :] - palette[:, None, :, :]  # (C, 16, 4, 3)
        dist = (diff ** 2).sum(axis=-1)                  # (C, 16, 4)
        idx  = dist.argmin(axis=-1).astype(np.uint32)    # (C, 16)

        # Pack 16 × 2-bit indices into one uint32
        shifts = np.arange(16, dtype=np.uint32) * 2      # [0,2,4,...,30]
        packed = (idx * (1 << shifts)).sum(axis=1).astype(np.uint32)  # (C,)

        # Serialise: 2B c0_565 (LE) + 2B c1_565 (LE) + 4B packed (LE) = 8 bytes/block
        chunk_bytes = np.empty((C, 8), dtype=np.uint8)
        chunk_bytes[:, 0] = (c0_565 & 0xFF).astype(np.uint8)
        chunk_bytes[:, 1] = ((c0_565 >> 8) & 0xFF).astype(np.uint8)
        chunk_bytes[:, 2] = (c1_565 & 0xFF).astype(np.uint8)
        chunk_bytes[:, 3] = ((c1_565 >> 8) & 0xFF).astype(np.uint8)
        chunk_bytes[:, 4] = (packed & 0xFF).astype(np.uint8)
        chunk_bytes[:, 5] = ((packed >> 8)  & 0xFF).astype(np.uint8)
        chunk_bytes[:, 6] = ((packed >> 16) & 0xFF).astype(np.uint8)
        chunk_bytes[:, 7] = ((packed >> 24) & 0xFF).astype(np.uint8)
        out_parts.append(chunk_bytes.tobytes())

    return b''.join(out_parts)


def write_dds_bc1(img_rgb, filepath):
    """Write a BC1/DXT1 DDS file. img_rgb must be uint8 numpy array (H×W×3)."""
    H, W = img_rgb.shape[:2]
    data   = encode_bc1(img_rgb)
    linear = ((W + 3) // 4) * ((H + 3) // 4) * 8

    # DDS header — 128 bytes total
    # dwFlags: DDSD_CAPS(0x1) | DDSD_HEIGHT(0x2) | DDSD_WIDTH(0x4) |
    #          DDSD_PIXELFORMAT(0x1000) | DDSD_LINEARSIZE(0x80000) = 0x81007
    hdr = struct.pack('<4sIIIIIII',
        b'DDS ', 124, 0x81007, H, W, linear, 0, 0)
    hdr += struct.pack('<11I', *([0] * 11))  # reserved1[11]

    # DDPIXELFORMAT (32 bytes)
    # dwFlags: DDPF_FOURCC(0x4)  dwFourCC: 'DXT1'
    pf = struct.pack('<II4sIIIII',
        32, 0x4, b'DXT1', 0, 0, 0, 0, 0)

    # DDCAPS (20 bytes) — DDSCAPS_TEXTURE(0x1000)
    caps = struct.pack('<IIIII', 0x1000, 0, 0, 0, 0)

    with open(filepath, 'wb') as f:
        f.write(hdr + pf + caps + data)


# ─── Save helpers ─────────────────────────────────────────────────────────────

def save_png(arr, path, label=""):
    mode = 'L' if arr.ndim == 2 else 'RGB'
    Image.fromarray(arr, mode).save(path)
    if label:
        print(f"    PNG  {os.path.basename(path)}" + (f"  ({label})" if label else ""))


def save_dds(arr, path, label=""):
    """Save a uint8 RGB array directly as a DDS BC1 file."""
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=2)
    write_dds_bc1(arr, path)
    if label:
        print(f"    DDS  {os.path.basename(path)}" + (f"  ({label})" if label else ""))


# ─── Terrain texture builder ──────────────────────────────────────────────────

def make_terrain_texture(name, seed, size, stops, normal_strength=8.0,
                         roughness=0.60, octaves=8, extra_seed=None):
    """
    Generate one terrain tile (albedo PNG + normal PNG + DDS versions).
    Also writes DDS directly so the mod can ship without texconv.
    """
    field = fbm_detail(size, seed, octaves=octaves, roughness=roughness)
    if extra_seed is not None:
        field2 = fbm_detail(size, extra_seed, octaves=5, roughness=0.70)
        field  = np.clip(field * 0.75 + field2 * 0.25, 0, 1)
        field  = (field - field.min()) / (field.max() - field.min())

    albedo = colorize(field, stops)
    normal = height_to_normal(field, strength=normal_strength)

    # PNG source files
    albedo_png = os.path.join(SRC_PARALLAX, f"{name}.png")
    normal_png = os.path.join(SRC_PARALLAX, f"{name}_nrm.png")
    save_png(albedo, albedo_png)
    save_png(normal, normal_png)

    # DDS files written directly (BC1 — good enough for terrain tiles)
    albedo_dds = os.path.join(DST_PARALLAX, f"{name}.dds")
    normal_dds = os.path.join(DST_PARALLAX, f"{name}_nrm.dds")
    save_dds(albedo, albedo_dds, label="albedo")
    save_dds(normal, normal_dds, label="normal")


# ─── Cloud texture builder ─────────────────────────────────────────────────────

def make_cloud_texture(name, seed, size, texture_type="generic",
                       octaves=6, roughness=0.62):
    """
    Generate a purpose-built cloud/smog texture for EVE.
    Greyscale PNG: white=opaque, black=transparent. EVE _Color tints the result.

    texture_type options:
      "dense"      — large-scale cloud masses, ~65% coverage, sharp edges
      "medium"     — medium coverage ~45%, more gaps visible
      "thin"       — horizontal banding pattern, good for gas-giant main tex
      "detail"     — fine swirling cloud cells for close-up detail tile
      "smog"       — near-opaque uniform smog deck, 70-100% coverage
      "smog_detail"— turbulence swirl for smog close-up
      "generic"    — raw fbm with supplied octaves/roughness (legacy fallback)
    """
    if texture_type == "dense":
        # BIG cloud masses: low-octave fbm gives features 1/4–1/8 of image size
        large = fbm(size, seed,      octaves=3, roughness=0.72)
        mid   = fbm(size, seed + 50, octaves=6, roughness=0.65)
        field = large * 0.70 + mid * 0.30
        lo, hi = field.min(), field.max()
        field = (field - lo) / (hi - lo)
        # tanh sharpening: push toward 0/1, threshold 0.48 → ~65% coverage
        field = 0.5 + 0.5 * np.tanh((field - 0.48) * 5.0)

    elif texture_type == "medium":
        large = fbm(size, seed,      octaves=3, roughness=0.65)
        mid   = fbm(size, seed + 50, octaves=6, roughness=0.60)
        field = large * 0.65 + mid * 0.35
        lo, hi = field.min(), field.max()
        field = (field - lo) / (hi - lo)
        # threshold 0.52 → ~45% coverage
        field = 0.5 + 0.5 * np.tanh((field - 0.52) * 4.0)

    elif texture_type == "thin":
        # Horizontal gas-giant banding warped by turbulence
        field = fbm(size, seed, octaves=5, roughness=0.50)
        lo, hi = field.min(), field.max()
        field = (field - lo) / (hi - lo)
        # Strong contrast: distinct bright zones and dark belts
        field = 0.5 + 0.5 * np.tanh((field - 0.5) * 5.0)

    elif texture_type == "detail":
        # Fine swirling cloud cells — tiled many times, adds close-up detail
        field = fbm(size, seed, octaves=9, roughness=0.72)
        lo, hi = field.min(), field.max()
        field = (field - lo) / (hi - lo)
        # Moderate sharpening — want visible swirls without pure black/white
        field = 0.5 + 0.5 * np.tanh((field - 0.5) * 2.5)

    elif texture_type == "smog":
        # Near-opaque smog deck: always 68–100% opaque, gentle variation
        base = fbm(size, seed, octaves=4, roughness=0.55)
        lo, hi = base.min(), base.max()
        base = (base - lo) / (hi - lo)
        field = 0.68 + base * 0.32  # clamp to [0.68, 1.0]

    elif texture_type == "smog_detail":
        # Fine turbulence swirl for smog close-up
        field = fbm(size, seed, octaves=8, roughness=0.70)
        lo, hi = field.min(), field.max()
        field = (field - lo) / (hi - lo)
        field = 0.5 + 0.5 * np.tanh((field - 0.5) * 2.0)

    else:  # generic / legacy fallback
        field = fbm(size, seed, octaves=octaves, roughness=roughness)
        lo, hi = field.min(), field.max()
        field = (field - lo) / (hi - lo)

    field = np.clip(field, 0.0, 1.0)
    arr   = (field * 255).astype(np.uint8)
    rgb   = np.stack([arr, arr, arr], axis=2)

    # Source PNG (gitignored terrain_src/ dir)
    png_src = os.path.join(SRC_EVE, f"{name}.png")
    save_png(rgb, png_src)

    # GameData PNG — committed to git (DDS is gitignored)
    png_dst = os.path.join(DST_EVE, f"{name}.png")
    save_png(rgb, png_dst)

    # DDS for local testing (gitignored)
    dds_path = os.path.join(DST_EVE, f"{name}.dds")
    save_dds(rgb, dds_path, label=name)


# ─── Terrain texture definitions ─────────────────────────────────────────────
#
# Colour stops for each terrain type — tuned to the book/film descriptions.
# Format: (height_value 0-1, (R, G, B))
# ─────────────────────────────────────────────────────────────────────────────

TERRAIN_TEXTURES = [

    # ── dark_basalt ─ TauCetiB / general airless dark rock ────────────────────
    dict(name="dark_basalt",  seed=100, roughness=0.72, octaves=9,
         normal_strength=9.0,
         stops=[
             (0.00, ( 18,  17,  18)),
             (0.25, ( 28,  27,  28)),
             (0.55, ( 42,  40,  42)),
             (0.78, ( 58,  56,  58)),
             (1.00, ( 78,  75,  78)),
         ]),

    # ── volcanic_basalt ─ TauCetiG lowlands ───────────────────────────────────
    dict(name="volcanic_basalt",  seed=101, roughness=0.68, octaves=8,
         normal_strength=10.0,
         stops=[
             (0.00, ( 12,   4,   2)),
             (0.20, ( 28,  10,   4)),
             (0.45, ( 52,  20,   8)),
             (0.70, ( 78,  32,  12)),
             (1.00, (105,  48,  18)),
         ]),

    # ── lava_rock ─ TauCetiG hot zones / mid-high ────────────────────────────
    dict(name="lava_rock",  seed=102, roughness=0.65, octaves=8,
         normal_strength=10.0, extra_seed=202,
         stops=[
             (0.00, (  8,   2,   0)),
             (0.15, ( 22,   6,   0)),
             (0.35, ( 55,  18,   4)),
             (0.55, ( 98,  36,   8)),
             (0.75, (155,  62,  14)),
             (1.00, (200,  92,  24)),
         ]),

    # ── acid_highland ─ TauCetiC surface (unreachable) ────────────────────────
    dict(name="acid_highland",  seed=103, roughness=0.60, octaves=7,
         normal_strength=7.0,
         stops=[
             (0.00, ( 55,  35,   8)),
             (0.30, ( 88,  58,  14)),
             (0.60, (125,  88,  22)),
             (0.85, (158, 118,  34)),
             (1.00, (188, 148,  48)),
         ]),

    # ── charcoal_sand ─ TauCetiD flat plains ─────────────────────────────────
    dict(name="charcoal_sand",  seed=104, roughness=0.55, octaves=7,
         normal_strength=5.0,
         stops=[
             (0.00, ( 38,  35,  30)),
             (0.30, ( 58,  54,  46)),
             (0.60, ( 78,  73,  62)),
             (0.85, ( 98,  92,  80)),
             (1.00, (118, 112,  98)),
         ]),

    # ── charcoal_cliff ─ TauCetiD steep faces ────────────────────────────────
    dict(name="charcoal_cliff",  seed=105, roughness=0.74, octaves=9,
         normal_strength=11.0,
         stops=[
             (0.00, ( 28,  26,  22)),
             (0.25, ( 42,  39,  34)),
             (0.55, ( 60,  56,  48)),
             (0.80, ( 80,  75,  66)),
             (1.00, (102,  96,  85)),
         ]),

    # ── astrophage_wet ─ TauCetiE low altitude (wet Astrophage rock) ──────────
    # Key texture. Teal-green, wet-looking, Astrophage colony.
    dict(name="astrophage_wet",  seed=106, roughness=0.65, octaves=8,
         normal_strength=7.0, extra_seed=206,
         stops=[
             (0.00, ( 22,  55,  48)),
             (0.22, ( 35,  82,  70)),
             (0.45, ( 48, 110,  92)),
             (0.68, ( 60, 135, 112)),
             (0.88, ( 75, 158, 130)),
             (1.00, ( 90, 178, 148)),
         ]),

    # ── astrophage_mid ─ TauCetiE mid altitude ────────────────────────────────
    dict(name="astrophage_mid",  seed=107, roughness=0.62, octaves=7,
         normal_strength=8.0,
         stops=[
             (0.00, ( 18,  42,  38)),
             (0.30, ( 30,  68,  58)),
             (0.60, ( 42,  92,  78)),
             (0.85, ( 55, 115,  96)),
             (1.00, ( 68, 135, 112)),
         ]),

    # ── astrophage_high ─ TauCetiE high peaks (above Astrophage saturation) ──
    dict(name="astrophage_high",  seed=108, roughness=0.60, octaves=7,
         normal_strength=9.0,
         stops=[
             (0.00, ( 42,  55,  52)),
             (0.30, ( 62,  78,  72)),
             (0.60, ( 82, 100,  92)),
             (0.85, (102, 122, 112)),
             (1.00, (125, 145, 135)),
         ]),

    # ── astrophage_cliff ─ TauCetiE cliff faces (dark basalt breaks through) ──
    dict(name="astrophage_cliff",  seed=109, roughness=0.75, octaves=9,
         normal_strength=12.0,
         stops=[
             (0.00, ( 12,  18,  15)),
             (0.25, ( 22,  35,  30)),
             (0.55, ( 35,  55,  46)),
             (0.80, ( 48,  72,  62)),
             (1.00, ( 62,  90,  78)),
         ]),

    # ── ice_flat ─ TauCetiF ice fields ────────────────────────────────────────
    dict(name="ice_flat",  seed=110, roughness=0.48, octaves=6,
         normal_strength=4.0,
         stops=[
             (0.00, (185, 202, 225)),
             (0.30, (200, 215, 235)),
             (0.60, (215, 228, 244)),
             (0.82, (228, 238, 250)),
             (1.00, (242, 248, 255)),
         ]),

    # ── ice_cliff ─ TauCetiF fractured ice cliffs ─────────────────────────────
    dict(name="ice_cliff",  seed=111, roughness=0.70, octaves=9,
         normal_strength=10.0,
         stops=[
             (0.00, (148, 172, 205)),
             (0.25, (168, 190, 218)),
             (0.55, (188, 208, 232)),
             (0.80, (208, 224, 244)),
             (1.00, (228, 240, 254)),
         ]),

    # ── iron_basalt ─ FortyEridaniI rust-red rock ─────────────────────────────
    dict(name="iron_basalt",  seed=112, roughness=0.68, octaves=8,
         normal_strength=9.0,
         stops=[
             (0.00, ( 58,  18,   6)),
             (0.22, ( 90,  32,  12)),
             (0.48, (128,  52,  20)),
             (0.72, (162,  72,  28)),
             (1.00, (192,  95,  38)),
         ]),

    # ── iron_steep ─ FortyEridaniI cliff faces ────────────────────────────────
    dict(name="iron_steep",  seed=113, roughness=0.72, octaves=9,
         normal_strength=11.0,
         stops=[
             (0.00, ( 42,  12,   4)),
             (0.28, ( 72,  24,  10)),
             (0.55, (108,  42,  16)),
             (0.80, (148,  62,  24)),
             (1.00, (182,  82,  32)),
         ]),

    # ── lava_basalt ─ EridianHome floor (near-black volcanic glass) ───────────
    dict(name="lava_basalt",  seed=114, roughness=0.70, octaves=9,
         normal_strength=10.0,
         stops=[
             (0.00, (  6,   2,   0)),
             (0.20, ( 14,   5,   1)),
             (0.45, ( 28,  10,   2)),
             (0.70, ( 48,  18,   4)),
             (1.00, ( 72,  28,   7)),
         ]),

    # ── lava_mid ─ EridianHome mid terrain (pahoehoe fields) ─────────────────
    dict(name="lava_mid",  seed=115, roughness=0.66, octaves=8,
         normal_strength=9.0, extra_seed=215,
         stops=[
             (0.00, ( 10,   4,   1)),
             (0.20, ( 22,   8,   2)),
             (0.45, ( 42,  16,   4)),
             (0.70, ( 68,  28,   7)),
             (1.00, ( 98,  42,  11)),
         ]),

    # ── lava_high ─ EridianHome ridges (jagged volcanic crust) ───────────────
    dict(name="lava_high",  seed=116, roughness=0.68, octaves=8,
         normal_strength=11.0,
         stops=[
             (0.00, ( 14,   5,   1)),
             (0.25, ( 30,  10,   2)),
             (0.50, ( 55,  20,   5)),
             (0.75, ( 85,  32,   8)),
             (1.00, (118,  45,  12)),
         ]),

    # ── lava_cliff ─ EridianHome near-vertical volcanic faces ─────────────────
    dict(name="lava_cliff",  seed=117, roughness=0.75, octaves=9,
         normal_strength=13.0,
         stops=[
             (0.00, (  4,   1,   0)),
             (0.25, ( 12,   4,   1)),
             (0.55, ( 28,  10,   2)),
             (0.80, ( 52,  18,   4)),
             (1.00, ( 80,  28,   7)),
         ]),

    # ── frozen_dust ─ FortyEridaniIII permafrost plains ───────────────────────
    dict(name="frozen_dust",  seed=118, roughness=0.55, octaves=7,
         normal_strength=5.0,
         stops=[
             (0.00, ( 72,  58,  44)),
             (0.28, ( 95,  78,  60)),
             (0.55, (118,  98,  76)),
             (0.78, (142, 118,  92)),
             (1.00, (168, 140, 110)),
         ]),

    # ── frozen_cliff ─ FortyEridaniIII exposed bedrock cliffs ─────────────────
    dict(name="frozen_cliff",  seed=119, roughness=0.68, octaves=8,
         normal_strength=9.0,
         stops=[
             (0.00, ( 52,  40,  28)),
             (0.25, ( 72,  58,  42)),
             (0.55, ( 95,  78,  58)),
             (0.80, (118,  98,  74)),
             (1.00, (145, 120,  92)),
         ]),
]


# ─── EVE cloud texture definitions ───────────────────────────────────────────
#
# texture_type controls the generator used — see make_cloud_texture docstring.
# seed must be unique per texture.
# ─────────────────────────────────────────────────────────────────────────────

EVE_TEXTURES = [

    # Large-scale cloud masses — main layer for TauCetiC, also smog-world decks.
    # Produces big white cloud regions and clear dark holes (≈65% coverage).
    dict(name="cloud_dense",  seed=200, texture_type="dense"),

    # Medium cloud coverage (~45%) — for secondary cloud layers.
    dict(name="cloud_medium", seed=210, texture_type="medium"),

    # Horizontal gas-giant banding — primary MainTex for TauCetiE, EridianHome.
    # Wraps around sphere as alternating dark belts and bright zones.
    dict(name="cloud_thin",   seed=202, texture_type="thin"),

    # Fine swirling cloud cells — always used as DetailTex (tiled 12–16×).
    # Provides close-up cloud detail when approaching from orbit.
    dict(name="cloud_detail", seed=203, texture_type="detail"),

    # Near-opaque smog — EridianHome main deck, 70–100% coverage, smooth.
    dict(name="smog_dense",   seed=204, texture_type="smog"),

    # Fine smog turbulence — DetailTex for smog-world layers.
    dict(name="smog_detail",  seed=205, texture_type="smog_detail"),
]


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    for d in [SRC_PARALLAX, SRC_EVE, DST_PARALLAX, DST_EVE]:
        os.makedirs(d, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Project Hail Mary — Terrain Texture Generator")
    print(f"{'='*60}")

    # ── Terrain textures ──────────────────────────────────────────────────────
    print(f"\n[1/2] Generating {len(TERRAIN_TEXTURES)} Parallax terrain tiles "
          f"({TILE_SIZE}×{TILE_SIZE}) ...\n")
    for i, spec in enumerate(TERRAIN_TEXTURES, 1):
        name   = spec["name"]
        seed   = spec["seed"]
        stops  = spec["stops"]
        ns     = spec.get("normal_strength", 8.0)
        rough  = spec.get("roughness", 0.60)
        oct    = spec.get("octaves", 8)
        extra  = spec.get("extra_seed", None)
        print(f"  [{i:02d}/{len(TERRAIN_TEXTURES):02d}] {name}")
        make_terrain_texture(name, seed, TILE_SIZE, stops,
                             normal_strength=ns, roughness=rough,
                             octaves=oct, extra_seed=extra)

    # ── EVE cloud textures ────────────────────────────────────────────────────
    print(f"\n[2/2] Generating {len(EVE_TEXTURES)} EVE cloud textures "
          f"({CLOUD_SIZE}×{CLOUD_SIZE}) ...\n")
    for i, spec in enumerate(EVE_TEXTURES, 1):
        name  = spec["name"]
        seed  = spec["seed"]
        ttype = spec.get("texture_type", "generic")
        oct   = spec.get("octaves", 6)
        rough = spec.get("roughness", 0.62)
        print(f"  [{i:02d}/{len(EVE_TEXTURES):02d}] {name}  [{ttype}]")
        make_cloud_texture(name, seed, CLOUD_SIZE,
                           texture_type=ttype, octaves=oct, roughness=rough)

    # ── Summary ───────────────────────────────────────────────────────────────
    n_terrain = len(TERRAIN_TEXTURES)
    n_eve     = len(EVE_TEXTURES)
    print(f"\n{'='*60}")
    print(f"  Done!")
    print(f"  Terrain tiles : {n_terrain * 2} DDS  ({n_terrain} albedo + {n_terrain} normal)")
    print(f"  EVE textures  : {n_eve} DDS")
    print(f"  Source PNGs   : {(n_terrain * 2 + n_eve)} files in Tools/terrain_src/")
    print(f"\n  DDS files written directly to:")
    print(f"    {os.path.abspath(DST_PARALLAX)}")
    print(f"    {os.path.abspath(DST_EVE)}")
    print(f"\n  For higher-quality normal maps, convert with texconv:")
    print(f"    texconv -f DXT5 -ddn -o {DST_PARALLAX}\\ Tools\\terrain_src\\parallax\\*_nrm.png")
    print(f"\n  Delete GameData/Kopernicus/Cache/*.bin before launching KSP.")
    print(f"{'='*60}\n")

    # Generate a convenience Windows batch script
    bat_path = os.path.join("Tools", "convert_terrain_textures.bat")
    with open(bat_path, "w") as f:
        f.write("@echo off\n")
        f.write(":: Project Hail Mary — texconv conversion script\n")
        f.write(":: Run from repo root after generate_terrain_textures.py\n\n")
        f.write(f'texconv -f DXT1 -o "{DST_PARALLAX}" Tools\\terrain_src\\parallax\\*[!m].png\n')
        f.write(f'texconv -f DXT5 -ddn -o "{DST_PARALLAX}" Tools\\terrain_src\\parallax\\*_nrm.png\n')
        f.write(f'texconv -f DXT1 -o "{DST_EVE}" Tools\\terrain_src\\eve\\*.png\n')
        f.write("echo Done.\n")
    print(f"  Batch script: {bat_path}\n")


if __name__ == "__main__":
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        print("Missing dependencies.  Run:  pip install Pillow numpy")
        sys.exit(1)
    main()
