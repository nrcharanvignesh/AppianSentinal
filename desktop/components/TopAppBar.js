'use client';

import { useRef } from 'react';
import DarkModeOutlinedIcon from '@mui/icons-material/DarkModeOutlined';
import LightModeOutlinedIcon from '@mui/icons-material/LightModeOutlined';
import { IconButton, Tooltip } from '@mui/material';
import { useAppTheme } from './AppThemeProvider';

export default function TopAppBar({ appName, connected, status, onUpload }) {
  const fileRef = useRef(null);
  const { mode, toggleMode } = useAppTheme();

  return (
    <header className="topbar">
      <div className="brand" aria-label="Appian Sentinel">
        <span className="brand-mark" aria-hidden="true">
          <img src="/icon.png" alt="" />
        </span>
        <span>Appian Sentinel</span>
        <span className="workspace-name">{appName || 'No application loaded'}</span>
      </div>
      <div className="topbar-actions">
        <span className={`connection ${connected ? 'is-online' : ''}`}>
          <span className="connection-dot" aria-hidden="true" />
          {connected ? 'Sidecar online' : 'Sidecar offline'}
        </span>
        <span className="status-pill">{String(status || 'idle').replaceAll('_', ' ')}</span>
        <Tooltip title={`Use ${mode === 'dark' ? 'light' : 'dark'} mode`}>
          <IconButton
            className="theme-toggle"
            aria-label={`Use ${mode === 'dark' ? 'light' : 'dark'} mode`}
            onClick={toggleMode}
            size="small"
          >
            {mode === 'dark' ? <LightModeOutlinedIcon /> : <DarkModeOutlinedIcon />}
          </IconButton>
        </Tooltip>
        <button className="primary-button" type="button" onClick={() => fileRef.current?.click()}>
          Import application
        </button>
        <input
          ref={fileRef}
          hidden
          type="file"
          accept=".zip"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onUpload(file);
            event.target.value = '';
          }}
        />
      </div>
    </header>
  );
}
