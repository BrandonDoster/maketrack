/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/maketrack/templates/**/*.html",
    "./src/maketrack/templates/**/*.jinja",
    "./src/maketrack/**/*.py",
  ],
  darkMode: "class",
  theme: {
    extend: {
      // Four brand tokens — see .claude/skills/maketrack-brand/SKILL.md
      // for the rationale and color rules.
      colors: {
        crimson: "#C8252C",
        "slate-ink": "#1F2937",
        bone: "#F5F2ED",
        steel: "#6B6E72",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["JetBrains Mono", "SF Mono", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
