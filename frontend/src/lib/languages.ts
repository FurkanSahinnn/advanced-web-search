export const REPORT_LANGUAGE_CODES = ["auto", "tr", "en", "es", "fr", "de", "ar", "ru", "zh"] as const;
export type ReportLanguageCode = (typeof REPORT_LANGUAGE_CODES)[number];
export function langKey(code: string): string {
  return `lang.${code}`;
}
