/* vtui_render.cpp - Valeroy AI terminal render accelerator */
#include "vtui_render.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>

namespace {

struct Cell {
    // One grapheme as UTF-8. Small enough to stay inline in practice.
    std::string glyph = " ";
    int32_t fg = -1;
    int32_t bg = -1;
    uint32_t attr = 0;
    // Second half of a double-width glyph; never emitted directly.
    bool continuation = false;

    bool operator==(const Cell &o) const
    {
        return glyph == o.glyph && fg == o.fg && bg == o.bg &&
               attr == o.attr && continuation == o.continuation;
    }
    bool operator!=(const Cell &o) const { return !(*this == o); }
};

struct Surface {
    int32_t cols = 0;
    int32_t rows = 0;
    std::vector<Cell> back;
    std::vector<Cell> front;
    bool full_repaint = true;

    Cell *at(int32_t x, int32_t y)
    {
        if (x < 0 || y < 0 || x >= cols || y >= rows) return nullptr;
        return &back[static_cast<size_t>(y) * cols + x];
    }
};

std::map<int32_t, Surface> g_surfaces;
int32_t g_next_handle = 1;

Surface *lookup(int32_t handle)
{
    auto it = g_surfaces.find(handle);
    return it == g_surfaces.end() ? nullptr : &it->second;
}

/* ------------------------------------------------------------------ *
 * UTF-8 + width
 * ------------------------------------------------------------------ */

// Decode one code point. Advances `i`. Returns 0xFFFD on malformed input so a
// bad byte never desynchronizes the whole line.
uint32_t decode(const char *s, size_t len, size_t &i)
{
    unsigned char c = static_cast<unsigned char>(s[i]);
    if (c < 0x80) {
        ++i;
        return c;
    }

    int extra;
    uint32_t cp;
    if ((c & 0xE0) == 0xC0) {
        extra = 1;
        cp = c & 0x1Fu;
    } else if ((c & 0xF0) == 0xE0) {
        extra = 2;
        cp = c & 0x0Fu;
    } else if ((c & 0xF8) == 0xF0) {
        extra = 3;
        cp = c & 0x07u;
    } else {
        ++i;
        return 0xFFFD;
    }

    // The loop below rejects any sequence that runs past the end of the buffer.
    for (int k = 1; k <= extra; ++k) {
        if (i + k >= len) {
            ++i;
            return 0xFFFD;
        }
        unsigned char cc = static_cast<unsigned char>(s[i + k]);
        if ((cc & 0xC0) != 0x80) {
            ++i;
            return 0xFFFD;
        }
        cp = (cp << 6) | (cc & 0x3Fu);
    }
    i += static_cast<size_t>(extra) + 1;
    return cp;
}

bool is_combining(uint32_t cp)
{
    return (cp >= 0x0300 && cp <= 0x036F) || (cp >= 0x1AB0 && cp <= 0x1AFF) ||
           (cp >= 0x20D0 && cp <= 0x20FF) || (cp >= 0xFE00 && cp <= 0xFE0F) ||
           (cp >= 0xFE20 && cp <= 0xFE2F);
}

// Conservative double-width ranges: CJK, Hangul, and the common emoji blocks.
bool is_wide(uint32_t cp)
{
    return (cp >= 0x1100 && cp <= 0x115F) || (cp >= 0x2E80 && cp <= 0x303E) ||
           (cp >= 0x3041 && cp <= 0x33FF) || (cp >= 0x3400 && cp <= 0x4DBF) ||
           (cp >= 0x4E00 && cp <= 0x9FFF) || (cp >= 0xA000 && cp <= 0xA4CF) ||
           (cp >= 0xAC00 && cp <= 0xD7A3) || (cp >= 0xF900 && cp <= 0xFAFF) ||
           (cp >= 0xFE30 && cp <= 0xFE6F) || (cp >= 0xFF00 && cp <= 0xFF60) ||
           (cp >= 0xFFE0 && cp <= 0xFFE6) || (cp >= 0x1F300 && cp <= 0x1F64F) ||
           (cp >= 0x1F900 && cp <= 0x1F9FF) || (cp >= 0x20000 && cp <= 0x3FFFD);
}

int cp_width(uint32_t cp)
{
    if (cp == 0) return 0;
    if (cp < 0x20 || (cp >= 0x7F && cp < 0xA0)) return 0;  // control
    if (is_combining(cp)) return 0;
    return is_wide(cp) ? 2 : 1;
}

void encode(uint32_t cp, std::string &out)
{
    if (cp < 0x80) {
        out += static_cast<char>(cp);
    } else if (cp < 0x800) {
        out += static_cast<char>(0xC0 | (cp >> 6));
        out += static_cast<char>(0x80 | (cp & 0x3F));
    } else if (cp < 0x10000) {
        out += static_cast<char>(0xE0 | (cp >> 12));
        out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
        out += static_cast<char>(0x80 | (cp & 0x3F));
    } else {
        out += static_cast<char>(0xF0 | (cp >> 18));
        out += static_cast<char>(0x80 | ((cp >> 12) & 0x3F));
        out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
        out += static_cast<char>(0x80 | (cp & 0x3F));
    }
}

/* A grapheme: a base code point plus any trailing combining marks. */
struct Grapheme {
    std::string text;
    int width = 1;
};

std::vector<Grapheme> graphemes(const char *utf8)
{
    std::vector<Grapheme> out;
    if (!utf8) return out;
    size_t len = std::strlen(utf8);
    size_t i = 0;
    while (i < len) {
        size_t start = i;
        uint32_t cp = decode(utf8, len, i);
        int w = cp_width(cp);
        if (w == 0 && !out.empty() && is_combining(cp)) {
            // Attach the mark to the preceding grapheme.
            out.back().text.append(utf8 + start, i - start);
            continue;
        }
        if (w == 0) continue;  // drop stray controls
        Grapheme g;
        g.text.assign(utf8 + start, i - start);
        g.width = w;
        out.push_back(std::move(g));
    }
    return out;
}

/* ------------------------------------------------------------------ *
 * ANSI emission
 * ------------------------------------------------------------------ */

void emit_style(std::string &out, int32_t fg, int32_t bg, uint32_t attr)
{
    out += "\x1b[0";
    if (attr & VR_BOLD)      out += ";1";
    if (attr & VR_DIM)       out += ";2";
    if (attr & VR_ITALIC)    out += ";3";
    if (attr & VR_UNDERLINE) out += ";4";
    if (attr & VR_REVERSE)   out += ";7";
    char buf[32];
    if (fg >= 0 && fg <= 255) {
        std::snprintf(buf, sizeof(buf), ";38;5;%d", fg);
        out += buf;
    }
    if (bg >= 0 && bg <= 255) {
        std::snprintf(buf, sizeof(buf), ";48;5;%d", bg);
        out += buf;
    }
    out += "m";
}

void emit_move(std::string &out, int32_t x, int32_t y)
{
    char buf[32];
    std::snprintf(buf, sizeof(buf), "\x1b[%d;%dH", y + 1, x + 1);
    out += buf;
}

int32_t emit_to(const std::string &s, char *out, size_t cap)
{
    if (!out) return -1;
    if (s.size() + 1 > cap) return -2;
    std::memcpy(out, s.data(), s.size());
    out[s.size()] = '\0';
    return static_cast<int32_t>(s.size());
}

}  // namespace

/* ------------------------------------------------------------------ *
 * Public C ABI
 * ------------------------------------------------------------------ */

extern "C" {

int32_t vr_create(int32_t cols, int32_t rows)
{
    if (cols <= 0 || rows <= 0 || cols > 2000 || rows > 2000) return 0;
    int32_t handle = g_next_handle++;
    Surface s;
    s.cols = cols;
    s.rows = rows;
    s.back.assign(static_cast<size_t>(cols) * rows, Cell{});
    s.front.assign(static_cast<size_t>(cols) * rows, Cell{});
    s.full_repaint = true;
    g_surfaces[handle] = std::move(s);
    return handle;
}

void vr_destroy(int32_t handle)
{
    g_surfaces.erase(handle);
}

int32_t vr_resize(int32_t handle, int32_t cols, int32_t rows)
{
    Surface *s = lookup(handle);
    if (!s) return -1;
    if (cols <= 0 || rows <= 0 || cols > 2000 || rows > 2000) return -1;
    s->cols = cols;
    s->rows = rows;
    s->back.assign(static_cast<size_t>(cols) * rows, Cell{});
    s->front.assign(static_cast<size_t>(cols) * rows, Cell{});
    s->full_repaint = true;
    return 0;
}

int32_t vr_clear(int32_t handle)
{
    Surface *s = lookup(handle);
    if (!s) return -1;
    std::fill(s->back.begin(), s->back.end(), Cell{});
    return 0;
}

int32_t vr_fill(int32_t handle, int32_t x, int32_t y, int32_t w, int32_t h, int32_t bg)
{
    Surface *s = lookup(handle);
    if (!s) return -1;
    for (int32_t row = y; row < y + h; ++row) {
        for (int32_t col = x; col < x + w; ++col) {
            Cell *cell = s->at(col, row);
            if (!cell) continue;
            cell->glyph = " ";
            cell->fg = -1;
            cell->bg = bg;
            cell->attr = 0;
            cell->continuation = false;
        }
    }
    return 0;
}

int32_t vr_put(int32_t handle, int32_t x, int32_t y, const char *utf8,
               int32_t fg, int32_t bg, uint32_t attr)
{
    Surface *s = lookup(handle);
    if (!s || !utf8) return -1;
    if (y < 0 || y >= s->rows) return 0;

    int32_t col = x;
    for (const Grapheme &g : graphemes(utf8)) {
        if (col >= s->cols) break;
        if (col + g.width > s->cols) break;  // would split a wide glyph
        if (col < 0) {
            col += g.width;
            continue;
        }
        Cell *cell = s->at(col, y);
        if (!cell) break;
        cell->glyph = g.text;
        cell->fg = fg;
        cell->bg = bg;
        cell->attr = attr;
        cell->continuation = false;
        if (g.width == 2) {
            Cell *next = s->at(col + 1, y);
            if (next) {
                next->glyph = "";
                next->fg = fg;
                next->bg = bg;
                next->attr = attr;
                next->continuation = true;
            }
        }
        col += g.width;
    }
    return col - x;
}

int32_t vr_flush(int32_t handle, char *out, size_t cap)
{
    Surface *s = lookup(handle);
    if (!s) return -1;

    std::string buf;
    bool style_valid = false;
    int32_t cur_fg = -2, cur_bg = -2;
    uint32_t cur_attr = 0xFFFFFFFFu;
    int32_t cursor_x = -1, cursor_y = -1;
    bool wrote_anything = false;

    for (int32_t y = 0; y < s->rows; ++y) {
        for (int32_t x = 0; x < s->cols; ++x) {
            size_t idx = static_cast<size_t>(y) * s->cols + x;
            const Cell &back = s->back[idx];
            if (back.continuation) continue;  // painted with its lead cell
            if (!s->full_repaint && back == s->front[idx]) continue;

            if (cursor_y != y || cursor_x != x) {
                emit_move(buf, x, y);
                cursor_x = x;
                cursor_y = y;
            }
            if (!style_valid || back.fg != cur_fg || back.bg != cur_bg ||
                back.attr != cur_attr) {
                emit_style(buf, back.fg, back.bg, back.attr);
                cur_fg = back.fg;
                cur_bg = back.bg;
                cur_attr = back.attr;
                style_valid = true;
            }
            buf += back.glyph.empty() ? " " : back.glyph;

            int advance = back.glyph.empty() ? 1 : 0;
            if (advance == 0) {
                // Recompute width from the stored grapheme.
                auto gs = graphemes(back.glyph.c_str());
                advance = gs.empty() ? 1 : gs[0].width;
            }
            cursor_x = x + advance;
            wrote_anything = true;
        }
    }

    if (wrote_anything) {
        buf += "\x1b[0m";
    }

    s->front = s->back;
    s->full_repaint = false;

    if (!wrote_anything) {
        if (out && cap > 0) out[0] = '\0';
        return 0;
    }
    return emit_to(buf, out, cap);
}

int32_t vr_invalidate(int32_t handle)
{
    Surface *s = lookup(handle);
    if (!s) return -1;
    s->full_repaint = true;
    return 0;
}

int32_t vr_display_width(const char *utf8)
{
    if (!utf8) return 0;
    int32_t total = 0;
    for (const Grapheme &g : graphemes(utf8)) total += g.width;
    return total;
}

int32_t vr_truncate(const char *utf8, int32_t max_cols, char *out, size_t cap)
{
    if (!utf8 || !out || max_cols < 0) return -1;
    auto gs = graphemes(utf8);

    int32_t total = 0;
    for (const Grapheme &g : gs) total += g.width;
    if (total <= max_cols) {
        size_t len = std::strlen(utf8);
        if (len + 1 > cap) return -2;
        std::memcpy(out, utf8, len);
        out[len] = '\0';
        return total;
    }

    // Reserve one column for the ellipsis.
    const char *ellipsis = "\xe2\x80\xa6";  // U+2026
    int32_t budget = max_cols - 1;
    if (budget < 0) {
        if (cap < 1) return -2;
        out[0] = '\0';
        return 0;
    }

    std::string result;
    int32_t used = 0;
    for (const Grapheme &g : gs) {
        if (used + g.width > budget) break;
        result += g.text;
        used += g.width;
    }
    result += ellipsis;
    used += 1;

    if (result.size() + 1 > cap) return -2;
    std::memcpy(out, result.data(), result.size());
    out[result.size()] = '\0';
    return used;
}

int32_t vr_wrap(const char *utf8, int32_t width, char *out, size_t cap)
{
    if (!utf8 || !out || width <= 0) return -1;

    std::vector<std::string> lines;
    std::string line;
    int32_t line_width = 0;
    std::string word;
    int32_t word_width = 0;

    auto flush_word = [&]() {
        if (word.empty()) return;
        if (line_width > 0 && line_width + 1 + word_width > width) {
            lines.push_back(line);
            line.clear();
            line_width = 0;
        }
        if (line_width > 0) {
            line += ' ';
            line_width += 1;
        }
        // A single word longer than the line gets hard-split.
        if (word_width > width) {
            auto gs = graphemes(word.c_str());
            for (const Grapheme &g : gs) {
                if (line_width + g.width > width) {
                    lines.push_back(line);
                    line.clear();
                    line_width = 0;
                }
                line += g.text;
                line_width += g.width;
            }
        } else {
            line += word;
            line_width += word_width;
        }
        word.clear();
        word_width = 0;
    };

    size_t len = std::strlen(utf8);
    size_t i = 0;
    while (i < len) {
        size_t start = i;
        uint32_t cp = decode(utf8, len, i);
        if (cp == '\n') {
            flush_word();
            lines.push_back(line);
            line.clear();
            line_width = 0;
            continue;
        }
        if (cp == ' ' || cp == '\t') {
            flush_word();
            continue;
        }
        if (cp == '\r') continue;
        int w = cp_width(cp);
        if (w == 0 && !word.empty()) {
            word.append(utf8 + start, i - start);
            continue;
        }
        if (w == 0) continue;
        word.append(utf8 + start, i - start);
        word_width += w;
    }
    flush_word();
    lines.push_back(line);

    std::string joined;
    for (size_t k = 0; k < lines.size(); ++k) {
        if (k) joined += '\n';
        joined += lines[k];
    }
    if (joined.size() + 1 > cap) return -2;
    std::memcpy(out, joined.data(), joined.size());
    out[joined.size()] = '\0';
    return static_cast<int32_t>(lines.size());
}

const char *vr_version(void)
{
    return "valeroy-vtui-render/1.0.0";
}

}  // extern "C"
