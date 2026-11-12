FROM node:26-alpine AS build
WORKDIR /app
RUN npm install --global pnpm@10.8.1
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile
COPY apps/web apps/web
RUN pnpm --filter @store-operator/web build
FROM nginx:alpine
COPY --from=build /app/apps/web/dist /usr/share/nginx/html
COPY infra/containers/nginx-web.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
