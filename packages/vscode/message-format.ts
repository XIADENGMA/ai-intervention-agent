export type MessageParams = Record<string, string | number>;

const PLURAL_BLOCK =
  /\{\s*(\w+)\s*,\s*plural\s*,((?:\s*(?:=\d+|\w+)\s*\{[^{}]*\})+)\s*\}/g;
const PLURAL_OPTION = /\s*(=\d+|\w+)\s*\{([^{}]*)\}/g;
const PLACEHOLDER = /\{\{(\w+)\}\}/g;

const pluralRulesByLang = new Map<string, Intl.PluralRules>();

export function lookupMessage(
  locale: Record<string, unknown> | null | undefined,
  key: string,
): string | null {
  let node: unknown = locale;
  for (const part of key.split(".")) {
    if (node === null || typeof node !== "object") return null;
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === "string" ? node : null;
}

function selectPlural(
  options: Map<string, string>,
  count: number,
  lang: string,
): string {
  const exact = options.get(`=${count}`);
  if (exact !== undefined) return exact;
  let rules = pluralRulesByLang.get(lang);
  if (!rules) {
    rules = new Intl.PluralRules(lang);
    pluralRulesByLang.set(lang, rules);
  }
  return options.get(rules.select(count)) ?? options.get("other") ?? "";
}

export function formatMessage(
  template: string,
  params: MessageParams,
  lang: string,
): string {
  const withPlurals = template.replace(
    PLURAL_BLOCK,
    (_block: string, name: string, body: string) => {
      const raw = Number(params[name]);
      const count = Number.isFinite(raw) ? raw : 0;
      const options = new Map<string, string>();
      for (const option of body.matchAll(PLURAL_OPTION)) {
        options.set(option[1], option[2]);
      }
      const formatted = new Intl.NumberFormat(lang).format(count);
      return selectPlural(options, count, lang).replace(/#/g, formatted);
    },
  );
  return withPlurals.replace(PLACEHOLDER, (placeholder: string, name: string) =>
    Object.prototype.hasOwnProperty.call(params, name)
      ? String(params[name])
      : placeholder,
  );
}
