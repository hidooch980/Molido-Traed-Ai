import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: "#0B2545",
        ocean: "#1B6CA8",
        cyan: { brand: "#22D3EE", signal: "#7DF9FF" },
        ice: "#EAF6FF",
        profit: "#10B981",
        loss: "#EF4444",
        warn: "#F59E0B",
      },
      fontFamily: {
        sans: ["var(--font-vazirmatn)", "Vazirmatn", "Segoe UI", "system-ui", "sans-serif"],
        mono: ["Cascadia Mono", "Consolas", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
