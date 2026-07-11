import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { Box, FormControlLabel, Switch, Typography } from "@mui/material";
import { api } from "../api/client";
import type { JobsOverlayResponse } from "../api/types";
import { useStore } from "../store/useStore";

const WIDTH = 420;
const HEIGHT = 140;
const MARGIN = { top: 10, right: 10, bottom: 20, left: 40 };

interface Props {
  sessionId: string | null;
  ready: boolean;
  times: string[]; // full session time axis
}

/** 3c: raw time series for lasso-selected nodes; brush sets the per-metric
 * baseline window, with the statistically-derived default region pre-shaded.
 */
export function ReadingInspection({ sessionId, ready, times }: Props) {
  const lassoNodeIds = useStore((s) => s.lassoNodeIds);
  const selectedMetrics = useStore((s) => s.selectedMetrics);
  const timeWindow = useStore((s) => s.timeWindow);
  const baselines = useStore((s) => s.baselines);
  const setBaseline = useStore((s) => s.setBaseline);

  const [showJobs, setShowJobs] = useState(false);
  const [jobs, setJobs] = useState<JobsOverlayResponse | null>(null);
  const [rawByMetric, setRawByMetric] = useState<Record<string, { times: string[]; series: Record<string, number[]> }>>(
    {},
  );
  const [defaultWindowByMetric, setDefaultWindowByMetric] = useState<Record<string, [number, number]>>({});
  const svgRefs = useRef<Record<string, SVGSVGElement | null>>({});

  const [t0, t1] = timeWindow ?? [0, times.length];

  useEffect(() => {
    if (!sessionId || !ready || lassoNodeIds.length === 0 || selectedMetrics.length === 0) {
      setRawByMetric({});
      return;
    }
    api.rawSeries(sessionId, lassoNodeIds, selectedMetrics, t0, t1).then((resp) => {
      const byMetric: Record<string, { times: string[]; series: Record<string, number[]> }> = {};
      selectedMetrics.forEach((metric) => {
        const series: Record<string, number[]> = {};
        lassoNodeIds.forEach((node) => {
          series[node] = resp.series[node]?.[metric] ?? [];
        });
        byMetric[metric] = { times: resp.times, series };
      });
      setRawByMetric(byMetric);
    });
  }, [sessionId, ready, lassoNodeIds, selectedMetrics, t0, t1]);

  useEffect(() => {
    if (!sessionId || !ready || lassoNodeIds.length === 0 || selectedMetrics.length === 0) return;
    selectedMetrics.forEach((metric) => {
      api.baseline(sessionId, metric, lassoNodeIds).then((resp) => {
        setDefaultWindowByMetric((prev) => ({ ...prev, [metric]: resp.window }));
      });
    });
  }, [sessionId, ready, lassoNodeIds, selectedMetrics]);

  useEffect(() => {
    if (!sessionId || !showJobs || lassoNodeIds.length === 0) {
      setJobs(null);
      return;
    }
    api.jobsOverlay(sessionId, lassoNodeIds).then(setJobs);
  }, [sessionId, showJobs, lassoNodeIds]);

  useEffect(() => {
    const color = d3.scaleOrdinal(d3.schemeSet2);
    selectedMetrics.forEach((metric) => {
      const svgEl = svgRefs.current[metric];
      const bundle = rawByMetric[metric];
      if (!svgEl || !bundle) return;
      const svg = d3.select(svgEl);
      svg.selectAll("*").remove();

      const localTimes = bundle.times.map((t) => new Date(t).getTime());
      if (localTimes.length === 0) return;
      const allValues = Object.values(bundle.series).flat();
      const x = d3.scaleLinear().domain(d3.extent(localTimes) as [number, number]).range([MARGIN.left, WIDTH - MARGIN.right]);
      const y = d3.scaleLinear().domain(d3.extent(allValues) as [number, number]).range([HEIGHT - MARGIN.bottom, MARGIN.top]);

      // pre-shade the statistically-derived default baseline window
      const defWindow = defaultWindowByMetric[metric];
      if (defWindow) {
        const [dw0, dw1] = defWindow;
        svg
          .append("rect")
          .attr("x", x(localTimes[Math.min(dw0, localTimes.length - 1)] ?? localTimes[0]))
          .attr(
            "width",
            Math.max(
              0,
              x(localTimes[Math.min(dw1, localTimes.length - 1)] ?? localTimes[localTimes.length - 1]) -
                x(localTimes[Math.min(dw0, localTimes.length - 1)] ?? localTimes[0]),
            ),
          )
          .attr("y", MARGIN.top)
          .attr("height", HEIGHT - MARGIN.top - MARGIN.bottom)
          .attr("fill", "#c8e6c9")
          .attr("opacity", 0.5);
      }

      // active user baseline (if brushed)
      const activeBaseline = baselines[metric];
      if (activeBaseline) {
        const [b0, b1] = activeBaseline;
        svg
          .append("rect")
          .attr("x", x(localTimes[Math.min(b0, localTimes.length - 1)] ?? localTimes[0]))
          .attr(
            "width",
            Math.max(
              0,
              x(localTimes[Math.min(b1, localTimes.length - 1)] ?? localTimes[localTimes.length - 1]) -
                x(localTimes[Math.min(b0, localTimes.length - 1)] ?? localTimes[0]),
            ),
          )
          .attr("y", MARGIN.top)
          .attr("height", HEIGHT - MARGIN.top - MARGIN.bottom)
          .attr("fill", "none")
          .attr("stroke", "#2e7d32")
          .attr("stroke-width", 2)
          .attr("stroke-dasharray", "4,2");
      }

      if (showJobs && jobs) {
        jobs.intervals.forEach((iv) => {
          const s = new Date(iv.start).getTime();
          const e = iv.end ? new Date(iv.end).getTime() : localTimes[localTimes.length - 1];
          svg
            .append("rect")
            .attr("x", x(s))
            .attr("width", Math.max(0, x(e) - x(s)))
            .attr("y", MARGIN.top)
            .attr("height", HEIGHT - MARGIN.top - MARGIN.bottom)
            .attr("fill", "#90caf9")
            .attr("opacity", 0.25)
            .append("title")
            .text(`${iv.job_id} (${iv.user})`);
        });
      }

      const line = d3
        .line<number>()
        .x((_d, i) => x(localTimes[i]))
        .y((d) => y(d));

      Object.entries(bundle.series).forEach(([node, series], ni) => {
        svg
          .append("path")
          .attr("d", line(series))
          .attr("fill", "none")
          .attr("stroke", color(String(ni)))
          .attr("stroke-width", 1.5)
          .append("title")
          .text(node);
      });

      svg.append("g").attr("transform", `translate(0,${HEIGHT - MARGIN.bottom})`).call(d3.axisBottom(x).ticks(4));
      svg.append("g").attr("transform", `translate(${MARGIN.left},0)`).call(d3.axisLeft(y).ticks(4));

      const brush = d3
        .brushX()
        .extent([
          [MARGIN.left, MARGIN.top],
          [WIDTH - MARGIN.right, HEIGHT - MARGIN.bottom],
        ])
        .on("end", (event) => {
          if (!event.selection) return;
          const [px0, px1] = event.selection as [number, number];
          const time0 = x.invert(px0);
          const time1 = x.invert(px1);
          const i0 = d3.bisectLeft(localTimes, time0);
          const i1 = d3.bisectRight(localTimes, time1);
          setBaseline(metric, [i0, Math.max(i0 + 1, i1)]);
        });
      svg.append("g").attr("class", "brush").call(brush);
    });
  }, [rawByMetric, selectedMetrics, defaultWindowByMetric, baselines, showJobs, jobs, setBaseline]);

  return (
    <Box>
      <Typography variant="subtitle1">3c — Reading Inspection</Typography>
      <FormControlLabel
        control={<Switch checked={showJobs} onChange={(e) => setShowJobs(e.target.checked)} size="small" />}
        label="show job overlay"
      />
      {jobs && jobs.unmapped_nodes.length > 0 && (
        <Typography variant="caption" color="warning.main">
          not mapped to any jobs: {jobs.unmapped_nodes.join(", ")}
        </Typography>
      )}
      {lassoNodeIds.length === 0 && <Typography variant="body2">lasso nodes in View 2</Typography>}
      {selectedMetrics.map((metric) => (
        <Box key={metric}>
          <Typography variant="caption">{metric}</Typography>
          <svg
            ref={(el) => {
              svgRefs.current[metric] = el;
            }}
            width={WIDTH}
            height={HEIGHT}
            data-testid={`reading-inspection-svg-${metric}`}
          />
        </Box>
      ))}
    </Box>
  );
}
