import { afterEach, describe, expect, it } from "vitest";
import { createApp, h } from "vue";
import { createI18n } from "vue-i18n";

import TaraLogo from "@/components/brand/TaraLogo.vue";
import { applyBrandIcons, brandAppIcon, brandMark, isArabicLocale } from "@/lib/brand";

function mountLogo(locale: string, props: Record<string, unknown> = {}) {
  const i18n = createI18n({ legacy: false, locale, messages: { ar: {}, en: {}, fr: {} } });
  const host = document.createElement("div");
  createApp({ render: () => h(TaraLogo, props) }).use(i18n).mount(host);
  const root = host.firstElementChild as HTMLElement;
  return {
    text: () => root.textContent ?? "",
    img: () => root.querySelector("img") as HTMLImageElement,
    all: () => Array.from(root.querySelectorAll("img")),
    attr: (name: string) => root.getAttribute(name),
  };
}

describe("brand logo follows the language", () => {
  afterEach(() => {
    document.head.innerHTML = "";
  });

  it("Arabic is the only language that gets the Arabic logo", () => {
    expect(isArabicLocale("ar")).toBe(true);
    expect(isArabicLocale("ar-EG")).toBe(true);
    for (const other of ["en", "fr", "de", "", null, undefined]) expect(isArabicLocale(other)).toBe(false);
  });

  it("picks the Arabic or English artwork, colour or white", () => {
    expect(brandMark("ar")).toContain("tara-ar");
    expect(brandMark("ar", "white")).toContain("tara-ar-white");
    expect(brandMark("en")).toContain("tara-en");
    expect(brandMark("fr", "white")).toContain("tara-en-white");
    expect(brandAppIcon("ar")).toBe("/icons/icon-ar-192.png");
    expect(brandAppIcon("en")).toBe("/icons/icon-en-192.png");
  });

  it("shows only the logo image in both languages, never an extra word", () => {
    const ar = mountLogo("ar");
    expect(ar.img().getAttribute("src")).toContain("tara-ar");
    expect(ar.text()).toBe("");
    const en = mountLogo("en");
    expect(en.img().getAttribute("src")).toContain("tara-en");
    expect(en.text()).toBe("");
  });

  it("dark themes use the white Arabic wordmark and the light-lettered English logo", () => {
    expect(brandMark("en", "gradient", true)).toContain("tara-en-dark");
    expect(brandMark("ar", "gradient", true)).toContain("tara-ar-white");
    for (const [lang, darkFile] of [["en", "tara-en-dark"], ["ar", "tara-ar-white"]]) {
      const imgs = mountLogo(lang).all();
      expect(imgs).toHaveLength(2);
      expect(imgs[0].className).toContain("dark:hidden");
      expect(imgs[1].className).toContain("dark:block");
      expect(imgs[1].getAttribute("src")).toContain(darkFile);
    }
  });

  it("keeps an accessible name and hides the image itself", () => {
    const w = mountLogo("ar", { label: "تارا" });
    expect(w.attr("role")).toBe("img");
    expect(w.attr("aria-label")).toBe("تارا");
    expect(w.img().getAttribute("alt")).toBe("");
  });

  it("swaps the favicon and home-screen icon with the language", () => {
    document.head.innerHTML =
      '<link id="tara-favicon" rel="icon" href="/icons/favicon-ar.png"><link id="tara-apple-icon" rel="apple-touch-icon" href="/icons/apple-touch-icon.png">';
    applyBrandIcons("en");
    expect(document.getElementById("tara-favicon")?.getAttribute("href")).toBe("/icons/favicon-en.png");
    expect(document.getElementById("tara-apple-icon")?.getAttribute("href")).toBe("/icons/apple-touch-icon-en.png");
    applyBrandIcons("ar");
    expect(document.getElementById("tara-favicon")?.getAttribute("href")).toBe("/icons/favicon-ar.png");
  });
});
