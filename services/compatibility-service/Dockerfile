FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN go test ./...
RUN CGO_ENABLED=0 GOOS=linux go build -o compatibility-service .

FROM alpine:3.19
WORKDIR /app
COPY --from=builder /app/compatibility-service .
EXPOSE 8004
CMD ["./compatibility-service"]
