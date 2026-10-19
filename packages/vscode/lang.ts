export type UiLang = "en" | "zh-CN" | "zh-TW";

export function normalizeUiLang(raw: unknown): UiLang {
  const s = typeof raw === "string" ? raw.trim().toLowerCase() : "";
  if (s.indexOf("zh") !== 0) return "en";
  if (
    s === "zh-tw" ||
    s === "zh-hk" ||
    s === "zh-mo" ||
    s === "zh-hant" ||
    s.indexOf("zh-hant-") === 0
  ) {
    return "zh-TW";
  }
  return "zh-CN";
}

export function resolveUiLang(
  serverLang: unknown,
  vscodeLang: unknown,
): UiLang {
  const explicit = typeof serverLang === "string" ? serverLang.trim() : "";
  if (explicit && explicit.toLowerCase() !== "auto") {
    return normalizeUiLang(explicit);
  }
  return normalizeUiLang(vscodeLang);
}
