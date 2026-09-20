'use client';

import { useRef } from 'react';
import AppsOutlinedIcon from '@mui/icons-material/AppsOutlined';
import DataObjectOutlinedIcon from '@mui/icons-material/DataObjectOutlined';
import DarkModeOutlinedIcon from '@mui/icons-material/DarkModeOutlined';
import LightModeOutlinedIcon from '@mui/icons-material/LightModeOutlined';
import MenuOutlinedIcon from '@mui/icons-material/MenuOutlined';
import PersonOutlineOutlinedIcon from '@mui/icons-material/PersonOutlineOutlined';
import SearchOutlinedIcon from '@mui/icons-material/SearchOutlined';
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined';
import { IconButton, Tooltip } from '@mui/material';
import { useAppTheme } from './AppThemeProvider';

export default function TopAppBar({
  appName,
  connected,
  status,
  onUpload,
  onOpenObjectOperations,
  onOpenSettings,
}) {
  const fileRef = useRef(null);
  const { mode, toggleMode } = useAppTheme();

  return (
    <header className="topbar">
      <div className="brand" aria-label="Appian Sentinel">
        <span className="brand-mark" aria-hidden="true">
          <AppsOutlinedIcon />
        </span>
        <span className="brand-product">Appian Sentinel</span>
        <span className="workspace-name">
          {appName || 'No application loaded'}
        </span>
      </div>
      <div className="topbar-actions">
        <span className={`connection ${connected ? 'is-online' : ''}`}>
          <span className="connection-dot" aria-hidden="true" />
          {connected ? 'Connected' : 'Connection unavailable'}
        </span>
        <span className="status-pill">{String(status || 'idle').replaceAll('_', ' ')}</span>
        <Tooltip title="Quick search (Ctrl+K)">
          <IconButton
            className="topbar-icon-button"
            aria-label="Quick search"
            onClick={() => document.getElementById('object-search')?.focus()}
            size="small"
          >
            <SearchOutlinedIcon />
          </IconButton>
        </Tooltip>
        <Tooltip title={`Use ${mode === 'dark' ? 'light' : 'dark'} mode`}>
          <IconButton
            className="topbar-icon-button theme-toggle"
            aria-label={`Use ${mode === 'dark' ? 'light' : 'dark'} mode`}
            onClick={toggleMode}
            size="small"
          >
            {mode === 'dark' ? <LightModeOutlinedIcon /> : <DarkModeOutlinedIcon />}
          </IconButton>
        </Tooltip>
        <Tooltip title="Settings">
          <IconButton
            className="topbar-icon-button"
            aria-label="Settings"
            onClick={onOpenSettings}
            size="small"
          >
            <SettingsOutlinedIcon />
          </IconButton>
        </Tooltip>
        <Tooltip title="Object operations">
          <IconButton
            className="topbar-icon-button"
            aria-label="Object operations"
            onClick={onOpenObjectOperations}
            size="small"
          >
            <DataObjectOutlinedIcon />
          </IconButton>
        </Tooltip>
        <Tooltip title="Navigation menu">
          <span>
            <IconButton
              className="topbar-icon-button"
              aria-label="Navigation menu"
              disabled
              size="small"
            >
              <MenuOutlinedIcon />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title="Local desktop user">
          <span>
            <IconButton
              className="topbar-icon-button"
              aria-label="User menu"
              disabled
              size="small"
            >
              <PersonOutlineOutlinedIcon />
            </IconButton>
          </span>
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
