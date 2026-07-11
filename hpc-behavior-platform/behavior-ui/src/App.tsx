import { useState } from "react";
import { Box, Button, Grid, Stack, TextField, Typography } from "@mui/material";
import { api } from "./api/client";
import { useClusters, useEmbedding, useExplain, useSessionStatus, useTimeDomain } from "./hooks/useSessionData";
import { useStore } from "./store/useStore";
import { TimeDomainView } from "./components/TimeDomainView";
import { NodeSimilarityView } from "./components/NodeSimilarityView";
import { MetricSelectionPanel } from "./components/MetricSelectionPanel";
import { ClusterReadingSummary } from "./components/ClusterReadingSummary";
import { ReadingInspection } from "./components/ReadingInspection";
import { NodeBehaviorView } from "./components/NodeBehaviorView";
import { SavedAnalysesPanel } from "./components/SavedAnalysesPanel";

function isoNoMs(d: Date) {
  return d.toISOString().replace(/\.\d+Z$/, "");
}

function SessionCreator() {
  const setSession = useStore((s) => s.setSession);
  const now = new Date();
  const tenMinAgo = new Date(now.getTime() - 30 * 1000);
  const [start, setStart] = useState(isoNoMs(tenMinAgo));
  const [end, setEnd] = useState(isoNoMs(now));
  const [resolution, setResolution] = useState(1);
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    setCreating(true);
    try {
      const resp = await api.createSession({ start, end, resolution_s: resolution });
      setSession(resp.session_id);
    } finally {
      setCreating(false);
    }
  };

  return (
    <Stack direction="row" spacing={2} alignItems="center" sx={{ p: 2 }}>
      <Typography variant="h5">HPC Cluster Behavior Intelligence</Typography>
      <TextField
        size="small"
        label="start"
        value={start}
        onChange={(e) => setStart(e.target.value)}
        data-testid="start-input"
      />
      <TextField size="small" label="end" value={end} onChange={(e) => setEnd(e.target.value)} data-testid="end-input" />
      <TextField
        size="small"
        label="resolution_s"
        type="number"
        value={resolution}
        onChange={(e) => setResolution(Number(e.target.value))}
      />
      <Button variant="contained" onClick={handleCreate} disabled={creating} data-testid="create-session-btn">
        Create Session
      </Button>
    </Stack>
  );
}

function Dashboard({ sessionId }: { sessionId: string }) {
  const status = useSessionStatus(sessionId);
  const ready = status?.status === "ready";
  const nodes = status?.nodes ?? [];
  const metrics = status?.metrics ?? [];
  const times = status?.times ?? [];

  const { embedding, loading: embeddingLoading } = useEmbedding(sessionId, ready);
  const { clusters } = useClusters(sessionId, ready);
  const explain = useExplain(sessionId, ready);
  const timedomain = useTimeDomain(sessionId, ready);

  if (status?.status === "pending") return <Typography sx={{ p: 2 }}>materializing tensor…</Typography>;
  if (status?.status === "error") return <Typography sx={{ p: 2 }} color="error">error: {status.error}</Typography>;
  if (!ready) return null;

  return (
    <Grid container spacing={2} sx={{ p: 2 }}>
      <Grid item xs={12}>
        <TimeDomainView timedomain={timedomain} times={times} />
      </Grid>
      <Grid item xs={6}>
        <NodeSimilarityView nodes={nodes} embedding={embedding} clusters={clusters} loading={embeddingLoading} />
      </Grid>
      <Grid item xs={3}>
        <MetricSelectionPanel metrics={metrics} explain={explain} />
      </Grid>
      <Grid item xs={3}>
        <ClusterReadingSummary sessionId={sessionId} ready={ready} />
      </Grid>
      <Grid item xs={6}>
        <ReadingInspection sessionId={sessionId} ready={ready} times={times} />
      </Grid>
      <Grid item xs={6}>
        <NodeBehaviorView sessionId={sessionId} ready={ready} nodes={nodes} clusterLabels={clusters?.labels ?? null} />
      </Grid>
      <Grid item xs={3}>
        <SavedAnalysesPanel />
      </Grid>
    </Grid>
  );
}

function App() {
  const session = useStore((s) => s.session);

  return (
    <Box>
      <SessionCreator />
      {session && <Dashboard sessionId={session} />}
    </Box>
  );
}

export default App;
