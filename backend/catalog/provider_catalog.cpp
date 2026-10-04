/* provider_catalog.cpp - Valeroy AI provider catalog + model normalizer */
#include "provider_catalog.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstring>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace {

/* ------------------------------------------------------------------ *
 * Provider catalog
 * ------------------------------------------------------------------ */

struct Provider {
    const char *id;
    const char *label;
    const char *base_url;
    const char *models_path;
    const char *auth_style;   // "bearer" | "x-api-key" | "query"
    const char *auth_field;   // header or query-param name
    const char *kind;         // "chat" | "image" | "video" | "audio" | "multi"
    const char *docs;
};

// Keep alphabetical by label so menus render in a stable order.
const Provider kProviders[] = {
    {"anthropic", "Anthropic", "https://api.anthropic.com/v1",
     "/models", "x-api-key", "x-api-key", "chat",
     "https://docs.anthropic.com"},
    {"cerebras", "Cerebras", "https://api.cerebras.ai/v1",
     "/models", "bearer", "Authorization", "chat",
     "https://inference-docs.cerebras.ai"},
    {"cohere", "Cohere", "https://api.cohere.com/v1",
     "/models", "bearer", "Authorization", "chat",
     "https://docs.cohere.com"},
    {"costruter", "Costruter", "https://api.costruter.com/v1",
     "/models", "bearer", "Authorization", "multi",
     "https://costruter.com/docs"},
    {"deepinfra", "DeepInfra", "https://api.deepinfra.com/v1/openai",
     "/models", "bearer", "Authorization", "multi",
     "https://deepinfra.com/docs"},
    {"deepseek", "DeepSeek", "https://api.deepseek.com/v1",
     "/models", "bearer", "Authorization", "chat",
     "https://api-docs.deepseek.com"},
    {"fal", "fal.ai", "https://fal.run",
     "/models", "query", "fal_key", "video",
     "https://fal.ai/docs"},
    {"fireworks", "Fireworks AI", "https://api.fireworks.ai/inference/v1",
     "/models", "bearer", "Authorization", "multi",
     "https://docs.fireworks.ai"},
    {"google", "Google AI Studio", "https://generativelanguage.googleapis.com/v1beta",
     "/models", "query", "key", "multi",
     "https://ai.google.dev/docs"},
    {"groq", "Groq", "https://api.groq.com/openai/v1",
     "/models", "bearer", "Authorization", "chat",
     "https://console.groq.com/docs"},
    {"hyperbolic", "Hyperbolic", "https://api.hyperbolic.xyz/v1",
     "/models", "bearer", "Authorization", "multi",
     "https://docs.hyperbolic.xyz"},
    {"lmstudio", "LM Studio (local)", "http://127.0.0.1:1234/v1",
     "/models", "bearer", "Authorization", "chat",
     "https://lmstudio.ai/docs"},
    {"mistral", "Mistral AI", "https://api.mistral.ai/v1",
     "/models", "bearer", "Authorization", "chat",
     "https://docs.mistral.ai"},
    {"novita", "Novita AI", "https://api.novita.ai/v3/openai",
     "/models", "bearer", "Authorization", "multi",
     "https://novita.ai/docs"},
    {"ollama", "Ollama (local)", "http://127.0.0.1:11434/v1",
     "/models", "bearer", "Authorization", "chat",
     "https://ollama.com/docs"},
    {"openai", "OpenAI", "https://api.openai.com/v1",
     "/models", "bearer", "Authorization", "multi",
     "https://platform.openai.com/docs"},
    {"opencode", "Opencode", "https://opencode.ai/api/v1",
     "/models", "bearer", "Authorization", "chat",
     "https://opencode.ai/docs"},
    {"openrouter", "OpenRouter", "https://openrouter.ai/api/v1",
     "/models", "bearer", "Authorization", "multi",
     "https://openrouter.ai/docs"},
    {"perplexity", "Perplexity", "https://api.perplexity.ai",
     "/models", "bearer", "Authorization", "chat",
     "https://docs.perplexity.ai"},
    {"replicate", "Replicate", "https://api.replicate.com/v1",
     "/models", "bearer", "Authorization", "video",
     "https://replicate.com/docs"},
    {"runway", "Runway", "https://api.dev.runwayml.com/v1",
     "/models", "bearer", "Authorization", "video",
     "https://docs.dev.runwayml.com"},
    {"sambanova", "SambaNova", "https://api.sambanova.ai/v1",
     "/models", "bearer", "Authorization", "chat",
     "https://docs.sambanova.ai"},
    {"together", "Together AI", "https://api.together.xyz/v1",
     "/models", "bearer", "Authorization", "multi",
     "https://docs.together.ai"},
    {"xai", "xAI", "https://api.x.ai/v1",
     "/models", "bearer", "Authorization", "multi",
     "https://docs.x.ai"},
};

const int kProviderCount =
    static_cast<int>(sizeof(kProviders) / sizeof(kProviders[0]));

/* ------------------------------------------------------------------ *
 * JSON writing helpers
 * ------------------------------------------------------------------ */

void json_escape(const std::string &in, std::string &out)
{
    for (unsigned char c : in) {
        switch (c) {
        case '"':  out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\b': out += "\\b";  break;
        case '\f': out += "\\f";  break;
        case '\n': out += "\\n";  break;
        case '\r': out += "\\r";  break;
        case '\t': out += "\\t";  break;
        default:
            if (c < 0x20) {
                char buf[7];
                std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                out += buf;
            } else {
                out += static_cast<char>(c);
            }
        }
    }
}

void json_field(std::string &out, const char *key, const std::string &value,
                bool last = false)
{
    out += '"';
    out += key;
    out += "\":\"";
    json_escape(value, out);
    out += last ? "\"" : "\",";
}

std::string provider_json(const Provider &p)
{
    std::string s = "{";
    json_field(s, "id", p.id);
    json_field(s, "label", p.label);
    json_field(s, "base_url", p.base_url);
    json_field(s, "models_path", p.models_path);
    json_field(s, "auth_style", p.auth_style);
    json_field(s, "auth_field", p.auth_field);
    json_field(s, "kind", p.kind);
    json_field(s, "docs", p.docs, true);
    s += "}";
    return s;
}

int emit(const std::string &s, char *out, size_t cap)
{
    if (!out) return -1;
    if (s.size() + 1 > cap) return -2;
    std::memcpy(out, s.data(), s.size());
    out[s.size()] = '\0';
    return static_cast<int>(s.size());
}

/* ------------------------------------------------------------------ *
 * Minimal JSON reader - enough to walk provider model-list payloads
 * ------------------------------------------------------------------ */

struct Value;
using ValuePtr = std::shared_ptr<Value>;

struct Value {
    enum Type { Null, Bool, Number, String, Array, Object } type = Null;
    bool        boolean = false;
    double      number = 0.0;
    std::string str;
    std::vector<ValuePtr> items;
    std::map<std::string, ValuePtr> fields;

    const ValuePtr *find(const std::string &key) const
    {
        auto it = fields.find(key);
        return it == fields.end() ? nullptr : &it->second;
    }
};

class Parser {
public:
    explicit Parser(const char *text) : p_(text) {}

    ValuePtr parse()
    {
        skip();
        ValuePtr v = value(0);
        return v;
    }

private:
    const char *p_;
    static const int kMaxDepth = 64;

    void skip()
    {
        while (*p_ && (*p_ == ' ' || *p_ == '\t' || *p_ == '\n' || *p_ == '\r'))
            ++p_;
    }

    ValuePtr value(int depth)
    {
        if (depth > kMaxDepth) return nullptr;
        skip();
        switch (*p_) {
        case '{': return object(depth);
        case '[': return array(depth);
        case '"': return string_value();
        case 't':
            if (std::strncmp(p_, "true", 4) == 0) {
                p_ += 4;
                auto v = std::make_shared<Value>();
                v->type = Value::Bool; v->boolean = true; return v;
            }
            return nullptr;
        case 'f':
            if (std::strncmp(p_, "false", 5) == 0) {
                p_ += 5;
                auto v = std::make_shared<Value>();
                v->type = Value::Bool; v->boolean = false; return v;
            }
            return nullptr;
        case 'n':
            if (std::strncmp(p_, "null", 4) == 0) {
                p_ += 4;
                return std::make_shared<Value>();
            }
            return nullptr;
        default:
            return number_value();
        }
    }

    ValuePtr object(int depth)
    {
        auto v = std::make_shared<Value>();
        v->type = Value::Object;
        ++p_;  // '{'
        skip();
        if (*p_ == '}') { ++p_; return v; }
        for (;;) {
            skip();
            if (*p_ != '"') return nullptr;
            ValuePtr key = string_value();
            if (!key) return nullptr;
            skip();
            if (*p_ != ':') return nullptr;
            ++p_;
            ValuePtr val = value(depth + 1);
            if (!val) return nullptr;
            v->fields[key->str] = val;
            skip();
            if (*p_ == ',') { ++p_; continue; }
            if (*p_ == '}') { ++p_; return v; }
            return nullptr;
        }
    }

    ValuePtr array(int depth)
    {
        auto v = std::make_shared<Value>();
        v->type = Value::Array;
        ++p_;  // '['
        skip();
        if (*p_ == ']') { ++p_; return v; }
        for (;;) {
            ValuePtr val = value(depth + 1);
            if (!val) return nullptr;
            v->items.push_back(val);
            skip();
            if (*p_ == ',') { ++p_; continue; }
            if (*p_ == ']') { ++p_; return v; }
            return nullptr;
        }
    }

    ValuePtr string_value()
    {
        auto v = std::make_shared<Value>();
        v->type = Value::String;
        ++p_;  // opening quote
        while (*p_ && *p_ != '"') {
            if (*p_ == '\\') {
                ++p_;
                switch (*p_) {
                case '"':  v->str += '"';  ++p_; break;
                case '\\': v->str += '\\'; ++p_; break;
                case '/':  v->str += '/';  ++p_; break;
                case 'b':  v->str += '\b'; ++p_; break;
                case 'f':  v->str += '\f'; ++p_; break;
                case 'n':  v->str += '\n'; ++p_; break;
                case 'r':  v->str += '\r'; ++p_; break;
                case 't':  v->str += '\t'; ++p_; break;
                case 'u': {
                    ++p_;
                    unsigned code = 0;
                    for (int i = 0; i < 4 && *p_; ++i, ++p_) {
                        char c = *p_;
                        code <<= 4;
                        if (c >= '0' && c <= '9')      code |= (unsigned)(c - '0');
                        else if (c >= 'a' && c <= 'f') code |= (unsigned)(c - 'a' + 10);
                        else if (c >= 'A' && c <= 'F') code |= (unsigned)(c - 'A' + 10);
                        else return nullptr;
                    }
                    // Encode as UTF-8; surrogate halves pass through replaced.
                    if (code >= 0xD800 && code <= 0xDFFF) code = 0xFFFD;
                    if (code < 0x80) {
                        v->str += static_cast<char>(code);
                    } else if (code < 0x800) {
                        v->str += static_cast<char>(0xC0 | (code >> 6));
                        v->str += static_cast<char>(0x80 | (code & 0x3F));
                    } else {
                        v->str += static_cast<char>(0xE0 | (code >> 12));
                        v->str += static_cast<char>(0x80 | ((code >> 6) & 0x3F));
                        v->str += static_cast<char>(0x80 | (code & 0x3F));
                    }
                    break;
                }
                default: return nullptr;
                }
            } else {
                v->str += *p_++;
            }
        }
        if (*p_ != '"') return nullptr;
        ++p_;
        return v;
    }

    ValuePtr number_value()
    {
        const char *start = p_;
        if (*p_ == '-' || *p_ == '+') ++p_;
        bool any = false;
        while (std::isdigit(static_cast<unsigned char>(*p_))) { ++p_; any = true; }
        if (*p_ == '.') {
            ++p_;
            while (std::isdigit(static_cast<unsigned char>(*p_))) { ++p_; any = true; }
        }
        if (*p_ == 'e' || *p_ == 'E') {
            ++p_;
            if (*p_ == '-' || *p_ == '+') ++p_;
            while (std::isdigit(static_cast<unsigned char>(*p_))) ++p_;
        }
        if (!any) return nullptr;
        auto v = std::make_shared<Value>();
        v->type = Value::Number;
        v->number = std::strtod(std::string(start, p_ - start).c_str(), nullptr);
        return v;
    }
};

/* ------------------------------------------------------------------ *
 * Model normalization
 * ------------------------------------------------------------------ */

struct Model {
    std::string id;
    std::string label;
    long long   context = 0;

    bool operator<(const Model &o) const { return id < o.id; }
};

// Providers disagree on where the list lives: OpenAI-style uses "data",
// Anthropic uses "data", Google uses "models", Ollama uses "models",
// some return a bare array.
const Value *locate_list(const Value *root)
{
    if (!root) return nullptr;
    if (root->type == Value::Array) return root;
    if (root->type != Value::Object) return nullptr;

    static const char *kKeys[] = {"data", "models", "results", "items", "model_list"};
    for (const char *key : kKeys) {
        if (const ValuePtr *found = root->find(key)) {
            const Value *v = found->get();
            if (v && v->type == Value::Array) return v;
        }
    }
    return nullptr;
}

std::string pick_string(const Value *obj, const char *const *keys, size_t n)
{
    for (size_t i = 0; i < n; ++i) {
        if (const ValuePtr *found = obj->find(keys[i])) {
            const Value *v = found->get();
            if (v && v->type == Value::String && !v->str.empty()) return v->str;
        }
    }
    return std::string();
}

long long pick_number(const Value *obj, const char *const *keys, size_t n)
{
    for (size_t i = 0; i < n; ++i) {
        if (const ValuePtr *found = obj->find(keys[i])) {
            const Value *v = found->get();
            if (!v) continue;
            if (v->type == Value::Number) return static_cast<long long>(v->number);
            if (v->type == Value::Object) {
                // OpenRouter nests context under top_provider.context_length
                static const char *kInner[] = {"context_length", "context_window"};
                long long inner = pick_number(v, kInner, 2);
                if (inner > 0) return inner;
            }
        }
    }
    return 0;
}

// Google returns "models/gemini-2.5-pro"; strip the namespace for display.
std::string strip_namespace(const std::string &id)
{
    size_t slash = id.rfind('/');
    if (slash == std::string::npos) return id;
    std::string head = id.substr(0, slash);
    if (head == "models" || head == "accounts") return id.substr(slash + 1);
    return id;
}

}  // namespace

/* ------------------------------------------------------------------ *
 * Public C ABI
 * ------------------------------------------------------------------ */

extern "C" {

int vcat_provider_count(void)
{
    return kProviderCount;
}

int vcat_provider_at(int index, char *out, size_t cap)
{
    if (index < 0 || index >= kProviderCount) return -1;
    return emit(provider_json(kProviders[index]), out, cap);
}

int vcat_catalog_json(char *out, size_t cap)
{
    std::string s = "[";
    for (int i = 0; i < kProviderCount; ++i) {
        if (i) s += ',';
        s += provider_json(kProviders[i]);
    }
    s += "]";
    return emit(s, out, cap);
}

int vcat_provider_by_id(const char *id, char *out, size_t cap)
{
    if (!id) return -1;
    for (int i = 0; i < kProviderCount; ++i) {
        if (std::strcmp(kProviders[i].id, id) == 0)
            return emit(provider_json(kProviders[i]), out, cap);
    }
    return -1;
}

int vcat_normalize_models(const char *provider_id,
                          const char *raw_json,
                          char *out, size_t cap)
{
    if (!provider_id || !raw_json) return -1;

    Parser parser(raw_json);
    ValuePtr root = parser.parse();
    const Value *list = locate_list(root.get());
    if (!list) return emit("[]", out, cap);

    static const char *kIdKeys[]    = {"id", "name", "model", "slug", "model_name"};
    static const char *kLabelKeys[] = {"display_name", "label", "title", "name", "id"};
    static const char *kCtxKeys[]   = {"context_length", "context_window",
                                       "max_context_length", "max_input_tokens",
                                       "inputTokenLimit", "top_provider"};

    std::vector<Model> models;
    models.reserve(list->items.size());

    for (const ValuePtr &item : list->items) {
        const Value *v = item.get();
        if (!v) continue;

        Model m;
        if (v->type == Value::String) {
            m.id = v->str;
        } else if (v->type == Value::Object) {
            m.id = pick_string(v, kIdKeys, sizeof(kIdKeys) / sizeof(kIdKeys[0]));
            m.label = pick_string(v, kLabelKeys,
                                  sizeof(kLabelKeys) / sizeof(kLabelKeys[0]));
            m.context = pick_number(v, kCtxKeys,
                                    sizeof(kCtxKeys) / sizeof(kCtxKeys[0]));
        } else {
            continue;
        }

        if (m.id.empty()) continue;
        m.id = strip_namespace(m.id);
        if (m.label.empty()) m.label = m.id;
        models.push_back(m);
    }

    std::sort(models.begin(), models.end());
    models.erase(std::unique(models.begin(), models.end(),
                            [](const Model &a, const Model &b) {
                                return a.id == b.id;
                            }),
                 models.end());

    std::string s = "[";
    for (size_t i = 0; i < models.size(); ++i) {
        if (i) s += ',';
        s += '{';
        json_field(s, "id", models[i].id);
        json_field(s, "label", models[i].label);
        s += "\"context\":";
        s += std::to_string(models[i].context);
        s += ',';
        json_field(s, "provider", provider_id, true);
        s += '}';
    }
    s += "]";
    return emit(s, out, cap);
}

const char *vcat_version(void)
{
    return "valeroy-catalog/1.0.0";
}

}  // extern "C"
