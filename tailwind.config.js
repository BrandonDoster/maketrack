/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/maketrack/templates/**/*.html",
    "./src/maketrack/templates/**/*.jinja",
    "./src/maketrack/**/*.py",
  ],
  darkMode: "class",
  theme: {
    extend: {},
  },
  plugins: [],
};
