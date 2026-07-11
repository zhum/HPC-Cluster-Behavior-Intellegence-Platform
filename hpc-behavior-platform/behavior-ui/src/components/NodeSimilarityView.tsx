import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { Box, Button, Stack, TextField, Typography } from "@mui/material";
import type { ClustersResponse, EmbeddingResponse } from "../api/types";
import { DEFAULT_UMAP_PARAMS, useStore } from "../store/useStore";

const WIDTH = 480;
const HEIGHT = 420;
const MARGIN = 24;

interface Props {
  nodes: string[];
  embedding: EmbeddingResponse | null;
  clusters: ClustersResponse | null;
  loading: boolean;
}

export function NodeSimilarityView({ nodes, embedding, clusters, loading }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const umapParams = useStore((s) => s.umapParams);
  const k = useStore((s) => s.k);
  const setUmapParams = useStore((s) => s.setUmapParams);
  const setK = useStore((s) => s.setK);
  const resetUmapDefaults = useStore((s) => s.resetUmapDefaults);
  const setLassoNodeIds = useStore((s) => s.setLassoNodeIds);
  const lassoNodeIds = useStore((s) => s.lassoNodeIds);

  const [pendingNeighbors, setPendingNeighbors] = useState(umapParams.n_neighbors);
  const [pendingMinDist, setPendingMinDist] = useState(umapParams.min_dist);

  const color = d3.scaleOrdinal(d3.schemeCategory10);

  useEffect(() => {
    if (!svgRef.current || !embedding) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const xExtent = d3.extent(embedding.E, (d) => d[0]) as [number, number];
    const yExtent = d3.extent(embedding.E, (d) => d[1]) as [number, number];
    const x = d3.scaleLinear().domain(xExtent).range([MARGIN, WIDTH - MARGIN]);
    const y = d3.scaleLinear().domain(yExtent).range([HEIGHT - MARGIN, MARGIN]);

    const lassoSet = new Set(lassoNodeIds);

    const points = svg
      .selectAll<SVGCircleElement, [number, number]>("circle.node-point")
      .data(embedding.E)
      .join("circle")
      .attr("class", "node-point")
      .attr("data-node-id", (_d, i) => nodes[i] ?? "")
      .attr("cx", (d) => x(d[0]))
      .attr("cy", (d) => y(d[1]))
      .attr("r", 5)
      .attr("fill", (_d, i) => {
        const cluster = clusters?.labels[i];
        const isInactive = embedding.inactive_flags[i];
        return isInactive ? "none" : cluster !== undefined ? color(String(cluster)) : "#999";
      })
      .attr("stroke", (_d, i) => {
        const cluster = clusters?.labels[i];
        return cluster !== undefined ? color(String(cluster)) : "#999";
      })
      .attr("stroke-width", 1.5)
      .attr("opacity", (_d, i) => (lassoSet.size === 0 || lassoSet.has(nodes[i]) ? 1 : 0.25));

    // freeform lasso: drag to trace a polygon, release to select enclosed points
    let path: [number, number][] = [];
    const lassoPath = svg
      .append("path")
      .attr("class", "lasso-path")
      .attr("fill", "rgba(25,118,210,0.08)")
      .attr("stroke", "#1976d2")
      .attr("stroke-dasharray", "4,2");

    const drag = d3
      .drag<SVGSVGElement, unknown>()
      .on("start", () => {
        path = [];
      })
      .on("drag", (event) => {
        path.push([event.x, event.y]);
        lassoPath.attr("d", d3.line()(path));
      })
      .on("end", () => {
        if (path.length < 3) {
          lassoPath.attr("d", null);
          return;
        }
        const selected: string[] = [];
        embedding.E.forEach((d, i) => {
          const px = x(d[0]);
          const py = y(d[1]);
          if (d3.polygonContains(path, [px, py])) {
            selected.push(nodes[i]);
          }
        });
        setLassoNodeIds(selected);
        lassoPath.attr("d", null);
      });

    svg.call(drag as unknown as (selection: d3.Selection<SVGSVGElement, unknown, null, undefined>) => void);
    points.raise();
  }, [embedding, clusters, nodes, lassoNodeIds]);

  const handleRecompute = () => {
    setUmapParams({ ...umapParams, n_neighbors: pendingNeighbors, min_dist: pendingMinDist });
  };

  const handleResetDefaults = () => {
    setPendingNeighbors(DEFAULT_UMAP_PARAMS.n_neighbors);
    setPendingMinDist(DEFAULT_UMAP_PARAMS.min_dist);
    resetUmapDefaults();
  };

  return (
    <Box>
      <Typography variant="h6">View 2 — Node Similarity</Typography>
      <Stack direction="row" spacing={2}>
        <svg
          ref={svgRef}
          width={WIDTH}
          height={HEIGHT}
          data-testid="node-similarity-svg"
          style={{ border: "1px solid #ddd", touchAction: "none" }}
        />
        <Stack spacing={1} width={200}>
          {loading && <Typography variant="body2">recomputing embedding…</Typography>}
          <TextField
            label="n_neighbors"
            type="number"
            size="small"
            value={pendingNeighbors}
            onChange={(e) => setPendingNeighbors(Number(e.target.value))}
            inputProps={{ "data-testid": "n-neighbors-input" }}
          />
          <TextField
            label="min_dist"
            type="number"
            size="small"
            inputProps={{ step: 0.05, "data-testid": "min-dist-input" }}
            value={pendingMinDist}
            onChange={(e) => setPendingMinDist(Number(e.target.value))}
          />
          <TextField
            label="k (clusters)"
            type="number"
            size="small"
            inputProps={{ min: 2, max: 12, "data-testid": "k-input" }}
            value={k}
            onChange={(e) => setK(Number(e.target.value))}
          />
          <Button variant="contained" size="small" onClick={handleRecompute} data-testid="recompute-btn">
            Recompute
          </Button>
          <Button variant="outlined" size="small" onClick={handleResetDefaults}>
            Reset Defaults
          </Button>
          {clusters && (
            <Typography variant="caption">
              silhouette: {clusters.quality_metrics.silhouette?.toFixed(3)}
            </Typography>
          )}
        </Stack>
      </Stack>
    </Box>
  );
}
