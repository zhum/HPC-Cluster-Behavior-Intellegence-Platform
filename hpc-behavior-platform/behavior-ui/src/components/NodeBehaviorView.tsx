import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { Box, Select, MenuItem, Stack, Typography } from "@mui/material";
import { api } from "../api/client";
import type { Band } from "../api/types";
import { useStore } from "../store/useStore";

const CELL = 28;
const MARGIN = { top: 20, right: 10, bottom: 10, left: 140 };

interface Props {
  sessionId: string | null;
  ready: boolean;
  nodes: string[];
  clusterLabels: number[] | null; // aligned to `nodes`
}

const BANDS: Band[] = ["5m", "30m", "2h", "24h", "7d"];

/** View 4: heatmap of mrDMD z-scores, rows=selected metrics,
 * columns=lasso-selected nodes. Recomputes on band or baseline change.
 */
export function NodeBehaviorView({ sessionId, ready, nodes, clusterLabels }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const lassoNodeIds = useStore((s) => s.lassoNodeIds);
  const selectedMetrics = useStore((s) => s.selectedMetrics);
  const band = useStore((s) => s.band);
  const setBand = useStore((s) => s.setBand);
  const baselines = useStore((s) => s.baselines);
  const setHoveredCell = useStore((s) => s.setHoveredCell);

  const [z, setZ] = useState<number[][] | null>(null); // [node][metric]
  const color = d3.scaleOrdinal(d3.schemeCategory10);

  const nodeToCluster = new Map(nodes.map((n, i) => [n, clusterLabels?.[i]]));

  useEffect(() => {
    if (!sessionId || !ready || lassoNodeIds.length === 0 || selectedMetrics.length === 0) {
      setZ(null);
      return;
    }
    const baselineArg = Object.keys(baselines).length > 0 ? baselines : undefined;
    api.zscores(sessionId, lassoNodeIds, selectedMetrics, band, baselineArg).then((resp) => {
      setZ(resp.z);
    });
  }, [sessionId, ready, lassoNodeIds, selectedMetrics, band, baselines]);

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    if (!z || lassoNodeIds.length === 0 || selectedMetrics.length === 0) return;

    const width = MARGIN.left + MARGIN.right + lassoNodeIds.length * CELL;
    const height = MARGIN.top + MARGIN.bottom + selectedMetrics.length * CELL;
    svg.attr("width", width).attr("height", height);

    const colorScale = d3.scaleDiverging(d3.interpolateRdBu).domain([5, 0, -5]);

    selectedMetrics.forEach((metric, m_i) => {
      svg
        .append("text")
        .attr("x", MARGIN.left - 6)
        .attr("y", MARGIN.top + m_i * CELL + CELL / 2 + 4)
        .attr("text-anchor", "end")
        .attr("font-size", 11)
        .text(metric);

      lassoNodeIds.forEach((node, n_i) => {
        const value = z[n_i]?.[m_i] ?? 0;
        svg
          .append("rect")
          .attr("x", MARGIN.left + n_i * CELL)
          .attr("y", MARGIN.top + m_i * CELL)
          .attr("width", CELL - 1)
          .attr("height", CELL - 1)
          .attr("fill", colorScale(value))
          .attr("data-testid", `heatmap-cell-${metric}-${node}`)
          .on("mouseenter", () => setHoveredCell({ metric, nodeId: node }))
          .on("mouseleave", () => setHoveredCell(null))
          .append("title")
          .text(`${node} / ${metric}: z=${value.toFixed(2)}`);
      });
    });

    lassoNodeIds.forEach((node, n_i) => {
      svg
        .append("text")
        .attr("x", MARGIN.left + n_i * CELL + CELL / 2)
        .attr("y", MARGIN.top - 6)
        .attr("text-anchor", "middle")
        .attr("font-size", 9)
        .attr("fill", () => {
          const cluster = nodeToCluster.get(node);
          return cluster !== undefined ? color(String(cluster)) : "#333";
        })
        .text(node.slice(-4));
    });
  }, [z, lassoNodeIds, selectedMetrics, nodeToCluster, setHoveredCell]);

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={2}>
        <Typography variant="h6">View 4 — Node Behavior</Typography>
        <Select size="small" value={band} onChange={(e) => setBand(e.target.value as Band)} data-testid="band-select">
          {BANDS.map((b) => (
            <MenuItem key={b} value={b}>
              {b}
            </MenuItem>
          ))}
        </Select>
      </Stack>
      {(lassoNodeIds.length === 0 || selectedMetrics.length === 0) && (
        <Typography variant="body2">lasso nodes + select metrics to see z-scores</Typography>
      )}
      <svg ref={svgRef} data-testid="node-behavior-svg" />
    </Box>
  );
}
