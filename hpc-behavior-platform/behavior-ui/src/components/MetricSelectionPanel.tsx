import { useMemo, useState } from "react";
import * as d3 from "d3";
import { Box, Checkbox, List, ListItem, ListItemButton, TextField, Typography } from "@mui/material";
import type { ExplainResponse } from "../api/types";
import { useStore } from "../store/useStore";

const BAR_WIDTH = 120;
const BAR_HEIGHT = 14;

interface Props {
  metrics: string[];
  explain: ExplainResponse | null;
}

/** 3a: searchable metric list, each row a horizontal diverging bar chart of
 * ccPCA contribution per cluster -- length=|weight|, direction: left=higher
 * (positive weight, by this project's ccPCA sign convention), right=lower.
 * Metrics ranked by max |contribution| across clusters.
 */
export function MetricSelectionPanel({ metrics, explain }: Props) {
  const [search, setSearch] = useState("");
  const selectedMetrics = useStore((s) => s.selectedMetrics);
  const setSelectedMetrics = useStore((s) => s.setSelectedMetrics);
  const color = d3.scaleOrdinal(d3.schemeCategory10);

  const weightByMetric = useMemo(() => {
    const map = new Map<string, number[]>(); // metric -> weight per cluster (in explain.results order)
    if (!explain) return map;
    metrics.forEach((metric, m_i) => {
      map.set(
        metric,
        explain.results.map((r) => r.weights[m_i] ?? 0),
      );
    });
    return map;
  }, [metrics, explain]);

  const rankedMetrics = useMemo(() => {
    const withScore = metrics.map((m) => {
      const weights = weightByMetric.get(m) ?? [];
      const maxAbs = weights.length ? Math.max(...weights.map(Math.abs)) : 0;
      return { metric: m, maxAbs };
    });
    withScore.sort((a, b) => b.maxAbs - a.maxAbs);
    return withScore
      .filter((w) => w.metric.toLowerCase().includes(search.toLowerCase()))
      .map((w) => w.metric);
  }, [metrics, weightByMetric, search]);

  const maxWeight = useMemo(() => {
    let m = 0.001;
    weightByMetric.forEach((weights) => weights.forEach((w) => (m = Math.max(m, Math.abs(w)))));
    return m;
  }, [weightByMetric]);

  const scale = d3.scaleLinear().domain([0, maxWeight]).range([0, BAR_WIDTH / 2]);

  const toggleMetric = (metric: string) => {
    setSelectedMetrics(
      selectedMetrics.includes(metric)
        ? selectedMetrics.filter((m) => m !== metric)
        : [...selectedMetrics, metric],
    );
  };

  return (
    <Box>
      <Typography variant="subtitle1">3a — Metric Selection</Typography>
      <TextField
        size="small"
        placeholder="filter metrics…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        fullWidth
        data-testid="metric-search"
      />
      <List dense sx={{ maxHeight: 320, overflow: "auto" }}>
        {rankedMetrics.map((metric) => {
          const weights = weightByMetric.get(metric) ?? [];
          return (
            <ListItem key={metric} disablePadding data-testid={`metric-row-${metric}`}>
              <ListItemButton onClick={() => toggleMetric(metric)}>
                <Checkbox edge="start" checked={selectedMetrics.includes(metric)} tabIndex={-1} size="small" />
                <Typography variant="body2" sx={{ width: 140, fontSize: 12 }}>
                  {metric}
                </Typography>
                <svg width={BAR_WIDTH} height={BAR_HEIGHT * weights.length || BAR_HEIGHT}>
                  <line
                    x1={BAR_WIDTH / 2}
                    x2={BAR_WIDTH / 2}
                    y1={0}
                    y2={BAR_HEIGHT * weights.length}
                    stroke="#ccc"
                  />
                  {weights.map((w, ci) => {
                    const barLen = scale(Math.abs(w));
                    const isHigher = w > 0; // positive weight => higher in this cluster => bar goes left
                    return (
                      <rect
                        key={ci}
                        x={isHigher ? BAR_WIDTH / 2 - barLen : BAR_WIDTH / 2}
                        y={ci * BAR_HEIGHT}
                        width={barLen}
                        height={BAR_HEIGHT - 2}
                        fill={color(String(ci))}
                      />
                    );
                  })}
                </svg>
              </ListItemButton>
            </ListItem>
          );
        })}
      </List>
    </Box>
  );
}
