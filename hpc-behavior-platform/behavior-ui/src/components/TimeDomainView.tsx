import { useEffect, useMemo, useRef } from "react";
import * as d3 from "d3";
import { Box, Typography } from "@mui/material";
import type { TimeDomainResponse } from "../api/types";
import { useStore } from "../store/useStore";

const WIDTH = 700;
const ROW_HEIGHT = 28;
const MARGIN = { top: 10, right: 20, bottom: 24, left: 80 };

interface Props {
  timedomain: TimeDomainResponse | null;
  times: string[];
}

export function TimeDomainView({ timedomain, times }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const setTimeWindow = useStore((s) => s.setTimeWindow);

  const timeIndex = useMemo(() => {
    const parsed = times.map((t) => new Date(t).getTime());
    return parsed;
  }, [times]);

  const clusterIds = useMemo(
    () => (timedomain ? Object.keys(timedomain.clusters).sort((a, b) => Number(a) - Number(b)) : []),
    [timedomain],
  );

  // planned downtime: timestamps where every cluster has at least one node
  // null simultaneously (all-cluster-null) vs an isolated per-cluster event.
  const plannedBands = useMemo(() => {
    if (!timedomain || clusterIds.length === 0 || timeIndex.length === 0) return [];
    const nullAt = clusterIds.map(() => new Array(timeIndex.length).fill(false));
    clusterIds.forEach((cid, ci) => {
      for (const seg of timedomain.clusters[cid]) {
        const s = new Date(seg.seg_start).getTime();
        const e = new Date(seg.seg_end).getTime();
        for (let i = 0; i < timeIndex.length; i++) {
          if (timeIndex[i] >= s && timeIndex[i] < e) nullAt[ci][i] = true;
        }
      }
    });
    const allNull = timeIndex.map((_, i) => nullAt.every((row) => row[i]));
    const bands: [number, number][] = [];
    let start = -1;
    allNull.forEach((v, i) => {
      if (v && start === -1) start = i;
      if (!v && start !== -1) {
        bands.push([start, i]);
        start = -1;
      }
    });
    if (start !== -1) bands.push([start, allNull.length]);
    return bands;
  }, [timedomain, clusterIds, timeIndex]);

  useEffect(() => {
    if (!svgRef.current || !timedomain || timeIndex.length === 0) return;
    const height = MARGIN.top + MARGIN.bottom + clusterIds.length * ROW_HEIGHT;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    svg.attr("height", height);

    const x = d3
      .scaleLinear()
      .domain([timeIndex[0], timeIndex[timeIndex.length - 1]])
      .range([MARGIN.left, WIDTH - MARGIN.right]);

    // planned-downtime bands (shaded across all rows)
    svg
      .selectAll("rect.planned")
      .data(plannedBands)
      .join("rect")
      .attr("class", "planned")
      .attr("x", (d) => x(timeIndex[d[0]]))
      .attr("width", (d) => Math.max(1, x(timeIndex[d[1] - 1] ?? timeIndex[d[0]]) - x(timeIndex[d[0]])))
      .attr("y", MARGIN.top)
      .attr("height", clusterIds.length * ROW_HEIGHT)
      .attr("fill", "#ffe0b2")
      .attr("opacity", 0.6);

    clusterIds.forEach((cid, ci) => {
      const rowY = MARGIN.top + ci * ROW_HEIGHT;
      svg
        .append("text")
        .attr("x", 4)
        .attr("y", rowY + ROW_HEIGHT / 2 + 4)
        .attr("font-size", 12)
        .text(`cluster ${cid}`);

      svg
        .selectAll(`rect.seg-${cid}`)
        .data(timedomain.clusters[cid])
        .join("rect")
        .attr("class", `seg-${cid}`)
        .attr("x", (d) => x(new Date(d.seg_start).getTime()))
        .attr(
          "width",
          (d) => Math.max(1, x(new Date(d.seg_end).getTime()) - x(new Date(d.seg_start).getTime())),
        )
        .attr("y", rowY + 4)
        .attr("height", ROW_HEIGHT - 8)
        .attr("fill", "#d32f2f")
        .append("title")
        .text((d) => `${d.node_id}: ${d.seg_start} - ${d.seg_end}`);
    });

    const brush = d3
      .brushX()
      .extent([
        [MARGIN.left, MARGIN.top],
        [WIDTH - MARGIN.right, MARGIN.top + clusterIds.length * ROW_HEIGHT],
      ])
      .on("end", (event) => {
        if (!event.selection) {
          setTimeWindow(null);
          return;
        }
        const [x0, x1] = event.selection as [number, number];
        const t0 = x.invert(x0);
        const t1 = x.invert(x1);
        const i0 = d3.bisectLeft(timeIndex, t0);
        const i1 = d3.bisectRight(timeIndex, t1);
        setTimeWindow([i0, Math.max(i0 + 1, i1)]);
      });

    svg.append("g").attr("class", "brush").call(brush);
  }, [timedomain, clusterIds, timeIndex, plannedBands, setTimeWindow]);

  return (
    <Box>
      <Typography variant="h6">View 1 — Time Domain</Typography>
      {!timedomain && <Typography variant="body2">loading…</Typography>}
      <svg ref={svgRef} width={WIDTH} data-testid="time-domain-svg" style={{ border: "1px solid #ddd" }} />
    </Box>
  );
}
