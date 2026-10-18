# VALZ Dashboard (SvelteKit + adapter-node).
# AI_BACKEND_URL selects the API; a public HTTPS URL also links browser requests directly to it.

FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@12.11.2 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
# Vercel uses its own adapter; Docker must produce the adapter-node build/ entry point.
ENV VERCEL=""
RUN pnpm exec svelte-kit sync && pnpm exec vite build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000 \
    AI_BACKEND_URL=http://api:8000 \
    # Videos are uploaded through this server (adapter-node default limit is 512K)
    BODY_SIZE_LIMIT=600M \
    # Behind nginx: take the public protocol / host from its headers (needed for same-origin form POSTs)
    PROTOCOL_HEADER=x-forwarded-proto \
    HOST_HEADER=x-forwarded-host
# Every dependency is bundled into build/ at build time; package.json only marks the output as ES modules
COPY --from=build /app/build ./build
COPY --from=build /app/package.json ./
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -qO- http://127.0.0.1:3000/ > /dev/null || exit 1
CMD ["node", "build"]
