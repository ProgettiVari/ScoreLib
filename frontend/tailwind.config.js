/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",
    "./public/index.html",
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ["'Cabinet Grotesk'", "ui-sans-serif", "system-ui", "sans-serif"],
        sans: ["'Satoshi'", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        ink: "hsl(var(--ink))",
        canvas: "var(--canvas, #FFFFFF)",
        canvas2: "var(--canvas2, #FAFAFA)",
        canvas3: "var(--canvas3, #F5F5F5)",
        rule: "var(--rule, #E5E5E5)",
        muted2: "var(--muted2, #737373)",
        muted3: "var(--muted3, #A3A3A3)",
        highlight: "#FEF08A",
        highlightFg: "#854D0E",
      },
      keyframes: {
        "accordion-down": { from: { height: "0" }, to: { height: "var(--radix-accordion-content-height)" } },
        "accordion-up": { from: { height: "var(--radix-accordion-content-height)" }, to: { height: "0" } },
        "fade-in": { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        "result-in": { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        "page-flash": {
          "0%": { boxShadow: "0 0 0 0 rgba(0,0,0,0)" },
          "15%": { boxShadow: "0 0 0 3px rgba(23,23,23,0.18)" },
          "100%": { boxShadow: "0 0 0 0 rgba(0,0,0,0)" },
        },
        "status-pop": {
          "0%": { transform: "scale(0.92)" },
          "55%": { transform: "scale(1.06)" },
          "100%": { transform: "scale(1)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "fade-in": "fade-in 220ms ease-out",
        "result-in": "result-in 320ms cubic-bezier(0.16, 1, 0.3, 1) backwards",
        "page-flash": "page-flash 900ms ease-out",
        "status-pop": "status-pop 320ms cubic-bezier(0.34, 1.56, 0.64, 1)",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
