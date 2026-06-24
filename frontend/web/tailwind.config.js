/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{vue,ts}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        arabic: ["Cairo", "Tahoma", "sans-serif"],
      },
      colors: {
        // Primary: deep blue. 50-200 double as the soft-blue secondary accents.
        brand: {
          50: "#eff5ff", 100: "#dbe8fe", 200: "#bfd7fe", 300: "#93bbfd",
          400: "#609afa", 500: "#3b76f6", 600: "#1d4ed8", 700: "#1e40af",
          800: "#1e3a8a", 900: "#1b346f", 950: "#172554",
        },
      },
      borderRadius: {
        // Medium-to-large default radii for cards/controls.
        xl: "0.9rem",
        "2xl": "1.15rem",
      },
    },
  },
  plugins: [],
};
