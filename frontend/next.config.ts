/** @type {import('next').NextConfig} */
const nextConfig: Record<string, unknown> = {
  output: 'standalone',
  images: {
    unoptimized: true,
  },
};

module.exports = nextConfig;
