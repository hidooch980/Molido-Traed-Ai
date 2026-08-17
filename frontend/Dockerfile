# Frontend image — multi-stage so the runtime carries no build toolchain.

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Baked at build time because Next inlines NEXT_PUBLIC_* into the client bundle.
# Changing the API URL therefore means a rebuild, not just a restart.
ARG NEXT_PUBLIC_API_URL=http://api:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
# Passed in by compose so the running build is identifiable in the UI. Computing
# it inside next.config would be evaluated per build too, but an explicit arg is
# visible in the deploy command and cannot be silently cached away by a layer.
ARG BUILD_STAMP=dev
ENV NEXT_PUBLIC_BUILD=$BUILD_STAMP
ARG APP_VERSION=dev
ENV NEXT_PUBLIC_VERSION=$APP_VERSION
ARG GIT_COMMIT=local
ENV NEXT_PUBLIC_COMMIT=$GIT_COMMIT
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1

RUN addgroup -g 10001 -S molido && adduser -u 10001 -S molido -G molido

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json

USER molido
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    # A route that renders nothing and reads nothing, rather than `/`.
    #
    # `/` is the heaviest page here - server-rendered, several API calls deep -
    # and on two cores under load it outran the probe timeout. The probe was
    # killed, the container was marked unhealthy, and every page it served was
    # returning 200 the whole time. A liveness probe that fails when the
    # database is slow restarts a healthy web server because something else is
    # busy, which makes the busy thing worse.
    CMD wget -q --spider http://localhost:3000/api/health || exit 1

CMD ["npm", "run", "start"]
