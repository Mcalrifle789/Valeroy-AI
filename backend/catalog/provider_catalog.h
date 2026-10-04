/* provider_catalog.h - Valeroy AI provider catalog + model normalizer (C++ layer)
 *
 * Exposes a flat C ABI so Python (ctypes) and Go (cgo) can both call in.
 * Owns two jobs:
 *   1. the built-in provider catalog (id, label, base url, models path, auth style)
 *   2. normalizing each provider's model-list JSON into one canonical shape
 */
#ifndef VALEROY_PROVIDER_CATALOG_H
#define VALEROY_PROVIDER_CATALOG_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(_WIN32) && defined(VALEROY_CATALOG_SHARED)
#  ifdef VALEROY_CATALOG_BUILD
#    define VCAT_API __declspec(dllexport)
#  else
#    define VCAT_API __declspec(dllimport)
#  endif
#else
#  define VCAT_API
#endif

/* Number of providers in the built-in catalog. */
VCAT_API int vcat_provider_count(void);

/* Writes provider `index` as a JSON object into `out`. Returns bytes written,
 * or -1 on error / -2 if `cap` is too small. */
VCAT_API int vcat_provider_at(int index, char *out, size_t cap);

/* Writes the whole catalog as a JSON array. Same return convention. */
VCAT_API int vcat_catalog_json(char *out, size_t cap);

/* Looks up a provider by id and writes it as JSON. Same return convention. */
VCAT_API int vcat_provider_by_id(const char *id, char *out, size_t cap);

/* Normalizes a provider model-list response into a canonical JSON array of
 * {"id","label","context","provider"} objects, sorted and de-duplicated.
 * Same return convention. */
VCAT_API int vcat_normalize_models(const char *provider_id,
                                  const char *raw_json,
                                  char *out, size_t cap);

/* Catalog revision, bumped when provider data changes. */
VCAT_API const char *vcat_version(void);

#ifdef __cplusplus
}
#endif
#endif /* VALEROY_PROVIDER_CATALOG_H */
