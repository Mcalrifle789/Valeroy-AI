/* vtui_render.h - Valeroy AI terminal render accelerator (C++ frontend layer)
 *
 * Holds a styled character grid and emits only the cells that changed since the
 * last flush. Doing the diff here instead of in Python keeps full-screen
 * repaints cheap, which is what stops the chatbox from flickering while the
 * model streams tokens in.
 */
#ifndef VALEROY_VTUI_RENDER_H
#define VALEROY_VTUI_RENDER_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(_WIN32) && defined(VALEROY_RENDER_SHARED)
#  ifdef VALEROY_RENDER_BUILD
#    define VR_API __declspec(dllexport)
#  else
#    define VR_API __declspec(dllimport)
#  endif
#else
#  define VR_API
#endif

/* Attribute bits for vr_put. */
#define VR_BOLD      0x01u
#define VR_DIM       0x02u
#define VR_ITALIC    0x04u
#define VR_UNDERLINE 0x08u
#define VR_REVERSE   0x10u

/* Create a surface. Returns a handle, or 0 on failure. */
VR_API int32_t vr_create(int32_t cols, int32_t rows);

/* Destroy a surface. Safe to call with an unknown handle. */
VR_API void vr_destroy(int32_t handle);

/* Resize a surface. Contents are cleared and the next flush repaints fully. */
VR_API int32_t vr_resize(int32_t handle, int32_t cols, int32_t rows);

/* Reset every cell of the back buffer to a space with default colors. */
VR_API int32_t vr_clear(int32_t handle);

/* Fill a rectangle with a background color. */
VR_API int32_t vr_fill(int32_t handle, int32_t x, int32_t y,
                       int32_t w, int32_t h, int32_t bg);

/* Write UTF-8 text at (x, y). `fg`/`bg` are 256-color indices, or -1 for the
 * terminal default. Returns the number of columns advanced, or -1 on error.
 * Text is clipped to the surface; double-width glyphs occupy two cells. */
VR_API int32_t vr_put(int32_t handle, int32_t x, int32_t y, const char *utf8,
                      int32_t fg, int32_t bg, uint32_t attr);

/* Emit the ANSI byte sequence that turns the previously flushed frame into the
 * current one, then promote the back buffer to front. Returns bytes written,
 * 0 when nothing changed, -2 if `cap` is too small, -1 on error. */
VR_API int32_t vr_flush(int32_t handle, char *out, size_t cap);

/* Force the next flush to repaint every cell (use after terminal resize). */
VR_API int32_t vr_invalidate(int32_t handle);

/* Display width of a UTF-8 string in terminal columns. */
VR_API int32_t vr_display_width(const char *utf8);

/* Truncate `utf8` to at most `max_cols` columns, appending an ellipsis when it
 * had to cut. Writes a NUL-terminated result. Returns columns used, -2 if the
 * buffer is too small. */
VR_API int32_t vr_truncate(const char *utf8, int32_t max_cols,
                           char *out, size_t cap);

/* Word-wrap `utf8` to `width` columns. Lines are newline-separated in `out`.
 * Returns the number of lines, or -2 if the buffer is too small. */
VR_API int32_t vr_wrap(const char *utf8, int32_t width, char *out, size_t cap);

VR_API const char *vr_version(void);

#ifdef __cplusplus
}
#endif
#endif /* VALEROY_VTUI_RENDER_H */
