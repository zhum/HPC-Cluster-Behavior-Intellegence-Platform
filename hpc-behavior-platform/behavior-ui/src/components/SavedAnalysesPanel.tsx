import { useEffect, useState } from "react";
import {
  Box,
  Button,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Stack,
  TextField,
  Typography,
  IconButton,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import { api } from "../api/client";
import type { SavedAnalysisSummary } from "../api/types";
import { extractSavedState, useStore } from "../store/useStore";

/** Phase 8 item 3: multi-user sessions / saved analyses. userId is a plain
 * free-text identifier -- no auth system is specified for this project;
 * ownership is enforced server-side by matching this string.
 */
export function SavedAnalysesPanel() {
  const userId = useStore((s) => s.userId);
  const setUserId = useStore((s) => s.setUserId);
  const currentAnalysisId = useStore((s) => s.currentAnalysisId);
  const currentAnalysisName = useStore((s) => s.currentAnalysisName);
  const setCurrentAnalysis = useStore((s) => s.setCurrentAnalysis);
  const applySavedState = useStore((s) => s.applySavedState);
  const fullState = useStore((s) => s);

  const [nameInput, setNameInput] = useState("");
  const [analyses, setAnalyses] = useState<SavedAnalysisSummary[]>([]);
  const [status, setStatus] = useState<string | null>(null);

  const refresh = async () => {
    if (!userId) {
      setAnalyses([]);
      return;
    }
    const resp = await api.listAnalyses(userId);
    setAnalyses(resp.analyses);
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  const handleSave = async () => {
    if (!userId || !nameInput) return;
    const saved = await api.saveAnalysis(
      userId,
      nameInput,
      extractSavedState(fullState) as unknown as Record<string, unknown>,
      currentAnalysisId,
    );
    setCurrentAnalysis(saved.id, saved.name);
    setStatus(`saved "${saved.name}"`);
    await refresh();
  };

  const handleLoad = async (analysisId: string) => {
    const detail = await api.getAnalysis(analysisId, userId);
    applySavedState(detail.state as never);
    setCurrentAnalysis(detail.id, detail.name);
    setNameInput(detail.name);
    setStatus(`loaded "${detail.name}"`);
  };

  const handleDelete = async (analysisId: string) => {
    await api.deleteAnalysis(analysisId, userId);
    if (currentAnalysisId === analysisId) {
      setCurrentAnalysis(null, "");
    }
    await refresh();
  };

  return (
    <Box>
      <Typography variant="subtitle1">Saved Analyses</Typography>
      <Stack spacing={1} sx={{ maxWidth: 320 }}>
        <TextField
          size="small"
          label="user id"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          inputProps={{ "data-testid": "user-id-input" }}
        />
        <Stack direction="row" spacing={1}>
          <TextField
            size="small"
            label="analysis name"
            value={nameInput}
            onChange={(e) => setNameInput(e.target.value)}
            inputProps={{ "data-testid": "analysis-name-input" }}
            fullWidth
          />
          <Button variant="contained" size="small" onClick={handleSave} data-testid="save-analysis-btn">
            Save
          </Button>
        </Stack>
        {currentAnalysisId && (
          <Typography variant="caption">
            editing: {currentAnalysisName} ({currentAnalysisId.slice(0, 8)})
          </Typography>
        )}
        {status && <Typography variant="caption">{status}</Typography>}
        <List dense data-testid="saved-analyses-list">
          {analyses.map((a) => (
            <ListItem
              key={a.id}
              disablePadding
              secondaryAction={
                <IconButton edge="end" size="small" onClick={() => handleDelete(a.id)} data-testid={`delete-${a.id}`}>
                  <DeleteIcon fontSize="small" />
                </IconButton>
              }
            >
              <ListItemButton onClick={() => handleLoad(a.id)} data-testid={`load-${a.id}`}>
                <ListItemText primary={a.name} secondary={a.updated_at} />
              </ListItemButton>
            </ListItem>
          ))}
        </List>
      </Stack>
    </Box>
  );
}
