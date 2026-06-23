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
        brand: {
          50: "#eef6ff", 100: "#d9eaff", 200: "#bcd9ff", 300: "#8ec0ff",
          400: "#599cff", 500: "#3577f5", 600: "#205ae0", 700: "#1b48c0",
          800: "#1c3d9b", 900: "#1c377a", 950: "#11214a",
        },
      },
    },
  },
  plugins: [],
};
