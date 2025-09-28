package main

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	backoff "github.com/cenkalti/backoff/v4"
	"github.com/gorilla/websocket"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	redis "github.com/redis/go-redis/v9"
	"github.com/segmentio/kafka-go"
)

type SinkType int

const (
	SinkNone SinkType = iota
	SinkRedis
	SinkKafka
)

type Gateway struct {
	wsURL     string
	symbols   []string
	sinkType  SinkType
	redis     *redis.Client
	redisKey  string
	kafkaW    *kafka.Writer
	kafkaTopic string

	conn   *websocket.Conn
	mu     sync.Mutex
	ctx    context.Context
	cancel context.CancelFunc
}

var (
	upgradesTotal = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "ws_gateway_reconnects_total",
		Help: "Total reconnects to Bybit WS",
	})
	messagesTotal = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "ws_gateway_messages_total",
		Help: "Total messages processed",
	}, []string{"type"})
	errorsTotal = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "ws_gateway_errors_total",
		Help: "Total errors",
	})
	connectedGauge = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "ws_gateway_connected",
		Help: "WS connection state (1 connected)",
	})
)

func init() {
	prometheus.MustRegister(upgradesTotal, messagesTotal, errorsTotal, connectedGauge)
}

func NewGateway() *Gateway {
	wsURL := getenv("WS_URL", "wss://stream-testnet.bybit.com/v5/public")
	symbols := strings.Split(getenv("SYMBOLS", "BTCUSDT,ETHUSDT"), ",")
	redisURL := os.Getenv("REDIS_URL")
	kafkaBrokers := getenv("KAFKA_BROKERS", "")
	kafkaTopic := getenv("KAFKA_TOPIC", "md_ticks")

	ctx, cancel := context.WithCancel(context.Background())

	g := &Gateway{
		wsURL:   wsURL,
		symbols: symbols,
		ctx:     ctx,
		cancel:  cancel,
	}

	if redisURL != "" {
		opt, err := redis.ParseURL(redisURL)
		if err != nil {
			log.Fatalf("invalid REDIS_URL: %v", err)
		}
		g.redis = redis.NewClient(opt)
		g.redisKey = getenv("REDIS_STREAM", "md_ticks")
		g.sinkType = SinkRedis
		log.Printf("sink=redis stream=%s", g.redisKey)
	} else if kafkaBrokers != "" {
		brokers := strings.Split(kafkaBrokers, ",")
		g.kafkaW = &kafka.Writer{
			Addr:         kafka.TCP(brokers...),
			Topic:        kafkaTopic,
			RequiredAcks: kafka.RequireAll,
		}
		g.kafkaTopic = kafkaTopic
		g.sinkType = SinkKafka
		log.Printf("sink=kafka topic=%s", kafkaTopic)
	} else {
		g.sinkType = SinkNone
		log.Printf("sink=none (stdout)")
	}

	return g
}

func getenv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func (g *Gateway) connect() error {
	dialer := websocket.Dialer{
		Proxy:            http.ProxyFromEnvironment,
		HandshakeTimeout: 15 * time.Second,
		TLSClientConfig:  &tls.Config{MinVersion: tls.VersionTLS12},
	}
	conn, _, err := dialer.Dial(g.wsURL, nil)
	if err != nil {
		return err
	}
	g.mu.Lock()
	g.conn = conn
	g.mu.Unlock()
	connectedGauge.Set(1)
	upgradesTotal.Inc()
	return nil
}

func (g *Gateway) closeConn() {
	g.mu.Lock()
	if g.conn != nil {
		_ = g.conn.Close()
		g.conn = nil
	}
	g.mu.Unlock()
	connectedGauge.Set(0)
}

func (g *Gateway) subscribe() error {
	g.mu.Lock()
	conn := g.conn
	g.mu.Unlock()
	if conn == nil {
		return fmt.Errorf("no connection")
	}
	for _, s := range g.symbols {
		msg := map[string]any{
			"op":   "subscribe",
			"args": []string{fmt.Sprintf("orderbook.25.%s", s), fmt.Sprintf("tickers.%s", s)},
		}
		b, _ := json.Marshal(msg)
		if err := conn.WriteMessage(websocket.TextMessage, b); err != nil {
			return err
		}
		time.Sleep(100 * time.Millisecond)
	}
	return nil
}

type OutEvent struct {
	Ts      int64       `json:"ts"`
	Symbol  string      `json:"symbol"`
	Type    string      `json:"type"`
	Payload interface{} `json:"payload"`
}

func (g *Gateway) publish(ev OutEvent) {
	data, _ := json.Marshal(ev)
	switch g.sinkType {
	case SinkRedis:
		_ = g.redis.XAdd(g.ctx, &redis.XAddArgs{Stream: g.redisKey, Values: map[string]interface{}{"data": data}}).Err()
	case SinkKafka:
		_ = g.kafkaW.WriteMessages(g.ctx, kafka.Message{Value: data})
	default:
		log.Printf("ev=%s", string(data))
	}
}

func (g *Gateway) run() {
	bo := backoff.NewExponentialBackOff()
	bo.InitialInterval = time.Second
	bo.MaxInterval = 30 * time.Second
	for {
		select {
		case <-g.ctx.Done():
			return
		default:
		}

		if err := g.connect(); err != nil {
			errorsTotal.Inc()
			d := bo.NextBackOff()
			log.Printf("connect_error err=%v backoff=%s", err, d)
			time.Sleep(d)
			continue
		}
		_ = g.subscribe()
		bo.Reset()

		g.readLoop()
		g.closeConn()
	}
}

func (g *Gateway) readLoop() {
	g.mu.Lock()
	conn := g.conn
	g.mu.Unlock()
	if conn == nil {
		return
	}
	conn.SetReadLimit(8 << 20)
	_ = conn.SetReadDeadline(time.Now().Add(60 * time.Second))
	conn.SetPongHandler(func(string) error {
		_ = conn.SetReadDeadline(time.Now().Add(60 * time.Second))
		return nil
	})

	for {
		_, message, err := conn.ReadMessage()
		if err != nil {
			errorsTotal.Inc()
			log.Printf("read_error err=%v", err)
			return
		}
		var raw map[string]any
		if err := json.Unmarshal(message, &raw); err != nil {
			errorsTotal.Inc()
			continue
		}
		topic, _ := raw["topic"].(string)
		data := raw["data"]
		ts := time.Now().UnixMilli()
		symbol := ""
		if m, ok := data.(map[string]any); ok {
			if s, ok2 := m["s"].(string); ok2 {
				symbol = s
			}
		}
		out := OutEvent{Ts: ts, Symbol: symbol, Type: topic, Payload: data}
		messagesTotal.WithLabelValues("ws").Inc()
		g.publish(out)
	}
}

func (g *Gateway) healthz(w http.ResponseWriter, r *http.Request) {
	g.mu.Lock()
	connected := g.conn != nil
	g.mu.Unlock()
	status := http.StatusOK
	if !connected {
		status = http.StatusServiceUnavailable
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write([]byte(fmt.Sprintf(`{"status":"%s"}`, map[bool]string{true: "ok", false: "unhealthy"}[connected])))
}

func main() {
	g := NewGateway()
	go g.run()

	http.Handle("/metrics", promhttp.Handler())
	http.HandleFunc("/healthz", g.healthz)

	addr := getenv("ADDR", ":8082")
	log.Printf("starting ws-gateway on %s", addr)
	if err := http.ListenAndServe(addr, nil); err != nil {
		log.Fatalf("http_server_error: %v", err)
	}
}


