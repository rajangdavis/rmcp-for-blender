//! Reading an image as text, in Rust.
//!
//! The counterpart of the Python script in python/mcp_scripts.py, and then some:
//! `grid` is the text-vision view — the plain facts on one line plus a palette (the
//! same first line the Python prints, so the two can be compared on one file), then
//! a tone grid, a hue-and-strength grid, a spectrum ordered by hue, and a summary
//! that names what is in the picture and where.
//!
//! Doing this here rather than inside Blender buys three things: it is fast, it
//! needs no Blender session at all, and it has unit tests — a file of pixels and
//! its expected text, asserted with `cargo test`, rather than a call to Blender and
//! a squint at the answer.

use std::collections::HashMap;

struct Stats {
    width: u32,
    height: u32,
    mean: [u64; 3],
    ranked: Vec<(u32, u64)>,
    cells: Vec<[f64; 3]>,
    cols: u32,
    rows: u32,
}

/// Load an image and reduce it to one mean colour per cell, plus the whole-image
/// numbers. `cols` is how many cells across; rows follow the aspect at 2:1 cells,
/// because a terminal cell is about twice as tall as it is wide.
fn load(path: &str, cols: u32, cell_aspect: f64) -> Result<Stats, String> {
    let source = image::open(path)
        .map_err(|e| format!("cannot load {}: {}", path, e))?
        .to_rgb8();
    let (width, height) = source.dimensions();
    let cols = cols.clamp(1, width.max(1));
    let rows = if width == 0 || height == 0 {
        1
    } else {
        ((cols as f64) * (height as f64) / (width as f64) / cell_aspect).round().max(1.0) as u32
    };
    let mut sums = [0u64; 3];
    // A 4-bit-per-channel key is only 12 bits, so a fixed 4096-slot array beats a
    // HashMap: one indexed increment per pixel instead of a SipHash insert, which
    // is what made the Rust palette slower than numpy's vectorised `unique` at
    // 1 MP. The array is the whole key space, so ranking is a scan of 4096 slots.
    let mut buckets = [0u64; 4096];
    let mut cell_sums = vec![[0f64; 3]; (cols * rows) as usize];
    let mut cell_counts = vec![0u64; (cols * rows) as usize];
    // Iterate the raw RGB8 buffer and hoist the cell index out of the inner loop:
    // the per-pixel `(x * cols) / width` division dominated the profile at 2048².
    // `cx` is the same for every pixel in a column and `cy` for every pixel in a
    // row, so both are precomputed and the inner loop does adds only.
    let raw = source.as_raw();
    let stride = width as usize * 3;
    let cx_of: Vec<usize> = (0..width as usize)
        .map(|x| ((x as u64 * cols as u64) / (width.max(1) as u64)).min(cols as u64 - 1) as usize)
        .collect();
    for y in 0..height as usize {
        let cy = ((y as u64 * rows as u64) / (height.max(1) as u64)).min(rows as u64 - 1) as usize;
        let row = cy * cols as usize;
        let mut off = y * stride;
        for x in 0..width as usize {
            let r = raw[off] as u64;
            let g = raw[off + 1] as u64;
            let b = raw[off + 2] as u64;
            off += 3;
            sums[0] += r;
            sums[1] += g;
            sums[2] += b;
            // The same 4-bit-per-channel quantisation the Python script uses: scale
            // by 15 rather than dividing by 16, so the two agree bucket for bucket.
            let key = (((r * 15 / 255) as u32) << 8)
                | (((g * 15 / 255) as u32) << 4)
                | ((b * 15 / 255) as u32);
            buckets[key as usize] += 1;
            let index = row + cx_of[x];
            cell_sums[index][0] += r as f64;
            cell_sums[index][1] += g as f64;
            cell_sums[index][2] += b as f64;
            cell_counts[index] += 1;
        }
    }
    let cells: Vec<[f64; 3]> = cell_sums
        .iter()
        .zip(cell_counts.iter())
        .map(|(sum, count)| {
            let n = (*count).max(1) as f64;
            [sum[0] / n / 255.0, sum[1] / n / 255.0, sum[2] / n / 255.0]
        })
        .collect();
    let pixels = ((width as u64) * (height as u64)).max(1);
    let mut ranked: Vec<(u32, u64)> = (0..4096u32)
        .filter(|key| buckets[*key as usize] > 0)
        .map(|key| (key, buckets[key as usize]))
        .collect();
    ranked.sort_by(|a, b| b.1.cmp(&a.1));
    Ok(Stats {
        width,
        height,
        mean: [sums[0] / pixels, sums[1] / pixels, sums[2] / pixels],
        ranked,
        cells,
        cols,
        rows,
    })
}

fn luminance(c: [f64; 3]) -> f64 {
    0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}

fn saturation(c: [f64; 3]) -> f64 {
    let high = c[0].max(c[1]).max(c[2]);
    let low = c[0].min(c[1]).min(c[2]);
    if high <= 0.01 {
        0.0
    } else {
        (high - low) / high
    }
}

fn hue_degrees(c: [f64; 3]) -> f64 {
    let high = c[0].max(c[1]).max(c[2]);
    let low = c[0].min(c[1]).min(c[2]);
    let span = high - low;
    if span <= 1e-6 {
        return 0.0;
    }
    let raw = if high == c[0] {
        ((c[1] - c[2]) / span) % 6.0
    } else if high == c[1] {
        (c[2] - c[0]) / span + 2.0
    } else {
        (c[0] - c[1]) / span + 4.0
    };
    let degrees = raw * 60.0;
    if degrees < 0.0 {
        degrees + 360.0
    } else {
        degrees
    }
}

/// The six families, with the name each band deserves. 180-240 degrees is azure
/// rather than cyan: a blue at 205 degrees lands here, and calling it cyan misleads.
fn family(hue: f64) -> (char, &'static str) {
    match (hue / 60.0) as i32 {
        0 => ('r', "red"),
        1 => ('y', "yellow"),
        2 => ('g', "green"),
        3 => ('c', "azure"),
        4 => ('b', "blue"),
        _ => ('m', "magenta"),
    }
}

fn key_to_rgb(key: u32) -> [u8; 3] {
    [
        (((key >> 8) & 0xf) * 17) as u8,
        (((key >> 4) & 0xf) * 17) as u8,
        ((key & 0xf) * 17) as u8,
    ]
}

fn palette_line(stats: &Stats, colours: usize) -> String {
    let total: u64 = stats.ranked.iter().map(|(_, n)| n).sum::<u64>().max(1);
    let ranked: Vec<String> = stats
        .ranked
        .iter()
        .take(colours)
        .map(|(key, count)| {
            let rgb = key_to_rgb(*key);
            format!("#{:02x}{:02x}{:02x} {:>2}%", rgb[0], rgb[1], rgb[2], count * 100 / total)
        })
        .collect();
    if ranked.is_empty() {
        "palette (none)".to_string()
    } else {
        format!("palette {}", ranked.join(", "))
    }
}

fn numbers_line(path: &str, stats: &Stats) -> String {
    let aspect = if stats.height == 0 {
        0.0
    } else {
        stats.width as f64 / stats.height as f64
    };
    format!(
        "image {}  {}x{}  aspect {:.3}  mean #{:02x}{:02x}{:02x}  grid {}x{}",
        path, stats.width, stats.height, aspect, stats.mean[0], stats.mean[1], stats.mean[2],
        stats.cols, stats.rows
    )
}

const TONE: &[u8] = b" .:-=+*#%@";

fn tone_char(value: f64) -> char {
    let last = (TONE.len() - 1) as f64;
    let index = (value * last).round().clamp(0.0, last) as usize;
    TONE[index] as char
}

/// A hue letter, with case carrying how saturated the cell is: `.` neutral,
/// lowercase weak, uppercase strong. Combining hue and strength in one cell is
/// what makes a pale cyan distinguishable from a saturated one.
fn hue_char(hue: f64, sat: f64) -> char {
    if sat < 0.12 {
        return '.';
    }
    let (letter, _) = family(hue);
    if sat < 0.45 {
        letter
    } else {
        letter.to_ascii_uppercase()
    }
}

fn where_is(column: f64, row: f64, cols: u32, rows: u32) -> String {
    let across = column / (cols.max(1) as f64);
    let down = row / (rows.max(1) as f64);
    let horizontal = if across < 0.34 {
        "left"
    } else if across < 0.67 {
        "centre"
    } else {
        "right"
    };
    let vertical = if down < 0.34 {
        "upper"
    } else if down < 0.67 {
        "middle"
    } else {
        "lower"
    };
    format!("{}, {}", horizontal, vertical)
}

/// The best guess in words: how much of the picture is neutral, and what the
/// coloured part is, how much of it, and roughly where.
fn summary(stats: &Stats) -> String {
    let total = stats.cells.len().max(1) as f64;
    let mut neutral = 0.0;
    let mut families: HashMap<char, (f64, f64, f64, &'static str)> = HashMap::new();
    for (index, cell) in stats.cells.iter().enumerate() {
        let sat = saturation(*cell);
        if sat < 0.12 {
            neutral += 1.0;
            continue;
        }
        let (letter, name) = family(hue_degrees(*cell));
        let column = (index % stats.cols as usize) as f64;
        let row = (index / stats.cols as usize) as f64;
        let entry = families.entry(letter).or_insert((0.0, 0.0, 0.0, name));
        entry.0 += 1.0;
        entry.1 += column;
        entry.2 += row;
    }
    let mut ranked: Vec<(f64, f64, f64, &'static str)> = families
        .values()
        .map(|(count, sum_x, sum_y, name)| (*count, sum_x / count, sum_y / count, *name))
        .collect();
    ranked.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    let mut parts: Vec<String> = Vec::new();
    if neutral > 0.0 {
        parts.push(format!("{:.0}% neutral", neutral * 100.0 / total));
    }
    for (count, x, y, name) in ranked.iter().take(3) {
        parts.push(format!(
            "{} {:.0}% ({})",
            name,
            count * 100.0 / total,
            where_is(*x, *y, stats.cols, stats.rows)
        ));
    }
    if parts.is_empty() {
        "summary: nothing to describe".to_string()
    } else {
        format!("summary: {}", parts.join("; "))
    }
}

fn spectrum(stats: &Stats, colours: usize) -> String {
    let total: u64 = stats.ranked.iter().map(|(_, n)| n).sum::<u64>().max(1);
    let mut neutrals: Vec<String> = Vec::new();
    let mut hues: Vec<(f64, String)> = Vec::new();
    for (key, count) in stats.ranked.iter().take(colours) {
        let rgb = key_to_rgb(*key);
        let channels = [rgb[0] as f64 / 255.0, rgb[1] as f64 / 255.0, rgb[2] as f64 / 255.0];
        let share = count * 100 / total;
        let entry = format!("#{:02x}{:02x}{:02x} {}%", rgb[0], rgb[1], rgb[2], share);
        if saturation(channels) < 0.12 {
            neutrals.push(format!("neutral {}", entry));
        } else {
            hues.push((hue_degrees(channels), format!("{:.0}° {}", hue_degrees(channels), entry)));
        }
    }
    hues.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    let mut parts = neutrals;
    parts.extend(hues.into_iter().map(|(_, text)| text));
    format!("spectrum: {}", if parts.is_empty() { "(none)".to_string() } else { parts.join(" · ") })
}

/// The text-vision view: the facts, a tone grid, a hue-and-strength grid, a
/// spectrum ordered by hue, and a summary that names what is there and where.
pub fn grid(path: &str, width: i32) -> String {
    let stats = match load(path, width.clamp(40, 200) as u32, 2.0) {
        Ok(stats) => stats,
        Err(message) => return message,
    };
    let mut lines: Vec<String> = Vec::new();
    lines.push(numbers_line(path, &stats));
    lines.push(palette_line(&stats, 6));

    let mut tones: Vec<f64> = stats.cells.iter().map(|c| luminance(*c)).collect();
    tones.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let low = tones[(tones.len() as f64 * 0.05) as usize];
    let high = tones[((tones.len() as f64 * 0.95) as usize).min(tones.len() - 1)];
    let span = if (high - low).abs() < 1e-6 { 1.0 } else { high - low };

    // A stretch is only honest when there is a range to stretch. On a nearly
    // uniform image the percentile map invents contrast: every cell lands at one
    // end or the other and the grid reads as a pattern that is not there. Below
    // the threshold the grid is drawn against the absolute scale instead, so a
    // flat image stays flat and the numbers above carry the values.
    let nearly_uniform = span < 0.08;
    lines.push(if nearly_uniform {
        format!("tone, dense = bright (nearly uniform: {:.3} to {:.3}, so this grid is flat by design):", low, high)
    } else {
        "tone, dense = bright:".to_string()
    });
    for row in 0..stats.rows {
        let mut text = String::new();
        for column in 0..stats.cols {
            let cell = stats.cells[(row * stats.cols + column) as usize];
            let value = if nearly_uniform {
                luminance(cell)
            } else {
                ((luminance(cell) - low) / span).clamp(0.0, 1.0)
            };
            text.push(tone_char(value));
        }
        lines.push(text);
    }
    lines.push("hue: R red Y yellow G green C azure B blue M magenta; lowercase weak, uppercase strong, . neutral".to_string());
    for row in 0..stats.rows {
        let mut text = String::new();
        for column in 0..stats.cols {
            let cell = stats.cells[(row * stats.cols + column) as usize];
            text.push(hue_char(hue_degrees(cell), saturation(cell)));
        }
        lines.push(text);
    }
    lines.push(spectrum(&stats, 6));
    lines.push(summary(&stats));
    lines.join("\n")
}

/// The image as coloured text, for a human rather than a model.
///
/// Each cell is a half-block: the top half is one sample's colour, the bottom
/// half the next, which makes each sample square in a terminal and leaves no
/// seam between rows. Truecolour escapes; a client that strips ANSI will show
/// the blocks in one colour, and nothing else.
// A 4x4 Bayer matrix: the ordered-dither thresholds, in sixteenths.
const BAYER4: [[f64; 4]; 4] = [
    [0.0, 8.0, 2.0, 10.0],
    [12.0, 4.0, 14.0, 6.0],
    [3.0, 11.0, 1.0, 9.0],
    [15.0, 7.0, 13.0, 5.0],
];

fn dither_threshold(x: usize, y: usize, dither: &str) -> f64 {
    if dither == "threshold" {
        0.5
    } else {
        (BAYER4[y % 4][x % 4] + 0.5) / 16.0
    }
}

/// Which braille dot a (column, row) inside a cell is, as its bit.
fn dot_bit(sx: usize, sy: usize) -> u32 {
    match (sx, sy) {
        (0, 0) => 1,
        (0, 1) => 2,
        (0, 2) => 4,
        (1, 0) => 8,
        (1, 1) => 16,
        (1, 2) => 32,
        (0, 3) => 64,
        (1, 3) => 128,
        _ => 0,
    }
}

fn rgb8(c: [f64; 3]) -> [u8; 3] {
    [
        (c[0].clamp(0.0, 1.0) * 255.0).round() as u8,
        (c[1].clamp(0.0, 1.0) * 255.0).round() as u8,
        (c[2].clamp(0.0, 1.0) * 255.0).round() as u8,
    ]
}

fn mean_of(sum: [f64; 3], count: f64) -> [f64; 3] {
    let n = count.max(1.0);
    [sum[0] / n, sum[1] / n, sum[2] / n]
}

/// A character painted with an optional background; without one the gaps show
/// the terminal's own background.
fn painted(foreground: [f64; 3], background: Option<[f64; 3]>, glyph: char) -> String {
    let fg = rgb8(foreground);
    match background {
        Some(back) => {
            let bg = rgb8(back);
            format!(
                "\x1b[38;2;{};{};{}m\x1b[48;2;{};{};{}m{}",
                fg[0], fg[1], fg[2], bg[0], bg[1], bg[2], glyph
            )
        }
        None => format!("\x1b[38;2;{};{};{}m{}", fg[0], fg[1], fg[2], glyph),
    }
}

/// The picture as coloured text, for a human rather than a model.
///
/// Three ways to spend a character cell:
///   `half`    two samples stacked, two colours: foreground above, background below.
///   `braille` eight samples (a 4x2 dot grid) drawn as one dithered glyph, one
///             colour for the lit dots and the terminal's own background in the gaps.
///   `blend`   eight samples and two colours: the lit dots' average in front, the
///             gaps' average behind, so shape and colour both survive.
///
/// Braille buys four times the vertical detail of a half block and is what makes
/// a dithered flat tone read as tone rather than as noise.
pub fn ansi(path: &str, width: i32, mode: &str, dither: &str) -> String {
    let cols = width.clamp(20, 200) as u32;
    let dots = mode == "braille" || mode == "blend";
    let stats = if dots {
        // A braille cell is 2 dots wide and 4 tall, and those dots are square, so
        // the sample grid is twice as wide and gets its rows at aspect 1.
        match load(path, cols * 2, 1.0) {
            Ok(stats) => stats,
            Err(message) => return message,
        }
    } else {
        match load(path, cols, 2.0) {
            Ok(stats) => stats,
            Err(message) => return message,
        }
    };
    let mut lines: Vec<String> = Vec::new();
    lines.push(numbers_line(path, &stats));

    if dots && stats.rows >= 4 {
        // The dot thresholds are relative to this image's own range, not to
        // absolute black and white, or a dark flat image becomes a uniform
        // stipple of noise.
        let mut dot_lums: Vec<f64> = stats.cells.iter().map(|c| luminance(*c)).collect();
        dot_lums.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let dot_low = dot_lums[(dot_lums.len() as f64 * 0.05) as usize];
        let dot_high = dot_lums[((dot_lums.len() as f64 * 0.95) as usize).min(dot_lums.len() - 1)];
        let world_span = (dot_high - dot_low).abs() >= 1e-6;
        let dot_span = if world_span { dot_high - dot_low } else { 1.0 };

        let cols_dots = stats.cols as usize;
        let rows_dots = stats.rows as usize;
        // Whether there is any colour in the picture at all. A monochrome image
        // has only density to show, so the shading ladder is right for it; one
        // with colour in it is never graded by brightness.
        let has_colour = stats.cells.iter().any(|cell| saturation(*cell) > 0.12);
        let level_at = |index: usize| -> f64 {
            ((luminance(stats.cells[index]) - dot_low) / dot_span).clamp(0.0, 1.0)
        };

        // Decide every dot before drawing any: error diffusion needs the whole
        // grid in reading order, because each dot's rounding error is pushed into
        // its neighbours. Ordered dithering is regular by construction, which
        // reads as a texture; a diffused one is irregular, which reads as tone.
        let ordered = dither != "diffusion";
        let mut lit = vec![false; cols_dots * rows_dots];
        if ordered {
            for y in 0..rows_dots {
                for x in 0..cols_dots {
                    lit[y * cols_dots + x] = level_at(y * cols_dots + x) > dither_threshold(x, y, dither);
                }
            }
        } else {
            let mut carry = vec![0.0f64; cols_dots + 2];
            let mut next = vec![0.0f64; cols_dots + 2];
            for y in 0..rows_dots {
                for x in 0..cols_dots {
                    let index = y * cols_dots + x;
                    let want = (level_at(index) + carry[x + 1]).clamp(0.0, 1.0);
                    let on = if world_span { want > 0.5 } else { false };
                    lit[index] = on;
                    let error = want - if on { 1.0 } else { 0.0 };
                    if x + 2 < next.len() {
                        carry[x + 2] += error * 7.0 / 16.0;
                    }
                    if x > 0 {
                        next[x] += error * 3.0 / 16.0;
                    }
                    next[x + 1] += error * 5.0 / 16.0;
                    next[x + 2] += error * 1.0 / 16.0;
                }
                std::mem::swap(&mut carry, &mut next);
                for slot in next.iter_mut() {
                    *slot = 0.0;
                }
            }
        }

        let width_cells = cols_dots / 2;
        let height_cells = rows_dots / 4;
        for row in 0..height_cells {
            let mut line = String::new();
            for column in 0..width_cells {
                let mut bits: u32 = 0;
                let mut cell = [0.0f64; 3];
                let mut lit_colour = [0.0f64; 3];
                let mut gaps = [0.0f64; 3];
                let mut lit_count = 0.0f64;
                let mut gap_count = 0.0f64;
                let mut cell_low = f64::MAX;
                let mut cell_high = f64::MIN;
                for sy in 0..4 {
                    for sx in 0..2 {
                        let sample = stats.cells[(row * 4 + sy) * cols_dots + column * 2 + sx];
                        let level = luminance(sample);
                        if level < cell_low {
                            cell_low = level;
                        }
                        if level > cell_high {
                            cell_high = level;
                        }
                    }
                }
                if cell_high - cell_low < 0.02 {
                    // No range inside this cell, so it is one tone: give it the right
                    // density rather than a wall of solid. The shading blocks tile
                    // seamlessly, so a gradual area reads as a gradient. If the whole
                    // image is one tone there is nothing to grade against, and a solid
                    // block is the honest answer.
                    let mut mean = [0.0f64; 3];
                    for sy in 0..4 {
                        for sx in 0..2 {
                            let sample = stats.cells[(row * 4 + sy) * cols_dots + column * 2 + sx];
                            for i in 0..3 {
                                mean[i] += sample[i] / 8.0;
                            }
                        }
                    }
                    // A flat cell is a colour as much as it is a tone, and
                    // luminance is the wrong scale for a colour: blue is 0.07, so
                    // grading it by brightness drew it as a space, invisible on a
                    // black background. When the picture has colour in it the cell
                    // is filled with its own; the shading ladder is for a
                    // monochrome image, where density is the only signal left.
                    if world_span && !has_colour {
                        let level = ((luminance(mean) - dot_low) / dot_span).clamp(0.0, 1.0);
                        let shades = [' ', '\u{2591}', '\u{2592}', '\u{2593}', '\u{2588}'];
                        let index = ((level * 4.999) as usize).min(shades.len() - 1);
                        line.push_str(&painted(mean, Some([0.0, 0.0, 0.0]), shades[index]));
                    } else {
                        line.push_str(&painted(mean, None, '\u{2588}'));
                    }
                    continue;
                }
                for sy in 0..4 {
                    for sx in 0..2 {
                        let sample = stats.cells[(row * 4 + sy) * cols_dots + column * 2 + sx];
                        for i in 0..3 {
                            cell[i] += sample[i];
                        }
                        if lit[(row * 4 + sy) * cols_dots + column * 2 + sx] {
                            bits |= dot_bit(sx, sy);
                            for i in 0..3 {
                                lit_colour[i] += sample[i];
                            }
                            lit_count += 1.0;
                        } else {
                            for i in 0..3 {
                                gaps[i] += sample[i];
                            }
                            gap_count += 1.0;
                        }
                    }
                }
                let glyph = char::from_u32(0x2800 + bits).unwrap_or('?');
                let foreground = if lit_count > 0.0 { mean_of(lit_colour, lit_count) } else { mean_of(cell, 8.0) };
                let background = if mode == "blend" && lit_count > 0.0 && gap_count > 0.0 {
                    Some(mean_of(gaps, gap_count))
                } else {
                    None
                };
                line.push_str(&painted(foreground, background, glyph));
            }
            line.push_str("\x1b[0m");
            lines.push(line);
        }
    } else {
        let mut row = 0usize;
        while row + 1 < stats.rows as usize {
            let mut line = String::new();
            for column in 0..stats.cols as usize {
                let top = stats.cells[row * stats.cols as usize + column];
                let bottom = stats.cells[(row + 1) * stats.cols as usize + column];
                line.push_str(&painted(top, Some(bottom), '\u{2580}'));
            }
            line.push_str("\x1b[0m");
            lines.push(line);
            row += 2;
        }
    }
    lines.join("\n")
}

#[cfg(test)]
mod ansi_tests {
    use super::ansi;

    #[test]
    fn the_colour_view_uses_truecolour_and_half_blocks() {
        let path = std::env::temp_dir().join("textvision-ansi.png").to_string_lossy().into_owned();
        let mut image = image::RgbImage::new(40, 20);
        for (_, _, pixel) in image.enumerate_pixels_mut() {
            *pixel = image::Rgb([255, 0, 0]);
        }
        image.save(&path).expect("write the probe image");
        let text = ansi(&path, 20, "half", "ordered");
        assert!(text.contains("\x1b[38;2;255;0;0m"), "no truecolour foreground: {:?}", text);
        assert!(text.contains("\x1b[48;2;255;0;0m"), "no truecolour background: {:?}", text);
        assert!(text.contains('\u{2580}'), "no half blocks: {:?}", text);
        assert!(text.lines().any(|line| line.ends_with("\x1b[0m")), "no reset at a line end");
        assert!(
            ansi("/definitely/not/here.png", 20, "braille", "ordered").starts_with("cannot load"),
            "no error text"
        );
        let _ = std::fs::remove_file(&path);
    }
}

#[cfg(test)]
mod tests {

    use super::grid;

    fn flat(path: &str, colour: [u8; 3], width: u32, height: u32) {
        let mut image = image::RgbImage::new(width, height);
        for (_, _, pixel) in image.enumerate_pixels_mut() {
            *pixel = image::Rgb(colour);
        }
        image.save(path).expect("write the probe image");
    }

    fn temp(name: &str) -> String {
        std::env::temp_dir().join(name).to_string_lossy().into_owned()
    }

    #[test]
    fn reads_dimensions_aspect_and_mean_of_a_known_image() {
        let path = temp("textvision-flat.png");
        flat(&path, [63, 169, 245], 4, 2);
        let text = grid(&path, 80);
        assert!(text.contains("4x2"), "dimensions missing: {}", text);
        assert!(text.contains("aspect 2.000"), "aspect missing: {}", text);
        assert!(text.contains("mean #3fa9f5"), "mean missing: {}", text);
        // The palette quantises to four bits per channel by scaling with 15, as the
        // Python one does (which is why both are full of #333333), so a mid-tone
        // floors into the bucket below: 63/169/245 becomes 51/153/238. The mean is
        // the number to compare when two decoders are in question, and it is exact.
        assert!(text.contains("#3399ee 100%"), "palette missing or not quantised: {}", text);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn says_so_when_the_file_is_not_there() {
        let text = grid("/definitely/not/here.png", 80);
        assert!(text.starts_with("cannot load"), "unexpected: {}", text);
    }

    #[test]
    fn a_flat_colour_becomes_one_family_in_the_summary() {
        let path = temp("textvision-flat-summary.png");
        flat(&path, [63, 169, 245], 80, 40);
        let text = grid(&path, 80);
        assert!(text.contains("azure"), "no azure family named: {}", text);
        assert!(text.contains("#3fa9f5"), "no colour in the spectrum: {}", text);
        assert!(!text.contains("neutral;"), "a saturated image called neutral: {}", text);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn a_two_colour_image_is_placed_left_and_right() {
        let path = temp("textvision-two-tone.png");
        let mut image = image::RgbImage::new(80, 20);
        for (x, _, pixel) in image.enumerate_pixels_mut() {
            *pixel = if x < 40 {
                image::Rgb([220, 32, 32])
            } else {
                image::Rgb([32, 64, 208])
            };
        }
        image.save(&path).expect("write the two-tone probe");
        let text = grid(&path, 80);
        assert!(text.contains("red"), "no red in: {}", text);
        assert!(text.contains("azure"), "no azure in: {}", text);
        assert!(text.contains("(left, middle)"), "nothing placed left: {}", text);
        assert!(text.contains("(right, middle)"), "nothing placed right: {}", text);
        let _ = std::fs::remove_file(&path);
    }
}


#[cfg(test)]
mod braille_tests {
    use super::ansi;

    fn probe(path: &str, pixels: &[[u8; 3]], width: u32, height: u32) {
        let mut image = image::RgbImage::new(width, height);
        for (x, y, pixel) in image.enumerate_pixels_mut() {
            *pixel = image::Rgb(pixels[(y * width + x) as usize]);
        }
        image.save(path).expect("write the probe image");
    }

    fn temp(name: &str) -> String {
        std::env::temp_dir().join(name).to_string_lossy().into_owned()
    }

    const WHITE: [u8; 3] = [255, 255, 255];
    const BLACK: [u8; 3] = [0, 0, 0];
    // 2x4 pixels, left column white: exactly one braille cell.
    const LEFT_LIT: [[u8; 3]; 8] = [WHITE, BLACK, WHITE, BLACK, WHITE, BLACK, WHITE, BLACK];

    #[test]
    fn a_white_left_column_is_dots_one_two_three_and_seven() {
        let path = temp("textvision-braille.png");
        probe(&path, &LEFT_LIT, 2, 4);
        let text = ansi(&path, 20, "braille", "threshold");
        assert!(text.contains('\u{2847}'), "expected dots 1237 (U+2847), got: {:?}", text);
        assert!(text.contains("\x1b[38;2;255;255;255m"), "the lit dots are not white: {:?}", text);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn blend_paints_lit_dots_and_gaps_in_two_colours() {
        let path = temp("textvision-blend.png");
        probe(&path, &LEFT_LIT, 2, 4);
        let text = ansi(&path, 20, "blend", "threshold");
        assert!(text.contains("\x1b[38;2;255;255;255m"), "no lit colour: {:?}", text);
        assert!(text.contains("\x1b[48;2;0;0;0m"), "no gap colour: {:?}", text);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn a_flat_mid_tone_dithers_instead_of_going_solid_or_empty() {
        let path = temp("textvision-dither.png");
        probe(&path, &[[128, 128, 128]; 8], 2, 4);
        let text = ansi(&path, 20, "blend", "ordered");
        // A flat cell has no range, so it is drawn solid rather than stippled:
        // noise would be worse than nothing, because it looks like detail.
        assert!(text.contains('\u{2588}'), "a flat cell should be a solid block: {:?}", text);
        assert!(!text.contains('\u{2800}'), "a mid grey dithered to nothing: {:?}", text);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn braille_gives_four_times_the_rows_of_half_blocks() {
        let path = temp("textvision-rows.png");
        probe(&path, &[[128, 128, 128]; 64 * 64], 64, 64);
        let braille = ansi(&path, 20, "braille", "ordered");
        let half = ansi(&path, 20, "half", "ordered");
        let rows = |text: &str| text.lines().filter(|line| line.contains("\x1b[")).count();
        assert!(rows(&braille) >= rows(&half) * 2, "braille rows {} vs half {}", rows(&braille), rows(&half));
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn a_gradient_grades_through_the_shading_blocks() {
        let path = temp("textvision-shade.png");
        // Bands rather than a per-pixel ramp: a braille cell spans two columns of
        // the sample grid, so on a smooth 40-pixel ramp every cell has a range of
        // its own and is dithered rather than shaded. Eight-pixel bands leave each
        // cell flat, which is the case the shading ladder exists for.
        let mut image = image::RgbImage::new(40, 4);
        for (x, _, pixel) in image.enumerate_pixels_mut() {
            let value = ((x / 8) * 255 / 4) as u8;
            *pixel = image::Rgb([value, value, value]);
        }
        image.save(&path).expect("write the gradient");
        let text = ansi(&path, 20, "blend", "ordered");
        let shades = ['\u{2591}', '\u{2592}', '\u{2593}', '\u{2588}'];
        let used = shades.iter().filter(|shade| text.contains(**shade)).count();
        assert!(used >= 2, "a gradient should use several densities, got: {:?}", text);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn braille_draws_the_picture_once() {
        let path = temp("textvision-once.png");
        probe(&path, &[[128, 128, 128]; 64 * 64], 64, 64);
        let text = ansi(&path, 20, "braille", "ordered");
        // 40 sample rows at aspect 1 is ten braille cells of four dots, so one
        // header line and ten rows. The cell loop was once written twice -- from
        // the pre-decided dots and again from the thresholds -- and every render
        // carried the picture at both sizes; this pins the count.
        assert_eq!(text.lines().count(), 11, "the picture was drawn more than once: {:?}", text);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn a_flat_saturated_cell_is_filled_with_its_colour() {
        let path = temp("textvision-blue.png");
        let mut image = image::RgbImage::new(4, 4);
        for (x, _, pixel) in image.enumerate_pixels_mut() {
            *pixel = if x < 2 { image::Rgb([0, 0, 255]) } else { image::Rgb([255, 255, 255]) };
        }
        image.save(&path).expect("write the blue probe");
        let text = ansi(&path, 20, "blend", "ordered");
        // Blue's luminance is 0.07, so grading a flat blue cell by brightness
        // drew it as a space: invisible on a black background.
        assert!(text.contains("\x1b[38;2;0;0;255m\u{2588}"), "the blue cell is not a solid blue block: {:?}", text);
        assert!(!text.contains("\x1b[38;2;0;0;255m "), "the blue cell is still a space: {:?}", text);
        let _ = std::fs::remove_file(&path);
    }
}
