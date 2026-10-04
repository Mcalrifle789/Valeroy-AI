/* catalog_selftest.cpp - tests for the Valeroy C++ provider catalog layer. */
#include "provider_catalog.h"

#include <cstdio>
#include <cstring>
#include <string>

static int failures = 0;

static void expect(bool condition, const char *name)
{
    if (condition) {
        std::printf("  ok   %s\n", name);
    } else {
        std::printf("  FAIL %s\n", name);
        ++failures;
    }
}

static void expect_contains(const std::string &haystack, const char *needle,
                            const char *name)
{
    if (haystack.find(needle) != std::string::npos) {
        std::printf("  ok   %s\n", name);
    } else {
        std::printf("  FAIL %s\n       %s not found in: %s\n", name, needle,
                    haystack.substr(0, 400).c_str());
        ++failures;
    }
}

static void test_catalog()
{
    expect(vcat_provider_count() > 10, "catalog has a useful number of providers");

    char buf[65536];
    int n = vcat_catalog_json(buf, sizeof(buf));
    expect(n > 0, "catalog_json succeeds");
    std::string catalog(buf, n > 0 ? n : 0);

    // The providers the spec calls out by name must all be present.
    expect_contains(catalog, "\"openrouter\"", "catalog includes openrouter");
    expect_contains(catalog, "\"costruter\"", "catalog includes costruter");
    expect_contains(catalog, "\"opencode\"", "catalog includes opencode");
    expect_contains(catalog, "\"novita\"", "catalog includes novita");

    n = vcat_provider_by_id("openrouter", buf, sizeof(buf));
    expect(n > 0, "provider_by_id finds a known provider");
    expect_contains(std::string(buf), "openrouter.ai", "openrouter has its base url");

    expect(vcat_provider_by_id("not-a-provider", buf, sizeof(buf)) == -1,
           "provider_by_id rejects an unknown id");
    expect(vcat_provider_at(-1, buf, sizeof(buf)) == -1,
           "provider_at rejects a negative index");
    expect(vcat_provider_at(vcat_provider_count(), buf, sizeof(buf)) == -1,
           "provider_at rejects an out-of-range index");

    char tiny[4];
    expect(vcat_catalog_json(tiny, sizeof(tiny)) == -2,
           "catalog_json reports a too-small buffer");
}

static void test_openai_style_normalization()
{
    const char *raw =
        "{\"object\":\"list\",\"data\":["
        "{\"id\":\"gpt-5.1\",\"object\":\"model\",\"context_length\":400000},"
        "{\"id\":\"gpt-5-mini\",\"object\":\"model\"}"
        "]}";
    char out[8192];
    int n = vcat_normalize_models("openai", raw, out, sizeof(out));
    expect(n > 0, "normalizes an OpenAI-style list");
    std::string s(out);
    expect_contains(s, "\"id\":\"gpt-5-mini\"", "keeps gpt-5-mini");
    expect_contains(s, "\"context\":400000", "carries context length through");
    expect_contains(s, "\"provider\":\"openai\"", "stamps the provider id");
    // Sorted output means gpt-5-mini precedes gpt-5.1 ('-' < '.').
    expect(s.find("gpt-5-mini") < s.find("gpt-5.1"), "output is sorted by id");
}

static void test_openrouter_nested_context()
{
    const char *raw =
        "{\"data\":[{\"id\":\"anthropic/claude-opus-5\","
        "\"name\":\"Anthropic: Claude Opus 5\","
        "\"top_provider\":{\"context_length\":200000}}]}";
    char out[8192];
    expect(vcat_normalize_models("openrouter", raw, out, sizeof(out)) > 0,
           "normalizes an OpenRouter list");
    std::string s(out);
    expect_contains(s, "\"context\":200000", "reads nested top_provider context");
    expect_contains(s, "anthropic/claude-opus-5", "keeps the vendor-prefixed id");
    expect_contains(s, "Anthropic: Claude Opus 5", "uses name as the label");
}

static void test_google_namespace_stripping()
{
    const char *raw =
        "{\"models\":[{\"name\":\"models/gemini-3-pro\","
        "\"displayName\":\"Gemini 3 Pro\",\"inputTokenLimit\":1048576}]}";
    char out[8192];
    expect(vcat_normalize_models("google", raw, out, sizeof(out)) > 0,
           "normalizes a Google list");
    std::string s(out);
    expect_contains(s, "\"id\":\"gemini-3-pro\"", "strips the models/ namespace");
    expect_contains(s, "\"context\":1048576", "reads inputTokenLimit");
}

static void test_bare_array_and_strings()
{
    char out[8192];
    expect(vcat_normalize_models("ollama", "[\"llama4\",\"qwen3\"]", out, sizeof(out)) > 0,
           "normalizes a bare array of strings");
    std::string s(out);
    expect_contains(s, "\"id\":\"llama4\"", "accepts plain string entries");
    expect_contains(s, "\"label\":\"qwen3\"", "falls back to id for the label");
}

static void test_deduplication()
{
    const char *raw = "{\"data\":[{\"id\":\"m1\"},{\"id\":\"m1\"},{\"id\":\"m2\"}]}";
    char out[8192];
    vcat_normalize_models("groq", raw, out, sizeof(out));
    std::string s(out);
    size_t first = s.find("\"id\":\"m1\"");
    size_t second = s.find("\"id\":\"m1\"", first + 1);
    expect(first != std::string::npos && second == std::string::npos,
           "duplicate model ids collapse to one");
}

static void test_malformed_input_is_safe()
{
    char out[8192];
    expect(vcat_normalize_models("openai", "not json at all", out, sizeof(out)) > 0,
           "garbage input yields an empty array, not a crash");
    expect(std::strcmp(out, "[]") == 0, "garbage input yields []");

    expect(vcat_normalize_models("openai", "{\"data\":[", out, sizeof(out)) > 0,
           "truncated JSON is handled");
    expect(std::strcmp(out, "[]") == 0, "truncated JSON yields []");

    expect(vcat_normalize_models("openai", "{\"error\":{\"message\":\"bad key\"}}",
                                out, sizeof(out)) > 0,
           "an error object yields []");
    expect(std::strcmp(out, "[]") == 0, "error object yields []");

    expect(vcat_normalize_models(nullptr, "[]", out, sizeof(out)) == -1,
           "null provider id is rejected");
    expect(vcat_normalize_models("openai", nullptr, out, sizeof(out)) == -1,
           "null payload is rejected");

    // Entries with no usable id are skipped rather than emitted blank.
    vcat_normalize_models("openai", "{\"data\":[{\"object\":\"model\"},{\"id\":\"ok\"}]}",
                          out, sizeof(out));
    std::string s(out);
    expect(s.find("\"id\":\"\"") == std::string::npos, "entries without an id are dropped");
    expect_contains(s, "\"id\":\"ok\"", "valid sibling entry survives");
}

static void test_escaping()
{
    const char *raw = "{\"data\":[{\"id\":\"quote\\\"model\",\"name\":\"line\\nbreak\"}]}";
    char out[8192];
    expect(vcat_normalize_models("openai", raw, out, sizeof(out)) > 0,
           "normalizes entries needing escapes");
    std::string s(out);
    expect_contains(s, "quote\\\"model", "re-escapes embedded quotes");
    expect_contains(s, "line\\nbreak", "re-escapes embedded newlines");
}

static void test_small_buffer()
{
    const char *raw = "{\"data\":[{\"id\":\"some-fairly-long-model-identifier\"}]}";
    char tiny[8];
    expect(vcat_normalize_models("openai", raw, tiny, sizeof(tiny)) == -2,
           "too-small output buffer is reported, not overrun");
}

int main()
{
    std::printf("valeroy catalog selftest (%s)\n", vcat_version());
    test_catalog();
    test_openai_style_normalization();
    test_openrouter_nested_context();
    test_google_namespace_stripping();
    test_bare_array_and_strings();
    test_deduplication();
    test_malformed_input_is_safe();
    test_escaping();
    test_small_buffer();

    if (failures == 0) {
        std::printf("all C++ catalog tests passed\n");
        return 0;
    }
    std::printf("%d C++ catalog test(s) failed\n", failures);
    return 1;
}
