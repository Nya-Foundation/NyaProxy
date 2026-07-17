# NyaProxy brand assets

The "Coin Cat" mark: a cat's head as negative space in a solid disc, closed by a
horizon line. Geometric, flat, two colors plus neutrals.

## Palette

| Role | Hex |
| --- | --- |
| Midnight (primary) | `#23264B` |
| Indigo (accent) | `#6C6FE0` (soft tint `#8A8DEB`) |
| Neutrals | white / off-white |

Wordmark: Space Grotesk Medium (outlined — the SVGs embed no fonts), lowercase
`nyaproxy`, light letterspacing.

## Files

| File | Use |
| --- | --- |
| `logo-horizontal-light.svg` | Lockup for **light** backgrounds (midnight artwork) |
| `logo-horizontal-dark.svg` | Lockup for **dark** backgrounds (white artwork) |
| `logo-mark-light.svg` / `logo-mark-dark.svg` | Standalone mark, same convention |
| `icon.svg` | Square app/favicon source (midnight), legible at 16px |
| `icon-512.png` | 512×512 raster icon, transparent background |
| `banner.svg` / `banner-1280x640.png` | GitHub social preview (1280×640) |

The dashboard serves an indigo variant of the mark (`nya/html/static/logo.svg`)
that keeps contrast on both dashboard themes; `nya/html/favicon.ico` carries
16/32/48 px renders of the icon.

All geometry is generated: see the mark construction in the repo history
(`scratchpad` scripts) or regenerate from `icon.svg`, which contains the
canonical path.
