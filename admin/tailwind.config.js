/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./pages/**/*.{js,jsx}",
    "./components/**/*.{js,jsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: "#0a0a0a",
        surface: "#141414",
        surface2: "#1c1c1c",
        border: "#2a2a2a",
        gold: {
          DEFAULT: "#C9A84C",
          dim: "#8a7333",
          bright: "#e0c46e",
        },
        // Semantic alias for the panel's one accent color — same value as
        // `gold`, just named for intent where "primary action" reads better
        // than "gold" in component code.
        primary: {
          DEFAULT: "#C9A84C",
          dim: "#8a7333",
          bright: "#e0c46e",
        },
      },
      fontFamily: {
        ethiopic: ["'Noto Sans Ethiopic'", "sans-serif"],
      },
    },
  },
  plugins: [],
};
