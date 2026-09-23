package main

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"
)

var catalogURL string
var httpClient = &http.Client{Timeout: 5 * time.Second}

func catalogServiceURL() string {
	if catalogURL == "" {
		catalogURL = os.Getenv("CATALOG_SERVICE_URL")
		if catalogURL == "" {
			catalogURL = "http://catalog-service:8002"
		}
	}
	return catalogURL
}

type Product struct {
	ID    int                    `json:"id"`
	SKU   string                 `json:"sku"`
	Name  string                 `json:"name"`
	Specs map[string]interface{} `json:"specs"`
}

type ComponentRequest struct {
	Type      string `json:"type"`
	ProductID int    `json:"product_id"`
}

type CompatibilityRequest struct {
	Components []ComponentRequest `json:"components"`
	UserID     *string            `json:"user_id"`
	SessionID  *string            `json:"session_id"`
}

type CheckResult struct {
	Rule    string                 `json:"rule"`
	Status  string                 `json:"status"`
	Details map[string]interface{} `json:"details"`
}

type CompatibilityResponse struct {
	Compatible     bool          `json:"compatible"`
	Checks         []CheckResult `json:"checks"`
	EventPublished bool          `json:"event_published"`
	EventKey       *string       `json:"event_key"`
}

func fetchProduct(productID int) (*Product, error) {
	url := fmt.Sprintf("%s/api/products/%d", catalogServiceURL(), productID)
	resp, err := httpClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("catalog unavailable: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusNotFound {
		return nil, fmt.Errorf("product %d not found", productID)
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("catalog error: status %d", resp.StatusCode)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	var product Product
	if err := json.Unmarshal(body, &product); err != nil {
		return nil, err
	}
	return &product, nil
}

func passOrFail(pass bool) string {
	if pass {
		return "PASS"
	}
	return "FAIL"
}

func toFloat(v interface{}) float64 {
	switch val := v.(type) {
	case float64:
		return val
	case int:
		return float64(val)
	}
	return 0
}

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func instanceID() string {
	if id := os.Getenv("INSTANCE_ID"); id != "" {
		return id
	}
	hostname, _ := os.Hostname()
	return hostname
}

func healthHandler(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{
		"service":  "compatibility-service",
		"status":   "healthy",
		"version":  "1.0.0",
		"instance": instanceID(),
	})
}

func compatibilityCheckHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"detail": "method not allowed"})
		return
	}
	var req CompatibilityRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid request body"})
		return
	}

	byType := map[string]int{}
	for _, c := range req.Components {
		byType[strings.ToLower(c.Type)] = c.ProductID
	}

	if len(byType) == 0 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "at least one component is required"})
		return
	}

	// fetch only requested products
	products := map[string]*Product{}
	for t, id := range byType {
		p, err := fetchProduct(id)
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]string{"detail": err.Error()})
			return
		}
		products[t] = p
	}

	checks := []CheckResult{}
	allPass := true

	// CPU_SOCKET
	if cpu, ok := products["cpu"]; ok {
		if mb, ok := products["motherboard"]; ok {
			cpuSocket, _ := cpu.Specs["socket"].(string)
			mbSocket, _ := mb.Specs["socket"].(string)
			pass := cpuSocket != "" && mbSocket != "" && cpuSocket == mbSocket
			st := passOrFail(pass)
			if !pass {
				allPass = false
			}
			checks = append(checks, CheckResult{
				Rule:   "CPU_SOCKET",
				Status: st,
				Details: map[string]interface{}{
					"cpu_socket":         cpuSocket,
					"motherboard_socket": mbSocket,
				},
			})
		}
	}

	// RAM_TYPE
	if ram, ok := products["ram"]; ok {
		if mb, ok := products["motherboard"]; ok {
			ramType, _ := ram.Specs["memory_type"].(string)
			mbType, _ := mb.Specs["memory_type"].(string)
			pass := ramType != "" && mbType != "" && ramType == mbType
			st := passOrFail(pass)
			if !pass {
				allPass = false
			}
			checks = append(checks, CheckResult{
				Rule:   "RAM_TYPE",
				Status: st,
				Details: map[string]interface{}{
					"ram_memory_type":         ramType,
					"motherboard_memory_type": mbType,
				},
			})
		}
	}

	// PSU_POWER
	if psu, ok := products["psu"]; ok {
		if gpu, ok := products["gpu"]; ok {
			psuWatts := toFloat(psu.Specs["wattage"])
			gpuRequired := toFloat(gpu.Specs["recommended_psu_watts"])
			pass := psuWatts > 0 && gpuRequired > 0 && psuWatts >= gpuRequired
			st := passOrFail(pass)
			if !pass {
				allPass = false
			}
			checks = append(checks, CheckResult{
				Rule:   "PSU_POWER",
				Status: st,
				Details: map[string]interface{}{
					"psu_wattage":           psuWatts,
					"gpu_recommended_watts": gpuRequired,
				},
			})
		}
	}

	if len(checks) == 0 {
		writeJSON(w, http.StatusBadRequest, map[string]string{
			"detail": "no applicable rules for the given component combination",
		})
		return
	}

	rules := make([]string, 0, len(checks))
	failedRules := []string{}
	for _, check := range checks {
		rules = append(rules, check.Rule)
		if check.Status == "FAIL" {
			failedRules = append(failedRules, check.Rule)
		}
	}

	eventPublished := false
	var eventKey *string
	event, err := buildEvent(
		"COMPATIBILITY_CHECKED",
		"compatibility-service",
		map[string]interface{}{
			"compatible":   allPass,
			"rules":        rules,
			"failed_rules": failedRules,
			"components":   byType,
			"checks":       checks,
		},
	)
	if err != nil {
		log.Printf("compatibility evaluated, but event creation failed: %v", err)
	} else {
		event.UserID = req.UserID
		event.SessionID = req.SessionID
		key, publishErr := publishEvent(r.Context(), event)
		if publishErr != nil {
			log.Printf("compatibility evaluated, but COMPATIBILITY_CHECKED could not be written to S3: %v", publishErr)
		} else {
			eventPublished = true
			eventKey = &key
		}
	}

	writeJSON(w, http.StatusOK, CompatibilityResponse{
		Compatible:     allPass,
		Checks:         checks,
		EventPublished: eventPublished,
		EventKey:       eventKey,
	})
}

const openAPISpec = `{
  "openapi": "3.0.3",
  "info": {
    "title": "Compatibility Service",
    "description": "Validación de compatibilidad entre componentes de PC — HardTech Hub",
    "version": "1.0.0"
  },
  "tags": [
    {"name": "health", "description": "Estado del servicio"},
    {"name": "compatibility", "description": "Reglas de compatibilidad de hardware"}
  ],
  "paths": {
    "/health": {
      "get": {
        "tags": ["health"],
        "summary": "Estado del servicio",
        "responses": {
          "200": {
            "description": "Servicio saludable",
            "content": {"application/json": {"schema": {"type": "object","properties": {"service": {"type": "string"},"status": {"type": "string"},"version": {"type": "string"}}}}}
          }
        }
      }
    },
    "/api/compatibility/check": {
      "post": {
        "tags": ["compatibility"],
        "summary": "Validar compatibilidad entre componentes",
        "description": "Aplica CPU_SOCKET (cpu+motherboard), RAM_TYPE (ram+motherboard) y PSU_POWER (psu+gpu) según los componentes enviados.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["components"],
                "properties": {
                  "user_id": {"type": "string","nullable": true},
                  "session_id": {"type": "string","nullable": true},
                  "components": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "required": ["type","product_id"],
                      "properties": {
                        "type": {"type": "string","enum": ["cpu","motherboard","ram","gpu","psu"]},
                        "product_id": {"type": "integer"}
                      }
                    }
                  }
                }
              },
              "example": {
                "user_id": "usr_demo_001",
                "session_id": "sess_demo_001",
                "components": [
                  {"type": "cpu", "product_id": 1},
                  {"type": "motherboard", "product_id": 2},
                  {"type": "ram", "product_id": 4},
                  {"type": "gpu", "product_id": 3},
                  {"type": "psu", "product_id": 5}
                ]
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Resultado de compatibilidad",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "compatible": {"type": "boolean"},
                    "event_published": {"type": "boolean"},
                    "event_key": {"type": "string","nullable": true},
                    "checks": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "rule": {"type": "string"},
                          "status": {"type": "string","enum": ["PASS","FAIL"]},
                          "details": {"type": "object","additionalProperties": true}
                        }
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {"description": "Componentes inválidos o reglas no aplicables"},
          "502": {"description": "Error al contactar Catalog Service"}
        }
      }
    }
  }
}`

func openAPIHandler(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(openAPISpec))
}

func docsHandler(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(`<!DOCTYPE html>
<html>
<head>
  <title>Compatibility Service — API Docs</title>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
  SwaggerUIBundle({
    url: "/compatibility/openapi.json",
    dom_id: '#swagger-ui',
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
    layout: "BaseLayout",
    docExpansion: "list"
  });
</script>
</body>
</html>`))
}

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/api/compatibility/check", compatibilityCheckHandler)
	mux.HandleFunc("/compatibility/openapi.json", openAPIHandler)
	mux.HandleFunc("/compatibility/docs", docsHandler)

	port := ":8004"
	log.Printf("compatibility-service listening on %s", port)
	if err := http.ListenAndServe(port, mux); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
