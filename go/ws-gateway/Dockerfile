FROM golang:1.21 as builder
WORKDIR /app
COPY go.mod ./
RUN go mod download
COPY . ./
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o ws-gateway

FROM gcr.io/distroless/base-debian11
WORKDIR /
COPY --from=builder /app/ws-gateway /ws-gateway
EXPOSE 8082
USER 65532:65532
ENTRYPOINT ["/ws-gateway"]


