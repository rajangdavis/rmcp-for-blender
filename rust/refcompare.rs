//! Putting a render beside the picture it is meant to match.
//!
//! `compare` writes one PNG: the reference on the left, the render on the right,
//! a magenta bar between them. Regions not built yet (a figure still to come, a
//! title that will be added later) are masked out of both with the same flat
//! grey, so the eye judges only what exists in both. An optional region zooms
//! both images on the same part of the frame.
//!
//! This is deliberately a picture and not a score. On 2026-10-13 SSIM, an edge
//! SSIM and a colour histogram all ranked the render the owner judged worst as
//! the best of twelve: averages reward a flat grey wash. Seeing the two side by
//! side is what found the real differences.

use image::{imageops, Rgb, RgbImage};

const GAP: u32 = 6;
const BAR: Rgb<u8> = Rgb([255, 0, 255]);
const MASKED: Rgb<u8> = Rgb([64, 64, 64]);

type Polygon = Vec<(f64, f64)>;

/// One masked region. With a colour, only the reference's pixels within
/// `tolerance` of it (per channel, 0-255) are masked inside the polygon, so a
/// title can be greyed out letter by letter while the scene behind it shows.
#[derive(Debug)]
struct Mask {
    polygon: Polygon,
    colour: Option<([u8; 3], u8)>,
}

/// "#rrggbb" or "#rrggbb~tolerance"; the tolerance defaults to 40.
fn parse_colour(text: &str) -> Result<([u8; 3], u8), String> {
    let (hex, tolerance) = match text.split_once('~') {
        Some((hex, t)) => (hex.trim(), t.trim().parse::<u8>().map_err(|_| format!("mask colour {:?}: tolerance {:?} is not 0-255", text, t))?),
        None => (text.trim(), 40),
    };
    let hex = hex.strip_prefix('#').unwrap_or(hex);
    if hex.len() != 6 {
        return Err(format!("mask colour {:?} is not #rrggbb", text));
    }
    let byte = |i: usize| u8::from_str_radix(&hex[i..i + 2], 16).map_err(|_| format!("mask colour {:?} is not #rrggbb", text));
    Ok(([byte(0)?, byte(2)?, byte(4)?], tolerance))
}

/// Polygons as "u v, u v, u v; u v, ..." in fractions of the frame, origin
/// top-left, each optionally prefixed "#rrggbb~tolerance:" to mask only that colour.
fn parse_mask(text: &str) -> Result<Vec<Mask>, String> {
    let mut masks = Vec::new();
    for part in text.split(';').map(str::trim).filter(|p| !p.is_empty()) {
        let (colour, part) = match part.split_once(':') {
            Some((spec, rest)) => (Some(parse_colour(spec)?), rest.trim()),
            None => (None, part),
        };
        let mut polygon = Vec::new();
        for point in part.split(',').map(str::trim).filter(|p| !p.is_empty()) {
            let numbers: Vec<&str> = point.split_whitespace().collect();
            if numbers.len() != 2 {
                return Err(format!("mask point {:?} is not \"u v\"", point));
            }
            let u: f64 = numbers[0].parse().map_err(|_| format!("mask point {:?}: {:?} is not a number", point, numbers[0]))?;
            let v: f64 = numbers[1].parse().map_err(|_| format!("mask point {:?}: {:?} is not a number", point, numbers[1]))?;
            polygon.push((u, v));
        }
        if polygon.len() < 3 {
            return Err(format!("mask polygon {:?} needs at least three points", part));
        }
        masks.push(Mask { polygon, colour });
    }
    Ok(masks)
}

/// "u0 v0 u1 v1" in fractions of the frame; empty is the whole frame.
fn parse_region(text: &str) -> Result<(f64, f64, f64, f64), String> {
    if text.trim().is_empty() {
        return Ok((0.0, 0.0, 1.0, 1.0));
    }
    let n: Vec<f64> = text
        .split_whitespace()
        .map(|s| s.parse::<f64>().map_err(|_| format!("region {:?}: {:?} is not a number", text, s)))
        .collect::<Result<_, _>>()?;
    if n.len() != 4 {
        return Err(format!("region {:?} is not \"u0 v0 u1 v1\"", text));
    }
    let (u0, v0, u1, v1) = (n[0].max(0.0), n[1].max(0.0), n[2].min(1.0), n[3].min(1.0));
    if u1 - u0 < 0.01 || v1 - v0 < 0.01 {
        return Err(format!("region {:?} is empty: u0 < u1 and v0 < v1, each between 0 and 1", text));
    }
    Ok((u0, v0, u1, v1))
}

fn inside(u: f64, v: f64, polygon: &Polygon) -> bool {
    let mut hit = false;
    let mut j = polygon.len() - 1;
    for i in 0..polygon.len() {
        let (ui, vi) = polygon[i];
        let (uj, vj) = polygon[j];
        if (vi > v) != (vj > v) && u < (uj - ui) * (v - vi) / (vj - vi) + ui {
            hit = !hit;
        }
        j = i;
    }
    hit
}

/// One panel: the region of `image`, resized to `width` x `height`.
fn panel(image: &RgbImage, region: (f64, f64, f64, f64), width: u32, height: u32) -> RgbImage {
    let (w, h) = image.dimensions();
    let x = (region.0 * w as f64).floor() as u32;
    let y = (region.1 * h as f64).floor() as u32;
    let cw = (((region.2 - region.0) * w as f64).round() as u32).clamp(1, w - x);
    let ch = (((region.3 - region.1) * h as f64).round() as u32).clamp(1, h - y);
    let cut = imageops::crop_imm(image, x, y, cw, ch).to_image();
    imageops::resize(&cut, width, height, imageops::FilterType::Triangle)
}

/// Write the side-by-side comparison to `out` and describe it; a failure comes
/// back as text starting "compare failed:".
pub fn compare(reference: &str, render: &str, mask: &str, region: &str, size: i32, out: &str) -> String {
    match build(reference, render, mask, region, size, out) {
        Ok(caption) => caption,
        Err(message) => format!("compare failed: {}", message),
    }
}

fn build(reference: &str, render: &str, mask: &str, region: &str, size: i32, out: &str) -> Result<String, String> {
    let masks = parse_mask(mask)?;
    let region = parse_region(region)?;
    let open = |path: &str| image::open(path).map(|i| i.to_rgb8()).map_err(|e| format!("cannot load {}: {}", path, e));
    let left_full = open(reference)?;
    let right_full = open(render)?;

    // The panel follows the reference region's aspect; the longest side is `size`.
    let (rw, rh) = left_full.dimensions();
    let aspect = ((region.2 - region.0) * rw as f64) / ((region.3 - region.1) * rh as f64);
    let size = size.clamp(128, 1000) as u32;
    let (pw, ph) = if aspect >= 1.0 {
        (size, ((size as f64) / aspect).round().max(1.0) as u32)
    } else {
        (((size as f64) * aspect).round().max(1.0) as u32, size)
    };
    let left = panel(&left_full, region, pw, ph);
    let right = panel(&right_full, region, pw, ph);

    // Whole polygons mask outright; colour polygons mask the reference's matching
    // pixels, grown by one pixel so anti-aliased letter edges go too.
    let (w, h) = (pw as usize, ph as usize);
    let mut hidden = vec![false; w * h];
    let mut by_colour = vec![false; w * h];
    for y in 0..h {
        let v = region.1 + (y as f64 + 0.5) / ph as f64 * (region.3 - region.1);
        for x in 0..w {
            let u = region.0 + (x as f64 + 0.5) / pw as f64 * (region.2 - region.0);
            let pixel = left.get_pixel(x as u32, y as u32).0;
            for m in masks.iter().filter(|m| inside(u, v, &m.polygon)) {
                match m.colour {
                    None => hidden[y * w + x] = true,
                    Some((c, t)) if (0..3).all(|i| pixel[i].abs_diff(c[i]) <= t) => by_colour[y * w + x] = true,
                    Some(_) => {}
                }
            }
        }
    }
    for y in 0..h {
        for x in 0..w {
            if by_colour[y * w + x] {
                for (dx, dy) in [(-1i64, -1i64), (0, -1), (1, -1), (-1, 0), (0, 0), (1, 0), (-1, 1), (0, 1), (1, 1)] {
                    let (nx, ny) = (x as i64 + dx, y as i64 + dy);
                    if nx >= 0 && ny >= 0 && (nx as usize) < w && (ny as usize) < h {
                        hidden[ny as usize * w + nx as usize] = true;
                    }
                }
            }
        }
    }

    let mut canvas = RgbImage::from_pixel(pw * 2 + GAP, ph, BAR);
    let mut masked = 0u64;
    for y in 0..ph {
        for x in 0..pw {
            if hidden[y as usize * w + x as usize] {
                masked += 1;
                canvas.put_pixel(x, y, MASKED);
                canvas.put_pixel(pw + GAP + x, y, MASKED);
            } else {
                canvas.put_pixel(x, y, *left.get_pixel(x, y));
                canvas.put_pixel(pw + GAP + x, y, *right.get_pixel(x, y));
            }
        }
    }
    if let Some(dir) = std::path::Path::new(out).parent() {
        std::fs::create_dir_all(dir).map_err(|e| format!("cannot create {}: {}", dir.display(), e))?;
    }
    canvas.save(out).map_err(|e| format!("cannot write {}: {}", out, e))?;
    let (lw, lh) = right_full.dimensions();
    Ok(format!(
        "reference (left, {}x{}) | render (right, {}x{}); region u {:.2}-{:.2}, v {:.2}-{:.2}; {} mask polygon(s) cover {:.0}% of the view; wrote {} ({}x{})",
        rw, rh, lw, lh, region.0, region.2, region.1, region.3,
        masks.len(), 100.0 * masked as f64 / (pw * ph) as f64, out, pw * 2 + GAP, ph
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp(name: &str) -> String {
        std::env::temp_dir().join(name).to_string_lossy().into_owned()
    }

    fn flat(path: &str, colour: [u8; 3], width: u32, height: u32) {
        RgbImage::from_pixel(width, height, Rgb(colour)).save(path).expect("write the probe image");
    }

    #[test]
    fn puts_reference_left_render_right_with_a_bar_between() {
        let (a, b, out) = (temp("rc-ref.png"), temp("rc-ren.png"), temp("rc-out.png"));
        flat(&a, [200, 0, 0], 300, 300);
        flat(&b, [0, 0, 200], 600, 600);
        let caption = compare(&a, &b, "", "", 200, &out);
        assert!(caption.starts_with("reference"), "{}", caption);
        let img = image::open(&out).unwrap().to_rgb8();
        assert_eq!(img.dimensions(), (406, 200));
        assert_eq!(*img.get_pixel(10, 10), Rgb([200, 0, 0]));
        assert_eq!(*img.get_pixel(203, 10), BAR);
        assert_eq!(*img.get_pixel(400, 10), Rgb([0, 0, 200]));
    }

    #[test]
    fn masks_the_same_place_in_both_panels() {
        let (a, b, out) = (temp("rc-ref2.png"), temp("rc-ren2.png"), temp("rc-out2.png"));
        flat(&a, [200, 200, 200], 100, 100);
        flat(&b, [10, 10, 10], 100, 100);
        // The left half of the frame.
        let caption = compare(&a, &b, "0 0, 0.5 0, 0.5 1, 0 1", "", 200, &out);
        assert!(caption.contains("cover 50%"), "{}", caption);
        let img = image::open(&out).unwrap().to_rgb8();
        assert_eq!(*img.get_pixel(20, 100), MASKED);
        assert_eq!(*img.get_pixel(206 + 20, 100), MASKED);
        assert_eq!(*img.get_pixel(180, 100), Rgb([200, 200, 200]));
        assert_eq!(*img.get_pixel(206 + 180, 100), Rgb([10, 10, 10]));
    }

    #[test]
    fn a_region_zooms_both_and_keeps_its_aspect() {
        let (a, b, out) = (temp("rc-ref3.png"), temp("rc-ren3.png"), temp("rc-out3.png"));
        flat(&a, [0, 120, 0], 400, 400);
        flat(&b, [0, 120, 0], 400, 400);
        let caption = compare(&a, &b, "", "0 0.5 1 0.75", 400, &out);
        assert!(caption.contains("v 0.50-0.75"), "{}", caption);
        assert_eq!(image::open(&out).unwrap().dimensions(), (806, 100));
    }

    #[test]
    fn a_colour_mask_hides_only_matching_pixels_and_their_edge() {
        let (a, b, out) = (temp("rc-ref4.png"), temp("rc-ren4.png"), temp("rc-out4.png"));
        // Reference: lime lettering colour on the left half, rock blue on the right.
        let mut reference = RgbImage::from_pixel(200, 200, Rgb([30, 60, 80]));
        for y in 0..200 {
            for x in 0..100 {
                reference.put_pixel(x, y, Rgb([0x78, 0x9c, 0x42]));
            }
        }
        reference.save(&a).unwrap();
        flat(&b, [10, 10, 10], 200, 200);
        let caption = compare(&a, &b, "#789c42~30: 0 0, 1 0, 1 1, 0 1", "", 200, &out);
        assert!(caption.contains("1 mask polygon(s)"), "{}", caption);
        let img = image::open(&out).unwrap().to_rgb8();
        assert_eq!(*img.get_pixel(50, 100), MASKED);
        assert_eq!(*img.get_pixel(206 + 50, 100), MASKED);
        assert_eq!(*img.get_pixel(100, 100), MASKED, "the one-pixel edge is grown");
        assert_eq!(*img.get_pixel(150, 100), Rgb([30, 60, 80]));
        assert_eq!(*img.get_pixel(206 + 150, 100), Rgb([10, 10, 10]));
    }

    #[test]
    fn bad_input_is_named() {
        assert!(parse_mask("#78c42: 0 0, 1 0, 1 1").unwrap_err().contains("#rrggbb"));
        assert!(parse_mask("#789c42~x: 0 0, 1 0, 1 1").unwrap_err().contains("tolerance"));
        assert!(parse_mask("0 0, 1 1").unwrap_err().contains("three points"));
        assert!(parse_mask("0 0, 1, 1 1").unwrap_err().contains("not \"u v\""));
        assert!(parse_region("0.5 0.5 0.5 0.9").unwrap_err().contains("empty"));
        assert!(compare("/no/such.png", "/no/such.png", "", "", 200, "/tmp/x.png").starts_with("compare failed: cannot load"));
    }
}
