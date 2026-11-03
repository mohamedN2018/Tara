/** @type {import('tailwindcss').Config} */
// Tara design tokens. Brand colours are fixed by the identity guide:
// Tara Purple #6A00F4, Neon Violet #A855F7, Accent Pink #FF4ED8,
// Deep Indigo #0B0B1F, Soft Lavender #E8E6FF.
// `gray` is replaced by an indigo-tinted neutral scale so every surface, border
// and muted text in the app speaks the brand without per-component changes.
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{vue,ts}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Manrope", "Cairo", "system-ui", "sans-serif"],
        arabic: ["Cairo", "Manrope", "Tahoma", "sans-serif"],
        display: ["Manrope", "Cairo", "system-ui", "sans-serif"],
      },
      colors: {
        brand: {
          50: "#F5F0FF",
          100: "#EBE0FF",
          200: "#D8C4FF",
          300: "#BE9BFF",
          400: "#A855F7", // Neon Violet
          500: "#8A2DF6",
          600: "#6A00F4", // Tara Purple
          700: "#5900CF",
          800: "#4700A6",
          900: "#360080",
          950: "#1E0649",
        },
        accent: {
          50: "#FFF0FC",
          100: "#FFDDF8",
          200: "#FFB8F0",
          300: "#FF8AE6",
          400: "#FF6BDF",
          500: "#FF4ED8", // Accent Pink
          600: "#E62BBE",
          700: "#BF1C9C",
          800: "#8F1675",
          900: "#5E104D",
        },
        ink: "#0B0B1F", // Deep Indigo
        lavender: "#E8E6FF", // Soft Lavender
        gray: {
          50: "#F8F7FF",
          100: "#F1F0FB",
          200: "#E4E2F3",
          300: "#CCC9E3",
          400: "#9E9AC0",
          500: "#6F6B95",
          600: "#545079",
          700: "#3A375E",
          800: "#25234A",
          900: "#15142F",
          950: "#0B0B1F",
        },
      },
      backgroundImage: {
        "tara-gradient": "linear-gradient(135deg, #6A00F4 0%, #A855F7 55%, #FF4ED8 100%)",
        "tara-gradient-soft":
          "linear-gradient(135deg, rgba(106,0,244,0.14) 0%, rgba(168,85,247,0.10) 55%, rgba(255,78,216,0.10) 100%)",
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.25rem",
        "3xl": "1.75rem",
      },
      boxShadow: {
        card: "0 1px 2px rgba(11,11,31,0.04), 0 4px 16px -6px rgba(11,11,31,0.08)",
        "card-dark": "0 1px 2px rgba(0,0,0,0.4), 0 8px 24px -12px rgba(0,0,0,0.6)",
        pop: "0 12px 40px -12px rgba(11,11,31,0.28)",
        glow: "0 8px 24px -8px rgba(106,0,244,0.55)",
      },
      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "pop-in": {
          "0%": { opacity: "0", transform: "translateY(4px) scale(0.98)" },
          "100%": { opacity: "1", transform: "translateY(0) scale(1)" },
        },
      },
      animation: {
        "pop-in": "pop-in 160ms ease-out",
      },
    },
  },
  plugins: [],
};
