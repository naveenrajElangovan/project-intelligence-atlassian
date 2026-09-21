import js from "@eslint/js";

export default [
  {
    ignores: ["node_modules/**"],
  },
  {
    files: ["src/**/*.js"],
    ...js.configs.recommended,
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        process: "readonly",
      },
    },
  },
];
