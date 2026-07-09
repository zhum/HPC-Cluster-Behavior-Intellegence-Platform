#!/bin/bash

# Start services using Docker Compose
docker-compose up -d

# Wait for ClickHouse to start
sleep 30

# Create ClickHouse tables
docker exec -it storage_server clickhouse-client --query="
CREATE TABLE observability_agent.metrics_raw
(
node_id String,
timestamp DateTime,
metric_name String,
metric_value Float64
) ENGINE = MergeTree()
ORDER BY (node_id, timestamp);
"

# Create Grafana data source
docker-compose exec grafana bash -c "curl -u admin:admin -X POST http://localhost:3000/api/datasources \
-H 'Content-Type: application/json' \
-d '{
\"name\": \"ClickHouse\",
\"type\": \"clickhouse\",
\"url\": \"http://storage_server:9000\",
\"access\": \"proxy\",
\"isDefault\": true,
\"jsonData\": {
  \"defaultDatabase\": \"observability_agent\"
},
\"secureJsonData\": {}
}'"

# Create a dashboard
docker-compose exec grafana bash -c "curl -u admin:admin -X POST http://localhost:3000/api/dashboards/db \
-H 'Content-Type: application/json' \
-d '{
\"dashboard\": {
  \"title\": \"HPC Cluster Telemetry Dashboard\",
  \"id\": null,
  \"panels\": [
    {
      \"id\": 1,
      \"title\": \"Metrics\",
      \"type\": \"timeseries\",
      \"datasource\": \"ClickHouse\",
      \"targets\": [
        {
          \"expr\": \"SELECT node_id, timestamp, metric_name, metric_value FROM metrics_raw WHERE timestamp > now() - 10\",
          \"refId\": \"A\"
        }
      ]
    }
  ]
}
}'"

