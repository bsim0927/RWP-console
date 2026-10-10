import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['tests/js/**/*.test.js'],
    environment: 'jsdom',
    coverage: {
      provider: 'v8',
      include: ['web/js/**/*.js'],
      reporter: ['text-summary', 'lcov'],
      reportsDirectory: 'coverage/js',
    },
  },
});
