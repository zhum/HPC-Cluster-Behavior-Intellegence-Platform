import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { Box, Slider, Stack, Typography } from "@mui/material";
import { api } from "../api/client";
import { useStore } from "../store/useStore";

const WIDTH = 420;
const HEIGHT = 160;
const MARGIN = { top: 10, right: 10, bottom: 20, left: 40 };

/** 3b: per-cluster average polylines over time for selected metrics, with a
 * smoothing-window control.
 */
export function ClusterReadingSummary({ sessionId, ready }: { sessionId: string | null; ready: boolean }) {
  const selectedMetrics = useStore((s) => s.selectedMetrics);
  const umapParams = useStore((s) => s.umapParams);
  const k = useStore((s) => s.k);
  const [smoothingW, setSmoothingW] = useState(1);
  const [data, setData] = useState<{ times: string[]; polylines: Record<string, Record<string, number[]>> } | null>(
    null,
  );
  const svgRefs = useRef<Record<string, SVGSVGElement | null>>({});
  const color = d3.scaleOrdinal(d3.schemeCategory10);

  useEffect(() => {
    if (!sessionId || !ready || selectedMetrics.length === 0) {
      setData(null);
      return;
    }
    api.clusterMeans(sessionId, k, umapParams, selectedMetrics, smoothingW).then(setData);
  }, [sessionId, ready, k, umapParams, selectedMetrics, smoothingW]);

  useEffect(() => {
    if (!data) return;
    const clusterIds = Object.keys(data.polylines).sort((a, b) => Number(a) - Number(b));
    const times = data.times.map((t) => new Date(t).getTime());

    selectedMetrics.forEach((metric) => {
      const svgEl = svgRefs.current[metric];
      if (!svgEl) return;
      const svg = d3.select(svgEl);
      svg.selectAll("*").remove();

      const allValues = clusterIds.flatMap((cid) => data.polylines[cid][metric] ?? []);
      const x = d3.scaleLinear().domain(d3.extent(times) as [number, number]).range([MARGIN.left, WIDTH - MARGIN.right]);
      const y = d3
        .scaleLinear()
        .domain(d3.extent(allValues) as [number, number])
        .range([HEIGHT - MARGIN.bottom, MARGIN.top]);

      const line = d3
        .line<number>()
        .x((_d, i) => x(times[i]))
        .y((d) => y(d));

      clusterIds.forEach((cid) => {
        const series = data.polylines[cid][metric];
        if (!series) return;
        svg
          .append("path")
          .attr("d", line(series))
          .attr("fill", "none")
          .attr("stroke", color(cid))
          .attr("stroke-width", 2);
      });

      svg.append("g").attr("transform", `translate(0,${HEIGHT - MARGIN.bottom})`).call(d3.axisBottom(x).ticks(4));
      svg.append("g").attr("transform", `translate(${MARGIN.left},0)`).call(d3.axisLeft(y).ticks(4));
    });
  }, [data, selectedMetrics]);

  return (
    <Box>
      <Typography variant="subtitle1">3b — Cluster Reading Summary</Typography>
      <Stack direction="row" alignItems="center" spacing={2} sx={{ maxWidth: 300 }}>
        <Typography variant="caption">smoothing window</Typography>
        <Slider
          size="small"
          min={1}
          max={15}
          value={smoothingW}
          onChange={(_e, v) => setSmoothingW(v as number)}
          data-testid="smoothing-slider"
        />
      </Stack>
      {selectedMetrics.length === 0 && <Typography variant="body2">select metrics in 3a</Typography>}
      {selectedMetrics.map((metric) => (
        <Box key={metric}>
          <Typography variant="caption">{metric}</Typography>
          <svg
            ref={(el) => {
              svgRefs.current[metric] = el;
            }}
            width={WIDTH}
            height={HEIGHT}
            data-testid={`cluster-means-svg-${metric}`}
          />
        </Box>
      ))}
    </Box>
  );
}
