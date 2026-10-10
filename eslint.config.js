// Flat config. The app is plain browser ES modules (web/js), no build step.
import js from '@eslint/js';
import globals from 'globals';

export default [
  { ignores: ['web/vendor/**', 'node_modules/**', '.venv/**', 'e2e/.report/**', 'e2e/.results/**', 'coverage/**', 'rust/**/target/**'] },
  js.configs.recommended,
  {
    files: ['web/js/**/*.js'],
    languageOptions: { ecmaVersion: 2024, sourceType: 'module', globals: globals.browser },
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', caughtErrors: 'none' }],
      eqeqeq: ['error', 'smart'],
      'no-implicit-globals': 'error',
      'no-console': ['warn', { allow: ['warn', 'error'] }],
    },
  },
  {
    files: ['**/*.config.js', 'e2e/**/*.{js,ts}', 'tests/js/**/*.js'],
    languageOptions: { ecmaVersion: 2024, sourceType: 'module', globals: { ...globals.node, ...globals.browser } },
    rules: { 'no-empty-pattern': 'off' }, // Playwright fixtures must destructure their first argument
  },
];
