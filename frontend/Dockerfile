FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

# Injeta a URL do backend em build time via ARG → ENV → arquivo .env
# O docker-compose passa VITE_API_URL como build arg
ARG VITE_API_URL=http://backend:8000
ENV VITE_API_URL=${VITE_API_URL}
RUN echo "VITE_API_URL=${VITE_API_URL}" > .env

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
