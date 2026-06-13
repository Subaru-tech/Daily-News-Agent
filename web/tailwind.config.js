/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#0f0c29',
        surface: 'rgba(255, 255, 255, 0.05)',
        primary: '#667eea',
        secondary: '#764ba2',
      }
    },
  },
  plugins: [],
}
